"""Known equipment assignments, separate from personally observed firing targets."""
import copy
import math


def _capture_rule_note(gun):
    rules = gun.get('capture_rules')
    excluded = rules.get('excludes_rocket') if isinstance(rules, dict) else None
    if excluded is True:
        admission = '当前原生规则不允许火箭筒兵接管；一名符合其余资格的步兵即可接管'
    elif excluded is False:
        admission = '当前原生规则允许火箭筒兵参与接管；一名符合其余资格的步兵即可接管'
    else:
        admission = '当前原生兵种接管规则未知，按capture_candidates的实际资格选择执行者'
    return '炮位已无人操作，' + admission + '，第二人不是硬门槛；清除近旁争夺者，借掩护接近并连续停留到接管完成。'


def equipment_brief(world, team, contacts, regions=None):
    known = {c['id']: c for c in contacts if c.get('id')}
    result = []
    for gun in world.get('at_guns', []):
        if gun.get('kind') != 'mortar' or not (gun.get('faction') == team or team in gun.get('seen_by', [])):
            continue
        # A completed fixed support site is retained for world history only.
        # It is not a currently usable asset or another capture opportunity.
        if (gun.get('retired') or gun.get('support_completed') or gun.get('phase') in ('retired', 'completed_support')
                or gun.get('faction') == team and gun.get('available_current_encounter') is False):
            continue
        row = {key: copy.deepcopy(gun[key]) for key in (
            'id', 'kind', 'faction', 'position', 'hp', 'damageable', 'target_policy', 'phase', 'capturable',
            'capture_radius', 'capture_seconds', 'required_crew', 'capture_team',
            'capture_progress', 'crew_alive', 'crew_ids', 'gunner_id', 'guard_id', 'shots',
            'minimum_range', 'range', 'last_block_reason', 'target_available', 'next_shot_in',
            'operator_ready', 'gunner_at_station', 'crew_at_weapon', 'operation_radius', 'gunner_station',
            'ammunition_policy', 'capture_rules', 'capabilities', 'available_current_encounter',
            'available_for_next_encounter', 'next_encounter_available', 'initial_owner', 'manifest_slot_id') if key in gun}
        if 'capabilities' in row:
            row['capabilities'] = _capability_brief(row['capabilities'])
        friendly = gun.get('faction') == team
        own_units = {u['id']: u for u in world.get('units', []) if u.get('faction') == team and u.get('hp', 0) > 0}
        # A native admission check may cover both teams. Only our own soldiers
        # may enter the model-facing view; discovering a gun reveals no enemy
        # candidate identity, suppression or current position.
        if isinstance(gun.get('capture_candidates'), list):
            row['capture_candidates'] = [
                {key: copy.deepcopy(candidate[key]) for key in
                 ('id', 'unit_id', 'eligible', 'unit_eligible', 'reason', 'eligibility_without_distance',
                  'blocking_conditions', 'block_reasons', 'within_radius', 'contested')
                 if key in candidate}
                for candidate in gun['capture_candidates']
                if candidate.get('unit_id', candidate.get('id')) in own_units]
        row['control_status'] = ('friendly_operated' if friendly else
                                 'unmanned' if gun.get('capturable') else 'enemy_operated')
        row['crew'] = []
        for uid in gun.get('crew_ids', []):
            contact = own_units.get(uid, {}) if friendly else known.get(uid, {})
            member = dict(id=uid, role='gunner' if uid == gun.get('gunner_id') else 'guard',
                          equipment_id=gun['id'], visible=bool(contact) if friendly else contact.get('visible', False),
                          identity_source='own_crew_state' if friendly else 'known_equipment_assignment',
                          targeting='friendly_do_not_attack' if friendly else
                                    'native_fire_validation' if contact.get('visible') else 'reacquire_visual_contact')
            # Equipment discovery does not reveal hidden crew coordinates or health.
            for key in ('position', 'last_seen', 'weapon'):
                if key in contact:
                    member[key] = copy.deepcopy(contact[key])
            if friendly:
                for key in ('hp', 'order_mode'):
                    if key in contact:member[key] = contact[key]
            row['crew'].append(member)
            if contact and not friendly:
                contact.update(equipment_id=gun['id'], equipment_role=member['role'])
        row['capture_condition'] = 'engine_capturable_then_one_operator'
        row['operation_status'] = ('ready' if gun.get('operator_ready') is True else
                                   'not_ready' if gun.get('operator_ready') is False else 'unknown')
        if gun.get('damageable') is False:
            row.pop('hp', None)
        row['note'] = ('这是己方控制的迫击炮；炮手不在可调动步兵列表里是因为正在操作，不能当成阵亡或敌军。比较侦察报点、清出友军爆炸范围和保护炮手；引擎按真实视野与射程自动瞄准开炮。' if friendly else
                       _capture_rule_note(gun) if gun.get('capturable') else
                       '炮手倒下后警戒兵可接替；capturable=false时尚不可接管，先依据实际目视处理炮组。炮组身份关联不等于目视或射界；未见炮组时先接近侦察。')
        row['note'] += ' crew_alive是分配给炮位的存活人数，不代表人在炮旁或能开火；operator_ready才表示实际可操作，返程或避险期间不能开炮。夺炮只以引擎capturable=true为准。'
        if regions and isinstance(row.get('position'), (list, tuple)):
            row['region_id'] = min(regions, key=lambda key: math.dist(regions[key]['center'], row['position']))
            row['region_basis'] = 'nearest_native_region_not_safe_route'
        result.append(row)
    return result


