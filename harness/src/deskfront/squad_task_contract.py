"""Whole-squad Choice binding, with historical task helpers retained.

The active contract selects a complete finite cooperation candidate in one
Choice. The old per-member binding remains importable for historical fixtures;
new provider requests use the complete team plan below.
"""
import copy
import math

VERSION = 'deskfront-squad-task/v1'
ROLES = ('establish_fire', 'maneuver', 'fire_support')
AREA_TASKS = {'hold', 'cover', 'regroup'}
ROLE_TEXT = dict(establish_fire='建立射位', maneuver='机动换位', fire_support='火力支援')
PURPOSES = {
    'defend_area': '守住所选阵地区域，阻止敌人通过；没有敌人接近时仍可有守备价值',
    'wait_contact': '在所选位置等已知/任务预期的敌人进入交战窗口；未出现不冒称已压制',
    'maintain_fire': '维护对当前已知目标的有效射位；实际射界和射击结果继续复核',
    'screen_task': '在所选区域屏护队友、炮组或阶段任务，不等于必须近期有射击',
    'recover_then_review': '为当前受威胁成员提供局部恢复空间，条件变化后复评，不等待自动回血',
}
REVIEW_TRIGGERS = {
    'contact_or_route_changed': '敌人进入/离开观察区、接近方向或通路变化时复评；常规小队复核仍保留',
    'fire_or_position_invalid': '射界、守备位置或目标失效时复评；没有开火本身不强制进攻',
    'ally_or_equipment_changed': '受护队友、装备控制或当前任务改变时复评',
    'threat_or_recovery_changed': '威胁、危险或恢复条件变化时复评；装填不是队友移动许可',
}


def relevance(context, routes=None):
    """Measured context, not a distance threshold or a tactical admission rule."""
    plan = context.get('current_plan', {})
    contacts = [row for row in context.get('contacts', []) if row.get('visible')]
    rows = {}
    for member in context.get('members', []):
        uid = member['id']; evidence = context.get('execution_evidence', {}).get('members', {}).get(uid, {})
        row = {key: copy.deepcopy(evidence[key]) for key in (
            'nearest_visible_contact_distance', 'visible_contacts_in_weapon_range',
            'engageable_visible_targets', 'seconds_since_last_shot', 'stationary_seconds',
            'route_progress', 'fire_effectiveness', 'fire_block_reason') if key in evidence}
        if plan.get('position') and member.get('position'):
            row['distance_to_commander_area'] = round(math.dist(member['position'], plan['position']), 3)
        row['accepted_area'] = copy.deepcopy(context.get('accepted_assignments', {}).get(uid, {}).get('task_area', {}))
        row['native_assignment_execution'] = copy.deepcopy(context.get('engine_squad', {}).get('assignment_execution', {}).get(uid, {}))
        rows[uid] = row
    return dict(members=rows, visible_target_ids=[row['id'] for row in contacts],
        current_task=copy.deepcopy(context.get('engine_squad', {}).get('task_contract', {})),
        mission_defence=context.get('mission_status', {}).get('defending_flag', False),
        review_due=context.get('stage_status', {}).get('review_due', False),
        policy='Facts for model comparison only. Distance, no contact, reload and lack of a recent shot do not forbid defence or movement. A hold needs a purpose and an authored area; re-evaluation never forces a charge.')


class Binding:
    def __init__(self, members, hold_modes, focus_options):
        self.members, self.hold_modes, self.focus_options = members, hold_modes, focus_options

    def decode(self, response):
        out = copy.deepcopy(response); answers = out.get('answers', {})
        selected = answers.get('intent', {}).get('choice')
        # Conditional parameters have no effect when continuation keeps work.
        if selected != 'continue_order':
            for uid, mapping in self.members.items():
                value = answers.get('task_' + uid, {}).get('choice')
                if value not in mapping:
                    raise ValueError('squad_member_task_not_offered:' + uid)
                role, route = mapping[value]
                answers['route_' + uid] = dict(type='choice', choice=route)
                if route != 'keep_assignment':
                    answers['role_' + uid] = dict(type='choice', choice=role)
        if selected in self.hold_modes:
            for key, options in (('hold_purpose', PURPOSES), ('hold_review', REVIEW_TRIGGERS), ('hold_focus', self.focus_options)):
                if answers.get(key, {}).get('choice') not in options:
                    raise ValueError('squad_hold_contract_not_offered:' + key)
        return out


