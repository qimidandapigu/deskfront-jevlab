"""Independent soldier state on the shared squad runtime; one fair async lane per faction."""
import copy
import math
import threading
from concurrent.futures import Future
from soldier_candidate_query import query as query_candidates
from strategic_regions import contains

CHOICES = {
    'continue_task': '继续当前职责，不覆盖有效路线和引擎自保',
    'move_to_site': '移动到所选候选位置；可用于接近、横移或短撤',
    'rush_to_site': '站姿短距离冲刺到所选位置，比普通移动快约40%；反坦克接近点会短时坚持冲锋，残血、强压制和迫近爆炸仍即时避险',
    'prone_approach': '卧姿匍匐到所选位置，速度较慢但降低身体暴露',
    'occupy_cover': '进入所选的可用掩体位置',
    'peek_fire': '进入所选掩体并针对已验证射线的敌人探头攻击',
    'focus_fire': '在当前位置集中攻击可见且武器合法的目标',
    'satchel': '近距离向可见敌方坦克投掷炸药包；有14秒冷却，引擎复验射线和友军安全',
    'report_blocked': '报告个人职责受阻，请团队调整分工或路线',
}
SITE_ACTIONS = {'move_to_site', 'rush_to_site', 'prone_approach', 'occupy_cover', 'peek_fire'}
INSTRUCTIONS = '''你是 self.id 对应的士兵，只能决定自己的局部行动。assignment 是当前团队职责。
保持行动连续；受伤不是等待回血。射界、开火、压制是不同事实，队友报告不等于亲眼所见。
每个选项是完整的“动作＋位置＋目标”，只选一个。候选编号每次查询重新编号，不能把上次的 C1 当作同一个位置。
候选里的 goal_distance_gain 是到个人任务落点的直线距离变化，不是路线代价；recently_visited 只表示最近真的走过，不禁止必要的撤退或绕行。
结合 task_progress、movement_history 与射界/威胁选择：到达一个局部点不等于完成职责；没有新射界或避险收益时，不要只因路短就在最近走过的两点之间反复移动。
continue_task 表示保持现有执行，不重新发移动令；需要改变时才选完整的新动作。风险高是软事实，并非全部位置必须绝对安全。
引擎会重新检查动作可行性，选择不表示已执行成功。实际射击、路线和即时避险由引擎负责。
有效移动、装填或正在自保时优先继续；持续没有接近或开火时选一个能改变现状的动作。
battlefield_equipment 中 capturable=true 的迫击炮由一名非火箭兵在 capture_radius 内无敌人争夺地持续停留 capture_seconds 秒即可接管。若小队职责要求夺炮，选择 equipment_approach 候选逐段接近；进入范围后 continue_task 保持到接管完成。敌方炮手还在时先交战，不能跳过守军直接夺炮；接管占用一名现有成员，不会凭空补兵。第二名士兵在炮旁警戒会改善射速和精度，但不是接管硬门槛。
若炸药包已就绪且可见坦克已进入投掷距离，先看 anti_armor_opportunity.throw_check：reason 为空时优先 satchel；若抛物线或友军安全暂时阻挡，选标明“反坦克投掷位”的短距离候选点横移后再投，避免反复提交不可用的 satchel。引擎仍复验目标、友军安全和自保状态。
若坦克尚在投掷距离外、而候选点标明“反坦克接近点”，需要反装甲时选择该点连续接近：体力足且有可达短路时优先 rush_to_site 快跑，普通命中或看见坦克不会让这段冲刺立刻掉头；已经残血、强压制或需躲迫近炮弹时再考虑 prone_approach 或避险。普通 move_to_site 不提供冲刺或低姿收益。每段到位后重新观察，进入投掷距离就优先 satchel。不要为了炸药包穿过未验证的区域。
否则，若自身已有 engageable_visible_targets 且仍在移动，优先考虑 focus_fire：它会暂停当前移动约三秒，让引擎停下瞄准、自动射击；当前射线不可用时再换位。
不能命令其他成员或改变小队分配的区域通路。置信度只供诊断。'''


