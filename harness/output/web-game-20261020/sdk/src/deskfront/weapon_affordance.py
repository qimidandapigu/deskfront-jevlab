"""Cheap weapon/position comparisons for model choice; never filters options.

All distances are native world units. Native cone parameters describe a spread
disk, not a hit probability. Preferred bands are explicitly advisory tuning.
"""
import math


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def preferred_band(unit):
    radius = unit.get('weapon_range')
    if unit.get('weapon') != 'smg' or not _number(radius) or radius <= 0:
        return None
    # A close-range role should not inherit the rifle-like default range band.
    # Support may stay farther back, but this is never a route/action veto.
    fractions = (.45, .75) if unit.get('position_role') == 'fire_support' else (.30, .60)
    return [round(radius * fraction, 3) for fraction in fractions]


def profile(unit):
    raw = unit.get('combat', {}).get('weapon_profile', {})
    result = {'weapon': unit.get('weapon'), 'preferred_distance_hint': preferred_band(unit),
              'hint_is_constraint': False}
    if not isinstance(raw, dict) or raw.get('schema') != 'small_arms_profile/v1':
        return dict(result, status='unknown', basis='native spread profile unavailable')
    fields = ('range', 'damage', 'shot_interval_s', 'accuracy_parameter', 'base_cone_rad',
              'still_cone_rad', 'current_cone_rad', 'moving_accuracy_multiplier')
    if any(not _number(raw.get(key)) for key in fields):
        return dict(result, status='unknown', basis='incomplete native spread profile')
    if not (raw['range'] > 0 and 0 <= raw['still_cone_rad'] < .5 and 0 <= raw['current_cone_rad'] < .5):
        return dict(result, status='unknown', basis='invalid native spread profile')
    result.update({key: raw[key] for key in fields})
    result.update(status='observed', moving=raw.get('moving') is True,
                  basis='native current weapon parameters; preferred distance is advisory; accuracy is not hit probability')
    return result


def at_distance(unit, distance):
    p = profile(unit)
    if not _number(distance) or distance < 0:
        return {'status': 'unknown'}
    maximum = p.get('range', unit.get('weapon_range'))
    value = {'distance': round(distance, 3), 'in_weapon_range': distance <= maximum if _number(maximum) else None}
    if p['status'] == 'observed':
        value.update(spread_radius_current=round(distance * math.tan(p['current_cone_rad']), 4),
                     spread_radius_still_unpressured=round(distance * math.tan(p['still_cone_rad']), 4),
                     spread_basis='ground_distance_estimate_not_exact_3d_ballistics')
    hint = p.get('preferred_distance_hint')
    if hint:
        value['distance_hint'] = ('closer_than_hint' if distance < hint[0] else
                                  'preferred' if distance <= hint[1] else
                                  'long_edge' if value['in_weapon_range'] else 'out_of_range')
    return value


def site_value(unit, row, now=None):
    """Compare only existing native site checks, without new spatial work."""
    result = []
    for check in row.get('fire_checks', [])[:4]:
        distance = check.get('distance')
        if not _number(distance) or distance < 0:
            continue
        result.append(dict(target_id=check.get('target_id'), native_line_clear=check.get('clear'),
                           **at_distance(unit, distance)))
    return {'targets': result, 'basis': 'existing native site checks; current posture/pressure held constant for comparison, not predicted hit chance or future safety'}