def prepare(context, questions):
    """After coordinate projection, join each role/route pair into one Choice."""
    state, out = copy.deepcopy(context), copy.deepcopy(questions)
    from coordinate_prompt import unshare
    facts = unshare(state)  # Read compact refs without expanding the actual wire.
    mappings = {}
    for name in list(out):
        if not name.startswith('route_'): continue
        uid = name[6:]; route_question = out.pop(name)
        role_question = out.pop('role_' + uid, {})
        roles = [role for role in role_question.get('criteria', {}) if role in ROLES]
        mapping, criteria = {}, {}
        for route, description in route_question.get('criteria', {}).items():
            if route == 'keep_assignment':
                mapping[route] = (None, route); criteria[route] = description
                continue
            for role in roles:
                key = role + ':' + route
                mapping[key] = (role, route)
                criteria[key] = ROLE_TEXT[role] + '；' + description
        if not criteria: continue
        mappings[uid] = mapping
        out['task_' + uid] = dict(type='choice', criteria=criteria,
            instructions=('为成员 ' + uid + ' 一起选择职责和路线。冒号前是职责，后面是本轮原生合法路线，二者作为同一个Choice执行。'
                '本题看不到本轮intent或队友答案，不假定其他人已掩护；continue_order时整题忽略。'
                'keep_assignment完整保留本兵已有任务。选hold/cover/regroup时，路线就是明确要去的守备/保护/收拢位置，先实际到位再保持；不是忽略路线而留在出生点。'
                '依据current_plan、hold_relevance及路线的接敌距离、射程、遮挡、当前收益比较：驻守可等待敌人，但应说明守什么、等什么和何时重评。'
                '没有近期射击、单发装填、远程武器或暂未见敌不禁止机动/守备；距离远本身也不是自动改派理由。'
                + route_question.get('instructions', '')))
    # These independent identity questions used to overwrite a member's role
    # without knowing its independently selected route. Joint member choices
    # now own that exact pair. Flank quality remains diagnostic, never a veto.
    out.pop('flank_mover', None); out.pop('flank_fire_base', None)
    old = facts.get('engine_squad', {}).get('intent')
    hold_modes = set(AREA_TASKS)
    focus_options = {'mission_area': '围绕本阶段任务区域守备/等待；具体落位仍由每兵task路线明确，不要求踏到指挥坐标'}
    for contact in facts.get('contacts', []):
        if contact.get('id'):
            focus_options['contact:' + contact['id']] = ('围绕当前已知敌人 ' if contact.get('visible') else '观察最后接触线索 ') + contact['id'] + '；已知位置不证明可射击'
    for kind, key in (('asset', 'support_assets'), ('equipment', 'battlefield_equipment')):
        for asset in facts.get(key, []):
            if isinstance(asset, dict) and asset.get('id'):
                focus_options[kind + ':' + asset['id']] = '屏护当前已知对象 ' + asset['id'] + '；不冒称已取得控制或支援'
    if old in AREA_TASKS: hold_modes.update(('continue_order', 'revise_order'))
    if AREA_TASKS.intersection(out.get('intent', {}).get('criteria', {})) or old in AREA_TASKS:
        out['hold_purpose'] = dict(type='choice', criteria=copy.deepcopy(PURPOSES),
            instructions='假设本轮选择或继续hold/cover/regroup，明确这次驻守、保护或重整的目的。位置来自每兵task所选路线；continue时保留已接受区域。按hold_relevance当前事实判断，不把后方无收益等待称作建立火力；其他行动时忽略。')
        out['hold_review'] = dict(type='choice', criteria=copy.deepcopy(REVIEW_TRIGGERS),
            instructions='假设选择或继续hold/cover/regroup，选择主要复评条件。每次延续都基于本轮事实重新判断目的是否仍成立；这不是无限续期、机械倒计时或计时强攻。个人wait_support期限单独处理；其他行动时忽略。')
        out['hold_focus'] = dict(type='choice', criteria=focus_options,
            instructions='假设选择或继续hold/cover/regroup，明确守备、保护或重整关注的任务区域或当前已知对象。此题不发攻击命令、不替队友选位置；具体站位由本兵task路线决定，个人在该任务区域/通路内选合法精确点。其他行动时忽略。')
    state['squad_task_contract'] = dict(version=VERSION, member_choice='joint_role_and_route',
        evaluation='independent_questions_conditional_consumption',
        candidate_growth='sum(member_route_count * 3), never product across members',
        hold_fields='purpose + per-member authored area + expected contact/mission + review trigger',
        unused_branch_policy='ignored; no hidden role override or substitute route')
    return state, out, Binding(mappings, hold_modes, focus_options)