class SoldierAgents:
    def __init__(self, owner):
        self.owner = owner
        self.agents = {}
        self.inflight = {}
        self.pending = None
        self.receipts = {}
        self.next_wall = 0.
        self.calls = 0
        self.accepted = 0
        self.discarded = 0

    def reset(self):
        # Keep transport occupied until it finishes; authority token invalidates its response.
        self.agents.clear()
        self.receipts.clear()
        # Old futures may still resolve. Keep the slot until they are harvested
        # so a stale call never silently occupies a new unit's slot.

    @staticmethod
    def _unit_slot(uid):
        """Stable per-unit slot; avoids hash randomization and synchronized reviews."""
        return sum((index + 1) * ord(char) for index, char in enumerate(str(uid)))

    def _initial_delay(self, uid):
        # Spread the first round over roughly one second.  Semantic assignment
        # changes and urgent anti-armour events still wake immediately below.
        return .35 + (self._unit_slot(uid) % 8) * .16

    def _independent_timing_enabled(self):
        # Keep the small direct-controller fixtures deterministic when they do
        # not opt into the production personal-lane timings.  Both Deskfront
        # hosts set soldier_interval explicitly.
        return 'soldier_interval' in self.owner.config

    def _review_interval(self, uid=None):
        """Periodic personal review interval; each unit owns its own timer."""
        try:
            base = float(self.owner.config.get('soldier_interval', 5.))
        except (TypeError, ValueError):
            base = 5.
        if uid is None or not self._independent_timing_enabled():
            return max(1., base)
        # A small deterministic per-unit offset prevents all JEV lanes from
        # becoming due on the same second after a shared squad update.
        phase = (self._unit_slot(uid) % 11 - 5) * .12
        return max(1., base + phase)

    def _token(self, squad):
        o = self.owner
        return (o.identity, o.version, squad.get('order_id'), o.world.get('navigation_revision'))

    def observe(self, members, squad, receipts):
        o = self.owner
        now = o.world.get('time', 0.)
        living = {u['id'] for u in members}
        self.agents = {k: v for k, v in self.agents.items() if k in living}
        contacts = o.world.get('squad_behavior', {}).get('perception', {}).get(o.team, {}).get('contacts', [])
        if isinstance(contacts, dict): contacts = list(contacts.values())
        dead_ids = {u.get('id') for u in o.world.get('units', []) if u.get('hp', 0) <= 0}
        visible_tanks = [c for c in contacts if c.get('visible') and c.get('kind') == 'tank'
                         and c.get('id') not in dead_ids and isinstance(c.get('position'), (list, tuple))
                         and len(c['position']) == 2]
        for u in members:
            uid = u['id']
            duty = squad.get('duties', {}).get(uid, {})
            a = self.agents.setdefault(uid, dict(id=uid, next_at=0., last_review=-100.,
                                                 memory=[], status='observing', failures=0))
            a['review_interval_s'] = round(self._review_interval(uid), 3)
            a['initial_delay_s'] = round(self._initial_delay(uid), 3)
            assignment = dict(order_id=squad.get('order_id'), intent=squad.get('intent'),
                              goal=squad.get('assignments', {}).get(uid, {}).get('position') or squad.get('goal'), assigned_role=squad.get('assignments', {}).get(uid, {}).get('role'),
                              role=duty.get('role', 'observe'),
                              reason=duty.get('reason', ''), mover=squad.get('mover'),
                              target_region_id=squad.get('assignments', {}).get(uid, {}).get('region_id'),
                              region_path=squad.get('assignments', {}).get(uid, {}).get('region_path', []),
                              support_ids=squad.get('support_ids', []))
            # A new order id is not, by itself, a new personal task.  The
            # commander may refresh progress/receipts while the soldier is
            # still doing the same job; waking every member for that update
            # was the main source of bursty, redundant personal JEV calls.
            # Keep order_id in the authority token below so stale replies are
            # still rejected, but wake only when the semantic assignment or a
            # survival/fire-lane fact changes.
            goal = assignment.get('goal')
            goal_key = tuple(round(float(value), 3) for value in goal) if isinstance(goal, (list, tuple)) and len(goal) == 2 else None
            target_key = tuple(sorted(u.get('combat', {}).get('engageable_targets') or ()))
            signature = (assignment.get('intent'), duty.get('role'), duty.get('reason', ''),
                         assignment['target_region_id'], goal_key, tuple(assignment.get('region_path') or ()),
                         target_key, u.get('survival_reason'), u.get('combat', {}).get('fire_block_reason'))
            if a.get('signature') != signature:
                previous = a.get('signature')
                a['memory'] = (a['memory'] + [dict(time=now, role=duty.get('role'), reason=signature[2] or signature[7] or signature[8] or '')])[-6:]
                a['signature'] = signature
                # A new semantic assignment deserves an immediate review.
                # Rapidly changing survival/fire-block facts are reported to
                # JEV without cancelling the normal review backoff; the
                # engine handles urgent survival without this model call.
                if previous is None:
                    # Do not fire every newly spawned personal lane on the
                    # same frame.  This is only the initial phase; later
                    # semantic changes remain immediate wakes.
                    a['next_at'] = (now + self._initial_delay(uid)
                                    if self._independent_timing_enabled() else now)
                    a['assignment_wake'] = True
                elif previous[:7] != signature[:7]:
                    a['next_at'] = min(a['next_at'], now)
                    a['assignment_wake'] = True
            history = a.setdefault('movement_history', [])
            # Bounded engine-observed samples, never selected/queued positions.
            if not history or now - history[-1]['time'] >= 1.:
                history.append(dict(time=round(now, 2), position=list(u['position'])))
                del history[:-8]
            a['assignment'] = assignment
            a['engine_execution'] = copy.deepcopy(squad.get('personal', {}).get(uid, {}))
            anti_armor_stage = ''
            if u.get('satchel_range', 0) > 0 and u.get('satchel_ready_in', 1) <= 0 and visible_tanks:
                distance = min(math.dist(u['position'], c['position']) for c in visible_tanks)
                anti_armor_stage = 'throw' if distance <= u['satchel_range'] else 'approach' if distance <= 1.2 else ''
            if anti_armor_stage != a.get('anti_armor_stage', ''):
                a['anti_armor_stage'] = anti_armor_stage
                if anti_armor_stage:
                    a['anti_armor_wake'] = True
                    a['next_at'] = min(a['next_at'], now)
            satchel_check = u.get('combat', {}).get('satchel_check', {})
            throw_clear = not satchel_check or not satchel_check.get('reason')
            throw_ready = (anti_armor_stage == 'throw' and throw_clear and not u.get('survival_reason')
                           and u.get('suppression', 0) < (.72 if u.get('antiarmor_charge_remaining', 0) > 0 else .35))
            if throw_ready and not a.get('anti_armor_throw_ready', False):
                a['anti_armor_wake'] = True
                a['next_at'] = min(a['next_at'], now)
            a['anti_armor_throw_ready'] = throw_ready
        for rid, item in list(self.receipts.items()):
            result = receipts.get(rid)
            if result is None and o.clock()-item['submitted'] <= 5:
                continue
            self.receipts.pop(rid)
            a = self.agents.get(item['uid'])
            if item['token'] != self._token(squad):
                o._record('soldier-receipt-discarded', unit_id=item['uid'], reason='assignment_changed')
                continue
            if a is None:
                continue
            ok = bool(result and result.get('accepted'))
            a['status'] = 'accepted' if ok else 'rejected'
            a['last_result'] = copy.deepcopy(result or dict(accepted=False, message='receipt_timeout'))
            a['failures'] = 0 if ok else a['failures'] + 1
            self.accepted += int(ok)
            o._record('soldier-action-receipt', unit_id=item['uid'], intent=item['intent'], result=a['last_result'])
            if not ok:
                o._wake('participation_gap', dict(unit_id=item['uid'], reason='soldier_action_rejected:' + str(a['last_result'].get('message', 'unknown'))))

    def _context(self, unit, squad):
        o = self.owner
        a = self.agents[unit['id']]
        fields = ('id', 'weapon', 'hp', 'max_hp', 'position', 'ammo', 'reload_remaining', 'suppression', 'survival_reason', 'in_cover', 'weapon_range', 'last_shot_at', 'last_hit_at', 'last_damage_at', 'order_mode', 'satchel_ready_in', 'satchel_range', 'antiarmor_charge_remaining')
        # Squad perception is explicitly a teammate report; no world enemy list is passed.
        team_context = o._context(o._members(o.world))
        contacts = team_context['contacts']
        last_shot = unit.get('last_shot_at', -1)
        last_hit = unit.get('last_hit_at', -1)
        return dict(time=o.world['time'], self={k: unit[k] for k in fields if k in unit},
                    battlefield_equipment=copy.deepcopy(team_context.get('battlefield_equipment', [])),
                    satchel_check=copy.deepcopy(unit.get('combat', {}).get('satchel_check', {})),
                    seconds_since_last_shot=round(o.world['time']-last_shot,1) if last_shot >= 0 else None,
                    seconds_since_last_hit=round(o.world['time']-last_hit,1) if last_hit >= 0 else None,
                    assignment=copy.deepcopy(a['assignment']), memory=copy.deepcopy(a['memory']),
                    teammate_reports=[dict(c, source='squad_report_not_personal_sight') for c in contacts],
                    execution_evidence=copy.deepcopy(team_context['execution_evidence']['members'].get(unit['id'], {})),
                    path_active=bool(unit.get('combat', {}).get('path_active')),
                    firing_awareness=copy.deepcopy(unit.get('combat', {}).get('firing_awareness', {})),
                    coordination={uid: {k: row[k] for k in ('role', 'reason') if k in row}
                                  for uid, row in squad.get('duties', {}).items() if uid in self.agents},
                    engine_execution=copy.deepcopy(a['engine_execution']), last_result=a.get('last_result'),
                    movement_history=copy.deepcopy(a.get('movement_history', [])),
                    task_progress=self._task_progress(unit, a))

    @staticmethod
    def _candidate_model_view(row):
        """Return a compact, read-only candidate description for JEV.

        ``row`` is kept unchanged in the local request/validator.  The model
        does not need empty collision identifiers, zero counts, or duplicate
        bookkeeping fields to choose an action, and sending those values for
        up to twelve candidates made personal requests disproportionately
        large.  Preserve every fact that can change the legal action set.
        """
        if not isinstance(row, dict):
            return row
        always = ('id', 'region_id', 'position', 'kind', 'path_length',
                  'goal_distance_gain', 'distance_from_self', 'target_distance')
        view = {}
        for key in always:
            value = row.get(key)
            if value is None:
                continue
            if key == 'position' and isinstance(value, (list, tuple)):
                view[key] = [round(float(item), 3) for item in value]
            elif key in ('path_length', 'goal_distance_gain', 'distance_from_self', 'target_distance') and isinstance(value, (int, float)):
                view[key] = round(float(value), 3)
            else:
                view[key] = copy.deepcopy(value)
        for key in ('cover_key', 'cover_id', 'target_id'):
            value = row.get(key)
            if value:
                view[key] = copy.deepcopy(value)
        fire_targets = row.get('fire_targets')
        if fire_targets:
            view['fire_targets'] = copy.deepcopy(fire_targets)
        if row.get('hard_cover'):
            view['hard_cover'] = True
        if row.get('potential_attackers'):
            view['potential_attackers'] = row['potential_attackers']
        if row.get('recently_visited'):
            view['recently_visited'] = True
            if row.get('last_visited_seconds_ago') is not None:
                view['last_visited_seconds_ago'] = round(float(row['last_visited_seconds_ago']), 2)
        return view

    def _task_progress(self, unit, agent):
        goal = agent['assignment'].get('goal')
        history = agent.get('movement_history', [])
        valid_goal = isinstance(goal, (list, tuple)) and len(goal) == 2
        region = self.owner.regions.get(agent['assignment'].get('target_region_id'))
        return dict(
            distance_to_assigned_goal=round(math.dist(unit['position'], goal), 3) if valid_goal else None,
            in_assigned_region=contains(unit['position'], region) if region else None,
            local_execution_status=agent.get('engine_execution', {}).get('status'),
            local_arrival_is_not_task_completion=True,
            observed_path_length=round(sum(math.dist(a['position'], b['position'])
                for a, b in zip(history, history[1:])), 3),
            observed_net_displacement=round(math.dist(history[0]['position'], unit['position']), 3) if history else 0.,
            window_seconds=round(self.owner.world['time']-history[0]['time'], 2) if history else 0.)

    @staticmethod
    def _site_facts(unit, assignment, agent, row, now):
        row = copy.deepcopy(row)
        goal = assignment.get('goal')
        if isinstance(goal, (list, tuple)) and len(goal) == 2:
            row['goal_distance_gain'] = round(math.dist(unit['position'], goal)-math.dist(row['position'], goal), 3)
        visits = [h for h in agent.get('movement_history', [])
                  if now-h['time'] >= 1. and math.dist(h['position'], row['position']) <= .06]
        row['recently_visited'] = bool(visits)
        row['last_visited_seconds_ago'] = round(now-visits[-1]['time'], 2) if visits else None
        row['distance_from_self'] = round(math.dist(unit['position'], row['position']), 3)
        return row

    @staticmethod
    def _action_options(choices, sites, focus_targets, satchel_targets):
        # Mechanical legal combinations only; no score, tactical ranking or rejection.
        options, criteria = {}, {}
        def add(intent, site_id=None, target_id=None):
            key = ':'.join(str(x) for x in (intent, site_id, target_id) if x is not None)
            options[key] = dict(intent=intent, site_id=site_id, target_id=target_id)
            suffix = ('；位置 ' + site_id + '，对应 candidate_sites 中的完整事实') if site_id else ''
            if target_id: suffix += '；目标 ' + target_id
            criteria[key] = choices[intent] + suffix
        for intent in choices:
            if intent in SITE_ACTIONS:
                for key, row in sites.items():
                    if intent == 'peek_fire':
                        if row.get('cover_key'):
                            for target in row.get('fire_targets', []): add(intent, key, target)
                    elif intent != 'occupy_cover' or row.get('cover_key'):
                        add(intent, key)
            elif intent in ('focus_fire', 'satchel'):
                for target in (focus_targets if intent == 'focus_fire' else satchel_targets): add(intent, target_id=target)
            else: add(intent)
        return options, criteria

    def tick(self, members, squad, receipts, *, active):
        o = self.owner
        self.observe(members, squad, receipts)
        if not active:
            return
        now = o.world.get('time', 0.)
        for request in list(self.inflight.values()):
            self.pending = request
            if not request['future'].done():
                if o.clock()-request['started'] > o.config.get('timeout', 10.)+1:
                    a = self.agents.get(request['uid'])
                    if a is not None and a['status'] != 'model_timeout':
                        a['status'] = 'model_timeout'
                        o._record('soldier-model-timeout', unit_id=request['uid'], engine_behavior='continue_valid_assignment')
                continue
            self.inflight.pop(request['uid'], None)
            uid = request['uid']
            a = self.agents.get(uid)
            try:
                response = request['future'].result()
                if (a is None or request['token'] != self._token(squad)
                        or o.pending_commands or o.clock()-request['started'] > o.config.get('timeout', 10.)+1):
                    self.discarded += 1
                    o._record('soldier-response-discarded', unit_id=uid, reason='authority_task_or_deadline_changed')
                else:
                    selected = response['answers']['action']['choice']
                    if selected not in request['options']:
                        raise ValueError('invalid_soldier_choice')
                    option = request['options'][selected]
                    choice, site_id, target_id = option['intent'], option['site_id'], option['target_id']
                    current = next(u for u in members if u['id'] == uid)
                    committed_throw = (choice == 'satchel' and current.get('antiarmor_charge_remaining', 0) > 0)
                    if (choice not in ('continue_task', 'report_blocked') and
                            (current.get('survival_reason') or current.get('suppression', 0) >= (.72 if committed_throw else .35))):
                        self.discarded += 1
                        a['status'] = 'survival_interrupted'
                        a['next_at'] = now + self._review_interval(uid)
                        o._record('soldier-response-discarded', unit_id=uid, reason='survival_changed')
                        continue
                    if choice == 'report_blocked':
                        a['reported_at'] = now
                        a['reported_order'] = squad['order_id']
                    sites = request['sites']
                    if choice in SITE_ACTIONS and site_id not in sites:
                        raise ValueError('invalid_soldier_site')
                    if choice in ('peek_fire', 'focus_fire', 'satchel'):
                        valid_targets = (sites[site_id]['fire_targets'] if choice == 'peek_fire' else
                                         request['satchel_targets'] if choice == 'satchel' else request['focus_targets'])
                        if target_id not in valid_targets:
                            raise ValueError('invalid_soldier_target')
                    a['last_choice'] = choice
                    a['last_review'] = now
                    if choice not in ('continue_task', 'report_blocked'):
                        a['last_action_at'] = now
                    a['next_at'] = now + self._review_interval(uid)
                    a['status'] = 'continued' if choice == 'continue_task' else 'submitting'
                    o._record('soldier-decision', unit_id=uid, choice=choice, site_id=site_id,
                              target_id=target_id, response=response)
                    if choice != 'continue_task':
                        command = dict(action='soldier_order', faction=o.team, unit_ids=[uid],
                            squad_id=o.squad_id, order_id=squad['order_id'], intent=choice,
                            run_id=o.world['run_id'], seen_tick=int(o.world['tick']),
                            control_epoch=o.world.get('control_epochs', {}).get(o.team, 0))
                        if choice in SITE_ACTIONS:
                            command.update(site_id=site_id, candidate_query_id=request['candidate_query_id'])
                        if choice in ('peek_fire', 'focus_fire', 'satchel'):
                            command['target_id'] = target_id
                        if getattr(o.game, 'session_id', None): command['instance_id'] = o.game.session_id
                        status, receipt = o.state.submit(command, source='lm')
                        if status != 202:
                            raise ValueError('soldier_queue_rejected:' + str(receipt.get('error', status)))
                        self.receipts[receipt['id']] = dict(uid=uid, intent=choice, submitted=o.clock(), token=self._token(squad))
            except Exception as error:
                if a is not None:
                    a['status'] = 'model_error'
                a['next_at'] = now + self._review_interval(uid)
                reason = str(error)[:160] if isinstance(error, (ValueError, KeyError, TypeError)) else type(error).__name__
                o._record('soldier-decision-failed', unit_id=uid, reason=reason)
        self.pending = next(iter(self.inflight.values()), None)
        if len(self.inflight) >= max(1, min(10, int(o.config.get('soldier_concurrency', 4)))) or o.pending_commands or not squad.get('order_id') or o.stopped.is_set() or o.budget_exhausted:
            return
        candidates = []
        for u in members:
            a = self.agents[u['id']]
            if (u['id'] in self.inflight or any(item['uid']==u['id'] for item in self.receipts.values())
                    or now < a['next_at'] or o.clock() < a.get('next_wall_at', 0)): continue
            personal = a.get('engine_execution', {})
            ready_to_throw = (a.get('anti_armor_stage') == 'throw' and a.get('anti_armor_throw_ready', True)
                              and not u.get('survival_reason')
                              and u.get('suppression', 0) < (.72 if u.get('antiarmor_charge_remaining', 0) > 0 else .35))
            if personal.get('status') in ('active', 'suspended') and now < personal.get('until', 0) and not ready_to_throw:
                continue
            # Effective actions do not require paid periodic reaffirmation.
            if a['last_review'] >= 0 and a['assignment']['role'] in (
                    'observe', 'approach', 'support', 'reload', 'recover', 'acquire_fire', 'blocked') \
                    and not a.get('anti_armor_wake') and not a.get('assignment_wake'):
                continue
            if a['last_review'] >= 0 and a['assignment']['role'] == 'observe' and not squad.get('duties', {}).get(u['id']):
                continue
            if (a.get('last_choice') == 'report_blocked' and a.get('reported_order') == squad.get('order_id')
                    and now-a.get('reported_at', -100) < 10):
                continue
            candidates.append(u)
        if not candidates: return
        unit = min(candidates, key=lambda u: self.agents[u['id']]['last_review'])
        a = self.agents[unit['id']]
        a['anti_armor_wake'] = False
        a['assignment_wake'] = False
        if o.request_count >= o.config.get('max_requests', 100): return
        shared = o.config.get('shared_request_budget')
        if shared is not None and not shared.claim():
            o.budget_exhausted = True
            return
        choices = dict(CHOICES)
        if a.get('reported_order') == squad.get('order_id') and now-a.get('reported_at', -100) < 15:
            choices.pop('report_blocked')
        assignment = squad.get('assignments', {}).get(unit['id'], {})
        context = self._context(unit, squad)
        visible_tanks = [c for c in context['teammate_reports']
                         if c.get('visible') and c.get('kind') == 'tank' and c.get('id')]
        if visible_tanks and unit.get('satchel_ready_in', 1) <= 0 and unit.get('satchel_range', 0) > 0:
            nearest = min((c for c in visible_tanks if isinstance(c.get('position'), (list, tuple))
                           and len(c['position']) == 2),
                          key=lambda c: math.dist(unit['position'], c['position']), default=None)
            if nearest:
                distance = math.dist(unit['position'], nearest['position'])
                context['anti_armor_opportunity'] = dict(target_id=nearest['id'],
                    distance=round(distance, 3), satchel_range=unit['satchel_range'],
                    stage='throw' if distance <= unit['satchel_range'] else 'approach')
                if distance <= unit['satchel_range']:
                    context['anti_armor_opportunity']['throw_check'] = context['satchel_check']
        result = (query_candidates(o.config.get('spatial_path'), o.world, unit, assignment,
                                   o.regions, o.topology, o.team, visible_tanks=visible_tanks,
                                   equipment=context.get('battlefield_equipment', [])) if o.model != 'mock'
                  else dict(status='mock', options=[]))
        sites = {row['id']: self._site_facts(unit, a['assignment'], a, row, now)
                 for row in result.get('options', []) if row.get('id')}
        if not sites:
            for choice in SITE_ACTIONS: choices.pop(choice, None)
        if not any(row.get('cover_key') for row in sites.values()):
            choices.pop('occupy_cover', None);choices.pop('peek_fire', None)
        if not any(row.get('cover_key') and row.get('fire_targets') for row in sites.values()):
            choices.pop('peek_fire', None)
        context['candidate_query_status'] = result.get('status', 'unknown')
        # The full native rows remain in ``sites`` for command validation.
        # JEV only needs the facts that distinguish a legal local action;
        # empty/default fields repeated for every candidate added a large
        # amount of input without changing the choice space.
        context['candidate_sites'] = [self._candidate_model_view(row) for row in sites.values()]
        anti_armor_sites = [row for row in sites.values() if row.get('kind') == 'anti_armor_approach']
        if context.get('anti_armor_opportunity', {}).get('stage') == 'approach' and anti_armor_sites:
            context['anti_armor_approach_sites'] = [dict(id=row['id'], target_distance=row.get('target_distance'),
                path_length=round(row.get('path_length', 0), 3), potential_attackers=row.get('potential_attackers', 0),
                hard_cover=bool(row.get('hard_cover'))) for row in anti_armor_sites]
            choices['rush_to_site'] = '反坦克快速接近：选择反坦克接近点，站姿约1.4倍速冲刺一段；短时承诺，普通命中和坦克压制不打断'
            choices['prone_approach'] = '反坦克低姿接近：选择反坦克接近点，卧姿匍匐一段；路线暴露但仍可推进时用'
        throw_sites = [row for row in sites.values() if row.get('kind') == 'anti_armor_throw_site']
        if throw_sites:
            context['anti_armor_throw_sites'] = [dict(id=row['id'], target_distance=row.get('target_distance'),
                path_length=round(row.get('path_length', 0), 3), potential_attackers=row.get('potential_attackers', 0))
                for row in throw_sites]
            choices['rush_to_site'] = '反坦克横移：选反坦克投掷位，短距离站姿冲刺到已验证的抛物线位置，再投炸药包'
        focus_targets = sorted(set(context['execution_evidence'].get('engageable_visible_targets') or []))
        if not focus_targets: choices.pop('focus_fire', None)
        satchel_targets = sorted({c['id'] for c in visible_tanks if
            isinstance(c.get('position'), (list, tuple)) and len(c['position']) == 2 and
            unit.get('satchel_ready_in', 1) <= 0 and unit.get('satchel_range', 0) > 0 and
            math.dist(unit['position'], c['position']) <= unit['satchel_range'] and
            (not context['satchel_check'] or context['satchel_check'].get('target_id') != c['id']
             or not context['satchel_check'].get('reason'))})
        if not satchel_targets: choices.pop('satchel', None)
        options, criteria = self._action_options(choices, sites, focus_targets, satchel_targets)
        future = Future()
        request = dict(uid=unit['id'], token=self._token(squad), started=o.clock(), future=future,
                       choices=choices, options=options, sites=sites,
                       focus_targets=focus_targets, satchel_targets=satchel_targets,
                       candidate_query_id=result.get('id', ''))
        self.inflight[unit['id']] = request
        self.pending = next(iter(self.inflight.values()), None)
        a['status'] = 'thinking'
        a['last_review'] = now
        a['next_at'] = now + self._review_interval(unit['id'])
        wall_cooldown = float(o.config.get('soldier_cooldown_s', 1.))
        wall_phase = (self._unit_slot(unit['id']) % 5) * .05 if self._independent_timing_enabled() else 0.
        a['next_wall_at'] = o.clock() + max(.25, wall_cooldown + wall_phase)
        self.next_wall = o.clock()
        self.calls += 1
        o.request_count += 1
        o._record('soldier-model-request', unit_id=unit['id'], context=context, choices=criteria, action_options=options)
        def ask():
            try:
                questions = {'action': dict(type='choice', instructions=INSTRUCTIONS, criteria=criteria)}
                response = (dict(answers={'action': dict(choice='continue_task')}) if o.model == 'mock' else
                    o.game.ask(context, questions))
                future.set_result(response)
            except Exception as error:
                future.set_exception(error)
        threading.Thread(target=ask, name='soldier-'+unit['id'], daemon=True).start()

    def snapshot(self):
        return dict(agents=copy.deepcopy(self.agents), calls=self.calls, accepted=self.accepted,
                    discarded=self.discarded,
                    pending=self.pending['uid'] if self.pending else None,
                    inflight_units=list(self.inflight))
