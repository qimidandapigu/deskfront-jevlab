"""Bounded approach facts for JEV; no routes, actors or targets are chosen here.

Only caller-filtered contacts and known cover footprints are read. Geometry is
two-dimensional and cannot prove concealment, discovery, safety, a walkable
path or a native muzzle line. All offered choices remain available.
"""
import math
from itertools import islice

from engagement_feedback import point_obstructions
from route_choice_evidence import execution_polyline
from weapon_affordance import at_distance


MAX_UNITS = 16
MAX_ROWS = 96
MAX_ROWS_PER_UNIT = 12
MAX_CONTACT_INPUTS = 64
MAX_TARGETS = 1
MAX_COVERS = 128
MAX_POINTS = 16
ROUTE_SAMPLES = 6


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _point(value):
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(_number(v) for v in value)


def _age(now, then):
    return round(now - then, 3) if _number(now) and _number(then) else None


def _contacts(unit, contacts, now):
    """Choose a bounded *comparison set*, stable across this actor's menu."""
    found = {}
    for contact in islice(contacts or (), MAX_CONTACT_INPUTS):
        if not isinstance(contact, dict) or not isinstance(contact.get('id'), str):
            continue
        if contact.get('faction') and contact.get('faction') == unit.get('faction'):
            continue
        hp = contact.get('hp')
        if _number(hp) and hp <= 0:
            continue
        age = _age(now, contact.get('last_seen'))
        state = ('current' if contact.get('visible') is True and age is not None and 0 <= age <= 2
                 else 'visible_time_unknown' if contact.get('visible') is True and age is None
                 else 'stale' if contact.get('visible') is True else 'last_seen_unconfirmed')
        item = dict(id=contact['id'], position=contact.get('position'), state=state, age_s=age)
        old = found.get(item['id'])
        if old is None or (item['state'] == 'current', -(age if age is not None else math.inf)) > (
                old['state'] == 'current', -(old['age_s'] if old['age_s'] is not None else math.inf)):
            found[item['id']] = item
    origin = unit.get('position')
    engaged = (unit.get('combat') or {}).get('firing_awareness', {}).get('target_id')
    ranked = sorted(found.values(), key=lambda c: (
        c['state'] != 'current',
        not _point(c['position']),
        c['id'] != engaged,
        math.dist(origin, c['position']) if _point(origin) and _point(c['position']) else math.inf,
        c['id']))
    return ranked[:MAX_TARGETS], max(0, len(ranked) - MAX_TARGETS)


def _known_covers(world):
    raw = world.get('covers') if isinstance(world, dict) else None
    if not isinstance(raw, (list, tuple)):
        return {'covers': []}, 'unknown'
    clean = []
    incomplete = len(raw) > MAX_COVERS
    for cover in raw[:MAX_COVERS]:
        if not isinstance(cover, dict):
            incomplete = True
            continue
        if not cover.get('alive', True) or cover.get('kind') != 'hard':
            continue
        size = cover.get('size')
        ray = cover.get('ray_size')
        if isinstance(ray, (list, tuple)) and len(ray) == 3 and all(_number(v) and v > 0 for v in ray):
            size = [ray[0], ray[2]]
        if (not isinstance(cover.get('id'), str) or not _point(cover.get('position'))
                or not _point(size) or min(size) <= 0 or not _number(cover.get('yaw', 0))):
            incomplete = True
            continue
        clean.append(dict(id=cover['id'], kind='hard', position=list(cover['position']),
                          size=list(size), yaw=cover.get('yaw', 0)))
    return {'covers': clean}, 'partial' if incomplete else 'known_input_complete'


def _route(unit, row, *, allow_direct=False):
    origin, endpoint = unit.get('position'), row.get('position')
    remaining = row.get('remaining_region_hops')
    remaining = remaining if type(remaining) is int and remaining >= 0 else None
    prefix = row.get('limitation') == 'intermediate_route_segment' or (remaining is not None and remaining > 0)
    fact = dict(endpoint_scope='intermediate_prefix' if prefix else 'offered_endpoint',
                remaining_region_hops=remaining,
                reaches_team_goal=row.get('route_reaches_team_goal') if type(row.get('route_reaches_team_goal')) is bool else None)
    if prefix:
        fact['reaches_team_goal'] = False
    if not _point(origin) or not _point(endpoint):
        return dict(fact, basis='unknown_invalid_position'), []
    points = row.get('route_positions')
    if isinstance(points, (list, tuple)) and points:
        if len(points) > MAX_POINTS or not all(_point(p) for p in points):
            return dict(fact, basis='unknown_route_budget_or_invalid_points'), []
        path = execution_polyline(origin, points, endpoint)
        fact['basis'] = 'offered_waypoint_estimate_not_native_walked_path'
    elif allow_direct:
        path = [origin, endpoint]
        fact['basis'] = 'direct_segment_geometry_only_not_route_or_walkability'
    else:
        return dict(fact, basis='unknown_missing_route'), []
    fact['polyline_length'] = round(sum(math.dist(a, b) for a, b in zip(path, path[1:])), 3)
    native_length = row.get('path_length')
    if _number(native_length) and native_length >= 0:
        fact['provided_native_path_length'] = native_length
    return fact, path


