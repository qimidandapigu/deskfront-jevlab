"""Data-driven engagement bands for model-facing route evidence.

Godot validates muzzle clearance, safety and paths. These coarse hints never
claim that a region center is a usable firing position.
"""
import json
from pathlib import Path

PROFILES = json.loads((Path(__file__).parent / 'world' / 'engagement_profiles.json').read_text(encoding='utf-8'))


def band(unit):
    weapon_range = unit.get('weapon_range')
    if not isinstance(weapon_range, (int, float)) or weapon_range <= 0:
        return None
    role = unit.get('position_role', 'establish_fire')
    profile = PROFILES.get(role, PROFILES['establish_fire'])
    return (round(weapon_range * profile['preferred_min'], 3),
            round(weapon_range * profile['preferred_max'], 3))


def range_fit(unit, distance):
    preferred = band(unit)
    if preferred is None:
        return 'unknown'
    if distance < preferred[0]:
        return 'too_close'
    if distance <= preferred[1]:
        return 'preferred'
    if distance <= unit['weapon_range']:
        return 'long_edge'
    return 'out_of_range'
