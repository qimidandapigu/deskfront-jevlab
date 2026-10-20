"""Bounded small-arms outcome observations; review evidence, never a tactic.

The native counters must explicitly cover every released/resolved small-arms
shot. Missing attribution is unknown, not proof that suppressive fire failed.
Orders and ammo/reload transitions are not outcomes and cannot erase an episode.
"""
import copy
import math

WINDOW_S = 8.
MIN_RESOLVED_SHOTS = 4
MAX_SAMPLE_GAP_S = 2.5
COUNTERS = ('shots', 'resolved_shots', 'damaging_hits', 'damage',
            'pressure_events', 'cover_damage')
OUTCOMES = ('damaging_hits', 'damage', 'pressure_events', 'cover_damage')
TIMES = ('last_shot_at', 'last_damage_at', 'last_pressure_at', 'last_cover_damage_at')


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _facts(unit, now):
    row = unit.get('combat', {}).get('fire_effects')
    if (unit.get('weapon') not in ('rifle', 'smg', 'pistol') or not isinstance(row, dict)
            or row.get('schema') != 'small_arms_effects/v1' or row.get('complete') is not True):
        return None
    if any(not _number(row.get(k)) or row[k] < 0 for k in COUNTERS):
        return None
    # World transport rounds simulation time to one decimal, while native
    # effect timestamps retain sub-frame precision. Clamp only that rounding
    # tolerance; a materially future timestamp is invalid attribution.
    if any(not _number(row.get(k)) or row[k] > now+.1 for k in TIMES):
        return None
    if any(row[k] != int(row[k]) for k in ('shots', 'resolved_shots', 'damaging_hits', 'pressure_events')):
        return None
    if row['resolved_shots'] > row['shots'] or row['damaging_hits'] > row['resolved_shots']:
        return None
    return dict({k: row[k] for k in COUNTERS}, **{k: min(row[k], now) for k in TIMES})


def _close(state, now, reason):
    episode = state.get('episode', {})
    if episode.get('active'):
        episode.update(active=False, resolved_at=now, resolution=reason)


