"""Bounded observations of local execution loops, never tactical vetoes.

Orders, danger labels and cover-entry transitions are not outcomes. A review
episode survives those changes until measured fire/hits, sustained protection
improvement or genuine route progress takes the actor out of the local loop.
"""
import copy
import math
from actor_roster import last_fire


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _point(value):
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(_number(v) for v in value)


def _motion(samples):
    vertices = []
    for row in samples:
        point = row['position']
        # Ignore sub-cell foot adjustments: otherwise a tiny sidestep can
        # split one clear return leg into unrelated directions.
        if not vertices or math.dist(point, vertices[-1]) >= .075:
            vertices.append(point)
    lengths = [math.dist(a, b) for a, b in zip(vertices, vertices[1:])]
    travel = sum(lengths)
    net = math.dist(vertices[0], vertices[-1]) if len(vertices) > 1 else 0.
    reversals = 0
    for a, b, c in zip(vertices, vertices[1:], vertices[2:]):
        ab, bc = [b[i]-a[i] for i in (0, 1)], [c[i]-b[i] for i in (0, 1)]
        if sum(ab[i]*bc[i] for i in (0, 1)) < -.5*math.dist(a, b)*math.dist(b, c):
            reversals += 1
    spread = max((math.dist(a, b) for a in vertices for b in vertices), default=0.)
    return travel, net, reversals, spread


def observe(history, unit, now, motion=None):
    """Update one observer-owned state; sparse history is not a frame replay."""
    point = unit.get('position')
    if not _point(point) or not _number(now):
        return {}
    state = history.setdefault('local_execution_watch', {})
    if now < state.get('observed_at', now):
        state.clear()
    state['observed_at'] = now
    native = unit.get('combat', {}).get('cover_execution', {})
    if not isinstance(native, dict):
        native = {}
    samples = state.setdefault('samples', [])
    shot, hit = last_fire(unit), unit.get('last_hit_at', -1)
    fired = _number(shot) and shot > state.get('last_shot', shot) and shot >= 0
    hit_recorded = _number(hit) and hit > state.get('last_hit', hit) and hit >= 0
    state.update(last_shot=shot, last_hit=hit)
    native_at = native.get('last_progress_at')
    native_gain = (_number(native_at) and native_at >= 0
                   and native_at > state.get('native_progress_at', native_at))
    if _number(native_at):
        state['native_progress_at'] = native_at
    if not samples or now-samples[-1]['time'] >= .75:
        samples.append(dict(time=now, position=list(point)))
    samples[:] = [row for row in samples[-16:] if now-row['time'] <= 12.]
    travel, net, reversals, spread = _motion(samples)
    episode = state.get('episode')
    motion = motion or {}
    route_at = history.get('route_progress_at', -1)
    real_route = (_number(route_at) and route_at >= 0 and 0 <= now-route_at <= 1.5
                  and motion.get('state') in ('executing', 'holding', 'completed'))
    # Stable protection is a result only when its measured risk/pressure has
    # improved. Merely returning to the same slot never refreshes progress.
    safe = bool(unit.get('in_cover') and not unit.get('survival_reason')
                and unit.get('suppression', 0) < .35)
    slot = unit.get('cover_slot') or unit.get('cover_id')
    if not safe or not slot or slot != state.get('safe_slot') or state.get('safe_since') is None:
        state.update(safe_since=now if safe and slot else None, safe_slot=slot)
    stable_safe = state.get('safe_since') is not None and now-state['safe_since'] >= 3.
    risk = unit.get('cover_risk')
    improved = bool(episode and stable_safe and _number(risk)
                    and _number(episode.get('initial_cover_risk'))
                    and risk <= .25 and risk <= episode['initial_cover_risk']-.15)
    route_escape = bool(episode and real_route and now-episode['since'] >= 3
                        and math.dist(point, episode['anchor']) > .18
                        and net > .12 and travel > 0 and net/travel >= .65)
    if fired or hit_recorded or native_gain or improved or route_escape or unit.get('hp', 1) <= 0:
        if episode:
            episode.update(active=False, resolved_at=now,
                resolution='actual_fire' if fired else 'actual_hit' if hit_recorded else 'native_execution_gain' if native_gain else
                'sustained_protection_gain' if improved else 'measured_route_progress' if route_escape else 'unit_removed')
        state['samples'] = [dict(time=now, position=list(point))]
        state['last_gain_at'] = now
        # A stale native review flag cannot immediately resurrect a resolved
        # attempt. A new native attempt or a newly observed cycle still can.
        state['resolved_native_attempt'] = native.get('attempt_id')
        return public(history, now)
    active = bool(episode and episode.get('active'))
    # A normal single-round launcher reload is useful ongoing execution, not
    # a failed loop. Start any subsequent motion window after reloading.
    if not active and unit.get('reload_remaining', 0) > 0:
        state['samples'] = [dict(time=now, position=list(point))]
        return {}
    local_context = bool(slot or unit.get('in_cover') or native or unit.get('order_mode') in
                         ('self_preserve', 'adjust_firing_lane', 'squad_firing_position', 'pinned'))
    span = now-samples[0]['time'] if samples else 0
    cyclic = (local_context and span >= 4. and reversals >= 2 and travel >= .24
              and spread <= .60 and net <= travel*.45 and not real_route)
    native_review = bool(native.get('review_required') and not native.get('review_handoff')
                         and native.get('attempt_id') is not None
                         and native.get('attempt_id') != state.get('resolved_native_attempt'))
    recent_fire = _number(shot) and shot >= 0 and 0 <= now-shot < 4.
    if not active and not recent_fire and (cyclic or native_review):
        serial = int(state.get('serial', 0))+1
        state['serial'] = serial
        episode = dict(episode_id=f"{unit.get('id', 'unit')}:{serial}:{now:.3f}",
            active=True, since=now, observed_from=samples[0]['time'], anchor=list(point),
            initial_cover_risk=risk, local_notified=False, commander_notified=False,
            personal_requested=False, native_attempt_id=native.get('attempt_id'))
        state['episode'] = episode
    if episode and episode.get('active'):
        episode.update(path_length=round(travel, 3), net_displacement=round(net, 3),
            direction_reversals=reversals, native_phase=native.get('phase'),
            native_reason=native.get('reason'), native_review_required=bool(native.get('review_required')),
            recent_positions=copy.deepcopy(samples[-8:]))
    return public(history, now)


def public(history, now):
    row = history.get('local_execution_watch', {}).get('episode')
    if not row or not row.get('active'):
        return {}
    result = {key: copy.deepcopy(row[key]) for key in (
        'episode_id', 'since', 'observed_from', 'path_length', 'net_displacement',
        'direction_reversals', 'native_phase', 'native_reason', 'native_attempt_id',
        'native_review_required', 'local_notified', 'commander_notified', 'personal_requested',
        'recent_positions') if key in row}
    result.update(active=True, unresolved_for_s=round(max(0, now-row['since']), 1),
        basis='sampled local reversals or native cover review; renewed orders, brief safety gaps and re-entering cover are not gain',
        policy='review evidence only; no legal candidate or model-selected action is forbidden')
    return result
