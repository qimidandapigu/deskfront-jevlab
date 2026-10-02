"""Bounded, coupled encounter budgets. JEV chooses a package, never two unrelated counts.

These are tuning rules, not an estimate of player skill or a predicted win rate.
The engine independently validates capacity and authored deployment sockets.
"""
import math

BASE_SQUAD = 3
MAX_FRIENDLIES = 6
MAX_DEFENDERS = 6


def force_packages(state, hormones=None, phase='explore', ensure_rocket=False):
    units = [u for u in state.get('units', []) if u.get('hp', 0) > 0 and u.get('faction') == 'green']
    if not units or len(units) > MAX_FRIENDLIES:
        return {}
    world=state.get('world_growth',{})
    if world.get('revision')==0 and not world.get('completed') and len(units)==5:
        return {'opening_5v3':dict(friendly_count=0,enemy_count=3,
            projected_friendly_count=5,effective_strength=5,label='首次实际遭遇：现有5名友军，不补员，3名守军；地图仍由JEV搭建')}
    h = hormones or {}
    recovery = phase == 'relax' or h.get('recovery', 0) >= .6
    peak = not recovery and (phase == 'peak' or h.get('pressure', 0) >= .6)
    # Count is primary; injury allows an explicit lighter encounter. A healthy
    # large team must not receive a tiny force just because relax was selected.
    def health_fraction(unit):
        maximum = unit.get('max_hp')
        if type(maximum) not in (int, float) or not math.isfinite(maximum) or maximum <= 0:
            # Unknown health capacity: count this unit, do not invent an injury discount.
            return 1.
        return min(1., unit['hp']/maximum)
    health = sum(health_fraction(u) for u in units)
    packages = {}
    needs_rocket = bool(ensure_rocket) and not any(u.get('weapon') == 'rocket' for u in units)
    max_friends = min(2, MAX_FRIENDLIES-len(units), max(0, BASE_SQUAD-len(units), int(needs_rocket)))
    for friends in range(int(needs_rocket), max_friends+1):
        projected = len(units)+friends
        effective = health+friends
        base = max(2, math.ceil((projected+effective)/2-.15))
        low = max(2, base-(1 if recovery else 0))
        high = min(MAX_DEFENDERS, base+(1 if peak else 0))
        for enemies in range(low, high+1):
            key = f'f{friends}_e{enemies}'
            packages[key] = dict(friendly_count=friends, enemy_count=enemies,
                projected_friendly_count=projected, effective_strength=round(effective, 2),
                label=f'补充 {friends} 人 → 我方 {projected} 人 / 守军 {enemies} 人；'
                    + ('舒缓遭遇' if recovery else '加强防线' if peak else '常规遭遇'))
    return packages


def validate_forces(state, forces, hormones=None, phase='explore', ensure_rocket=False, support_type=None):
    if any(type(forces.get(k)) is not int for k in ('friendly_count', 'enemy_count')):
        return False
    if (support_type or forces.get('support_type')) == 'tank':
        return forces['enemy_count'] == 2 and any(
            forces['friendly_count'] == row['friendly_count']
            for row in force_packages(state, hormones, phase, ensure_rocket).values())
    return any(all(forces[k] == row[k] for k in ('friendly_count', 'enemy_count'))
               for row in force_packages(state, hormones, phase, ensure_rocket).values())
