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

from human_squad_contract import (
    CLEAR_PLAN_INSTRUCTIONS, EXECUTOR_INSTRUCTIONS, INTENTS,
    PLAN_INSTRUCTIONS,
)
from human_squad_validation import _position, validate_plan
from squad_region_choices import build as build_squad_region_choices, split_approach


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
        if (role == 'executor' and self.revision[role] <= self.consumed[role]
                and self.world.get('time', 0) >= self.next_at[role]
                and self._order_matches_plan()):
            now = self.world.get('time', 0)
            members = self._members(self.world)
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

    def _launch(self, role, members, regions=None):
        if self.request_count >= self.config.get('max_requests', 100):
            self.budget_exhausted = True
            return
        shared = self.config.get('shared_request_budget')
        if shared is not None and not shared.claim():
            self.budget_exhausted = True
            return
        context = self._context(members)
        if role == 'commander':
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
            if (context['mission_status']['approach_stalled'] or context['mission_status']['intermediate_complete']) and len(regions) > 1:
                regions = {key: value for key, value in regions.items() if key != self.plan.get('region_id')}
                context['replan_constraint'] = (('中间区域接近阶段已完成，不能重复安排接近同一区域。请选择下一可达区域继续接敌或守备；危险时允许撤离。'
                    if context['mission_status']['primary_objective'] == 'eliminate_opponents' else
                    '中间区域接近阶段已由引擎报告完成，不能重复安排接近同一区域。请选择下一可达区域继续占旗任务；危险时允许撤离。')
                    if context['mission_status']['intermediate_complete'] else
                    '接近任务超过20游戏秒没有任何成员缩短距离，当前区域暂不提供。请选择另一可达区域进行机动或撤离；不要强行冲锋。')
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
                    and not context['contacts'] and _position(target)
                    and _position(current_region.get('center'))):
                old_distance = math.dist(current_region['center'], target)
                forward = {key: regions[key] for key in current_region.get('neighbors', [])
                           if key in regions and math.dist(regions[key]['center'], target) < old_distance - .05}
                if forward:
                    regions = forward
                    context['replan_constraint'] = ('已到达中间区域且当前没有目视敌人；下列候选均与当前位置相邻，'
                        '且更接近本段搜索目标。请选择下一可达区域继续接敌，不能在同一纵列横向往返。'
                        '若正在受到急迫威胁，引擎仍可先自保。')
            context['regions'] = {key: {k: region[k] for k in ('center', 'neighbors', 'radius', 'walkability', 'purpose') if k in region}
                                  for key, region in regions.items()}
            questions = {'plan': dict(type='json', instructions=(CLEAR_PLAN_INSTRUCTIONS
                if context['mission_status']['primary_objective'] == 'eliminate_opponents' else PLAN_INSTRUCTIONS))}
            choices = None
        else:
            choices = dict(INTENTS)
            routing_members = [dict(u, position_role=('fire_support' if
                self.world.get('weapons', {}).get(u.get('weapon'), {}).get('splash', 0) > 0
                else self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {})
                    .get('assignments', {}).get(u['id'], {}).get('role', 'establish_fire')))
                for u in members]
            region_options = self._route_builder()(routing_members, self.regions, self.topology,
                                                   self.plan['region_id'],
                                                   contacts=context['contacts'], now=context['time'],
                                                   destination_ids=self._active_destination_ids(),
                                                   support_assets=context['support_assets'])
            context['member_region_choices'] = region_options
            light = [u for u in members if u.get('weapon') not in ('rocket', 'cannon')]
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
            if expired or resume:
                choices.pop('hold'); choices.pop('cover')
                if context['engine_squad'].get('intent') == 'regroup':
                    choices.pop('regroup')
            if resume:
                choices.pop('regroup', None)
                context['execution_constraint'] = '短时保护已完成，当前任务仍需接近区域。请选择下一段推进方式；引擎让尚受压成员继续自保。'
            if self._order_matches_plan() and not expired:
                choices = dict(continue_order='继续当前命令：已有真实接近、有效火力或明确期限内的等待时保持；不会重置路线，长期无贡献时需重新选择执行方式', **choices)
            questions = {'intent': dict(type='choice', instructions=EXECUTOR_INSTRUCTIONS, criteria=choices)}
            if len(light) >= 2:
                questions['flank_mover'] = dict(type='choice',
                    criteria={'not_applicable': '本次不使用这项成员参数',
                        **{u['id']: '可承担机动职责；候选通路见该成员的 route 问题' for u in side_members or light}},
                    instructions='先选择小队意图。仅当 intent=flank 时指定一名机动者，其 route 应为有不同最终接近区域的侧路；其他意图选 not_applicable，此项不执行。')
                questions['flank_fire_base'] = dict(type='choice',
                    criteria={'not_applicable': '本次不使用这项成员参数',
                        **{u['id']: '可承担建立火力职责；候选通路见该成员的 route 问题' for u in front_members or light}},
                    instructions='先选择小队意图。仅当 intent=flank 时指定另一名正面火力者，其 route 选正面接近区域；两名指定职责优先于通用 role。其他意图选 not_applicable，此项不执行。')
            for unit in members:
                role_choices = ({'fire_support': '后侧支援，保持安全射界，不承担持续压制'} if unit.get('weapon') in ('rocket', 'cannon') else
                    {'establish_fire': '先建立真实射界，解除全队等待；不等待他人先开火', 'maneuver': '借助已建立的火力分段接近，优先完成近距离交战', 'fire_support': '保持射界支援移动同伴'})
                questions['role_' + unit['id']] = dict(type='choice', criteria=role_choices,
                    instructions='给 ' + unit['id'] + ' 分配本阶段职责。轻武器成员中至少一人负责 establish_fire，冲锋枪优先 maneuver；不要让所有人互等掩护。若职责仍有效则保持。')
                options = region_options.get(unit['id'], {})
                if options:
                    questions['route_' + unit['id']] = dict(type='choice',
                        criteria={key: f"到区域 {row['region_id']}，经过 {' → '.join(row['region_path'])}；{row['relation']}；"
                                       f"最终落点 {row.get('position')}（{row.get('endpoint_basis', '区域中心')}，{row.get('endpoint_id', '未标识')}）；"
                                       f"{row.get('side', '正面')}，最终接近区域 {row.get('approach_region', row['region_id'])}；"
                                       f"图上距离 {row.get('route_length', 0)}；"
                                       + (f"从本兵最短路在 {row['split_from_primary_at']} 分开"
                                          if row.get('split_from_primary_at') else '与本兵最短路未分叉')
                                       + '；' + _contact_route_note(row)
                                       + ('；交战距离=' + str(row['contact_approach']['range_fit'])
                                          if row.get('contact_approach') else '')
                                       + ('；相对载具=' + str(row['support_screen']['position'])
                                          + '，前出距离=' + str(row['support_screen']['ahead_by'])
                                          if row.get('support_screen') else '')
                                  for key, row in options.items()},
                        instructions='只给 ' + unit['id'] + ' 选择一条已列出的区域通路，结合本次意图、接敌收益与绕行代价；有效路线可保持。仅在 intent=flank 时，指定的机动者与火力者才按侧路/正面分工核对最终接近区域。引擎会复验实际移动。')
        from task_modes import mode_id
        if mode_id(self.world)=='clear_exit':
            context['mode_objective']=('清除本段红方守军；全部死亡后自动生成下一段，无需前往出口' if self.team=='green' else '守住当前阵地、阻止绿色进攻；绿色才是敌人，保持小队联系')
            for name, question in questions.items():
                if name == 'plan':
                    continue  # The clear-mode commander prompt is authored separately.
                if 'instructions' in question:
                    question['instructions']=question['instructions'].replace('本模式没有自动回血；recover应当完成躲避、撤离或重新集结，不能原地等待生命恢复。','无尽模式有条件回血；以实际 regeneration 和当前受火证据为准。射界受阻或敌人超出射程不是撤回出生区的充分理由；优先重新接敌或换射位。恢复阶段必须设退出条件，危险解除后改为 approach 或 reposition，不得靠轮换后方区域无限续期。')
                    question['instructions']=question['instructions'].replace('objective_flag 是旗圈内经过原生导航采样的落点；普通区域中心不等于旗圈。没有明确阻碍时应推进占旗。','当前没有旗帜任务；选择有助于对抗敌方的可达区域，保持小队协作。').replace('占旗','接敌').replace('旗圈','交战区域')
            context['mission_status']['note']='当前为清场模式；以实际移动、射界、开火和自保为依据，不要求占旗或抵达出口。'
        token = dict(identity=self.identity, members=tuple(sorted(u['id'] for u in members)),
                     plan_version=self.version, critical=self.critical[role], navigation=self.world.get('navigation_revision'),
                     region_id=self.plan.get('region_id'), revision=self.revision[role])
        self.request_serial += 1
        model_context = (self._executor_context(context) if role == 'executor'
                         else self._commander_context(context))
        request = dict(serial=self.request_serial, role=role, future=Future(), token=token,
                       started=self.clock(), started_game=self.world.get('time', 0),
                       completed_at=None, expired=False,
                       context=context, model_context=model_context, questions=questions, choices=choices, regions=copy.deepcopy(regions),
                       member_region_choices=copy.deepcopy(context.get('member_region_choices', {})))
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
                     source='local_rules_baseline' if self.model == 'mock' else 'model',
                     context=model_context,
                     context_chars=len(json.dumps(model_context, ensure_ascii=False, separators=(',', ':'))),
                     full_context_chars=len(json.dumps(context, ensure_ascii=False, separators=(',', ':'))),
                     questions=questions)

        def ask():
            try:
                if self.model == 'mock':
                    result = self._baseline(request)
                else:
                    result = self.game.ask(model_context, questions, **({'role': 'commander'} if role == 'commander' else {}))
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
            key = current if current in request['regions'] else min(request['regions'], key=lambda k: math.dist(request['regions'][k]['center'], objective))
            value = dict(region_id=key, objective='规则基线：结伴接近目标区域并保持掩护',
                         risk='规则基线只知道当前感知，通路采样不证明安全',
                         stage='hold' if mode_id(self.world) == 'clear_exit' and self.team != 'green' else 'approach',
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
        return dict(requestId='baseline-' + str(request['serial']), source='local_rules_baseline',
                    answers={'intent': dict(type='choice', choice=choice, confidence=1,
                                            probabilities={key: int(key == choice) for key in choices})})

    def _valid_token(self, request, members):
        token = request['token']
        if token['identity'] != self.identity:
            return 'authority_changed'
        if token['members'] != tuple(sorted(u['id'] for u in members)):
            return 'membership_changed'
        if token['navigation'] != self.world.get('navigation_revision'):
            return 'navigation_changed'
        if token['critical'] != self.critical[request['role']]:
            return 'critical_event_changed'
        if request['role'] == 'executor' and token['plan_version'] != self.version:
            return 'commander_plan_changed'
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
                if plan['region_id'] not in self._active_destination_ids():
                    raise ValueError('commander_region_no_longer_exists')
                same_region = self.plan.get('region_id') == plan['region_id']
                same_stage = same_region and self.plan.get('stage') == plan['stage']
                mission = self._mission_status(members)
                if (self.plan.get('stage') == 'recover' and plan['stage'] == 'recover'
                        and not mission['acute_recovery']
                        and self.world.get('time', 0) - (self.stage_started or 0) >= 15):
                    raise ValueError('recovery_complete_choose_reposition_or_approach_not_another_rear_region')
                if same_region and plan['stage'] in ('approach', 'probe', 'reposition') and (mission['approach_stalled'] or mission['intermediate_complete']):
                    raise ValueError('intermediate_region_exhausted_choose_new_region_or_concrete_combat_stage')
                if same_region and plan['stage'] in ('observe', 'recover', 'hold') and self._mission_status(members)['wait_expired']:
                    raise ValueError('wait_expired_choose_concrete_maneuver_or_different_region')
                # Narrative rewording is useful context, but must not revoke
                # in-flight squad/soldier work when the executable plan is unchanged.
                changed = any(self.plan.get(k) != plan.get(k)
                              for k in ('region_id', 'position', 'radius', 'stage'))
                now = self.world.get('time', 0)
                if not same_region:
                    self.region_started = now
                    self.region_renewals = 0
                    self.arrived_at = None
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
                self.plan = dict(plan, source='local_rules_baseline' if self.model == 'mock' else 'deepseek_commander',
                                 request_id=response.get('requestId'))
                if changed:
                    self.version += 1
                    self.revision['executor'] += 1
                self._record('human-commander-plan', version=self.version, plan=self.plan)
            else:
                answer = response['answers']['intent']
                choice = answer.get('choice') if isinstance(answer, dict) and answer.get('type') == 'choice' else None
                if choice not in request['choices']:
                    raise ValueError('invalid_executor_intent')
                # Confidence is diagnostic. A valid selected action is never filtered by probability.
                if choice == 'continue_order':
                    if not self._order_matches_plan():
                        raise ValueError('engine_order_changed_while_deciding')
                    # A member can change area/route while the squad keeps its
                    # tactic. _submit compares the full assignment signature.
                    self._submit(self.last_order['intent'], members, response, request)
                else:
                    self._submit(choice, members, response, request)
            self.error = ''
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
            self.feedback = self.error
            self.revision[role] += 1
            self.next_wall[role] = self.clock() + self.config.get('failure_cooldown_s', 2.)
            self._record('human-model-failed', request_serial=request['serial'], role=role,
                         reason=self.error, engine_behavior='continue_accepted_order')
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
            self._record('human-model-timeout', request_serial=request['serial'], role=role,
                         elapsed_s=elapsed, engine_behavior='continue_accepted_order')