def equipment_opportunities(equipment, members, contacts, weapon_configs=None):
    """Comparable discovered capture facts; no route or tactical choice is made.

    Distances are straight-line measurements. Native eligibility and payload
    configuration remain separate from safe navigation and actual hit results.
    A missing native field stays unknown rather than acquiring a policy default.
    """
    weapon_configs = weapon_configs or {}
    visible_armor = [contact for contact in contacts
                     if contact.get('visible') is True and contact.get('kind') == 'tank'
                     and _point(contact.get('position'))]
    result = []
    for gun in equipment:
        if gun.get('kind') != 'mortar' or gun.get('capturable') is not True or not _point(gun.get('position')):
            continue
        native_candidates = {row.get('unit_id', row.get('id')): row
                             for row in gun.get('capture_candidates', [])}
        candidates = []
        for unit in members:
            if not unit.get('id') or not _point(unit.get('position')) or unit.get('hp', 0) <= 0:
                continue
            distance = math.dist(unit['position'], gun['position'])
            native = native_candidates.get(unit['id'], {})
            candidate = {key: copy.deepcopy(unit[key]) for key in
                         ('id', 'hp', 'max_hp', 'weapon', 'suppression', 'survival_reason') if key in unit}
            candidate.update(distance=round(distance, 3), distance_basis='euclidean_not_navigation_cost',
                             in_capture_radius=(native['within_radius'] if isinstance(native.get('within_radius'), bool)
                                                else distance <= gun['capture_radius']
                                                if _number(gun.get('capture_radius')) else None),
                             path_cost=None, path_status='unknown_not_queried',
                             native_capture_eligible=native.get('eligible'),
                             eligibility_without_distance=native.get('eligibility_without_distance'),
                             native_admission_reason=native.get('reason',
                                 ','.join(native['block_reasons']) if native.get('block_reasons') else None),
                             contested=native.get('contested'),
                             emergency_status=('active' if unit.get('survival_reason') else 'inactive')
                                              if 'survival_reason' in unit else 'unknown')
            if 'blocking_conditions' in native or 'block_reasons' in native:
                candidate['native_blocking_conditions'] = copy.deepcopy(native.get('blocking_conditions', native.get('block_reasons')))
            candidates.append(candidate)
        candidates.sort(key=lambda row: (row['distance'], row['id']))
        capability = {key: copy.deepcopy(gun.get('capabilities', {}).get(key)) for key in
                      ('damage', 'armor_multiplier', 'top_attack', 'tank_damage_multiplier',
                       'accuracy', 'dispersion_model', 'splash', 'setup_seconds',
                       'single_setup_seconds', 'cooldown', 'single_crew_cooldown')}
        capability.update(ammunition_policy=gun.get('ammunition_policy'),
                          basis='native_equipment_snapshot',
                          direct_damage_before_target_armor=_armor_payload(gun.get('capabilities', {})),
                          tank_effect_basis=('top_attack_payload_times_tank_multiplier_before_blast_and_shield'
                                             if capability.get('top_attack') is True else
                                             'damage_times_armor_and_tank_multipliers_before_directional_armor'),
                          firing_arc='unknown_not_queried', actual_hit_damage=None)
        single_crew = gun.get('capabilities', {}).get('single_crew')
        if isinstance(single_crew, dict):
            capability['single_crew'] = {key: copy.deepcopy(single_crew[key]) for key in
                                       ('damage', 'armor_multiplier', 'top_attack', 'tank_damage_multiplier',
                                        'accuracy', 'splash', 'cooldown', 'setup_seconds')
                                       if key in single_crew}
        armor_rows = []
        for tank in visible_armor:
            distance = math.dist(gun['position'], tank['position'])
            weapon_rows = []
            for unit in members:
                if unit.get('hp', 0) <= 0 or not _point(unit.get('position')):
                    continue
                config = weapon_configs.get(unit.get('weapon'), {})
                weapon_rows.append(dict(unit_id=unit['id'], weapon=unit.get('weapon'),
                    damage=config.get('damage'), armor_multiplier=config.get('armor_multiplier'),
                    direct_damage_before_target_armor=_armor_payload(config),
                    distance=round(math.dist(unit['position'], tank['position']), 3),
                    weapon_range=config.get('range'), basis='native_weapon_config',
                    actual_hit_damage=None, firing_line='unknown_not_queried'))
            armor_rows.append(dict(id=tank.get('id'), equipment_distance=round(distance, 3),
                position_basis='current_visible_contact', distance_basis='euclidean_not_navigation_cost',
                in_equipment_range=(gun['minimum_range'] <= distance <= gun['range']
                                    if _number(gun.get('minimum_range')) and _number(gun.get('range')) else None),
                friendly_blast_clearance='unknown_not_queried', own_weapon_comparison=weapon_rows))
        progress, seconds = gun.get('capture_progress'), gun.get('capture_seconds')
        result.append(dict(equipment_id=gun['id'], control_status=gun.get('control_status'),
            candidates=candidates, capture_radius=gun.get('capture_radius'),
            capture_rules=copy.deepcopy(gun.get('capture_rules', {})),
            capture_seconds=seconds, capture_team=gun.get('capture_team'), capture_progress=progress,
            remaining_capture_seconds=(round(seconds * (1 - progress), 3)
                                       if _number(seconds) and _number(progress) and 0 <= progress <= 1 else None),
            capability=capability, visible_armor=armor_rows,
            interpretation='候选按直线距离排列，不代表导航代价或安全路线；接管资格以引擎检查为准。伤害是配置载荷在目标装甲方向衰减前的值，散射、射界、爆炸距离与遮挡仍由引擎执行；没有自动选择夺炮。'))
    return result


