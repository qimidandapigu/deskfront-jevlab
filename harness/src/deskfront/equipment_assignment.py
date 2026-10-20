"""JEV squad equipment personnel contract; no tactical defaults or engine actions.

Commander goals identify equipment and phase. This module validates the squad's
explicit personnel against its offered routes and exposes accepted tasks only.
"""
import copy


STATE_FIELDS = ('faction', 'capturable', 'gunner_id', 'guard_id')


def goal_key(goal):
    if not goal:
        return None
    basis = goal.get('state_basis') or {}
    return (goal.get('equipment_id'), goal.get('phase'),
            tuple((key, basis.get(key)) for key in STATE_FIELDS))


def state_key(world, goal):
    if not goal:
        return None
    gun = next((g for g in world.get('at_guns', []) if g.get('id') == goal.get('equipment_id')), None)
    return (goal.get('equipment_id'), tuple((key, gun.get(key)) for key in STATE_FIELDS)) if gun else ('missing', goal.get('equipment_id'))


def assignment_key(assignment):
    if not assignment:
        return None
    return (goal_key(assignment), assignment.get('actor_id'),
            tuple(sorted(assignment.get('support_ids', []))), assignment.get('status'))


def _actor_allowed(unit, phase, gun):
    if not unit.get('id') or unit.get('hp', 0) <= 0:
        return False
    if phase != 'capture':
        return True
    if gun.get('capturable') is not True or unit.get('weapon') == 'cannon':
        return False
    native = next((r for r in gun.get('capture_candidates', [])
                   if r.get('unit_id', r.get('id')) == unit['id']), {})
    if unit.get('weapon') == 'rocket':
        rules = gun.get('capture_rules')
        excluded = rules.get('excludes_rocket') if isinstance(rules, dict) else None
        # Native facts own weapon admission. Keep old packages compatible and
        # do not invent eligibility when neither rule nor candidate proves it.
        if excluded is True:
            return False
        if (excluded is not False and native.get('eligibility_without_distance') is not True
                and native.get('eligible') is not True):
            return False
    # Being outside the radius does not invalidate planning an approach.
    # Native safety, contest and full eligibility are rechecked on execution.
    reasons = native.get('blocking_conditions', native.get('block_reasons', [])) or []
    return not any(reason in ('unsupported_weapon', 'operator_ineligible', 'already_operating',
                              'wrong_faction', 'dead', 'not_active', 'tank', 'assigned',
                              'rocket', 'inactive', 'weapon_unavailable') for reason in reasons)


def live_assignment(goal, accepted, version, world, team, members):
    if not goal:
        return None
    row = dict(equipment_id=goal.get('equipment_id'), phase=goal.get('phase'),
               actor_id=None, support_ids=[], status='awaiting_squad_assignment',
               source='jev_squad_not_engine_choice')
    if goal.get('phase') == 'defer':
        row['status'] = 'deferred_by_commander'
        return row
    if not accepted or accepted.get('plan_version') != version or goal_key(accepted) != goal_key(goal):
        return row
    gun = next((g for g in world.get('at_guns', []) if g.get('id') == goal.get('equipment_id')), None)
    if (not gun or accepted.get('run_id') != world.get('run_id')
            or world.get('control', {}).get(team) != 'lm'
            or accepted.get('control_epoch') != world.get('control_epochs', {}).get(team, 0)
            or any(gun.get(key) != value for key, value in (goal.get('state_basis') or {}).items())):
        row.update(status='invalidated', reason='equipment_or_authority_changed')
        return row
    living = {u['id']: u for u in members}
    actor, support = accepted.get('actor_id'), accepted.get('support_ids', [])
    if accepted.get('status') == 'unassigned':
        row.update(status='unassigned', reason='squad_selected_no_assignment')
        return row
    if (actor not in living or not _actor_allowed(living[actor], goal.get('phase'), gun)
            or any(uid not in living for uid in support)):
        row.update(status='invalidated', reason='assigned_member_unavailable')
        return row
    row.update(actor_id=actor, support_ids=copy.deepcopy(support), status='assigned',
               request_id=accepted.get('request_id'), order_id=accepted.get('order_id'))
    return row


def effective_goal(goal, assignment):
    if not goal:
        return None
    value = copy.deepcopy(goal)
    # Explicit empty personnel also prevents personal route hints from
    # silently assigning the commander's equipment task to every soldier.
    value.update(actor_id=None, support_ids=[])
    if assignment and assignment.get('status') == 'assigned':
        value.update(actor_id=assignment['actor_id'], support_ids=copy.deepcopy(assignment['support_ids']))
    value['assignment_status'] = assignment.get('status') if assignment else 'awaiting_squad_assignment'
    return value


