"""Read-only cover and firing evidence shared by tactical views.

These facts describe the native cover cycle; they never select a model action.
"""


def cover_phase(unit):
    slot = unit.get('cover_slot')
    if isinstance(slot, dict):
        slot = slot.get('key')
    # The external game's compact observation omits cover_slot, while its
    # full snapshot retains it. cover_id persists throughout the native cycle.
    if not unit.get('cover_id'):
        return 'none'
    if slot is not None and not slot:
        return 'none'
    stance = unit.get('cqb_stance')
    if stance == 'peek':
        return 'peeking'
    if stance == 'hide':
        return 'hiding'
    if unit.get('combat', {}).get('path_active'):
        return 'moving_with_reserved_cover'
    if unit.get('in_cover'):
        return 'at_cover'
    return 'reserved_position_unknown'


def recent_support(unit, now, target_id=None):
    """A recent observed shot can remain valid during a brief native hide step.

    This is evidence of recent covering fire, not a prediction of a future shot.
    """
    shot_at = unit.get('last_shot_at', -100)
    if not isinstance(shot_at, (int, float)) or not 0 <= now - shot_at < 2.3:
        return False
    if target_id and unit.get('last_shot_target') != target_id:
        return False
    combat = unit.get('combat', {})
    check = combat.get('fire_check') or {}
    blocked = (check.get('status') == 'blocked' and
               (not target_id or check.get('target_id') == target_id) and
               isinstance(check.get('time'), (int, float)) and
               0 <= now - check['time'] < 3)
    if blocked:
        return False
    if (unit.get('hp', 0) <= 0 or unit.get('ammo', 0) <= 0 or
            unit.get('reload_remaining', 0) > 0 or unit.get('suppression', 0) >= .72 or
            unit.get('order_mode') == 'self_preserve'):
        return False
    if cover_phase(unit) != 'none':
        return True
    return not combat.get('path_active') and bool(combat.get('engageable_targets'))