def personal_equipment_opportunities(opportunities, unit_id):
    """A personal JEV lane sees only its own admission and weapon comparison."""
    rows = []
    for opportunity in opportunities:
        candidates = [candidate for candidate in opportunity.get('candidates', []) if candidate.get('id') == unit_id]
        if not candidates:
            continue
        row = copy.deepcopy(opportunity)
        row['candidates'] = copy.deepcopy(candidates)
        for armor in row.get('visible_armor', []):
            armor['own_weapon_comparison'] = [weapon for weapon in armor.get('own_weapon_comparison', [])
                                              if weapon.get('unit_id') == unit_id]
        rows.append(row)
    return rows


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _capability_brief(config):
    """Static equipment rules cannot disclose an unseen target's live range."""
    if not isinstance(config, dict):
        return {}
    keys = ('damage', 'armor_multiplier', 'top_attack', 'tank_damage_multiplier', 'accuracy',
            'splash', 'setup_seconds', 'single_setup_seconds', 'cooldown', 'single_crew_cooldown',
            'range', 'minimum_range', 'projectile_speed', 'pressure', 'cover_damage',
            'fire_mode', 'dispersion_model')
    row = {key: copy.deepcopy(config[key]) for key in keys if key in config}
    if isinstance(config.get('single_crew'), dict):
        row['single_crew'] = {key: copy.deepcopy(config['single_crew'][key]) for key in keys
                              if key in config['single_crew']}
    return row


