"""Classify observed progress on one fire task without issuing a tactical order.

``assess`` is deliberately independent of model/provider latency. The caller
stores its result as ``previous`` on the next game observation and may react to
``action``. Candidate inputs, when supplied, must contain *currently valid*
local reposition choices; ``None`` means the query has not completed, while an
empty collection means it completed and found none.
"""

import math


FIRE_COMMANDS = frozenset(('support', 'eliminate'))
SHOT_WINDOW_S = 2.3
MOVEMENT_STALL_S = 4.0
SETTLE_S = 1.5
FIRE_START_S = 3.0
COVER_CYCLE_GRACE_S = 6.0


def _point(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        return None
    return value


def _elapsed(now, start):
    return max(0.0, now - start) if isinstance(start, (int, float)) else 0.0


def _identity(task):
    # A moved route cursor and rewritten area geometry must not reset the clock.
    return repr((task.get('stage_id'), task.get('task_revision'), task.get('command'),
                 task.get('target_id'), task.get('region_id'),
                 tuple(task.get('region_path') or ()), task.get('route')))


def _arrived(task, unit, feedback):
    # A newer commander may leave region/route selection to JEV. In that case
    # only an observed selected destination can prove destination arrival.
    if not task.get('region_id') and not task.get('region_path'):
        destination = feedback.get('selected_destination')
        if destination is None:
            destination = (feedback.get('active_task') or {}).get('destination')
        if isinstance(destination, dict):
            destination = destination.get('position')
        here, there = _point(unit.get('position')), _point(destination)
        return here is not None and there is not None and math.dist(here, there) <= .08
    nav = feedback.get('region_navigation') or {}
    if nav.get('status') == 'arrived':
        return True
    destination = task.get('region_id')
    observed = (feedback.get('dynamic_task') or {}).get('regions')
    if destination and isinstance(observed, list) and destination in observed:
        return True
    area = task.get('destination_area')
    if isinstance(area, dict) and _point(unit.get('position')) is not None:
        from strategic_regions import contains
        return contains(unit['position'], area)
    return False


def _fresh_block(unit, now, target):
    check = unit.get('combat', {}).get('fire_check') or {}
    if check.get('status') != 'blocked' or (target and check.get('target_id') != target):
        return None
    age = now - check.get('time', -100)
    here, there = _point(unit.get('position')), _point(check.get('position'))
    if not 0 <= age <= 3 or here is None or there is None or math.dist(here, there) > .08:
        return None
    return check.get('reason') or 'muzzle_blocked'


def _cover_cycle(unit):
    """A reserved slot survives the short move between the hiding and peek points.

    ``in_cover`` alone cannot identify this state: it is false at the shoulder.
    A stationed building has the same native hide/peek behavior without a slot.
    """
    stance = unit.get('cqb_stance')
    if stance not in ('hide', 'peek', 'crouch'):
        return None
    slot = unit.get('cover_slot')
    if isinstance(slot, dict):
        slot = slot.get('key')
    if slot and unit.get('cover_id'):
        return str(slot)
    if unit.get('building_phase') == 'stationed':
        return 'building:' + str(unit.get('building_floor', ''))
    return None


def assess(task, unit, state, feedback, previous=None, candidates=None):
    """Return observed phase, evidence, advisory next review and stable clocks.

    ``action`` is one of ``continue``, ``local_reposition`` and
    ``commander_reassess``. It requests a decision from the owning layer; this
    function does not choose a route, claim a firing lane or submit game input.
    An empty *bounded* local query means no sampled option, not no reachable
    firing position anywhere on the map.
    """
    now = state['time']
    identity = _identity(task)
    prior = previous or {}
    if prior.get('identity') != identity or now < prior.get('observed_at', now):
        prior = {}
    started = prior.get('started_at', now)
    position = _point(unit.get('position'))
    anchor = _point(prior.get('movement_anchor')) or position
    movement_at = prior.get('movement_at', now)
    if position is not None and (anchor is None or math.dist(position, anchor) >= .04):
        anchor, movement_at = position, now
    arrived = _arrived(task, unit, feedback)
    arrived_at = prior.get('arrived_at', now) if arrived else None
    if arrived and not prior.get('arrived', False):
        arrived_at = now
    cover_key = _cover_cycle(unit)
    cover_cycle_at = (prior.get('cover_cycle_at', now)
                      if cover_key and prior.get('cover_cycle_key') == cover_key else now)
    target = task.get('target_id')
    combat = unit.get('combat') or {}
    native_targets = combat.get('engageable_targets')
    shot_at = unit.get('last_shot_at', -100)
    matching_shot = (isinstance(shot_at, (int, float)) and started <= shot_at <= now
                     and (not target or unit.get('last_shot_target') == target))
    candidate_count = len(candidates) if candidates is not None else None
    evidence = dict(
        cover_cycle=bool(cover_key), cover_stance=unit.get('cqb_stance'),
        reserved_cover_slot=cover_key, native_path_active=bool(combat.get('path_active')),
        native_fire_lane=('unknown' if not isinstance(native_targets, list) else
                          'candidate' if (target in native_targets if target else native_targets) else
                          'not_in_candidates'),
        last_assigned_shot_at=shot_at if matching_shot else None,
        local_query='not_run' if candidates is None else 'sampled',
        sampled_local_options=candidate_count)
    result = dict(identity=identity, observed_at=now, started_at=started,
                  movement_anchor=list(anchor) if anchor is not None else None,
                  movement_at=movement_at, arrived=arrived, arrived_at=arrived_at,
                  cover_cycle_key=cover_key, cover_cycle_at=cover_cycle_at if cover_key else None,
                  evidence=evidence)

    def report(phase, reason, severity='info', action='continue', **details):
        result.update(phase=phase, reason=reason, severity=severity, action=action,
                      duration_s=round(_elapsed(now, arrived_at if arrived else started), 2))
        result.update(details)
        return result

    def reposition(reason, **details):
        if candidates is not None and not candidates:
            return report('blocked', 'no_local_reposition_candidate', 'failed',
                          'commander_reassess', local_failure_reason=reason, **details)
        return report('blocked', reason, 'warning', 'local_reposition', **details)

    if task.get('command') not in FIRE_COMMANDS:
        return report('not_applicable', 'not_a_fire_task')
    if unit.get('hp', 0) <= 0:
        return report('interrupted', 'unit_dead', 'failed', 'commander_reassess')
    enemy = next((u for u in state.get('units', []) if u.get('id') == target), None) if target else None
    if enemy is not None and position is not None:
        enemy_position = _point(enemy.get('position'))
        reach = unit.get('weapon_range')
        if (enemy_position is not None and isinstance(reach, (int, float))
                and not isinstance(reach, bool) and math.isfinite(reach) and reach > 0):
            evidence['range_gap_at_current_position'] = round(
                max(0, math.dist(position, enemy_position) - reach), 3)
            evidence['range_basis'] = 'current_position_distance_only_not_peek_muzzle'
    if target and (enemy is None or enemy.get('hp', 0) <= 0):
        return report('completed', 'target_unavailable', 'info', 'commander_reassess')

    fired = matching_shot and now - shot_at <= SHOT_WINDOW_S
    if fired:
        return report('effective', 'observed_shot_at_assigned_target')
    phase = (feedback.get('task_execution') or {}).get('phase')
    if phase in ('preparing', 'waiting'):
        return report('waiting', 'dependency_not_observed')
    if unit.get('order_mode') == 'self_preserve':
        return report('interrupted', 'native_survival_override', 'warning')

    if unit.get('reload_remaining', 0) > 0 or unit.get('weapon_state') == 'reload':
        return report('recovering', 'reloading')
    if unit.get('suppression', 0) >= .95:
        return report('recovering', 'heavy_suppression')
    if unit.get('weapon_state') == 'cooldown':
        return report('recovering', 'weapon_cooldown')

    # The engine traverses hide/peek on a reserved slot and may report an
    # active path, no current fire lane, or in_cover=false during normal play.
    # None of those observations alone prove that this firing position failed.
    if cover_key:
        block = _fresh_block(unit, now, target)
        if block:
            return reposition('muzzle_blocked', block_reason=block)
        since = max(started, cover_cycle_at, arrived_at or started,
                    shot_at if matching_shot else started)
        if _elapsed(now, since) < COVER_CYCLE_GRACE_S:
            reason = ('cover_step_in_progress' if unit.get('cover_step') or
                      unit.get('locomotion') == 'cover_step' else
                      'native_cover_hide' if unit.get('cqb_stance') == 'hide' else
                      'native_cover_peek')
            return report('engaging', reason,
                          fire_wait_s=round(_elapsed(now, since), 2))
        # A sustained absence of assigned fire is a reason to *review* local
        # alternatives, not proof that the peek point has no line of sight.
        return reposition('fire_not_observed_during_cover_cycle',
                          fire_wait_s=round(_elapsed(now, since), 2))

    moving = bool(combat.get('path_active'))
    if moving:
        if _elapsed(now, movement_at) >= MOVEMENT_STALL_S:
            return reposition('route_stalled',
                              no_movement_s=round(_elapsed(now, movement_at), 2))
        return report('advancing', 'moving_toward_task')
    nav = feedback.get('region_navigation') or {}
    if (task.get('region_id') or task.get('region_path')) and nav.get('status') == 'blocked':
        return reposition('route_blocked', navigation_reason=nav.get('reason'))
    if not task.get('region_id') and not task.get('region_path') and not arrived:
        # No ordered route exists. A stationary unit with no useful lane needs
        # JEV to choose one, while a unit already in a plausible fire position
        # gets a brief aim window. Neither state proves support succeeded.
        if _elapsed(now, started) < SETTLE_S:
            return report('positioned', 'awaiting_local_route_or_fire')
        if enemy is not None and position is not None:
            enemy_position = _point(enemy.get('position'))
            reach = unit.get('weapon_range')
            if enemy_position is not None and isinstance(reach, (int, float)) and reach > 0:
                gap = math.dist(position, enemy_position) - reach
                if gap > .02:
                    return reposition('no_local_route_selected', range_gap=round(gap, 3))
        engageable = combat.get('engageable_targets')
        if isinstance(engageable, list) and (target not in engageable if target else not engageable):
            return reposition('no_local_route_selected')
        if _elapsed(now, started) >= FIRE_START_S:
            return reposition('fire_not_observed_at_stationary_position')
        return report('positioned', 'aiming_or_awaiting_fire')
    if not arrived:
        return report('advancing', 'route_not_arrived')

    if unit.get('ammo') == 0:
        return reposition('empty_magazine')

    block = _fresh_block(unit, now, target)
    if block:
        return reposition('muzzle_blocked', block_reason=block)
    if enemy is not None and position is not None:
        enemy_position = _point(enemy.get('position'))
        reach = unit.get('weapon_range')
        if enemy_position is not None and isinstance(reach, (int, float)) and reach > 0:
            gap = math.dist(position, enemy_position) - reach
            if gap > .02:
                return reposition('target_out_of_range_at_destination',
                                  range_gap=round(gap, 3))
    engageable = combat.get('engageable_targets')
    if isinstance(engageable, list) and (target not in engageable if target else not engageable):
        return reposition('no_target_fire_lane_at_destination')
    if _elapsed(now, arrived_at) < SETTLE_S:
        return report('positioned', 'settling_at_firing_position')
    if _elapsed(now, arrived_at) < FIRE_START_S:
        return report('positioned', 'aiming_or_awaiting_fire')
    return reposition('fire_not_observed_after_arrival')