def add_questions(questions, goal, equipment, members, routes, accepted):
    if not goal or goal.get('phase') == 'defer':
        return
    gun = next((g for g in equipment if g.get('id') == goal.get('equipment_id')), {})
    routable = [u for u in members if routes.get(u['id']) or accepted.get(u['id'], {}).get('keep_available')]
    candidates = [u for u in routable if _actor_allowed(u, goal.get('phase'), gun)]
    questions['equipment_actor'] = dict(type='choice', criteria={
        'unassigned': '本轮不分配装备执行者；如无可执行方案明确选择，不能把此选项当已执行装备任务',
        **{u['id']: '作为本阶段装备任务执行者；实际职责与路线由本轮独立预选参数组合并校验' for u in candidates}},
        instructions='为 current_plan.equipment_goal 独立预选执行者或unassigned，看不到本轮intent、role、route和支援答案。仅最终不是continue_order时消费本题；continue_order保持已接受人员。候选合法性仍会复验，不能编造成员或路线。')
    for unit in routable:
        uid = unit['id']
        questions['equipment_support_' + uid] = dict(type='choice', criteria={
            'not_assigned': '假设本成员不是执行者，仍不承担装备支援',
            'support': '假设已有另一名执行者，本成员愿意承担装备支援；实际职责和路线需通过候选验证'},
            instructions='为 ' + uid + ' 独立预选装备支援职责：假设另有执行者且本兵不是执行者时，是否支援 current_plan.equipment_goal。看不到本轮actor答案；continue_order、actor=unassigned或本兵被选为actor时，代码忽略本题。')


def select_assignment(goal, response, request, members, accepted, world, team, version):
    if not goal or goal.get('phase') == 'defer':
        return None
    from battlefield_equipment import equipment_brief
    live = equipment_brief(world, team, [], {})
    gun = next((g for g in live if g.get('id') == goal.get('equipment_id')), None)
    if gun is None or any(gun.get(key) != value for key, value in (goal.get('state_basis') or {}).items()):
        raise ValueError('equipment_control_changed')
    answers, questions = response.get('answers', {}), request.get('questions', {})
    choice = answers.get('intent', {}).get('choice')
    if choice == 'continue_order':
        if not accepted or accepted.get('status') not in ('assigned', 'unassigned'):
            raise ValueError('equipment_assignment_invalid_choose_new_squad_assignment')
        return None  # All personnel remain untouched, just as role/route do.

    def selected(key):
        answer, question = answers.get(key, {}), questions.get(key, {})
        value = answer.get('choice')
        if answer.get('type') != 'choice' or value not in question.get('criteria', {}):
            raise ValueError('invalid_equipment_assignment:' + key)
        return value

    actor = selected('equipment_actor')
    # Speculative questions describe support only if a different actor exists.
    # Ignore unused branches; do not invent an actor or require the model to
    # see another independent question's answer. Used choices stay validated.
    supports = [key.removeprefix('equipment_support_') for key in questions
                if key.startswith('equipment_support_') and actor != 'unassigned'
                and key.removeprefix('equipment_support_') != actor
                and selected(key) == 'support']
    if actor == 'unassigned':
        actor = None
    units = {u['id']: u for u in members}
    if actor is not None and (actor not in units or not _actor_allowed(units[actor], goal.get('phase'), gun)):
        raise ValueError('equipment_actor_no_longer_eligible')
    if any(uid not in units for uid in supports):
        raise ValueError('equipment_support_member_unavailable')
    for uid in ([actor] if actor else []) + supports:
        route = answers.get('route_' + uid, {})
        role = answers.get('role_' + uid, {})
        if route.get('type') != 'choice':
            raise ValueError('equipment_member_requires_explicit_route:' + uid)
        if route.get('choice') == 'keep_assignment':
            if not request.get('accepted_assignments', {}).get(uid, {}).get('keep_available'):
                raise ValueError('equipment_member_keep_unavailable:' + uid)
        elif (route.get('choice') not in request.get('member_region_choices', {}).get(uid, {})
              or role.get('type') != 'choice'
              or role.get('choice') not in questions.get('role_' + uid, {}).get('criteria', {})):
            raise ValueError('equipment_member_requires_explicit_role_and_route:' + uid)
    return dict(equipment_id=goal['equipment_id'], phase=goal['phase'],
                state_basis=copy.deepcopy(goal.get('state_basis', {})), actor_id=actor, support_ids=supports,
                status='assigned' if actor else 'unassigned', source='jev_squad',
                plan_version=version, run_id=world.get('run_id'),
                control_epoch=world.get('control_epochs', {}).get(team, 0), request_id=response.get('requestId'))