def _point(value):
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(_number(n) for n in value)


def _armor_payload(config):
    damage, multiplier = config.get('damage'), config.get('armor_multiplier')
    tank_multiplier = config.get('tank_damage_multiplier', 1.)
    # Existing native weapons omit the optional tank-only modifier and retain
    # their payload. This is a multiplicative engine rule, not a strength guess.
    if not _number(tank_multiplier):
        return None
    if config.get('top_attack') is True:
        return round(damage * tank_multiplier, 3) if _number(damage) else None
    return round(damage * multiplier * tank_multiplier, 3) if _number(damage) and _number(multiplier) else None


def equipment_task(goal, equipment, units):
    """Report progress on the model-selected goal without choosing its action."""
    if not isinstance(goal, dict):
        return None
    gun = next((row for row in equipment if row.get('id') == goal.get('equipment_id')), None)
    if gun is None:
        return None
    actor = next((u for u in units if u.get('id') == goal.get('actor_id')), None)
    visible = [c['id'] for c in gun.get('crew', []) if c.get('visible') and c.get('targeting') != 'friendly_do_not_attack']
    engageable = actor.get('combat', {}).get('engageable_targets', []) if actor else []
    distance = math.dist(actor['position'], gun['position']) if actor and gun.get('position') else None
    return dict(equipment_id=gun['id'], phase=goal.get('phase'), actor_id=goal.get('actor_id'),
                support_ids=copy.deepcopy(goal.get('support_ids', [])),
                assignment_status=goal.get('assignment_status', 'unknown'),
                control_status=gun.get('control_status'), capturable=gun.get('capturable'),
                operator_ready=gun.get('operator_ready'), visible_crew_ids=visible,
                actor_engageable_crew_ids=[uid for uid in visible if uid in engageable],
                actor_distance_to_weapon=round(distance, 3) if distance is not None else None,
                actor_in_capture_radius=(distance <= gun['capture_radius'] if distance is not None
                                         and isinstance(gun.get('capture_radius'), (int, float)) else None),
                capture_progress=gun.get('capture_progress'),
                completion_basis='接近或到位不算完成；attack_crew看炮组真实失去控制，capture看炮位真实变为己方，射程内不证明可射击')


def equipment_route_fact(unit, destination, goal, equipment):
    """Describe a candidate against its explicit equipment task, not a nearby tank."""
    if not isinstance(goal, dict) or not isinstance(destination, (list, tuple)) or len(destination) != 2:
        return None
    # Before the squad selects personnel, compare every offered member's
    # route to the strategic task. Personal callers supply an explicit role.
    if 'actor_id' in goal and unit.get('id') not in [goal.get('actor_id'), *goal.get('support_ids', [])]:
        return None
    gun = next((row for row in equipment if row.get('id') == goal.get('equipment_id')), None)
    if gun is None or not isinstance(gun.get('position'), (list, tuple)):
        return None
    target, target_id, basis = gun['position'], gun['id'], 'known_fixed_weapon_position'
    if goal.get('phase') == 'attack_crew':
        visible = [c for c in gun.get('crew', []) if c.get('visible') and
                   c.get('targeting') != 'friendly_do_not_attack' and isinstance(c.get('position'), (list, tuple))]
        if not visible:
            return dict(equipment_id=gun['id'], phase='attack_crew', basis='crew_visual_contact_lost',
                        visible_crew_ids=[], firing_line='unverified')
        crew = min(visible, key=lambda c: math.dist(unit['position'], c['position']))
        target, target_id, basis = crew['position'], crew['id'], 'visible_assigned_crew_position'
    current, remaining = math.dist(unit['position'], target), math.dist(destination, target)
    weapon_range = unit.get('weapon_range')
    fact = dict(equipment_id=gun['id'], phase=goal.get('phase'), target_id=target_id, basis=basis,
                destination_distance=round(remaining, 3), distance_gain=round(current-remaining, 3),
                firing_line='unverified')
    if basis == 'visible_assigned_crew_position':
        fact['in_weapon_range'] = remaining <= weapon_range if isinstance(weapon_range, (int, float)) else None
    if goal.get('phase') == 'capture':
        fact['inside_capture_radius'] = remaining <= gun['capture_radius'] if isinstance(gun.get('capture_radius'), (int, float)) else None
    return fact


