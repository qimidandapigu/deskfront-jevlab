"""Measured engagement failures and bounded geometry facts, never tactical orders."""
import copy
import math


BLOCKED_REASONS = {'muzzle_cover', 'target_occluded', 'friendly_in_firing_lane', 'friendly_lane'}


def observe(history, unit, now, navigation_revision):
    if history.get('firing_sites_revision') != navigation_revision:
        history['failed_firing_sites'] = []
        history['firing_sites_revision'] = navigation_revision
    sites = history.setdefault('failed_firing_sites', [])
    sites[:] = [s for s in sites if now-s['last_observed_at'] <= 45]
    fact = unit.get('combat', {}).get('firing_awareness', {})
    key = (fact.get('target_id'), fact.get('blocker_id'), navigation_revision)
    blocked = (fact.get('clear') is False and fact.get('reason') in BLOCKED_REASONS
               and key[0] and key[1])
    if blocked:
        site = next((s for s in sites if s['target_id'] == key[0]
                     and s['blocker_id'] == key[1]
                     and math.dist(s['position'], unit['position']) <= .04), None)
        if site is None:
            site = dict(position=list(unit['position']), target_id=key[0], blocker_id=key[1],
                        first_observed_at=now, observations=0)
            sites.append(site)
        site.update(last_observed_at=now, reason=fact['reason'], observations=site['observations']+1)
        sites[:] = sorted(sites, key=lambda s: s['last_observed_at'])[-8:]
    if not blocked:
        history.pop('engagement_block', None)
        return
    old = history.get('engagement_block', {})
    shot = unit.get('last_shot_at', -1)
    # A shot against this target ends the no-fire episode; walking, taking a
    # hit, changing cover and renewing the same plan do not.
    if old.get('key') != key or (shot > old.get('last_shot', -1)
                                and unit.get('last_shot_target') == key[0]):
        old = dict(key=key, since=now, notified=False)
    old.update(last_shot=shot, reason=fact['reason'])
    history['engagement_block'] = old


def failed_sites(history, now):
    """Recent measured failures survive movement, empty rays and order renewal.

    Historical observations are not bans: new native candidate checks can
    show that moving targets or posture changes have reopened a lane.
    """
    return [dict(position=[round(v, 3) for v in s['position']], target_id=s['target_id'],
                 blocker_id=s['blocker_id'], reason=s['reason'],
                 age_s=round(now-s['last_observed_at'], 1))
            for s in history.get('failed_firing_sites', []) if 0 <= now-s['last_observed_at'] <= 45]


def review(history, fact, now, region_id, near_destination):
    old = history.get('engagement_block', {})
    if not old or old['key'][:2] != (fact.get('target_id'), fact.get('blocker_id')):
        return {}
    return dict(target_id=fact['target_id'], blocker_id=fact['blocker_id'],
                reason=old['reason'], blocked_without_target_fire_s=round(now-old['since'], 1),
                region_id=region_id, currently_near_destination=near_destination,
                basis='native consecutive blocked firing checks; movement is not fire contribution')


def _crosses(start, end, cover):
    """Oriented 2D footprint test. It is deliberately NOT a muzzle ray test."""
    cx, cy = cover['position']
    yaw = cover.get('yaw', 0) or 0
    co, si = math.cos(yaw), math.sin(yaw)
    def local(p):
        x, y = p[0]-cx, p[1]-cy
        return (co*x-si*y, si*x+co*y)
    a, b = local(start), local(end)
    low, high = 0., 1.
    for i in range(2):
        half = cover['size'][i]/2
        delta = b[i]-a[i]
        if abs(delta) < 1e-9:
            if abs(a[i]) > half:
                return False
        else:
            x, y = sorted(((-half-a[i])/delta, (half-a[i])/delta))
            low, high = max(low, x), min(high, y)
            if low > high:
                return False
    return True


