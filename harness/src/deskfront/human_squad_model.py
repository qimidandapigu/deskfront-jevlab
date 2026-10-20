"""Model request lifecycle and scheduling for a Deskfront squad.

This mixin owns provider requests, wall-clock deadlines and stale-response checks;
engine execution remains on the controller and IntentExecutor.
"""
import copy
import json
import math
import sys
import threading
from concurrent.futures import Future

from human_squad_contract import INTENTS
from human_squad_validation import _position, validate_plan, current_region_stage_admission
from squad_region_choices import build as build_squad_region_choices, split_approach
from battlefield_equipment import equipment_route_fact
from combat_prompt import instructions as combat_instructions, model_view, route_instructions
from actor_roster import signature as actor_signature


def _contact_route_note(row):
    """Describe the measured contact trade-off used in a route question.

    This belongs to the provider-bound request builder rather than the
    controller entrypoint.  It intentionally only formats facts already
    validated by the native perception view.
    """
    fact = row.get('contact_approach')
    if not fact:
        return '接敌收益未知：无己方已知接触'
    age = fact.get('age_s')
    seen = '目视' if fact['visible'] else ('记忆' + (f'{age}秒前' if age is not None else '，时间未知'))
    gain = fact['distance_gain']
    change = f'较当前位置接近 {gain:.3f}' if gain >= 0 else f'较当前位置远离 {-gain:.3f}'
    in_range = fact.get('in_weapon_range')
    reach = '终点在几何射程内' if in_range is True else '终点在几何射程外' if in_range is False else '武器射程未知'
    return f"对本兵最近已知敌 {fact['target_id']}（{seen}），终点距离 {fact['destination_distance']:.3f}，{change}；{reach}，射线未验证"


def _equipment_route_note(row):
    fact = row.get('equipment_approach')
    if not fact:
        return ''
    if fact.get('basis') == 'crew_visual_contact_lost':
        return '；当前炮组已失去目视，需重新侦察'
    gain = fact['distance_gain']
    change = f'接近{gain:.3f}' if gain >= 0 else f'远离{-gain:.3f}'
    return (f"；对指定炮位任务{fact['phase']}的目标{fact['target_id']}，{change}，"
            f"终点距离{fact['destination_distance']:.3f}；炮组射程内={fact.get('in_weapon_range')}，"
            f"接管范围内={fact.get('inside_capture_radius')}；不证明射界或已接管")


def _plan_execution_key(plan):
    """Only executable dependencies revoke accepted squad work.

    Equipment and phase are commander dependencies. Personnel belong to
    the accepted JEV squad assignment and cannot change this plan version.
    """
    equipment = plan.get('equipment_goal') or {}
    state_basis = equipment.get('state_basis')
    equipment_key = (equipment.get('equipment_id'), equipment.get('phase'),
                     tuple((key, state_basis.get(key)) for key in ('faction', 'capturable', 'gunner_id', 'guard_id'))
                     if state_basis else None) if equipment else None
    return (plan.get('region_id'), tuple(plan.get('position', [])), plan.get('radius'),
            plan.get('stage'), equipment_key)