def live_plan_brief(plan, world, team, members):
    """Remove invalid narrative dependencies without inventing replacement tactics."""
    brief = copy.deepcopy(plan)
    living = {u['id'] for u in members}
    unavailable = {u['id'] for u in world.get('units', [])
                   if u.get('faction') == team and u.get('id') not in living}
    dependencies = sorted(uid for uid in unavailable
                          if any(uid in str(brief.get(key, '')) for key in ('objective', 'wait_for')))
    goal = brief.get('equipment_goal') or {}
    gun = next((g for g in world.get('at_guns', []) if g.get('id') == goal.get('equipment_id')), None)
    basis = goal.get('state_basis')
    if gun and basis and any(gun.get(key) != value for key, value in basis.items()):
        brief.update(objective='', risk='', wait_for='', requires_replan=True,
                     invalid_reason='equipment_control_changed')
        brief.pop('equipment_goal', None)
    if dependencies:
        brief.update(objective='', risk='', wait_for='', invalid_dependencies=dependencies,
                     requires_replan=True, invalid_reason='referenced_member_unavailable')
        brief.pop('equipment_goal', None)
    return brief


def validate_equipment_goal(value, equipment, members):
    """Validate a model's explicit equipment intent; never pick the alternative."""
    if value is None:
        return None  # Existing integrations may omit this optional field.
    if not isinstance(value, dict):
        raise ValueError('equipment_goal_not_object')
    gun = next((g for g in equipment if g.get('id') == value.get('equipment_id')), None)
    if gun is None:
        raise ValueError('equipment_goal_not_discovered')
    phase = value.get('phase')
    if phase not in ('reconnoitre', 'attack_crew', 'capture', 'support_fire', 'defer'):
        raise ValueError('equipment_goal_invalid_phase')
    reason = value.get('reason')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('equipment_goal_missing_reason')
    # Personnel are selected by the existing JEV squad request, never by the
    # strategic plan or a weapon-based fallback.
    if 'actor_id' in value or 'support_ids' in value:
        raise ValueError('equipment_personnel_belongs_to_squad')
    if phase == 'capture' and not gun.get('capturable'):
        raise ValueError('equipment_goal_not_capturable')
    if phase == 'attack_crew' and not any(c.get('visible') for c in gun.get('crew', [])):
        raise ValueError('equipment_goal_crew_unseen_choose_reconnaissance')
    if gun.get('control_status') == 'friendly_operated' and phase in ('capture', 'attack_crew', 'reconnoitre'):
        raise ValueError('equipment_goal_already_friendly_choose_support_or_defer')
    if phase == 'support_fire' and gun.get('control_status') != 'friendly_operated':
        raise ValueError('equipment_goal_support_requires_friendly_operator')
    risk = value.get('risk', '')
    if not isinstance(risk, str):
        raise ValueError('equipment_goal_invalid_risk')
    return dict(equipment_id=gun['id'], phase=phase, risk=risk[:400],
                reason=reason[:400], source='commander_intent_not_personnel_assignment',
                state_basis={key: copy.deepcopy(gun.get(key)) for key in ('faction', 'capturable', 'gunner_id', 'guard_id')})