def _wall_sides(point, target, cover):
    """Explicit opposite-side fact for a crossed thin wall, not a firing ray."""
    if max(cover['size']) < min(cover['size']) * 3:
        return None
    yaw = cover.get('yaw', 0) or 0
    co, si = math.cos(yaw), math.sin(yaw)
    normal = (co, -si) if cover['size'][0] < cover['size'][1] else (si, co)
    def side(p):
        distance = sum((p[i]-cover['position'][i])*normal[i] for i in (0, 1))
        label = 'positive_normal' if distance > 0 else 'negative_normal'
        if abs(normal[0]) > .999:
            label = 'east' if distance*normal[0] > 0 else 'west'
        elif abs(normal[1]) > .999:
            label = 'positive_z' if distance*normal[1] > 0 else 'negative_z'
        return label
    return dict(cover_id=cover['id'], point_side=side(point), target_side=side(target),
                same_side_as_target=side(point) == side(target))


def point_obstructions(world, point, contacts):
    """Bounded endpoint facts placed next to the route being selected."""
    covers = _physical_covers(world)
    return [dict(target_id=t['id'], crossing_hard_cover_ids=[c['id'] for c in covers
                 if _crosses(point, t['position'], c)][:4], native_firing_line='unknown')
            for t in sorted((c for c in contacts if c.get('visible')),
                            key=lambda t: math.dist(point, t['position']))[:3]]


def _physical_covers(world):
    covers = [dict(c) for c in world.get('covers', []) if c.get('alive', True)
              and c.get('kind') == 'hard' and len(c.get('position', [])) == 2
              and len(c.get('size', [])) == 2]
    for cover in covers:
        if len(cover.get('ray_size', [])) == 3:
            cover['size'] = [cover['ray_size'][0], cover['ray_size'][2]]
    return covers


def geometry(world, members, contacts, regions, plan, *, include_offered=False):
    visible = {c['id']: c for c in contacts if c.get('visible')}
    if not visible or not members or not regions:
        return {}
    origin = [sum(u['position'][i] for u in members)/len(members) for i in range(2)]
    blocked_ids = {u.get('combat', {}).get('firing_awareness', {}).get('target_id') for u in members}
    targets = sorted(visible.values(), key=lambda c: (
        0 if c.get('kind') == 'tank' else 1 if c['id'] in blocked_ids else 2,
        math.dist(origin, c['position']), c['id']))[:3]
    covers = _physical_covers(world)
    blocker_ids = {u.get('combat', {}).get('firing_awareness', {}).get('blocker_id') for u in members}
    relevant = sorted(covers, key=lambda c: (c['id'] not in blocker_ids,
        min(math.dist(c['position'], origin), *(math.dist(c['position'], t['position']) for t in targets))))[:12]
    # Bounded samples describe both ends of the engagement. All original
    # regions remain available; these facts neither recommend nor ban a route.
    sample_ids = set()
    anchors = [origin] + [t['position'] for t in targets]
    for point in anchors:
        sample_ids.update(sorted(regions, key=lambda k: math.dist(regions[k]['center'], point))[:3])
    if plan.get('region_id') in regions:
        sample_ids.add(plan['region_id'])
    # Include the offered region itself, rather than only the few nearest
    # regions. A numerical map elsewhere in the prompt is too easy to miss.
    if include_offered:
        sample_ids.update(sorted(regions, key=lambda rid: min(
            math.dist(regions[rid]['center'], p) for p in anchors))[:64])
    checks = {rid: [dict(target_id=t['id'], distance=round(math.dist(regions[rid]['center'], t['position']), 3),
                        crossing_hard_cover_ids=[c['id'] for c in covers if _crosses(regions[rid]['center'], t['position'], c)][:4],
                        blocking_wall_sides=[fact for c in covers
                            if _crosses(regions[rid]['center'], t['position'], c)
                            and (fact := _wall_sides(regions[rid]['center'], t['position'], c))][:2],
                        native_firing_line='unknown') for t in targets]
              for rid in sorted(sample_ids)}
    return dict(hard_covers=[{k: copy.deepcopy(c[k]) for k in ('id', 'position', 'size', 'yaw', 'height') if k in c}
                            for c in relevant], region_checks=checks,
                basis='2D hard-cover footprints only; crossing warns of obstruction, no crossing does not prove a clear muzzle ray or safe route; unsampled regions remain unknown')