class SquadModelMixin:
    @staticmethod
    def _route_builder():
        """Resolve the legacy public patch point used by harness checks.

        ``human_squad.build_squad_region_choices`` predates this split and is
        intentionally kept as a compatibility seam for deterministic route
        fixtures.  Production calls still resolve to the same implementation.
        """
        public = sys.modules.get('human_squad')
        return getattr(public, 'build_squad_region_choices', build_squad_region_choices)

    def _due(self, role):
        if role == 'executor':
            from survival_review import blocks_duplicate_periodic
            from coordination_handover import blocks_periodic
            if blocks_duplicate_periodic(self) or blocks_periodic(self):
                return False
            if self._order_observation_pending():
                key = (self.world.get('run_id'), self.last_order['order_id'], self.last_order['accepted_tick'])
                if getattr(self, '_order_observation_wait_key', None) != key:
                    self._record('human-review-deferred', role=role, reason='awaiting_accepted_order_snapshot',
                                 order_id=self.last_order['order_id'], accepted_tick=self.last_order['accepted_tick'],
                                 observed_tick=self.world.get('tick'))
                    self._order_observation_wait_key = key
                # Keep the wake and deadline. A stale snapshot would remove
                # keep_assignment and invite a needless replacement route.
                return False
            self._order_observation_wait_key = None
            members = self._tactical_members(self.world)
            escaping = bool(members) and all(u.get('survival_reason') == 'incoming_explosive' for u in members)
            if escaping:
                if not getattr(self, '_escape_review_deferred', False):
                    self._record('human-review-deferred', role=role, reason='whole_squad_explosive_evasion')
                self._escape_review_deferred = True
                # Keep the pending revision and ordinary review deadline.
                # Native escape continues; one safe teammate keeps this lane available.
                return False
            self._escape_review_deferred = False
        if (role == 'executor' and self.revision[role] <= self.consumed[role]
                and self.world.get('time', 0) >= self.next_at[role]
                and not self.pending_commander_plan
                and self._order_matches_plan()):
            now = self.world.get('time', 0)
            members = self._tactical_members(self.world)
            # Only measured ongoing activity can defer a periodic review. A route
            # merely existing or a protective pose is not evidence of progress.
            effective = bool(members) and all(
                now - self.unit_history.get(u['id'], {}).get('progress_at', -100) < 5
                for u in members)
            if effective:
                self.next_at[role] = now + self.config.get('squad_interval', 5.)
                return False
        return (not self.slots[role] and self.clock() >= self.next_wall[role]
                and (self.world.get('time', 0) >= self.next_at[role]
                     or self.revision[role] > self.consumed[role]))

    def _current_region_stage_admission(self, members, context=None):
        """Keep the exhausted phase for this visit; re-evaluate task evidence."""
        context = self._context(members) if context is None else context
        mission = context['mission_status']
        current = self.plan.get('region_id')
        if self.region_stage_limit.get('region_id') != current:
            self.region_stage_limit = {}
        if current and (mission['intermediate_complete'] or mission['approach_stalled']):
            if not self.region_stage_limit:
                self.region_stage_limit = dict(region_id=current,
                    reason='intermediate_complete' if mission['intermediate_complete'] else 'approach_stalled',
                    observed_at=self.world.get('time', 0))
        from task_modes import mode_id
        facts = dict(context, defensive_mission=mode_id(self.world) == 'clear_exit' and self.team != 'green')
        return current_region_stage_admission(facts, self.region_stage_limit.get('reason', ''))

    def _launch(self, role, members, regions=None):
        if self.request_count >= self.config.get('max_requests', 100):
            self.budget_exhausted = True
            return
        context = self._context(members)
        from battlefield_map import build as battlefield_map
        from engagement_feedback import geometry, point_obstructions
        context['tactical_map'] = battlefield_map(self.world, self.topology, self.regions,
                                                members, context['contacts'], self.plan)
        context['engagement_map'] = geometry(self.world, members, context['contacts'], self.regions, self.plan)
        autonomy_reason = self._autonomous_goal_reason(members) if role == 'executor' else None
        autonomous = bool(autonomy_reason)
        autonomy_review_key = self._autonomous_goal_key(autonomy_reason) if autonomous else None
        autonomous_options = {}
        autonomous_equipment_options = {}
        if autonomous and regions is None:
            regions, issue = self._eligible_regions(members)
            if not regions:
                self.feedback = issue or 'waiting_for_fresh_native_navigation'
                return
        if role == 'commander' or autonomous:
            now = self.world.get('time', 0)
            self.failed_regions = {key: value for key, value in self.failed_regions.items() if value['until'] > now}
            if context['mission_status']['prolonged_pressure'] and self.plan:
                self.failed_regions[self.plan['region_id']] = dict(until=now+30, reason='持续受压15秒，需要另一条接近或撤离路线')
            alternatives = {key: value for key, value in regions.items() if key not in self.failed_regions}
            if alternatives:
                regions = alternatives
            context['recent_region_failures'] = copy.deepcopy(self.failed_regions)
            if context['mission_status']['prolonged_pressure']:
                context['replan_constraint'] = '成员长期受压，不能无限等待恢复。请重新选择机动或撤离区域，禁止以取消自保强行推进。候选不足时解释限制。'
            admission = self._current_region_stage_admission(members, context)
            current_id = self.plan.get('region_id')
            regions = copy.deepcopy(regions)
            if current_id in regions:
                regions[current_id].update(admission)
                if not admission['allowed_stages']:
                    regions.pop(current_id)
            context['current_region_stage_admission'] = dict(region_id=current_id, **admission)
            if admission['exhausted_approach_reason']:
                context['replan_constraint'] = ('同区接近阶段已完成或持续停滞，不能重复 approach/reposition。'
                    '当前区域只允许 allowed_stages 列出的有事实依据阶段；否则选择其他可达区域。'
                    '切换阶段不延长原复核期限，不清除失败历史；引擎即时自保仍有效。')
            # In a clear-the-defenders stage with no current contact, an
            # intermediate waypoint is only useful if the next waypoint
            # approaches this stage's search direction. Offer the commander
            # connected forward neighbours instead of lateral oscillation.
            from task_modes import mode_id
            target = self.world.get('world_growth', {}).get('mission', {}).get('target')
            current_region = self.regions.get(self.plan.get('region_id'), {})
            if (mode_id(self.world) == 'clear_exit' and self.team == 'green'
                    and context['mission_status']['intermediate_complete']
                    and not context['mission_status']['acute_recovery']
                    and not context['contacts']
                    and not context['search_intelligence']['last_seen_contacts'] and _position(target)
                    and _position(current_region.get('center'))):
                old_distance = math.dist(current_region['center'], target)
                forward = {key: regions[key] for key in current_region.get('neighbors', [])
                           if key in regions and math.dist(regions[key]['center'], target) < old_distance - .05}
                if forward:
                    regions = forward
                    context['replan_constraint'] = ('已到达中间区域且当前没有目视敌人；下列候选均与当前位置相邻，'
                        '且更接近本段搜索目标。请选择下一可达区域继续接敌，不能在同一纵列横向往返。'
                        '若正在受到急迫威胁，引擎仍可先自保。')
            if not regions:
                self.feedback = 'no_legal_region_stage_wait_for_new_facts'
                self.next_at[role] = now + self.config.get('commander_interval', 20.)
                self.next_wall[role] = self.clock() + self.config.get('commander_cooldown_s', 5.)
                self.consumed[role] = self.revision[role]
                self._record('human-review-deferred', role=role, reason=self.feedback,
                             current_region_stage_admission=context['current_region_stage_admission'])
                return
            context['regions'] = {key: {k: region[k] for k in ('center', 'neighbors', 'radius', 'walkability', 'purpose',
                        'allowed_stages', 'exhausted_approach_reason', 'stage_evidence', 'deadline_policy') if k in region}
                                  for key, region in regions.items()}
            context['engagement_map'] = geometry(self.world, members, context['contacts'], regions, self.plan,
                                                 include_offered=True)
            for rid, region in context['regions'].items():
                region['reachable_member_ids'] = [uid for uid, fact in context['navigation_access']['members'].items()
                    if rid in fact['reachable_destination_ids']]
                region['engagement_checks'] = context['engagement_map'].get('region_checks', {}).get(rid, [])
            if autonomous:
                from human_squad_autonomy import choices as goal_choices
                criteria, autonomous_options = goal_choices(regions)
                if not criteria:
                    return
                questions = {'autonomous_plan': dict(type='choice', criteria=criteria)}
                if context.get('battlefield_equipment'):
                    from human_squad_autonomy import equipment_choices
                    equipment_criteria, autonomous_equipment_options = equipment_choices(
                        context['battlefield_equipment'], members)
                    questions['autonomous_equipment'] = dict(type='choice', criteria=equipment_criteria,
                        instructions='在无可用指挥方案时，由JEV独立选择当前已知装备的阶段任务或none；不猜目标、不指定炮手。此题与自主区域题独立求值，后续小队明确人员与通路，原生确认前不算接管成功。')
                context['planning_authority'] = dict(mode='jev_autonomous',
                    commander_available=False,
                    reason=autonomy_reason,
                    commander_pending=self.slots['commander'] is not None,
                    commander_error=self.role_errors.get('commander', ''),
                    rule='JEV selects a real offered goal now; no inferred commander order or algorithm-selected destination')
                choices = criteria
            else:
                questions = {'plan': dict(type='json')}
                choices = None
        else:
            choices = dict(INTENTS)
            movable = self._members(self.world)
            routing_members = [dict(u, position_role=('fire_support' if
                self.world.get('weapons', {}).get(u.get('weapon'), {}).get('splash', 0) > 0
                else self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {})
                    .get('assignments', {}).get(u['id'], {}).get('role', 'establish_fire')))
                for u in movable]
            region_options = self._route_builder()(routing_members, self.regions, self.topology,
                                                   self.plan['region_id'],
                                                   contacts=context['contacts'], now=context['time'],
                                                   destination_ids=self._active_destination_ids(),
                                                   support_assets=context['support_assets'])
            from wall_bypass_routes import augment as add_wall_bypass_routes
            add_wall_bypass_routes(region_options, routing_members, self.regions, self.topology,
                                   self.world, context['contacts'], self._active_destination_ids(), goal_id=self.plan['region_id'])
            from firing_position_contract import describe as describe_firing_position
            for unit in movable:
                for row in region_options.get(unit['id'], {}).values():
                    row['endpoint_obstructions'] = point_obstructions(self.world, row['position'], context['contacts'])
                    row['firing_position'] = describe_firing_position(unit, row['position'], context['time'], row['endpoint_obstructions'])
                    fact = equipment_route_fact(unit, row.get('position'),
                        context['current_plan'].get('equipment_goal'), context['battlefield_equipment'])
                    if fact:
                        row['equipment_approach'] = fact
            from equipment_assignment import add_questions as equipment_questions
            # All movable members compare the same strategic equipment task;
            # no actor is silently nominated while constructing the menu.
            equipment_questions_context = context['current_plan'].get('equipment_goal')
            from route_choice_evidence import annotate as annotate_route_choices
            annotate_route_choices(region_options, movable, context['contacts'], self.plan['position'])
            from close_engagement import annotate as annotate_close_engagement
            context['close_engagement_comparison'] = annotate_close_engagement(
                region_options, routing_members, context['contacts'], self.world, now=context['time'])
            context['member_region_choices'] = region_options
            from squad_task_contract import relevance as hold_relevance
            context['hold_relevance'] = hold_relevance(context, region_options)
            light = [u for u in movable if u.get('weapon') not in ('rocket', 'cannon')]
            side_members = [u for u in light if any(
                row.get('flankable') for row in region_options.get(u['id'], {}).values())]
            front_members = [u for u in light if any(
                not row.get('flankable') for row in region_options.get(u['id'], {}).values())]
            split_available = any(
                split_approach(side, front)
                for mover in side_members for base in front_members if mover['id'] != base['id']
                for side in region_options[mover['id']].values()
                for front in region_options[base['id']].values())
            context['flank_path_feasibility'] = dict(
                split_candidate_available=split_available,
                side_route_members=[u['id'] for u in side_members],
                front_route_members=[u['id'] for u in front_members])
            expired = self._mission_status(members)['wait_expired']
            resume = (context['engine_squad'].get('phase') == 'cover_ready'
                      and self.plan.get('stage') in ('approach', 'probe', 'reposition')
                      and not context['mission_status']['defending_flag'])
            if (expired or resume) and self.model == 'mock':
                choices.pop('hold'); choices.pop('cover')
                if context['engine_squad'].get('intent') == 'regroup':
                    choices.pop('regroup')
            if resume:
                if self.model == 'mock':choices.pop('regroup', None)
                context['execution_constraint'] = '原生报告旧短时保护完成。比较当前任务、可用成员和持续保护收益，再选择保持或下一段行动；不因计时强制冲锋。尚受压成员继续原生自保。'
            if expired:
                context['hold_relevance']['prior_wait_expired'] = True
                context['hold_relevance']['review_requirement'] = '原阶段等待已到复核期限，不改写原期限；按本轮任务目的、实际区域与新事实明确决定继续或改派，不能用重复理由冒充恢复或任务成果。'
            if self._order_matches_plan() and (not expired or self.model != 'mock'):
                choices = dict(continue_order='保持已接受的全部步兵任务和路线；本次成员参数不执行，支援参数独立；不重建任务或路线，hold可提交本次明确复评记录',
                               revise_order='维持当前小队行动类型，只修改明确选择新任务的成员；其余成员选 keep_assignment', **choices)
            questions = {'intent': dict(type='choice', criteria=choices)}
            if len(light) >= 2:
                questions['flank_mover'] = dict(type='choice',
                    criteria={'not_applicable': '本次不使用这项成员参数',
                        **{u['id']: '可承担机动职责；候选通路见该成员的 route 问题' for u in side_members or light}},
                    instructions='独立预选：假设采用 flank，从当前成员与路线事实中选择适合机动的一名成员；没有合适者可选 not_applicable。你看不到本轮 intent、其他成员或路线答案，不能假定其已配合。最终非 flank 时本题被忽略；实际组合是否分路由回执报告。')
                questions['flank_fire_base'] = dict(type='choice',
                    criteria={'not_applicable': '本次不使用这项成员参数',
                        **{u['id']: '可承担建立火力职责；候选通路见该成员的 route 问题' for u in front_members or light}},
                    instructions='独立预选：假设采用 flank，从当前成员与路线事实中选择适合正面建立火力的一名成员；没有合适者可选 not_applicable。你看不到本轮机动者和路线答案，不要宣称已选了不同的人或协调路线。最终非 flank 时本题被忽略；两名有效且不同的明确成员职责优先于通用 role，同一人不能充当这对角色。')
            for unit in movable:
                accepted = context.get('accepted_assignments', {}).get(unit['id'], {})
                can_keep = accepted.get('keep_available') is True
                role_choices = {'establish_fire': '沿已选路线建立真实射界，不等待别人先开火',
                    'maneuver': '沿已选路线分段机动；重武器可换位跟进，不等于近战突击',
                    'fire_support': '保持有效射界支援同伴；单发武器不等于持续压制'}
                if can_keep:
                    role_choices = dict(keep_role='保留已接受的职责；选择新路线时也可保持职责', **role_choices)
                questions['role_' + unit['id']] = dict(type='choice', criteria=role_choices,
                    instructions='给 ' + unit['id'] + ' 独立预选本阶段职责；本题看不到本轮intent或route答案。continue_order或本兵route=keep_assignment时不执行本答案；有效flank明确成员职责可能覆盖本答案。按weapon_behavior_slots中本兵当前武器习惯，结合存活人数、弹药、射界、武器距离收益与实际射击效果；需要持续接近时明确选 maneuver，需要建立射界时选 establish_fire。已有有效射位时比较保持与继续机动，不因更近就默认更好。人数少时不要互等不存在的火力。合法选择不会被自动改派；职责仍有效则保持。')
                options = region_options.get(unit['id'], {})
                if options or can_keep:
                    questions['route_' + unit['id']] = dict(type='choice',
                        criteria={**({'keep_assignment': '保留 accepted_assignments 中本兵的完整职责和路线，不依赖新菜单；本兵 role 参数不执行'} if can_keep else {}),
                                  **{key: f"区域 {row['region_id']}；{row['relation']}；事实见 member_region_choices.{unit['id']}.{key}"
                                  for key, row in options.items()}},
                        instructions=route_instructions(unit['id']))
            equipment_questions(questions, equipment_questions_context,
                context['battlefield_equipment'], movable, region_options,
                context.get('accepted_assignments', {}))
            support_options = self._support_options(context['contacts'])
            context['support_options'] = support_options
            for asset in support_options:
                questions['support_' + asset['id']] = dict(type='choice', criteria=asset['choices'],
                    instructions='为支援单位 ' + asset['id'] + ' 独立选择阶段任务；不依赖本轮步兵intent答案，continue_order也会消费本题。选择会进入原生执行与失败反馈；炮组不参与步兵移动。engage仅攻击选定目标，support_area授权自动选敌；不能把位置已知当成射界通畅。')
        from task_modes import mode_id
        if mode_id(self.world)=='clear_exit':
            context['mode_objective']=('清除本段红方守军；全部死亡后自动生成下一段，无需前往出口' if self.team=='green' else '守住当前阵地、阻止绿色进攻；绿色才是敌人，保持小队联系')
            context['mission_status']['note']='当前为清场模式；以实际移动、射界、开火和自保为依据，不要求占旗或抵达出口。'
        # One authored role contract replaces incremental prompt string patches.
        primary = 'plan' if role == 'commander' else 'autonomous_plan' if autonomous else 'intent'
        if autonomous:
            from human_squad_autonomy import INSTRUCTIONS as autonomy_instructions
            questions[primary]['instructions'] = autonomy_instructions
        else:
            questions[primary]['instructions'] = combat_instructions(
                role, context, clear=mode_id(self.world) == 'clear_exit')
        if any(r['support'] for r in context.get('actor_roster', [])):
            questions[primary]['instructions'] += ('\nactor_roster说明实际能力：tactical参与战术，movable才可接受步兵路线。'
                '坦克和固定炮组的任务只通过support_*选项提交；个人步兵行动不适用于它们。'
                '没有可移动步兵时仍需规划支援区域与火力任务，固定炮组不需要走到目标区域。'
                'support_execution是实际执行状态，blocked应比较更换目标、任务或让炮组撤离，不要无限重复受阻任务。')
        shared = self.config.get('shared_request_budget')
        if shared is not None and not shared.claim():
            self.budget_exhausted = True
            return
        token = dict(identity=self.identity, members=tuple(sorted(u['id'] for u in members)),
                     plan_version=self.version, critical=self.critical[role], navigation=self.world.get('navigation_revision'),
                     region_id=self.plan.get('region_id'), revision=self.revision[role])
        token['actor_modes'] = actor_signature(self.world, self.team)
        token['member_weapons'] = tuple(sorted((u['id'], u.get('weapon')) for u in members))
        from equipment_assignment import state_key as equipment_state_key
        token['equipment_state'] = equipment_state_key(self.world, self.plan.get('equipment_goal'))
        self.request_serial += 1
        model_context = (self._executor_context(context) if role == 'executor' and not autonomous
                         else self._commander_context(context))
        if role == 'executor' and not autonomous:
            from coordination_handover import context as handover_context
            model_context['handover'] = handover_context(self)
            model_context['cooperation_protocol'] = self.world.get('squad_behavior', {}).get('cooperation_protocol')
            execution = self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {}).get('cooperation_plan')
            if isinstance(execution, dict):
                model_context['cooperation_execution'] = {
                    key: copy.deepcopy(execution[key]) for key in ('schema', 'candidate_id', 'plan_id', 'status', 'support_relations') if key in execution}
                model_context['cooperation_execution']['bindings'] = {
                    uid: {key: copy.deepcopy(row[key]) for key in (
                        'mode', 'role', 'status', 'phase', 'stage', 'until', 'grant_plan_id',
                        'assignment_token', 'assignment_id', 'local_action_revision', 'local_action_active',
                        'handover_waiting', 'local', 'local_options', 'review_due', 'review_reason', 'review_id') if key in row}
                    for uid, row in execution.get('bindings', {}).items() if isinstance(row, dict)}
        if autonomous:
            model_context['planning_authority'] = context['planning_authority']
        model_context = model_view(model_context, role)
        from coordinate_prompt import prepare
        validation_questions = copy.deepcopy(questions)
        coordinate_binding = None
        if self.config.get('coordinate_protocol', True):
            model_context, questions, coordinate_binding = prepare(model_context, questions, role)
        task_binding = None
        if role == 'executor' and not autonomous and self.model != 'mock':
            from squad_task_contract import prepare as prepare_member_tasks
            model_context, questions, task_binding = prepare_member_tasks(model_context, questions)
            if not getattr(task_binding, 'available', True):
                self.feedback = 'no_complete_native_squad_candidate_keep_accepted_work'
                self.next_wall[role] = self.clock() + self.config.get('failure_cooldown_s', 2.)
                self._record('human-review-deferred', role=role, reason=self.feedback,
                             engine_behavior='continue_accepted_order')
                return
        if role == 'executor' and not autonomous:
            from combat_prompt import share_executor_contract
            model_context, questions = share_executor_contract(model_context, questions)
            if getattr(task_binding, 'schema', None) == 'combat-coordination/v1':
                model_context.setdefault('prompt_contract', {}).update(
                    question_evaluation='one_complete_squad_plan_plus_independent_support')
                questions['intent']['instructions'] = ('读取共享完整配合合同和cooperation_candidates；'
                    '一次选择整套步兵计划，包括意图、全部成员职责、路线和装备人员。'
                    '不混搭候选，不假定support_*已执行。')
        request = dict(serial=self.request_serial, role=role, future=Future(), token=token,
                       autonomous_plan=autonomous, autonomous_options=autonomous_options,
                       autonomous_equipment_options=autonomous_equipment_options,
                       autonomy_reason=autonomy_reason, autonomy_review_key=autonomy_review_key,
                       started=self.clock(), started_game=self.world.get('time', 0),
                       completed_at=None, expired=False,
                       squad_task_contract=task_binding is not None,
                       cooperation_contract=getattr(task_binding, 'schema', None) == 'combat-coordination/v1',
                       validation_questions=validation_questions,
                       context=context, model_context=model_context, questions=questions, choices=choices, regions=copy.deepcopy(regions),
                       member_region_choices=copy.deepcopy(context.get('member_region_choices', {})),
                       accepted_assignments=copy.deepcopy(context.get('accepted_assignments', {})),
                       support_options=copy.deepcopy(context.get('support_options', [])))
        self.slots[role] = request
        self.request_count += 1
        self.commander_calls += role == 'commander'
        self.executor_calls += role == 'executor'
        self.consumed[role] = self.revision[role]
        self.next_at[role] = self.world.get('time', 0) + (self.config.get('commander_interval', 20.) if role == 'commander' else self.config.get('squad_interval', 5.))
        self.next_wall[role] = self.clock() + self.config.get(
            'commander_cooldown_s' if role == 'commander' else 'squad_cooldown_s',
            5. if role == 'commander' else 2.)
        self._record('human-model-request', request_serial=request['serial'], role=role, token=token,
                     planning_mode='jev_autonomous_goal' if autonomous else role,
                     source='local_rules_baseline' if self.model == 'mock' else 'model',
                     context=model_context,
                     context_chars=len(json.dumps(model_context, ensure_ascii=False, separators=(',', ':'))),
                     cooperation_candidate_count=(len(task_binding.candidates)
                         if getattr(task_binding, 'schema', None) == 'combat-coordination/v1' else None),
                     full_context_chars=len(json.dumps(context, ensure_ascii=False, separators=(',', ':'))),
                     questions_chars=len(json.dumps(questions, ensure_ascii=False, separators=(',', ':'))),
                     questions=questions)

        def ask():
            try:
                if self.model == 'mock':
                    result = self._baseline(request)
                else:
                    result = self.game.ask(model_context, questions, **({'role': 'commander'} if role == 'commander' else {}))
                    if task_binding:
                        self._record('human-member-task-response', role=role, request_serial=request['serial'], response=result)
                        result = task_binding.decode(result)
                    if coordinate_binding:
                        self._record('human-coordinate-response', role=role, request_serial=request['serial'], response=result)
                        result = coordinate_binding.decode(result)
                # Mark completion before publishing the Future.  A paused game can
                # delay harvesting for a long time; the deadline is about transport
                # completion, not when the next active tick happens to observe it.
                request['completed_at'] = self.clock()
                request['future'].set_result(result)
            except Exception as error:
                request['completed_at'] = self.clock()
                request['future'].set_exception(error)
        # A stalled transport must neither spawn concurrent retries nor keep the process alive.
        threading.Thread(target=ask, name='human-' + role, daemon=True).start()

    def _baseline(self, request):
        context = request['context']
        if request['role'] == 'commander':
            objective = context.get('objective', {}).get('position') or context['members'][0]['position']
            from task_modes import mode_id
            if mode_id(self.world) == 'clear_exit':
                if self.team == 'green':
                    # The mock rehearsal has no model to infer a search
                    # direction. Use the generated stage's far edge instead
                    # of the first soldier's position, which made completed
                    # approach plans alternate between rear spawn regions.
                    stage_target = self.world.get('world_growth', {}).get('mission', {}).get('target')
                    if _position(stage_target):
                        objective = stage_target
                else:
                    objective = context['members'][0]['position']
            current = context['current_plan'].get('region_id')
            preferred = 'hold' if mode_id(self.world) == 'clear_exit' and self.team != 'green' else 'approach'
            candidates = {key: row for key, row in request['regions'].items()
                          if preferred in row.get('allowed_stages', {preferred})}
            candidates = candidates or request['regions']
            key = current if current in candidates else min(candidates, key=lambda k: math.dist(candidates[k]['center'], objective))
            allowed = candidates[key].get('allowed_stages', [preferred])
            selected_stage = preferred if preferred in allowed else allowed[0]
            value = dict(region_id=key, objective='规则基线：结伴接近目标区域并保持掩护',
                         risk='规则基线只知道当前感知，通路采样不证明安全',
                         stage=selected_stage,
                         replan_when='通路失效或成员损失', completion='小队到达并建立位置')
            return dict(requestId='baseline-' + str(request['serial']), source='local_rules_baseline',
                        answers={'plan': {'type': 'json', 'value': value}})
        choices = request['choices']
        stressed = any(u.get('suppression', 0) > .6 or u.get('hp', 100) < u.get('max_hp', 100) * .4 for u in context['members'])
        choice = 'regroup' if stressed else ('bound' if context['contacts'] else 'advance')
        if choice not in choices:
            choice = 'bound' if context['contacts'] else 'advance'
        if context.get('engine_squad', {}).get('intent') == choice and 'continue_order' in choices:
            choice = 'continue_order'
        answers = {'intent': dict(type='choice', choice=choice, confidence=1,
                                 probabilities={key: int(key == choice) for key in choices})}
        answers.update({'support_' + row['id']: dict(type='choice', choice='support_area')
                        for row in request.get('support_options', [])})
        return dict(requestId='baseline-' + str(request['serial']), source='local_rules_baseline', answers=answers)

    def _valid_token(self, request, members):
        token = request['token']
        if token['identity'] != self.identity:
            return 'authority_changed'
        if token['members'] != tuple(sorted(u['id'] for u in members)):
            return 'membership_changed'
        if 'member_weapons' in token and token['member_weapons'] != tuple(sorted((u['id'], u.get('weapon')) for u in members)):
            return 'weapon_changed'
        if 'actor_modes' in token and token['actor_modes'] != actor_signature(self.world, self.team):
            return 'actor_capability_changed'
        if token['navigation'] != self.world.get('navigation_revision'):
            return 'navigation_changed'
        if token['critical'] != self.critical[request['role']]:
            return 'critical_event_changed'
        if request['role'] == 'executor' and token['plan_version'] != self.version:
            return 'commander_plan_changed'
        if request['role'] == 'executor' and 'equipment_state' in token:
            from equipment_assignment import state_key as equipment_state_key
            if token['equipment_state'] != equipment_state_key(self.world, self.plan.get('equipment_goal')):
                return 'equipment_control_changed'
        return None

    def _harvest(self, role, members):
        request = self.slots[role]
        if not request:
            return
        self._check_deadline(role)
        if not request['future'].done():
            return
        self.slots[role] = None
        response = None
        try:
            response = request['future'].result()
            completed_at = request.get('completed_at')
            now = self.clock()
            transport_elapsed = max(0., (completed_at if completed_at is not None else now) - request['started'])
            harvest_wait = max(0., now - completed_at) if completed_at is not None else 0.
            self._record('human-model-response', request_serial=request['serial'], role=role,
                         response=response, elapsed_s=transport_elapsed + harvest_wait,
                         transport_elapsed_s=transport_elapsed, harvest_wait_s=harvest_wait)
            stale = 'wall_deadline_expired' if request['expired'] else self._valid_token(request, members)
            if stale:
                self.discarded += 1
                self.revision[role] += 1
                self._record('human-model-discarded', request_serial=request['serial'], role=role, reason=stale)
                return
            if role == 'commander':
                value = response['answers']['plan']['value']
                plan = validate_plan(value, request['regions'])
                from commander_tactical_brief import validate_tactical_brief
                brief = validate_tactical_brief(value.get('tactical_brief'), request['regions'], request['context'])
                if brief:
                    plan['tactical_brief'] = brief
                from battlefield_equipment import live_plan_brief, validate_equipment_goal
                goal = validate_equipment_goal(value.get('equipment_goal'), request['context'].get('battlefield_equipment', []), members)
                if goal:
                    plan['equipment_goal'] = goal
                if live_plan_brief(plan, self.world, self.team, members).get('requires_replan'):
                    raise ValueError('plan_dependency_or_equipment_changed_replan_from_current_state')
                if plan['region_id'] not in self._active_destination_ids():
                    raise ValueError('commander_region_no_longer_exists')
                self.commander_failures = 0
                if self.plan:
                    self.pending_commander_plan = dict(plan=plan, request=request, response=response)
                    self._record('human-commander-plan-deferred', request_serial=request['serial'],
                                 reason='preserve_current_work_until_squad_review', plan=plan)
                else:
                    self._apply_plan(plan, request, response,
                        'local_rules_baseline' if self.model == 'mock' else 'deepseek_commander')
            elif request.get('autonomous_plan'):
                key = response.get('answers', {}).get('autonomous_plan', {}).get('choice')
                options = request['autonomous_options']
                if key not in options:
                    raise ValueError('autonomous_plan_not_offered')
                if self.plan and request.get('autonomy_reason') == 'missing_plan':
                    raise ValueError('autonomous_plan_superseded')
                plan = validate_plan(options[key], request['regions'])
                equipment_options = request.get('autonomous_equipment_options')
                if equipment_options:
                    equipment_key = response.get('answers', {}).get('autonomous_equipment', {}).get('choice')
                    if equipment_key not in equipment_options:
                        raise ValueError('autonomous_equipment_not_offered')
                    if equipment_options[equipment_key]:
                        from battlefield_equipment import validate_equipment_goal
                        goal = validate_equipment_goal(equipment_options[equipment_key],
                            self._context(members)['battlefield_equipment'], members)
                        goal['source'] = 'jev_autonomous_intent_not_personnel_assignment'
                        plan['equipment_goal'] = goal
                if plan['region_id'] not in self._active_destination_ids():
                    raise ValueError('autonomous_region_no_longer_exists')
                self._apply_plan(plan, request, response, 'jev_autonomous')
                self.autonomous_review_key = self._autonomous_goal_key(request['autonomy_reason'])
            else:
                answer = response['answers']['intent']
                choice = answer.get('choice') if isinstance(answer, dict) and answer.get('type') == 'choice' else None
                if choice not in request['choices']:
                    raise ValueError('invalid_executor_intent')
                movable = self._members(self.world)
                # Validate infantry continuation before support submissions mutate
                # their pending receipts. Support-only tasks have their own checks.
                if choice in ('continue_order', 'revise_order') and movable and not self._order_matches_plan():
                    raise ValueError('engine_order_changed_while_deciding')
                from equipment_assignment import select_assignment
                request['selected_equipment_assignment'] = select_assignment(
                    self.plan.get('equipment_goal'), response,
                    dict(request, questions=request.get('validation_questions', request['questions'])), movable,
                    self._equipment_assignment(), self.world, self.team, self.version)
                self._submit_support(response, request)
                # Confidence is diagnostic. A valid selected action is never filtered by probability.
                if choice == 'continue_order':
                    # An authored hold review is an explicit acknowledgement,
                    # not a new route/order. Other continuation remains inert.
                    if movable:self._submit(self.last_order['intent'], movable, response, request)
                    else:
                        self.kept_orders += 1
                        self._record('human-order-kept', request_serial=request['serial'],
                                     reason='explicit_continue_order', order_id=(self.last_order or {}).get('order_id'))
                elif choice == 'revise_order':
                    if movable:self._submit(self.last_order['intent'], movable, response, request)
                else:
                    if movable:self._submit(choice, movable, response, request)
            self.role_errors[role] = ''
            self.error = next((error for error in self.role_errors.values() if error), '')
            self.feedback = ''
            self.call_log.append(dict(run_id=self.world.get('run_id'), unit_id=self.squad_id,
                                      role=role, status='selected', response=response, context=request['context']))
        except Exception as error:
            # Error strings may contain provider URLs; log the bounded type and local validation only.
            detail = str(error) if isinstance(error, (ValueError, KeyError)) else type(error).__name__
            # Keep the provider boundary diagnostic useful without copying an
            # arbitrary exception string (which may contain URLs or credentials).
            if isinstance(error, RuntimeError) and str(error).strip() in {
                    'request-timeout', 'request-aborted', 'request-cancelled',
                    'session_stopped', 'quickplay_protocol_mismatch'}:
                detail = str(error).strip()
            self.error = role + '_request_failed:' + detail[:160]
            self.role_errors[role] = self.error
            self.feedback = self.error
            self.revision[role] += 1
            delay = self.config.get('failure_cooldown_s', 2.)
            if role == 'commander':
                self.commander_failures += 1
                delay = min(60., max(5., self.config.get('commander_cooldown_s', 5.))
                            * 2 ** min(4, self.commander_failures - 1))
            self.next_wall[role] = max(self.next_wall[role], self.clock() + delay)
            self._record('human-model-failed', request_serial=request['serial'], role=role,
                         reason=self.error, retry_after_s=delay,
                         engine_behavior='jev_autonomous_when_no_plan' if not self.plan else 'continue_accepted_order')
    def _apply_plan(self, plan, request, response, source):
        members = self._tactical_members(self.world)
        same_region = self.plan.get('region_id') == plan['region_id']
        same_stage = same_region and self.plan.get('stage') == plan['stage']
        mission = self._mission_status(members)
        if (self.plan.get('stage') == 'recover' and plan['stage'] == 'recover'
                and not mission['acute_recovery']
                and self.world.get('time', 0) - (self.stage_started or 0) >= 15):
            raise ValueError('recovery_complete_choose_reposition_or_approach_not_another_rear_region')
        if same_region:
            live_admission = self._current_region_stage_admission(members)
            if plan['stage'] not in live_admission['allowed_stages']:
                raise ValueError('commander_stage_no_longer_supported_by_current_facts')
        # Narrative rewording is useful context, but must not revoke
        # in-flight squad/soldier work when the executable plan is unchanged.
        changed = _plan_execution_key(self.plan) != _plan_execution_key(plan)
        now = self.world.get('time', 0)
        if not same_region:
            self.region_started = now
            self.region_renewals = 0
            self.arrived_at = None
            self.region_stage_limit = {}
        else:
            self.region_renewals += 1
        if not same_stage and not (self.plan.get('stage') == 'recover' and plan['stage'] == 'recover'):
            self.stage_started = now
        previous_deadline = self.stage_review_at
        self.stage_review_at = now + plan['review_after_s']
        if same_region and previous_deadline is not None:
            self.stage_review_at = min(previous_deadline, self.stage_review_at)
        # A review is an event, not a permanent per-tick request source.
        self.stage_review_notified = bool(same_region and self.stage_review_notified and self.stage_review_at <= now)
        self.plan = dict(plan, source=source,
                         request_id=response.get('requestId'),
                         assessment_basis=dict(observed_game_time=request['started_game'],
                             accepted_game_time=now, source='jev_request_snapshot' if source == 'jev_autonomous' else 'commander_request_snapshot'))
        if changed:
            self.version += 1
            self.revision['executor'] += 1
        self._record('human-autonomous-plan' if source == 'jev_autonomous' else 'human-commander-plan', version=self.version, plan=self.plan)

    def _autonomous_goal_key(self, reason):
        return (self.version, self.plan.get('region_id'), self.plan.get('stage'), self.stage_review_at, reason)

    def _autonomous_goal_reason(self, members):
        if not self.plan:
            return 'missing_plan'
        if self.model == 'mock' or self.pending_commander_plan:
            return None
        if (self.plan.get('source') != 'jev_autonomous' and not self.commander_failures
                and self.slots['commander'] is None):
            return None
        mission = self._mission_status(members)
        reason = ('intermediate_complete' if mission['intermediate_complete'] else
                  'approach_stalled' if mission['approach_stalled'] else
                  'stage_review_due' if self.stage_review_at is not None
                      and self.world.get('time', 0) >= self.stage_review_at else None)
        # A conscious same-stage choice does not create a permanent per-tick
        # request source. Changed goals, new facts and normal squad reviews
        # retain their existing paths; no algorithm chooses the next goal.
        return reason if reason and self._autonomous_goal_key(reason) != self.autonomous_review_key else None

    def _adopt_commander_plan(self, members):
        pending = self.pending_commander_plan
        if not pending:
            return False
        if self.slots['executor'] or self.pending_commands or self._order_observation_pending():
            return False
        self.pending_commander_plan = None
        request, plan = pending['request'], pending['plan']
        stale = self._valid_token(request, members)
        from battlefield_equipment import live_plan_brief
        if not stale and plan['region_id'] not in self._active_destination_ids():
            stale = 'commander_region_no_longer_exists'
        if not stale and live_plan_brief(plan, self.world, self.team, members).get('requires_replan'):
            stale = 'commander_dependency_changed'
        if not stale and plan['region_id'] == self.plan.get('region_id'):
            admission = self._current_region_stage_admission(members)
            if plan['stage'] not in admission['allowed_stages']:
                stale = 'commander_stage_no_longer_supported_by_current_facts'
        if stale:
            self._record('human-commander-proposal-discarded', request_serial=request['serial'], reason=stale)
            self.revision['commander'] += 1
            return False
        try:
            self._apply_plan(plan, request, pending['response'],
                'local_rules_baseline' if self.model == 'mock' else 'deepseek_commander')
        except ValueError as error:
            self._record('human-commander-proposal-discarded', request_serial=request['serial'], reason=str(error))
            self.revision['commander'] += 1
            return False
        return True

    def _check_deadline(self, role):
        request = self.slots[role]
        if not request:
            return
        # The external runtime bounds the live commander route at 18s. Keep
        # a small local grace period for the response/error to cross stdin;
        # do not let an old commander request occupy the squad for 36s.
        deadline = self.config.get('commander_timeout', 20.) if role == 'commander' else self.config.get('timeout', 10.) + 1.
        completed_at = request.get('completed_at')
        if not request['expired'] and completed_at is None and request['future'].done():
            # The completion timestamp is written immediately before publishing
            # the Future. This branch only protects the tiny publication race.
            return
        elapsed = ((completed_at if completed_at is not None else self.clock())
                   - request['started'])
        if not request['expired'] and elapsed > deadline:
            request['expired'] = True
            self.error = role + '_wall_timeout_engine_continues'
            self.role_errors[role] = self.error
            self._record('human-model-timeout', request_serial=request['serial'], role=role,
                         elapsed_s=elapsed, engine_behavior='continue_accepted_order')

