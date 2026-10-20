"""Actor capabilities are independent of locomotion and emotional identity."""

SUPPORT_ACTIONS = ('support_area', 'hold_fire', 'engage')


def roster(world, team):
    equipment = {uid: gun['id'] for gun in world.get('at_guns', [])
                 if gun.get('faction') == team and gun.get('kind') == 'mortar'
                 and gun.get('available_current_encounter') is not False
                 and not gun.get('retired') and not gun.get('support_completed')
                 and gun.get('phase') not in ('retired', 'completed_support')
                 for uid in gun.get('crew_ids', [])}
    rows = []
    for unit in world.get('units', []):
        if unit.get('faction') != team or unit.get('hp', 0) <= 0:
            continue
        tank = unit.get('kind') == 'tank' or unit.get('tank', False)
        gun = equipment.get(unit['id']) or unit.get('gun_id', '')
        phase = unit.get('deployment_phase', 'active')
        active = phase == 'active' and unit.get('combat_ready', True)
        mode = 'vehicle' if tank else 'equipment_crew' if gun else 'infantry' if active else phase
        rows.append(dict(id=unit['id'], mode=mode, equipment_id=gun,
                         tactical=active, movable=active and not tank and not gun
                         and not unit.get('garrison_phase'), emotional=not tank,
                         support=active and (tank or bool(gun))))
    return rows


def select(world, team, capability):
    ids = {r['id'] for r in roster(world, team) if r[capability]}
    return [u for u in world.get('units', []) if u.get('id') in ids]


def signature(world, team):
    return tuple((r['id'], r['mode'], r['equipment_id']) for r in roster(world, team) if r['tactical'])


def action_capabilities(world, unit, team):
    row = next((r for r in roster(world, team) if r['id'] == unit['id']), None)
    if row is None:
        return []
    result = []
    if row['movable']:
        result += ['squad.' + k for k in ('advance', 'cover', 'bound', 'flank', 'hold', 'regroup')]
    if row['support']:
        result += ['support.' + k for k in SUPPORT_ACTIONS]
        result += ['support.move_area'] if row['mode'] == 'vehicle' else ['support.release_crew']
    if row['emotional']:
        result.append('presentation.emotion')
    return result


def last_fire(unit):
    return max(unit.get('last_shot_at', -1), unit.get('support_activity', {}).get('last_fire_observed_at', -1))


def effective_range(unit):
    return unit.get('support_activity', {}).get('range', unit.get('weapon_range'))