def selected_hold(response, request, context, intent):
    """Bounded authored meaning; never pretends that the plan has executed."""
    if intent not in AREA_TASKS: return None
    answers = response.get('answers', {})
    purpose = answers.get('hold_purpose', {}).get('choice')
    trigger = answers.get('hold_review', {}).get('choice')
    if purpose not in PURPOSES or trigger not in REVIEW_TRIGGERS:
        # Historical/in-process legacy callers keep their accepted mechanics;
        # all newly sent JEV requests require the explicit conditional fields.
        return None
    plan = context.get('current_plan', {})
    focus_key = answers.get('hold_focus', {}).get('choice', 'mission_area')
    focus_kind, _, focus_id = focus_key.partition(':')
    known_contacts = {row.get('id') for row in context.get('contacts', [])}
    focus = dict(kind=focus_kind)
    if focus_id: focus['id'] = focus_id
    areas = {}
    routes = request.get('member_region_choices', {})
    for uid in sorted(set(routes) | set(request.get('accepted_assignments', {}))):
        options = routes.get(uid, {})
        route = answers.get('route_' + uid, {}).get('choice')
        accepted = request.get('accepted_assignments', {}).get(uid, {})
        continuing = answers.get('intent', {}).get('choice') == 'continue_order'
        row = accepted if continuing or route == 'keep_assignment' else options.get(route, {})
        if row.get('position'):
            native = context.get('engine_squad', {}).get('assignment_execution', {}).get(uid, {})
            radius = native.get('radius', row.get('radius', plan.get('radius'))) if continuing or route == 'keep_assignment' else plan.get('radius')
            areas[uid] = dict(region_id=row.get('region_id'), position=copy.deepcopy(row['position']),
                             endpoint_id=row.get('endpoint_id', ''))
            if isinstance(radius, (int, float)) and not isinstance(radius, bool): areas[uid]['radius'] = radius
    return dict(version=VERSION, purpose=purpose, purpose_text=PURPOSES[purpose],
        member_areas=areas,
        commander_reference_area=dict(region_id=plan.get('region_id'), position=copy.deepcopy(plan.get('position'))),
        focus=focus, watch_target_ids=[focus_id] if focus_kind == 'contact' and focus_id in known_contacts else [],
        wait_for=plan.get('wait_for') or ('敌人进入所选阵地观察/交战窗口' if purpose == 'wait_contact' else PURPOSES[purpose]),
        review_on=trigger, review_text=REVIEW_TRIGGERS[trigger],
        reviewed_game_time=context.get('time'), request_serial=request.get('serial'),
        task_kind=intent, execution_policy='model_selected_member_routes_then_' + intent + '; review_does_not_renew_native_deadline')


def make_review(response, request, context, intent):
    """One actual model response can acknowledge one bounded hold review.

    Native execution owns rearming and idempotence. This never manufactures a
    review on tick/poll, substitutes a route, or revives failed work.
    """
    contract = selected_hold(response, request, context, intent)
    if contract is None: return None
    token = request.get('token', {})
    return dict(id=str(token.get('identity', context.get('squad_id', 'squad'))) + ':' +
        str(request.get('serial', '')) + ':' + str(response.get('requestId', '')),
        decision='continue_' + intent, basis=dict(purpose=contract['purpose'], focus=contract['focus'], review_on=contract['review_on'],
            observed_game_time=context.get('time'), member_areas=copy.deepcopy(contract['member_areas'])))


# Historical callers can explicitly request the old independent-member wire.
# Production prepare is one whole-squad Choice after coordinate projection.
prepare_member_tasks_legacy = prepare


def prepare(context, questions):
    # A current observation must advertise the runtime contract. Older native
    # packages and historical fixtures keep their original supported wire.
    if context.get('cooperation_protocol') != 'combat-coordination/v1':
        return prepare_member_tasks_legacy(context, questions)
    from combat_coordination_candidates import prepare as prepare_cooperation
    return prepare_cooperation(context, questions)
