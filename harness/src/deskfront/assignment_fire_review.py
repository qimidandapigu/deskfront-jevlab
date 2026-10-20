"""Expire a proven ineffective firing commitment, without selecting its replacement."""
import math

from firing_position_contract import has_active_breach, proven_blocked_position


def decision_blocked(unit, legacy_pressure=.35):
    """Follow current native safety, retaining old-engine and hard-danger guards."""
    if unit.get('survival_reason') or unit.get('suppression', 0) >= .72:
        return True
    combat = unit.get('combat')
    reaction = combat.get('fire_reaction') if isinstance(combat, dict) else None
    blocked = reaction.get('decision_blocked') if isinstance(reaction, dict) else None
    if type(blocked) is bool:
        return blocked
    return unit.get('suppression', 0) >= legacy_pressure


def _point(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(type(n) in (int, float) and math.isfinite(n) for n in value))


def _active_route(unit, motion):
    return bool(unit.get('path_active') or unit.get('combat', {}).get('path_active')
                or unit.get('route') or motion.get('state') in ('executing', 'suspended'))


def _departing_endpoint(unit, motion):
    """A real route to a different point may be a valid local bypass attempt.

    An executing label or renewed order to the already reached point is not
    evidence of departure. Missing route destinations remain unknown rather
    than being classified as a failed route.
    """
    if not _active_route(unit, motion):
        return False
    if motion.get('state') == 'suspended':
        return True
    destinations = [p for p in (motion.get('destination'), unit.get('goal')) if _point(p)]
    return not destinations or any(math.dist(unit['position'], p) > .04 for p in destinations)


def review(unit, assignment, history, now, motion):
    if assignment.get('role') != 'establish_fire' or has_active_breach(unit):
        return {}
    last_shot = unit.get('last_shot_at', -1)
    if (decision_blocked(unit)
            or unit.get('reload_remaining', 0) > 0
            or last_shot >= 0 and 0 <= now-last_shot < 8):
        return {}
    # Reaching a movement endpoint and establishing fire are separate facts.
    # Current native failure at that endpoint needs no twelve-second timer;
    # new order IDs, timestamps and tiny same-point routes cannot renew it.
    endpoint = proven_blocked_position(unit, assignment.get('position'), now)
    if endpoint and not _departing_endpoint(unit, motion):
        return dict(endpoint, review_required=True, stage='arrived_without_fire',
                    route_progress_at=history.get('route_progress_at'))
    if _active_route(unit, motion):
        return {}
    fact = unit.get('combat', {}).get('firing_awareness', {})
    # One blocked target does not invalidate a real fire opportunity against
    # another target. Missing native target lists are not a fireless finding.
    targets = [value for value in (unit.get('combat', {}).get('engageable_targets'),
               fact.get('engageable_visible_targets')) if isinstance(value, list)]
    if not targets or any(targets):
        return {}
    episode = history.get('engagement_block', {})
    if (fact.get('clear') is not False or fact.get('reason') not in ('muzzle_cover', 'target_occluded')
            or not fact.get('target_id') or not fact.get('blocker_id')
            or tuple(episode.get('key', ()))[:2] != (fact['target_id'], fact['blocker_id'])):
        return {}
    if (now-episode.get('since', now) >= 12
            and now-history.get('stationary_at', now) >= 8
            and now-unit.get('last_shot_at', -1) >= 8):
        return dict(review_required=True, stage='persistent_native_obstruction',
                    target_id=fact['target_id'], blocker_id=fact['blocker_id'],
                    reason=fact['reason'], sampled_at=now,
                    basis='native blocked firing episode without route execution or effective fire')
    return {}


def required(unit, assignment, history, now, motion):
    return bool(review(unit, assignment, history, now, motion))


