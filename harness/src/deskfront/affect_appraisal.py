"""Small, observable appraisal for a soldier's JEV emotion question.

Values are game-scale estimates, not medical measurements or emotion decisions.
Only the soldier's own snapshot and reported team losses enter this reducer.
"""
import math


def _bounded(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value)) if math.isfinite(value) else 0.0


def _fade(value, dt, half_life):
    return _bounded(value) * 2 ** (-dt / half_life)


def advance(previous, unit, now, events):
    """Update one soldier's appraisal once per observed game-time snapshot."""
    previous = previous or {}
    dt = max(0.0, now - previous.get('time', now))
    combat = unit.get('combat') or {}
    max_hp = max(1.0, float(unit.get('max_hp') or 1.0))
    suppression = _bounded(unit.get('suppression'))
    survival = unit.get('survival_reason') or ''
    kinds = {event['kind'] for event in events}

    pain = _fade(previous.get('pain', 0), dt, 10.0)
    surprise = _fade(previous.get('surprise', 0), dt, 2.5)
    loss = _fade(previous.get('loss', 0), dt, 40.0)
    relief = _fade(previous.get('relief', 0), dt, 6.0)
    for event in events:
        if event['kind'] == 'received_damage':
            fraction = _bounded(event.get('hp_lost_since_last_observation', 0) / max_hp)
            pain = _bounded(pain + .25 + fraction * .8)
            surprise = max(surprise, .55)
        elif event['kind'] == 'suppression_started':
            surprise = max(surprise, .35)
        elif event['kind'] == 'incoming_threat':
            surprise = max(surprise, .75)
        elif event['kind'] == 'teammate_died':
            # Team status is not evidence that this soldier witnessed the death.
            loss = _bounded(loss + .55)

    immediate_danger = .12  # Combat mission baseline; absence of a contact is not proof of safety.
    if combat.get('engageable_targets'):
        immediate_danger = max(immediate_danger, .42)
    if suppression:
        immediate_danger = max(immediate_danger, .12 + .85 * suppression)
    if combat.get('incoming_threats'):
        immediate_danger = max(immediate_danger, .85)
    if survival:
        immediate_danger = max(immediate_danger, .78 if 'explosive' in survival else .62)
    if 'received_damage' in kinds:
        immediate_danger = max(immediate_danger, .76)
    damage_at = unit.get('last_damage_at', -100)
    if isinstance(damage_at, (int, float)) and damage_at >= 0 and 0 <= now - damage_at < 3:
        immediate_danger = max(immediate_danger, .56)
    danger = max(immediate_danger, _fade(previous.get('danger', .12), dt, 4.0))

    coping = .45 + (.20 if unit.get('in_cover') else 0)
    coping += .15 if combat.get('engageable_targets') and (unit.get('ammo') or 0) > 0 else 0
    coping += .10 if combat.get('path_active') else 0
    coping -= .25 * suppression
    coping -= .18 if combat.get('incoming_threats') else 0
    coping -= .18 if survival else 0
    coping -= .18 if unit.get('path_failure') else 0
    coping = _bounded(coping)

    if 'emergency_ended' in kinds and immediate_danger < .4:
        relief = max(relief, .5)
    if previous.get('danger', 0) >= .55 and danger < .3 and immediate_danger < .3:
        relief = max(relief, .55)
    drive = max(danger * .85, pain * .8, surprise * .75)
    arousal = max(drive, _fade(previous.get('arousal', .12), dt, 12.0))
    strain = _bounded(_fade(previous.get('strain', 0), dt, 150.0)
                      + min(dt, 5.0) * max(0, arousal - .35) / 75.0)
    return dict(time=now, danger=_bounded(danger), pain=pain, arousal=_bounded(arousal),
                coping=coping, strain=strain, loss=loss, surprise=surprise, relief=relief,
                danger_change=_bounded(danger) - previous.get('danger', .12))


def public_state(state):
    """Bound/round once at the request boundary; keep full precision internally."""
    return {name: round(_bounded(state.get(name, 0)), 2)
            for name in ('danger', 'pain', 'arousal', 'coping', 'strain', 'loss', 'surprise', 'relief')} | {
                'danger_change': round(max(-1.0, min(1.0, state.get('danger_change', 0))), 2),
                'scale': '0=low,1=high; danger_change may be negative',
                'scope': 'own_observation_and_reported_team_loss; no_hidden_enemies',
            }


def emotion_support(state, unit):
    """Soft fit scores for all labels; JEV retains the final choice."""
    d, p, a = (state.get(key, 0) for key in ('danger', 'pain', 'arousal'))
    c, s, loss = (state.get(key, 0) for key in ('coping', 'strain', 'loss'))
    surprise, relief = state.get('surprise', 0), state.get('relief', 0)
    blocked = bool(unit.get('path_failure'))
    scores = dict(
        calm=(1-d) * (1-a) * (1-p) * (1-.6*loss),
        # Alert is most apt with manageable danger; injury and low coping
        # make a pure watchful expression less convincing.
        alert=2*d*(1-.7*d) * math.sqrt(c) * (1-.8*p),
        nervous=d * a * (1-.45*c),
        afraid=d * a * (1-c),
        angry=max(.35*p, .55*loss) * c,
        determined=d * c * (.3+.7*s),
        relieved=relief * (1-.5*d),
        sad=.75*loss,
        surprised=.75*surprise,
        confused=(.45 if blocked else .06) * (1-c),
        exhausted=s,
        hurt=p,
        happy=0.0,
    )
    return {key: round(_bounded(value), 2) for key, value in scores.items()}