def _samples(path):
    if not path:
        return []
    lengths = [math.dist(a, b) for a, b in zip(path, path[1:])]
    total = sum(lengths)
    if total < 1e-9:
        return [path[0]]
    result = []
    for i in range(ROUTE_SAMPLES):
        left = total * i / (ROUTE_SAMPLES - 1)
        for a, b, length in zip(path, path[1:], lengths):
            if left <= length + 1e-9 and length > 0:
                t = min(1., left / length)
                result.append([a[j] + (b[j] - a[j]) * t for j in (0, 1)])
                break
            left -= length
        else:
            result.append(path[-1])
    return result


def _current_check(unit, target_id, now):
    combat = unit.get('combat') or {}
    ray = combat.get('firing_awareness') or {}
    if ray.get('target_id') != target_id:
        return {'status': 'unknown'}
    age = _age(now, ray.get('sampled_at'))
    same_position = (_point(ray.get('position')) and _point(unit.get('position'))
                     and math.dist(ray['position'], unit['position']) <= .04)
    fresh = age is not None and -.1 <= age <= 1.1 and same_position and bool(ray.get('posture')) and ray['posture'] == unit.get('posture')
    if not fresh:
        return dict(status='stale_or_pose_changed', age_s=age)
    return dict(status='current_native_sample', clear=ray.get('clear') if type(ray.get('clear')) is bool else None,
                reason=ray.get('reason'), blocker_id=ray.get('blocker_id'), posture=ray.get('posture'))


def _site_check(unit, row, target_id, now):
    checks = row.get('fire_checks')
    if not isinstance(checks, (list, tuple)):
        return {'status': 'unknown'}
    check = next((c for c in checks[:16] if isinstance(c, dict) and c.get('target_id') == target_id), None)
    if check is None:
        return {'status': 'unknown'}
    posture = row.get('fire_check_posture', 'unknown')
    age = _age(now, row.get('sampled_at'))
    stale = age is not None and not (-.1 <= age <= 2)
    return dict(status='stale_native_site_sample' if stale else 'provided_native_site_sample',
                clear=check.get('clear') if type(check.get('clear')) is bool else None,
                reason=check.get('reason'), blocker_id=check.get('blocker_id'),
                checked_posture=posture, current_posture_matches=posture != 'unknown' and posture == unit.get('posture'),
                age_s=age, applies_to_current_posture='unknown' if stale or posture != unit.get('posture') else 'sample_only_not_future_guarantee')


def _geometry(known, coverage, origin, endpoint, samples, target, current_check):
    fact = dict(basis='2d_known_hard_footprints_not_stealth_safety_or_native_fire', coverage=coverage)
    if coverage == 'unknown':
        return fact
    contact = [dict(id=target['id'], position=target['position'], visible=True)]
    def crossings(point):
        return point_obstructions(known, point, contact)[0]['crossing_hard_cover_ids']
    start, end = crossings(origin), crossings(endpoint)
    crossed = [crossings(p) for p in samples]
    fact.update(current_crossings=start, endpoint_crossings=end, samples=len(samples),
                crossing_samples=sum(bool(ids) for ids in crossed),
                no_crossing_samples=sum(not ids for ids in crossed))
    blocker = current_check.get('blocker_id') if current_check.get('clear') is False else None
    if blocker:
        # A bounded crossing list can prove presence, but cannot prove absence.
        fact['same_current_blocker_at_endpoint'] = True if blocker in end else (
            False if coverage == 'known_input_complete' and len(end) < 4 and any(c['id'] == blocker for c in known['covers']) else None)
    return fact


def _facts(unit, row, selected, known, coverage, now, *, allow_direct=False):
    route, path = _route(unit, row, allow_direct=allow_direct)
    samples = _samples(path)
    result = dict(schema='close_engagement/v1', weapon=unit.get('weapon'), route=route, targets=[],
                  comparison_basis='current_native_cones_held_constant; ground_distance_not_hit_probability; distance_hints_are_advisory')
    origin, endpoint = unit.get('position'), row.get('position')
    for target in selected:
        fact = dict(target_id=target['id'], contact_state=target['state'], age_s=target['age_s'])
        result['targets'].append(fact)
        if target['state'] != 'current' or not all(_point(p) for p in (origin, endpoint, target['position'])):
            fact['comparison'] = 'unknown_contact_or_position'
            continue
        current = math.dist(origin, target['position'])
        destination = math.dist(endpoint, target['position'])
        fact.update(current=at_distance(unit, current), endpoint=at_distance(unit, destination),
                    distance_gain=round(current-destination, 3),
                    native_current_check=_current_check(unit, target['id'], now),
                    native_site_check=_site_check(unit, row, target['id'], now))
        fact['geometry'] = _geometry(known, coverage, origin, endpoint, samples, target, fact['native_current_check'])
    if not selected:
        result['contact_status'] = 'unknown_no_supplied_contacts'
    return result