def observe(history, unit, now):
    """One constant-size observer per living actor; reads no enemy state."""
    if not _number(now):
        return {}
    state = history.setdefault('fire_effect_watch', {})
    previous_at = state.get('observed_at')
    if _number(previous_at) and now < previous_at:
        state.clear()
        previous_at = None
    state['observed_at'] = now
    if unit.get('hp', 1) <= 0:
        _close(state, now, 'unit_removed')
        state.update(status='removed', complete=False, ready=False)
        return public(history, now)
    facts = _facts(unit, now)
    if facts is None:
        # Preserve notification identity through an incomplete snapshot, but
        # restart the comparison window once complete facts return.
        state.pop('baseline', None)
        state.pop('previous', None)
        state.update(status='unknown', complete=False, ready=False, reason='native_effect_attribution_unavailable')
        return public(history, now)
    previous = state.get('previous')
    backwards = bool(previous and any(facts[k] < previous[k] for k in COUNTERS))
    gap = _number(previous_at) and now-previous_at > MAX_SAMPLE_GAP_S
    if backwards:
        _close(state, now, 'native_counter_reset')
    if not state.get('baseline') or backwards or gap:
        state.update(baseline=dict(facts, time=now), route_at=history.get('route_progress_at', -1),
                     last_gain_at=now, firing_since=None, window={}, reason='new_complete_observation_window')
    gain = bool(previous and not backwards and any(facts[k] > previous[k] for k in OUTCOMES))
    route_at = history.get('route_progress_at', -1)
    route_gain = (_number(route_at) and route_at >= 0 and route_at <= now
                  and route_at > state.get('route_at', route_at))
    state.update(previous=facts, route_at=route_at, complete=True)
    if gain or route_gain:
        _close(state, now, 'native_effect' if gain else 'measured_route_progress')
        state.update(baseline=dict(facts, time=now), last_gain_at=now, firing_since=None)
    fired = bool(previous and not backwards and not gap and facts['shots'] > previous['shots'])
    # Idle time before the first burst is not eight seconds of ineffective
    # shooting. Start at the immediately preceding native comparison sample
    # (at most one second), and restart that window after a long fire break.
    fire_break = facts['last_shot_at'] < 0 or now-facts['last_shot_at'] > 3.
    if fired and previous['last_shot_at'] >= 0 and now-previous['last_shot_at'] > 3.:
        state.update(baseline=dict(previous, time=now), firing_since=None)
    if fire_break:
        state.update(baseline=dict(facts, time=now), firing_since=None)
    elif fired and state.get('firing_since') is None and not gain and not route_gain:
        started = max(previous_at if _number(previous_at) else now, now-1.)
        state.update(baseline=dict(previous, time=started), firing_since=started)
    base = state['baseline']
    window = {k: facts[k]-base[k] for k in COUNTERS}
    window.update(duration_s=round(max(0., now-base['time']), 2),
                  pending_shots=facts['shots']-facts['resolved_shots'])
    state['window'] = window
    recent_fire = facts['last_shot_at'] >= base['time'] and 0 <= now-facts['last_shot_at'] <= 3.
    state['ready'] = bool(unit.get('reload_remaining', 0) <= 0
        and unit.get('survival_reason') != 'incoming_explosive' and unit.get('suppression', 0) < .65)
    low_effect = (state.get('firing_since') is not None and window['duration_s'] >= WINDOW_S
                  and window['resolved_shots'] >= MIN_RESOLVED_SHOTS
                  and window['shots'] >= MIN_RESOLVED_SHOTS and recent_fire
                  and window['pending_shots'] <= 2 and not any(window[k] > 0 for k in OUTCOMES))
    episode = state.get('episode', {})
    if low_effect and state['ready'] and not episode.get('active'):
        serial = state.get('serial', 0)+1
        state['serial'] = serial
        state['episode'] = dict(episode_id=f"{unit.get('id', 'unit')}:fire:{serial}:{now:.3f}",
            active=True, since=now, observed_from=base['time'], local_notified=False,
            commander_notified=False, personal_requested=False)
        episode = state['episode']
    state['status'] = ('low_effect' if episode.get('active') and window['duration_s'] >= WINDOW_S
                       else 'effective' if gain or route_gain else 'observing')
    state['reason'] = ('resolved_shots_without_observed_effect_or_route_progress' if state['status'] == 'low_effect'
                       else 'native_effect_or_route_progress' if gain or route_gain else 'collecting_complete_outcomes')
    return public(history, now)


def public(history, now):
    """Compact model-visible evidence, with unknown and deferred states explicit."""
    state = history.get('fire_effect_watch', {})
    if not state:
        return dict(status='unknown', complete=False, active=False,
                    reason='native_effect_attribution_unobserved')
    episode = state.get('episode', {})
    fresh = _number(now) and _number(state.get('observed_at')) and 0 <= now-state['observed_at'] <= MAX_SAMPLE_GAP_S
    complete = bool(state.get('complete') and fresh)
    active = bool(complete and state.get('status') == 'low_effect' and episode.get('active'))
    result = dict(status=state.get('status', 'unknown') if complete else 'unknown', complete=complete,
        active=active, review_ready=active and bool(state.get('ready')),
        reason=state.get('reason', ''), observed_at=state.get('observed_at'),
        window=copy.deepcopy(state.get('window', {})) if complete else {},
        effect_free_for_s=round(max(0., now-state.get('last_gain_at', now)), 1) if complete else None,
        last_effect_or_route_progress_at=state.get('last_gain_at'),
        basis='complete native small-arms attribution plus measured route progress; fire itself is execution only',
        policy='one coalesced review per episode; no forced movement, weapon change or tactical veto')
    if active:
        result.update({k: episode[k] for k in ('episode_id', 'since', 'observed_from',
            'local_notified', 'commander_notified', 'personal_requested') if k in episode})
        result['unresolved_for_s'] = round(max(0., now-episode['since']), 1)
    return result