def observe_participation(history, unit, assignment, now, motion, contacts, intent, stage):
    """Observe an attack endpoint, without invalidating or replacing its order.

    Unlike a fire-position admission check, this also covers a maneuver that
    has finished short of weapon range. Orders are deliberately not episode
    identity: an equivalent reissue cannot erase unresolved execution facts.
    """
    from actor_roster import effective_range
    state = history.setdefault('attack_position_watch', {})
    state['ready'] = False
    if now < state.get('observed_at', now):
        state.clear()
    state['observed_at'] = now
    episode = state.get('episode', {})
    def close(reason):
        if episode.get('active'):
            episode.update(active=False, resolved_at=now, resolution=reason)
        return {}
    if (unit.get('hp', 1) <= 0 or intent not in ('advance', 'bound', 'flank')
            or stage not in ('approach', 'probe', 'engage', 'reposition')
            or assignment.get('role') not in ('maneuver', 'establish_fire', 'fire_support')):
        return close('attack_assignment_ended')
    # Explicitly segmented routes remain legitimate intermediate movement.
    # Different local destinations alone do not imply a transport prefix.
    remaining = assignment.get('remaining_region_hops', assignment.get('route_remaining_region_steps', 0))
    if type(remaining) in (int, float) and remaining > 0:
        return close('intermediate_route_segment')
    position, destination = unit.get('position'), assignment.get('position')
    if not _point(position) or not _point(destination):
        return {}
    # Retain the failure through safety/transport transitions, but do not
    # request a decision or claim it is currently actionable during recovery.
    if (decision_blocked(unit)
            or unit.get('reload_remaining', 0) > 0 or motion.get('state') == 'suspended'):
        return {}
    if has_active_breach(unit):
        return close('native_breach_available')
    last_shot = unit.get('last_shot_at', -1)
    if last_shot >= 0 and 0 <= now-last_shot < 5:
        return close('actual_fire')
    if _departing_endpoint(unit, motion):
        return {}
    # Native completion is useful only when its accepted point is still the
    # current assignment. A completed intermediate segment is not arrival.
    completed = (motion.get('state') == 'completed' and _point(motion.get('destination'))
                 and math.dist(motion['destination'], destination) <= .04)
    arrived = math.dist(position, destination) <= (.12 if completed else .04)
    combat = unit.get('combat') or {}
    visible = {c['id']: c for c in contacts if c.get('visible') is True and c.get('id')
               and c.get('hp', 1) > 0 and _point(c.get('position'))
               and 0 <= now-c.get('last_seen', now) <= 2.}
    targets = [x for x in (combat.get('engageable_targets'),
               combat.get('firing_awareness', {}).get('engageable_visible_targets')) if isinstance(x, list)]
    if any(targets):
        return close('native_fire_opportunity')
    if not visible:
        return {}  # stale/missing sight is unknown, not a new failure
    reach = effective_range(unit)
    if type(reach) not in (int, float) or not math.isfinite(reach) or reach <= 0:
        reach = None
    distances = {key: math.dist(position, contact['position']) for key, contact in visible.items()}
    nearest = min(distances, key=distances.get)
    ray = combat.get('firing_awareness') or {}
    sampled_at, sampled_position = ray.get('sampled_at'), ray.get('position')
    current_ray = (type(sampled_at) in (int, float) and math.isfinite(sampled_at)
        and -.1 <= now-sampled_at <= 1.1 and _point(sampled_position)
        and math.dist(position, sampled_position) <= .04
        and bool(ray.get('posture')) and ray['posture'] == unit.get('posture'))
    obstruction = (bool(targets) and not any(targets) and ray.get('clear') is False
        and ray.get('reason') in ('muzzle_cover', 'target_occluded')
        and ray.get('target_id') in visible and bool(ray.get('blocker_id')) and current_ray)
    blocked_episode = history.get('engagement_block', {})
    persistent_block = (obstruction and tuple(blocked_episode.get('key', ()))[:2]
        == (ray.get('target_id'), ray.get('blocker_id')) and now-blocked_episode.get('since', now) >= 5.)
    if not arrived and not persistent_block:
        if current_ray and ray.get('clear') is True:
            return close('native_ray_cleared')
        # A persistent obstruction can be observed before the final assigned
        # endpoint. A stale ray does not mean this stopped actor left the
        # failure location; require actual displacement from its old anchor.
        if episode.get('active') and math.dist(position, episode['position']) <= .06:
            return {}
        return close('left_attack_endpoint')
    if arrived and reach is not None and all(distance > reach for distance in distances.values()):
        reason = 'arrived_outside_weapon_range'
        detail = dict(weapon_range=reach, nearest_visible_contact_distance=round(distances[nearest], 3),
                      target_id=nearest)
    elif obstruction:
        reason = 'arrived_native_firing_obstruction' if arrived else 'stationary_native_firing_obstruction'
        detail = {key: ray[key] for key in ('target_id', 'blocker_id', 'reason')}
        detail['native_reason'] = detail.pop('reason')
    else:
        # Missing/stale rays, a moved muzzle or a changed posture are unknown,
        # not proof that the previous obstruction cleared. Preserve its one
        # notification through the next native sampling deadline.
        if current_ray and ray.get('clear') is True:
            return close('native_ray_cleared')
        if (episode.get('reason') == 'arrived_outside_weapon_range' and reach is not None
                and any(distance <= reach for distance in distances.values())):
            return close('visible_contact_entered_weapon_range')
        return {}
    # Tiny same-site motion and new order IDs retain one notification. Moving
    # to a genuinely different point or resolving the failure earns a new one.
    same = episode.get('active') and math.dist(position, episode['position']) <= .06
    if not same:
        serial = state.get('serial', 0)+1
        state['serial'] = serial
        episode = dict(episode_id=f"{unit.get('id', 'actor')}:attack-position:{serial}",
                       active=True, since=now, position=list(position), local_notified=False)
        state['episode'] = episode
    for key in ('target_id', 'blocker_id', 'native_reason', 'weapon_range', 'nearest_visible_contact_distance'):
        episode.pop(key, None)
    episode.update(reason=reason, destination=list(destination), arrived_at_assignment=arrived, **detail)
    # One second of a measured stop lets an ordinary arrival settle. This is
    # an event condition, not a periodic request interval.
    state['ready'] = now-history.get('stationary_at', now) >= 1.
    return participation(history, now)


def participation(history, now):
    state = history.get('attack_position_watch', {})
    row = state.get('episode', {})
    if not row.get('active'):
        return {}
    return dict({key: row[key] for key in ('episode_id', 'reason', 'position', 'destination',
        'target_id', 'blocker_id', 'native_reason', 'weapon_range', 'nearest_visible_contact_distance', 'arrived_at_assignment') if key in row},
        review_ready=bool(state.get('ready') and state.get('observed_at') == now),
        seconds_unresolved=round(max(0, now-row['since']), 1),
        basis='accepted attack endpoint reached or persistent native obstruction while stopped; current visible-range/native-firing facts; review only, movement completion is not attack contribution')