def site_facts(unit, row, contacts, world, *, now=None):
    """Return one independent fact for a site, preserving native check/pose scope.

    With no offered waypoints, sampled lines describe only a straight geometric
    segment. They do not invent a native route or imply it can be walked.
    """
    selected, omitted = _contacts(unit, contacts, now)
    known, coverage = _known_covers(world)
    result = _facts(unit, row, selected, known, coverage, now, allow_direct=True)
    if omitted:
        result['comparison_contacts_omitted'] = omitted
    return result


def _compact_distance(value):
    return {k: v for k, v in value.items() if k in ('distance', 'in_weapon_range', 'spread_radius_current')}


def _compact_route(fact):
    """Current actor facts live once in the summary, not once per route."""
    # The offered row already has route_length/comparison, limitation and
    # remaining_region_hops. Do not send another copy for every route.
    result = {'targets': []}
    if fact['route']['endpoint_scope'] == 'intermediate_prefix':
        result['endpoint_scope'] = 'intermediate_prefix_only'
    if fact['route'].get('basis', '').startswith('unknown'):
        result['route_geometry'] = 'unknown'
    for item in fact['targets']:
        target = {k: v for k, v in item.items() if k not in (
            'current', 'native_current_check', 'contact_state', 'age_s')}
        if 'endpoint' in target:
            target['endpoint'] = _compact_distance(target['endpoint'])
        if target.get('native_site_check', {}).get('status') == 'unknown':
            target.pop('native_site_check')
        if 'geometry' in target:
            target['geometry'] = {k: v for k, v in target['geometry'].items()
                                  if k not in ('basis', 'coverage', 'current_crossings', 'no_crossing_samples')}
        result['targets'].append(target)
    if 'contact_status' in fact:
        result['contact_status'] = fact['contact_status']
    return result


def annotate(options, units, contacts, world, *, now=None):
    """Annotate offered rows in place; return compact shared limits/semantics.

    No menu key, endpoint, route, role, target or admission field is changed.
    Omitted comparisons remain unknown, and every original choice survives.
    """
    known, coverage = _known_covers(world)
    contact_list = list(islice(contacts or (), MAX_CONTACT_INPUTS))
    count = 0
    summary = dict(schema='close_engagement/v1', annotated_rows=0,
                   max_rows=MAX_ROWS, max_targets_per_actor=MAX_TARGETS, route_samples=ROUTE_SAMPLES,
                   members={}, geometry_coverage=coverage,
                   data_limits={'members': MAX_UNITS, 'rows_per_member': MAX_ROWS_PER_UNIT,
                                'contacts_read': MAX_CONTACT_INPUTS, 'covers_read': MAX_COVERS},
                   basis='same_contacts_across_each_actor_menu; distances_to_offered_prefix_endpoint_only; no_route_or_target_selection',
                   limits='waypoint estimates are not native walked paths; 2D samples do not prove concealment, discovery, safety, walkability or native fire; absent native_site_check and omitted comparisons are unknown; native cones held constant, ground-distance radius is not hit probability; distance hints advisory; no candidate filtered')
    for unit in islice(units, MAX_UNITS):
        if not isinstance(unit, dict):
            continue
        menu = options.get(unit.get('id'), {})
        if not isinstance(menu, dict):
            continue
        selected, omitted = _contacts(unit, contact_list, now)
        shared = dict(weapon=unit.get('weapon'), targets=[])
        for contact in selected:
            view = {k: contact[k] for k in ('id', 'state', 'age_s')}
            if contact['state'] == 'current' and _point(contact['position']) and _point(unit.get('position')):
                view['current'] = _compact_distance(at_distance(unit, math.dist(unit['position'], contact['position'])))
                current_check = _current_check(unit, contact['id'], now)
                if current_check['status'] != 'unknown':
                    view['native_current_check'] = current_check
            shared['targets'].append(view)
        if omitted:
            shared['other_contacts_not_compared'] = omitted
        summary['members'][unit.get('id')] = shared
        for row in islice(menu.values(), MAX_ROWS_PER_UNIT):
            if count >= MAX_ROWS:
                break
            if isinstance(row, dict):
                row['close_engagement'] = _compact_route(_facts(unit, row, selected, known, coverage, now))
                count += 1
    summary['annotated_rows'] = count
    return summary
