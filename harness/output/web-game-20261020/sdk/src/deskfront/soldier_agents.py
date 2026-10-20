"""Independent soldier state on the shared squad runtime; one fair async lane per faction."""
import copy
import math
import threading
import uuid
from concurrent.futures import Future
from background_query import optional_kwargs, receipt_unknown
from local_behavior import grant as local_grant, identity as local_grant_identity, action_options as local_action_options
from soldier_candidate_query import query as query_candidates
from strategic_regions import contains
from assignment_fire_review import decision_blocked
from survival_review import current as survival_handoff, matches as handoff_matches, can_execute as handoff_can_execute
from survival_review import finish as finish_survival_review
from coordination_handover import waiting_member as handover_waiting_member

CHOICES = {
    'continue_task': '不发新命令，继续当前职责和有效路线/引擎自保；不下达换位或换目标指令',
    'move_to_site': '移动到所选候选位置；可用于接近、横移或短撤',
    'rush_to_site': '站姿短距离冲刺到所选位置，比普通移动快约40%；只移动，不自动投弹',
    'approach_satchel': '接近并投弹：沿选中的原生反坦克候选路段接近指定可见坦克，进入合法范围后准备投掷一次；接近最多4.5秒，准备不等于投出，危险、目标失效或路段结束仍不可投则结束本次尝试，不自动换目标或续路',
    'prone_approach': '卧姿匍匐到所选位置，速度较慢但降低身体暴露',
    'occupy_cover': '进入所选的可用掩体位置',
    'peek_fire': '进入所选掩体并针对已验证射线的敌人探头攻击',
    'focus_fire': '指定可见且武器合法目标，取消当前运动执行并清掉当前移动路径后，短时集中射击约3游戏秒；不承诺保留原运动执行。若需要保留已接受路线，比较当前可用的hold_fire_position',
    'hold_fire_position': '在当前位置保持射位并继续合法射击，最多3游戏秒；保留上级路线、游标和原期限，结束后可继续原路线；危险、换本兵任务或失去有效射界提前结束，不是停火或无限驻守',
    'grenade': '向原生已验证可投的可见敌步兵投普通手榴弹，有限库存；逼退掩体后的敌人或协助突击，引擎复验距离、弧线和友军安全',
    'breach_cover': '用火箭向所选可破坏掩体发射一发，打开射界或通路；原生复验真实掩体ID、枪口、友军安全及当前原生射击条件，不自动移位或续射',
    'satchel': '近距离向可见敌方坦克投掷炸药包；有14秒冷却，引擎复验射线和友军安全',
    'report_blocked': '仅上报受阻，不下达换位或换目标指令；职责内无可行方案时请求团队调整',
}
SITE_ACTIONS = {'move_to_site', 'rush_to_site', 'approach_satchel', 'prone_approach', 'occupy_cover', 'peek_fire'}
from combat_prompt import instructions as combat_instructions, model_view
# Keep the public import used by diagnostics; live requests are conditional.
INSTRUCTIONS = combat_instructions('personal', {}, all_capabilities=True)


def native_grenade_checks(world, team, unit, contacts):
    """Filter native check facts to current visible living enemy infantry."""
    dead_ids = {u.get('id') for u in world.get('units', []) if u.get('hp', 0) <= 0}
    visible = {c.get('id') for c in contacts if c.get('visible') is True
               and c.get('kind') == 'infantry' and c.get('id')
               and c.get('id') not in dead_ids and c.get('hp', 1) > 0
               and c.get('faction') != team}
    checks = unit.get('combat', {}).get('grenade_checks', [])
    if not isinstance(checks, list):
        return []
    return [copy.deepcopy(row) for row in checks if isinstance(row, dict)
            and row.get('target_id') in visible]


def native_grenade_opportunities(world, team, unit, contacts):
    """A missing native arc/safety check never makes a grenade option."""
    inventory, reach = unit.get('grenades'), unit.get('grenade_range')
    if (not isinstance(inventory, (int, float)) or isinstance(inventory, bool)
            or not math.isfinite(inventory) or inventory <= 0
            or not isinstance(reach, (int, float)) or isinstance(reach, bool)
            or not math.isfinite(reach) or reach <= 0
            ):
        return []
    opportunities, seen = [], set()
    for check in native_grenade_checks(world, team, unit, contacts):
        distance = check.get('distance')
        if (check.get('reason') != '' or not isinstance(distance, (int, float))
                or isinstance(distance, bool) or not math.isfinite(distance)
                or not 0 <= distance <= reach or check['target_id'] in seen):
            continue
        seen.add(check['target_id'])
        opportunities.append(check)
    return opportunities


def native_satchel_opportunities(unit, contacts):
    """Only an explicit, matching native check can advertise a direct throw."""
    check = unit.get('combat', {}).get('satchel_check', {})
    reach, ready = unit.get('satchel_range'), unit.get('satchel_ready_in')
    if (not isinstance(check, dict) or check.get('reason') != ''
            or not isinstance(reach, (int, float)) or isinstance(reach, bool) or not math.isfinite(reach) or reach <= 0
            or not isinstance(ready, (int, float)) or isinstance(ready, bool) or not math.isfinite(ready) or ready > 0):
        return []
    distance = check.get('distance')
    if not isinstance(distance, (int, float)) or isinstance(distance, bool) or not math.isfinite(distance) or not 0 <= distance <= reach:
        return []
    visible = {c.get('id') for c in contacts if c.get('visible') is True and c.get('kind') == 'tank' and c.get('hp', 1) > 0}
    return [copy.deepcopy(check)] if check.get('target_id') in visible else []


def native_breach_opportunities(unit):
    """Only native checked cover IDs can become a breach action, never coordinates."""
    if (unit.get('weapon') != 'rocket' or unit.get('hp', 0) <= 0
            or (unit.get('ammo_infinite') is not True and (unit.get('ammo', 0) <= 0 or unit.get('reload_remaining', 0) > 0))
            or unit.get('survival_reason') or unit.get('suppression', 0) >= .65):
        return []
    checks = unit.get('combat', {}).get('cover_breach_checks', [])
    if not isinstance(checks, list): return []
    results, seen = [], set()
    for row in checks:
        if not isinstance(row, dict): continue
        key, distance = row.get('target_id'), row.get('distance')
        if (not isinstance(key, str) or not key or key in seen or row.get('reason') != ''
                or not isinstance(distance, (int, float)) or isinstance(distance, bool)
                or not math.isfinite(distance) or not 0 <= distance <= unit.get('weapon_range', 0)
                or row.get('hp', 0) <= 0):
            continue
        seen.add(key);results.append(copy.deepcopy(row))
    return results


class SoldierAgents:
    def __init__(self, owner):
        self.owner = owner
        self.agents = {}
        self.capture_samples = {}
        self.inflight = {}
        # Candidate and model transports retain their real slots across resets.
        self.candidate_inflight = {}
        self.candidate_serial = 0
        self.candidate_timeouts = 0
        self.pending = None
        self.receipts = {}
        self.next_wall = 0.
        self.calls = 0
        self.accepted = 0
        self.discarded = 0
        self.deferred = 0
        self.rebased = 0

    def reset(self):
        # Keep transport occupied until it finishes; authority token invalidates its response.
        self.agents.clear()
        self.capture_samples.clear()
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

    def _token(self, uid):
        o = self.owner
        return (o.identity, o.world.get('navigation_revision'),
                self.agents.get(uid, {}).get('task_version'))

    def _invalid_reason(self, request):
        uid = request['uid']
        if uid not in self.agents:
            return 'unit_dead_or_removed'
        current = self._token(uid)
        if request['token'][0] != current[0]:
            return 'authority_changed'
        if request['token'][1] != current[1]:
            return 'navigation_changed'
        if request['token'][2] != current[2]:
            return 'personal_task_changed'
        current_unit = next((u for u in self.owner._members(self.owner.world) if u['id'] == uid), {})
        if 'weapon' in request and request['weapon'] != current_unit.get('weapon'):
            return 'weapon_changed'
        current_squad = self.owner.world.get('squad_behavior', {}).get('squads', {}).get(self.owner.squad_id, {})
        current_handoff = survival_handoff(self.owner.world, current_unit, self.owner.team, current_squad)
        requested_handoff = request.get('survival_handoff')
        if requested_handoff and not handoff_matches(requested_handoff, current_handoff):
            return 'survival_review_expired'
        if not requested_handoff and current_handoff.get('decision_allowed') is True:
            return 'survival_review_changed'
        if self.owner.clock()-request['started'] > self.owner.config.get('timeout', 10.)+1:
            return 'response_timeout'
        return None

    @staticmethod
    def _survival_busy(unit, *, committed_throw=False):
        return decision_blocked(unit, legacy_pressure=.72 if committed_throw else .35)

    def _grenade_checks(self, unit, contacts):
        """Only native checks for current visible enemy infantry may cross the wire."""
        return native_grenade_checks(self.owner.world, self.owner.team, unit, contacts)

    def _grenade_opportunities(self, unit, contacts):
        """No inferred arc/safety: a missing native check never makes an option."""
        return native_grenade_opportunities(self.owner.world, self.owner.team, unit, contacts)

    def _context_contacts(self):
        contacts = self.owner.world.get('squad_behavior', {}).get('perception', {}).get(self.owner.team, {}).get('contacts', [])
        return list(contacts.values()) if isinstance(contacts, dict) else contacts

    def _defer(self, row, agent, reason):
        # Keep one latest wake / one completed response; repeated ticks do not
        # create model work or extend its original validity deadline.
        if row.get('deferred_reason') != reason:
            row['deferred_reason'] = reason
            self.deferred += 1
            self.owner._record('soldier-review-deferred', unit_id=agent['id'], reason=reason)

    def _finish_survival(self, request, reason, *, accepted=False):
        token = (request.get('survival_handoff') or {}).get('token')
        if token:
            finish_survival_review(self.owner, request['uid'], token, reason, accepted=accepted)

    def _squad_wait_reason(self, squad):
        if self.owner.pending_commands:
            return 'awaiting_squad_receipt'
        order = self.owner.last_order or {}
        # Receipts and observations are read independently. An accepted new
        # squad command can arrive alongside the previous world snapshot.
        # Wait for the engine to observe that order; never rewrite its facts.
        if order.get('accepted') and order.get('order_id') != squad.get('order_id'):
            return 'awaiting_squad_observation'
        return None

    def _task_signature(self, uid, squad):
        row = squad.get('assignments', {}).get(uid, {})
        point = row.get('position') or squad.get('goal')
        endpoint = row.get('endpoint_id')
        if endpoint:
            destination = ('endpoint', endpoint, row.get('approach_region', row.get('region_id')))
        elif isinstance(point, (list, tuple)) and len(point) == 2:
            destination = ('point', *(round(float(value), 3) for value in point))
        else:
            destination = None
        gear = self.owner._equipment_goal() or {}
        gear_role = ('actor' if gear.get('actor_id') == uid else
                     'support' if uid in gear.get('support_ids', []) else None)
        equipment = (gear.get('equipment_id'), gear.get('phase'), gear_role) if gear_role else None
        # Native duties, explanation text, visible target sets and a shrinking
        # route prefix are execution progress, not a new model assignment.
        token = squad.get('assignment_tokens', {}).get(uid)
        # A kept member retains its own native assignment even when another
        # member changes the squad's headline intent. Its real token is the
        # authority; a global label must not discard this unit's valid answer.
        intent_identity = squad.get('intent') if token is None else None
        return (intent_identity, row.get('role'), row.get('region_id'), destination, equipment, token)

    def observe(self, members, squad, receipts):
        o = self.owner
        now = o.world.get('time', 0.)
        living = {u['id'] for u in members}
        self.agents = {k: v for k, v in self.agents.items() if k in living}
        self.capture_samples = {k: v for k, v in self.capture_samples.items() if k in living}
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
            current_weapon = u.get('weapon')
            if 'observed_weapon' in a and a['observed_weapon'] != current_weapon:
                a['weapon_wake'] = True
                a['next_at'] = min(a['next_at'], now)
            a['observed_weapon'] = current_weapon
            a['review_interval_s'] = round(self._review_interval(uid), 3)
            a['initial_delay_s'] = round(self._initial_delay(uid), 3)
            assignment = dict(order_id=squad.get('order_id'), intent=squad.get('intent'),
                              assignment_token=squad.get('assignment_tokens', {}).get(uid),
                              goal=squad.get('assignments', {}).get(uid, {}).get('position') or squad.get('goal'), assigned_role=squad.get('assignments', {}).get(uid, {}).get('role'),
                              role=duty.get('role', 'observe'),
                              reason=duty.get('reason', ''), mover=squad.get('mover'),
                              target_region_id=squad.get('assignments', {}).get(uid, {}).get('region_id'),
                              region_path=squad.get('assignments', {}).get(uid, {}).get('region_path', []),
                              support_ids=squad.get('support_ids', []))
            assignment['task_contract'] = copy.deepcopy(squad.get('task_contract', {}))
            assignment['task_area'] = copy.deepcopy(squad.get('task_contract', {}).get('member_areas', {}).get(uid, {}))
            assignment['assignment_execution'] = copy.deepcopy(squad.get('assignment_execution', {}).get(uid, {}))
            permission = local_grant(squad, uid, now)
            assignment['local_behavior_grant'] = copy.deepcopy(permission)
            permission_identity = local_grant_identity(permission)
            if a.get('grant_identity') != permission_identity:
                a['assignment_wake'] = True
                a['next_at'] = min(a['next_at'], now)
            a['grant_identity'] = permission_identity
            a['local_behavior_grant'] = permission
            binding = squad.get('cooperation_plan', {}).get('bindings', {}).get(uid, {})
            review_identity = (permission_identity, binding.get('review_id'), binding.get('review_reason'))
            if permission.get('review_due') and review_identity != a.get('reviewed_local_behavior'):
                a['local_behavior_wake'] = True
                a['next_at'] = min(a['next_at'], now)
            # A new order id is not, by itself, a new personal task.  The
            # commander may refresh progress/receipts while the soldier is
            # still doing the same job; waking every member for that update
            # was the main source of bursty, redundant personal JEV calls.
            # Each member owns a semantic task version. A teammate's new order
            # must not cancel a still-valid personal response.
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
            task_signature = self._task_signature(uid, squad)
            if a.get('task_signature') != task_signature:
                if 'task_signature' in a:
                    a['next_at'] = min(a['next_at'], now)
                a['task_signature'] = task_signature
                a['task_version'] = a.get('task_version', 0) + 1
                a['assignment_wake'] = True
            history = a.setdefault('movement_history', [])
            # Bounded engine-observed samples, never selected/queued positions.
            if not history or now - history[-1]['time'] >= 1.:
                history.append(dict(time=round(now, 2), position=list(u['position'])))
                del history[:-8]
            a['assignment'] = assignment
            a['failed_firing_sites'] = copy.deepcopy(o.unit_history.get(uid, {}).get('failed_firing_sites', []))
            # One review per persistent local loop, including blocked/recover
            # duties that otherwise do not need paid periodic reaffirmation.
            from movement_stall_episode import public as local_execution_episode
            episode = local_execution_episode(o.unit_history.get(uid, {}), now)
            a['episode_wake'] = bool(episode and episode['episode_id'] != a.get('reviewed_episode_id'))
            if a['episode_wake'] and episode['episode_id'] != a.get('episode_id'):
                a['next_at'] = min(a['next_at'], now)
            a['episode_id'] = episode.get('episode_id')
            from fire_effectiveness import public as fire_effectiveness
            fire_episode = fire_effectiveness(o.unit_history.get(uid, {}), now)
            fire_was_ready = a.get('fire_effect_wake', False)
            a['fire_effect_wake'] = bool(fire_episode.get('review_ready')
                and fire_episode['episode_id'] != a.get('reviewed_fire_effect_id'))
            if a['fire_effect_wake'] and (not fire_was_ready or fire_episode['episode_id'] != a.get('fire_effect_id')):
                a['next_at'] = min(a['next_at'], now)
            a['fire_effect_id'] = fire_episode.get('episode_id')
            from assignment_fire_review import participation as attack_position_review
            position_review = attack_position_review(o.unit_history.get(uid, {}), now)
            was_ready = a.get('attack_position_wake', False)
            a['attack_position_wake'] = bool(position_review.get('review_ready')
                and position_review['episode_id'] != a.get('reviewed_attack_position_id'))
            if a['attack_position_wake'] and (not was_ready or position_review['episode_id'] != a.get('attack_position_id')):
                a['next_at'] = min(a['next_at'], now)
            a['attack_position_id'] = position_review.get('episode_id')
            handoff = survival_handoff(o.world, u, o.team, squad)
            was_ready = a.get('survival_review_wake', False)
            a['survival_review_wake'] = bool(handoff.get('decision_allowed') is True
                and handoff['token'] != a.get('reviewed_survival_token'))
            if a['survival_review_wake'] and (not was_ready or handoff['token'] != a.get('survival_review_token')):
                a['next_at'] = min(a['next_at'], now)
            a['survival_review_token'] = handoff.get('token')
            equipment_goal = o._equipment_goal() or {}
            equipment_role = ('actor' if equipment_goal.get('actor_id') == uid else
                              'support' if uid in equipment_goal.get('support_ids', []) else None)
            equipment_signature = ((equipment_goal.get('equipment_id'), equipment_goal.get('phase'), equipment_role)
                                   if equipment_role else None)
            if a.get('equipment_signature') != equipment_signature:
                a['equipment_signature'] = equipment_signature
                a['next_at'] = min(a['next_at'], now)
                a['assignment_wake'] = True
            a['engine_execution'] = copy.deepcopy(squad.get('personal', {}).get(uid, {}))
            movement = o._motion_execution().get(uid, {})
            failure = ((movement.get('order_id'), movement.get('reason'), movement.get('ended_at'))
                       if movement.get('state') == 'failed' and movement.get('order_id') == squad.get('order_id') else None)
            if failure and failure != a.get('motion_failure'):
                a['next_at'] = min(a['next_at'], now)
                a['assignment_wake'] = True
            a['motion_failure'] = failure
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
            throw_clear = bool(native_satchel_opportunities(u, visible_tanks))
            throw_ready = anti_armor_stage == 'throw' and throw_clear
            if throw_ready and not a.get('anti_armor_throw_ready', False):
                a['anti_armor_wake'] = True
                a['next_at'] = min(a['next_at'], now)
            a['anti_armor_throw_ready'] = throw_ready
            grenade_targets = tuple(sorted(row['target_id'] for row in self._grenade_opportunities(u, contacts)))
            if set(grenade_targets) - set(a.get('grenade_targets', ())):
                # Notify JEV of a newly feasible action once.  This does not
                # interrupt active personal motion or choose a throw itself.
                a['grenade_wake'] = True
                a['next_at'] = min(a['next_at'], now)
            a['grenade_targets'] = grenade_targets
            breach_targets = tuple(sorted(row['target_id'] for row in native_breach_opportunities(u)))
            if set(breach_targets) - set(a.get('breach_targets', ())):
                a['breach_wake'] = True
                a['next_at'] = min(a['next_at'], now)
            a['breach_targets'] = breach_targets
        for rid, item in list(self.receipts.items()):
            result = receipts.get(rid)
            if result is None and o.clock()-item['submitted'] <= 5:
                continue
            if result is None or receipt_unknown(result):
                unresolved=bool(result and result.get('status')=='unresolved') or o.clock()-item['submitted']>14.
                a=self.agents.get(item['uid'])
                actual=copy.deepcopy(result or dict(accepted=None,status='unknown',message='receipt_missing'))
                if unresolved:actual.update(accepted=None,status='unresolved')
                if a is not None:
                    a['status']='receipt_unresolved' if unresolved else 'receipt_unknown'
                    a['last_result']=actual
                if not item.get('unknown_recorded') or unresolved:
                    o._record('soldier-action-receipt-unknown',unit_id=item['uid'],intent=item['intent'],
                        result=actual,engine_behavior='continue_authoritative_native_assignment')
                    item['unknown_recorded']=True
                if unresolved:
                    self.receipts.pop(rid,None)
                    self._finish_survival(item,'native_action_outcome_unknown')
                continue
            self.receipts.pop(rid)
            a = self.agents.get(item['uid'])
            if item['token'][0] != o.identity:
                o._record('soldier-receipt-discarded', unit_id=item['uid'], reason='authority_changed')
                continue
            if a is None:
                continue
            ok = bool(result and result.get('accepted'))
            superseded = item['token'] != self._token(item['uid'])
            actual_result = copy.deepcopy(result or dict(accepted=False, message='receipt_timeout'))
            if not superseded:
                a['status'] = 'accepted' if ok else 'rejected'
                a['last_result'] = actual_result
                a['failures'] = 0 if ok else a['failures'] + 1
            self.accepted += int(ok)
            self._finish_survival(item, 'native_action_accepted' if ok else 'native_action_rejected', accepted=ok)
            o._record('soldier-action-receipt', unit_id=item['uid'], intent=item['intent'],
                      result=actual_result, superseded=superseded)
            if not ok and not superseded:
                a['assignment_wake'] = True
                a['next_at'] = now + self._review_interval(item['uid'])
                o._wake('participation_gap', dict(unit_id=item['uid'], reason='soldier_action_rejected:' + str(a['last_result'].get('message', 'unknown'))))

    def _context(self, unit, squad):
        o = self.owner
        a = self.agents[unit['id']]
        fields = ('id', 'weapon', 'hp', 'max_hp', 'position', 'ammo', 'ammo_infinite', 'reload_remaining', 'suppression', 'survival_reason', 'armor_risk', 'in_cover', 'weapon_range', 'last_shot_at', 'last_hit_at', 'last_damage_at', 'order_mode', 'satchel_ready_in', 'satchel_range', 'antiarmor_charge_remaining', 'grenades', 'grenade_range')
        # Squad perception is explicitly a teammate report; no world enemy list is passed.
        team_context = o._context(o._members(o.world))
        from battlefield_equipment import personal_equipment_opportunities
        equipment = copy.deepcopy(team_context.get('battlefield_equipment', []))
        for gun in equipment:
            if 'capture_candidates' in gun:
                gun['capture_candidates'] = [candidate for candidate in gun['capture_candidates']
                                             if candidate.get('unit_id', candidate.get('id')) == unit['id']]
        contacts = team_context['contacts']
        from battlefield_map import build as battlefield_map
        from engagement_feedback import geometry
        members = o._members(o.world)
        last_shot = unit.get('last_shot_at', -1)
        last_hit = unit.get('last_hit_at', -1)
        return dict(time=o.world['time'], self={k: unit[k] for k in fields if k in unit},
                    tactical_map=battlefield_map(o.world, o.topology, o.regions, members, contacts, o.plan, focus=unit),
                    engagement_map=geometry(o.world, [unit], contacts, o.regions, o.plan),
                    visibility=copy.deepcopy(team_context.get('visibility', {})),
                    ammunition_rules=copy.deepcopy(team_context.get('ammunition_rules', {})),
                    battlefield_equipment=equipment,
                    equipment_opportunities=personal_equipment_opportunities(
                        team_context.get('equipment_opportunities', []), unit['id']),
                    equipment_goal=copy.deepcopy(o._equipment_goal()),
                    equipment_assignment=copy.deepcopy(team_context.get('equipment_assignment')),
                    equipment_task=copy.deepcopy(team_context.get('equipment_task')),
                    throw_rules=copy.deepcopy(unit.get('combat', {}).get('throw_rules', {})),
                    satchel_check=copy.deepcopy(unit.get('combat', {}).get('satchel_check', {})),
                    satchel_execution=copy.deepcopy(unit.get('combat', {}).get('satchel', {})),
                    grenade_checks=self._grenade_checks(unit, contacts),
                    grenade_opportunities=self._grenade_opportunities(unit, contacts),
                    grenade_execution=copy.deepcopy(unit.get('combat', {}).get('grenade', {})),
                    cover_breach_opportunities=native_breach_opportunities(unit),
                    cover_breach_execution=copy.deepcopy(unit.get('combat', {}).get('cover_breach', {})),
                    seconds_since_last_shot=round(o.world['time']-last_shot,1) if last_shot >= 0 else None,
                    seconds_since_last_hit=round(o.world['time']-last_hit,1) if last_hit >= 0 else None,
                    assignment=copy.deepcopy(a['assignment']), memory=copy.deepcopy(a['memory']),
                    teammate_reports=[dict(c, source='squad_report_not_personal_sight') for c in contacts],
                    execution_evidence=copy.deepcopy(team_context['execution_evidence']['members'].get(unit['id'], {})),
                    path_active=bool(unit.get('combat', {}).get('path_active')),
                    firing_awareness=copy.deepcopy(unit.get('combat', {}).get('firing_awareness', {})),
                    coordination={uid: {k: row[k] for k in ('role', 'reason') if k in row}
                                  for uid, row in squad.get('duties', {}).items() if uid in self.agents},
                    engine_execution=copy.deepcopy(a['engine_execution']),
                    cooperation_board=copy.deepcopy(team_context.get('cooperation_board', {})),
                    motion_execution=o._motion_execution().get(unit['id'], {}), last_result=a.get('last_result'),
                    movement_history=copy.deepcopy(a.get('movement_history', [])),
                    recent_failed_firing_sites=copy.deepcopy(team_context['execution_evidence']['members'].get(unit['id'], {}).get('recent_failed_firing_sites', [])),
                    task_progress=self._task_progress(unit, a),
                    local_behavior_grant=copy.deepcopy(a.get('local_behavior_grant', {})))

    @staticmethod
    def _candidate_model_view(row):
        """Return a compact, read-only candidate description for JEV.

        ``row`` is kept unchanged in the local request/validator.  The model
        does not need empty collision identifiers, zero counts, or duplicate
        bookkeeping fields to choose an action, and sending those values for
        up to twelve candidates made personal requests disproportionately
        large. Empty fire_targets is meaningful negative evidence and must
        survive projection, even though moving to that point remains legal.
        """
        if not isinstance(row, dict):
            return row
        always = ('id', 'region_id', 'position', 'kind', 'path_length', 'equipment_id', 'purpose',
                  'goal_distance_gain', 'distance_from_self', 'target_distance', 'equipment_task_approach')
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
        if 'fire_targets' in row:
            view['fire_targets'] = copy.deepcopy(row['fire_targets'])
        target = row.get('equipment_task_approach', {}).get('target_id') or row.get('target_id')
        if 'fire_checks' in row:
            checks = sorted(row['fire_checks'], key=lambda c: c.get('target_id') != target)
            view['fire_checks'] = copy.deepcopy(checks[:4])
            view['fire_check_posture'] = row.get('fire_check_posture', 'unknown')
        if row.get('site_engagement_failures'):
            view['site_engagement_failures'] = copy.deepcopy(row['site_engagement_failures'])
        if row.get('engagement_value'):
            view['engagement_value'] = copy.deepcopy(row['engagement_value'])
        if row.get('close_engagement'):
            view['close_engagement'] = copy.deepcopy(row['close_engagement'])
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
        from engagement_feedback import failed_sites
        row['site_engagement_failures'] = [s for s in failed_sites(agent, now)
                                         if math.dist(s['position'], row['position']) <= .06]
        from weapon_affordance import site_value
        weapon_unit = dict(unit, position_role=assignment.get('assigned_role', unit.get('position_role')))
        row['engagement_value'] = site_value(weapon_unit, row, now)
        return row

    @staticmethod
    def _action_options(choices, sites, focus_targets, satchel_targets, grenade_targets=(), breach_targets=()):
        # Mechanical legal combinations only; no score, tactical ranking or rejection.
        options, criteria = {}, {}
        def add(intent, site_id=None, target_id=None):
            key = ':'.join(str(x) for x in (intent, site_id, target_id) if x is not None)
            options[key] = dict(intent=intent, site_id=site_id, target_id=target_id)
            criteria[key] = intent + (('；位置 ' + site_id) if site_id else '') + (('；目标 ' + target_id) if target_id else '')
        for intent in choices:
            if intent in SITE_ACTIONS:
                for key, row in sites.items():
                    if intent == 'approach_satchel':
                        if row.get('kind') in ('anti_armor_approach', 'anti_armor_throw_site') and row.get('target_id'):
                            add(intent, key, row['target_id'])
                    elif intent == 'peek_fire':
                        if row.get('cover_key'):
                            for target in row.get('fire_targets', []): add(intent, key, target)
                    elif intent != 'occupy_cover' or row.get('cover_key'):
                        add(intent, key)
            elif intent in ('focus_fire', 'satchel', 'grenade', 'breach_cover'):
                targets = {'focus_fire': focus_targets, 'satchel': satchel_targets, 'grenade': grenade_targets, 'breach_cover': breach_targets}[intent]
                for target in targets: add(intent, target_id=target)
            else: add(intent)
        return options, criteria

    def _capacity(self):
        return max(1, min(10, int(self.owner.config.get('soldier_concurrency', 4))))

    def _candidate_episode(self, unit, squad):
        handoff=survival_handoff(self.owner.world,unit,self.owner.team,squad)
        return (self._token(unit['id']),unit.get('weapon'),
            local_grant_identity(local_grant(squad,unit['id'],self.owner.world.get('time',0.))),handoff.get('token'))

    def _candidate_ready(self, unit, squad):
        agent=self.agents[unit['id']]
        episode=self._candidate_episode(unit,squad)
        if episode!=agent.get('candidate_episode'):
            agent['candidate_episode']=copy.deepcopy(episode)
            agent['candidate_retry_count']=0
            agent['candidate_next_wall_at']=0.
        return self.owner.clock()>=agent.get('candidate_next_wall_at',0.)

    def _candidate_backoff(self, request, reason):
        agent=self.agents.get(request['uid'])
        if not agent:return
        # A completed old-scope query cannot impose retry state on a newly
        # authorized task. Repeated wakes of the same episode do not reset it.
        if request.get('episode') is not None and request['episode']!=agent.get('candidate_episode'):return
        failures=min(5,agent.get('candidate_retry_count',0)+1)
        delay=min(2.,.25*(2**(failures-1)))
        agent.update(candidate_retry_count=failures,candidate_next_wall_at=self.owner.clock()+delay,
            assignment_wake=True)
        self.owner._record('soldier-candidate-backoff',unit_id=request['uid'],query_serial=request.get('serial'),
            reason=reason,retry_after_s=delay,episode_retry=failures,
            engine_behavior='continue_valid_assignment')

    def _candidate_completed_record(self,serial,request):
        if request.get('completion_recorded') or not request['future'].done():return
        request['completion_recorded']=True
        try:
            result=request['future'].result()
            status=result.get('status','missing_status') if isinstance(result,dict) else 'invalid_result_shape'
            count=len(result.get('options',[])) if isinstance(result,dict) and isinstance(result.get('options',[]),list) else None
            native_timing=result.get('query_timing') if isinstance(result,dict) else None
            error=None
        except Exception as exc:
            status='exception';count=None;native_timing=None;error=type(exc).__name__
        request['result_status']=status;request['result_option_count']=count
        self.owner._record('soldier-candidate-completed',unit_id=request['uid'],query_serial=serial,
            result_status=status,option_count=count,error_type=error,
            completed_wall=request.get('completed_at'),started_wall=request['started'],
            deadline_wall=request.get('deadline'),transport_timing=copy.deepcopy(request.get('timing',{})),
            native_query_timing=copy.deepcopy(native_timing),request_authority_token=copy.deepcopy(request.get('token')))

    def _schedule_candidate(self, unit, squad):
        """Freeze one bounded query while the controller owns its short lock.

        A single query transport per faction also preserves the legacy native
        file mailbox. Model calls have their existing independent actor lanes.
        Neither a timeout nor reset releases an occupied transport slot.
        """
        o = self.owner
        if self.candidate_inflight or len(self.inflight) >= self._capacity():
            return
        context = self._context(unit, squad)
        visible_tanks = [c for c in context['teammate_reports']
                         if c.get('visible') and c.get('kind') == 'tank' and c.get('id')]
        assignment = squad.get('assignments', {}).get(unit['id'], {})
        self.candidate_serial += 1
        serial, future = self.candidate_serial, Future()
        permission = local_grant(squad, unit['id'], o.world.get('time', 0.))
        request = dict(uid=unit['id'], token=self._token(unit['id']),
                       weapon=unit.get('weapon'), started=o.clock(), future=future,
                       survival_handoff=survival_handoff(o.world, unit, o.team, squad),
                       local_grant=copy.deepcopy(permission), completed_at=None,serial=serial,
                       episode=copy.deepcopy(self._candidate_episode(unit,squad)))
        budget=max(.1,min(2.,float(o.config.get('soldier_candidate_timeout_s',2.))))
        request['deadline']=request['started']+budget
        request['timing']=dict(started_wall=request['started'],deadline_wall=request['deadline'],query_serial=serial)
        self.candidate_inflight[serial] = request
        self.agents[unit['id']]['status'] = 'querying_candidates'
        self.agents[unit['id']]['candidate_attempt_serial']=serial
        frozen = copy.deepcopy(dict(world=o.world, unit=unit, assignment=assignment,
            regions=o.regions, topology=o.topology, team=o.team,
            visible_tanks=visible_tanks, equipment=context.get('battlefield_equipment', [])))
        request['timing']['freeze_completed_wall']=o.clock()
        query, path = o.config.get('candidate_query', query_candidates), o.config.get('spatial_path')
        mock = o.model == 'mock'
        o._record('soldier-candidate-request', unit_id=unit['id'], query_serial=serial,
                  token=copy.deepcopy(request['token']), transport='async_bounded',
                  started_wall=request['started'],deadline_wall=request['deadline'])

        def collect():
            # Everything passed to a transport belongs to the frozen request.
            # Do not touch live controller facts or acquire its lock during I/O.
            try:
                request['timing']['thread_started_wall']=o.clock()
                options=optional_kwargs(query,dict(deadline=request['deadline'],timing=request['timing']))
                request['timing']['callback_accepts_deadline']='deadline' in options
                result = (dict(status='mock', options=[]) if mock else
                          query(path, frozen['world'], frozen['unit'], frozen['assignment'],
                                frozen['regions'], frozen['topology'], frozen['team'],
                                visible_tanks=frozen['visible_tanks'], equipment=frozen['equipment'],**options))
                request['completed_at'] = o.clock()
                request['timing']['completed_wall']=request['completed_at']
                future.set_result(result)
            except Exception as error:
                request['completed_at'] = o.clock()
                request['timing']['completed_wall']=request['completed_at']
                future.set_exception(error)
            # Publish/launch only after native identity and task revalidation.
            # No network or waiting work occurs in this critical section.
            with o.lock:
                request['timing']['callback_lock_acquired_wall']=o.clock()
                self._candidate_completed_record(serial,request)
                current_squad = o.world.get('squad_behavior', {}).get('squads', {}).get(o.squad_id, {})
                growth = o.world.get('world_growth', {})
                active = (not o.stopped.is_set() and not o.world.get('paused')
                          and not o.world.get('winner')
                          and o.config.get('soldier_agents', True)
                          and o.world.get('demo', {}).get('phase', 'battle') == 'battle'
                          and (not growth.get('enabled') or growth.get('mission', {}).get('status') == 'active')
                          and o.world.get('control', {}).get(o.team) == o.config.get('control_mode', 'lm'))
                self._harvest_candidates(current_squad, active=active)
        threading.Thread(target=collect, name='soldier-candidates-' + o.team, daemon=True).start()

    def _harvest_candidates(self, squad, *, active):
        o = self.owner
        if not active:
            return
        for serial, request in list(self.candidate_inflight.items()):
            age = o.clock() - request['started']
            deadline=request.get('deadline',request['started']+max(.1,float(o.config.get('soldier_candidate_timeout_s',2.))))
            if not request['future'].done():
                if o.clock() >= deadline and not request.get('timeout_reported'):
                    request['timeout_reported'] = True
                    self.candidate_timeouts += 1
                    o._record('soldier-candidate-timeout', unit_id=request['uid'], query_serial=serial,
                              capacity_retained=True, engine_behavior='continue_valid_assignment')
                    self._finish_survival(request, 'personal_candidate_timeout')
                continue
            # Physical completion is the only event that frees this slot.
            self.candidate_inflight.pop(serial)
            self._candidate_completed_record(serial,request)
            uid, a = request['uid'], self.agents.get(request['uid'])
            try:
                o._record('soldier-candidate-harvested',unit_id=uid,query_serial=serial,
                    result_status=request.get('result_status'),option_count=request.get('result_option_count'),
                    harvest_wall=o.clock(),completed_wall=request.get('completed_at'),
                    transport_timing=copy.deepcopy(request.get('timing',{})))
                invalid = self._invalid_reason(request)
                if (request.get('completed_at') or o.clock()) >= deadline:
                    invalid = invalid or 'candidate_response_timeout'
                if local_grant_identity(request.get('local_grant')) != local_grant_identity(local_grant(squad, uid, o.world.get('time', 0.))):
                    invalid = invalid or 'local_behavior_grant_changed'
                if invalid:
                    self._finish_survival(request, invalid)
                    self.discarded += 1
                    if a is not None:
                        a['status'] = 'candidate_discarded'
                        a['assignment_wake'] = True
                    o._record('soldier-candidate-discarded', unit_id=uid, query_serial=serial, reason=invalid)
                    if invalid=='candidate_response_timeout':self._candidate_backoff(request,invalid)
                    continue
                result = request['future'].result()
                if not isinstance(result,dict):raise ValueError('invalid_candidate_result_shape')
                if result.get('status') not in ('fresh','no_proposals','mock'):
                    self._candidate_backoff(request,str(result.get('status','unknown_query_result')))
                    if a is not None:a['status']='candidate_unavailable'
                    o._record('soldier-candidate-failed',unit_id=uid,query_serial=serial,
                        reason=result.get('status','unknown_query_result'),option_count=len(result.get('options',[])))
                    continue
                unit = next((u for u in o._members(o.world) if u['id'] == uid), None)
                if (unit is None or self._squad_wait_reason(squad) or handover_waiting_member(o, uid) or o.stopped.is_set()
                        or o.budget_exhausted or o.request_count >= o.config.get('max_requests', 100)):
                    if a is not None:
                        a['assignment_wake'] = True
                    continue
                self._launch_model(unit, squad, result)
                if a is not None:a['candidate_retry_count']=0
            except Exception as error:
                self._finish_survival(request, 'personal_candidate_failed')
                if a is not None:
                    a['status'] = 'candidate_error'
                    a['assignment_wake'] = True
                    a['next_at'] = o.world.get('time', 0.) + self._review_interval(uid)
                o._record('soldier-candidate-failed', unit_id=uid, query_serial=serial,
                          reason=str(error)[:160] if isinstance(error, (ValueError, KeyError, TypeError)) else type(error).__name__)
                self._candidate_backoff(request,type(error).__name__)

    def tick(self, members, squad, receipts, *, active):
        o = self.owner
        self.observe(members, squad, receipts)
        self._harvest_candidates(squad, active=active)
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
                        self._finish_survival(request, 'personal_model_timeout')
                continue
            uid = request['uid']
            a = self.agents.get(uid)
            try:
                response = request['future'].result()
                invalid = self._invalid_reason(request)
                if invalid:
                    self._finish_survival(request, invalid)
                    self.inflight.pop(uid, None)
                    self.discarded += 1
                    if a is not None:
                        a['status'] = 'response_discarded'
                        a['assignment_wake'] = True
                        if invalid not in ('personal_task_changed', 'survival_review_changed'):
                            a['next_at'] = now + self._review_interval(uid)
                    o._record('soldier-response-discarded', unit_id=uid, reason=invalid)
                else:
                    squad_wait = self._squad_wait_reason(squad)
                    if squad_wait:
                        self._defer(request, a, squad_wait)
                        continue
                    if request.get('local_grant') and local_grant_identity(request['local_grant']) != local_grant_identity(local_grant(squad, uid, now)):
                        raise ValueError('local_behavior_grant_changed')
                    selected = response['answers']['action']['choice']
                    if selected not in request['options']:
                        raise ValueError('invalid_soldier_choice')
                    option = request['options'][selected]
                    choice, site_id, target_id = option['intent'], option['site_id'], option['target_id']
                    if handover_waiting_member(o, uid) and choice not in ('continue_task', 'report_blocked'):
                        self.inflight.pop(uid, None)
                        a['status'] = 'handover_pending'
                        self._finish_survival(request, 'new_squad_intent_waiting')
                        o._record('soldier-response-discarded', unit_id=uid, reason='handover_pending')
                        continue
                    current = next(u for u in members if u['id'] == uid)
                    committed_throw = (choice == 'satchel' and current.get('antiarmor_charge_remaining', 0) > 0)
                    handoff = survival_handoff(o.world, current, o.team, squad)
                    requested_handoff = request.get('survival_handoff')
                    handoff_wait = bool(requested_handoff and not handoff_can_execute(requested_handoff, handoff))
                    if choice not in ('continue_task', 'report_blocked') and (handoff_wait or (
                            choice not in ('grenade', 'satchel', 'breach_cover')
                            and not (choice == 'approach_satchel' and current.get('combat', {}).get('throw_rules', {}).get('satchel', {}).get('danger_reason') == '')
                            and self._survival_busy(current, committed_throw=committed_throw)
                            and not handoff_can_execute(requested_handoff, handoff))):
                        a['status'] = 'survival_interrupted'
                        self._defer(request, a, 'survival_active')
                        continue
                    self.inflight.pop(uid, None)
                    if choice == 'report_blocked':
                        a['reported_at'] = now
                        a['reported_order'] = squad['order_id']
                        a['reported_task_version'] = a['task_version']
                    if choice in ('continue_task', 'report_blocked'):
                        self._finish_survival(request, 'personal_no_replacement_selected')
                    sites = request['sites']
                    if choice in SITE_ACTIONS and site_id not in sites:
                        raise ValueError('invalid_soldier_site')
                    if choice in ('peek_fire', 'focus_fire', 'satchel', 'approach_satchel', 'grenade', 'breach_cover'):
                        valid_targets = ([sites[site_id].get('target_id')] if choice == 'approach_satchel' else
                                         sites[site_id]['fire_targets'] if choice == 'peek_fire' else
                                         request['breach_targets'] if choice == 'breach_cover' else
                                         request['grenade_targets'] if choice == 'grenade' else
                                         request['satchel_targets'] if choice == 'satchel' else request['focus_targets'])
                        if target_id not in valid_targets:
                            raise ValueError('invalid_soldier_target')
                    if choice == 'grenade':
                        contacts = o.world.get('squad_behavior', {}).get('perception', {}).get(o.team, {}).get('contacts', [])
                        if isinstance(contacts, dict): contacts = list(contacts.values())
                        if target_id not in {row['target_id'] for row in self._grenade_opportunities(current, contacts)}:
                            raise ValueError('grenade_opportunity_expired')
                    if choice == 'satchel' and target_id not in {row['target_id'] for row in native_satchel_opportunities(current, self._context_contacts())}:
                        raise ValueError('satchel_opportunity_expired')
                    if choice == 'breach_cover' and target_id not in {row['target_id'] for row in native_breach_opportunities(current)}:
                        raise ValueError('breach_opportunity_expired')
                    a['last_choice'] = choice
                    a['last_review'] = now
                    if choice not in ('continue_task', 'report_blocked'):
                        a['last_action_at'] = now
                    a['next_at'] = now + self._review_interval(uid)
                    a['status'] = 'continued' if choice == 'continue_task' else 'submitting'
                    if request['order_id'] != squad.get('order_id'):
                        self.rebased += 1
                        o._record('soldier-response-rebased', unit_id=uid,
                                  previous_order_id=request['order_id'], order_id=squad.get('order_id'),
                                  task_version=a['task_version'])
                    provider_id = response.get('requestId')
                    provider_id = provider_id if isinstance(provider_id, str) and provider_id.strip() else None
                    action_id = provider_id or request['local_decision_id']
                    o._record('soldier-decision', unit_id=uid, choice=choice, site_id=site_id,
                              target_id=target_id, response=response,
                              local_decision_id=request['local_decision_id'], provider_request_id=provider_id,
                              local_behavior=copy.deepcopy(option.get('local_behavior')),
                              action_id=action_id if choice == 'hold_fire_position' or option.get('local_behavior') else None)
                    if choice != 'continue_task':
                        command = dict(action='soldier_order', faction=o.team, unit_ids=[uid],
                            squad_id=o.squad_id, order_id=squad['order_id'], intent=choice,
                            run_id=o.world['run_id'], seen_tick=int(o.world['tick']),
                            control_epoch=o.world.get('control_epochs', {}).get(o.team, 0))
                        if requested_handoff and choice != 'report_blocked':
                            command['survival_review_token'] = requested_handoff['token']
                        if choice == 'hold_fire_position' or option.get('local_behavior'):
                            command['action_id'] = action_id[:160]
                        if option.get('local_behavior'):
                            command['local_behavior'] = copy.deepcopy(option['local_behavior'])
                            command['assignment_token'] = copy.deepcopy(option['local_behavior']['parent_assignment_token'])
                        if choice in SITE_ACTIONS:
                            command.update(site_id=site_id, candidate_query_id=request['candidate_query_id'])
                        if choice in ('peek_fire', 'focus_fire', 'satchel', 'approach_satchel', 'grenade', 'breach_cover'):
                            command['target_id'] = target_id
                        if choice in ('grenade', 'breach_cover', 'satchel', 'approach_satchel', 'hold_fire_position') and uid in squad.get('assignment_tokens', {}):
                            command['assignment_token'] = copy.deepcopy(squad['assignment_tokens'][uid])
                        if getattr(o.game, 'session_id', None): command['instance_id'] = o.game.session_id
                        status, receipt = o.state.submit(command, source='lm')
                        if status != 202:
                            raise ValueError('soldier_queue_rejected:' + str(receipt.get('error', status)))
                        self.receipts[receipt['id']] = dict(uid=uid, intent=choice, submitted=o.clock(), token=self._token(uid),
                            survival_handoff=copy.deepcopy(request.get('survival_handoff')))
            except Exception as error:
                self._finish_survival(request, 'personal_decision_failed')
                self.inflight.pop(uid, None)
                if a is not None:
                    a['status'] = 'model_error'
                    a['next_at'] = now + self._review_interval(uid)
                    a['assignment_wake'] = True
                reason = str(error)[:160] if isinstance(error, (ValueError, KeyError, TypeError)) else type(error).__name__
                o._record('soldier-decision-failed', unit_id=uid, reason=reason)
        self.pending = next(iter(self.inflight.values()), None)
        if len(self.inflight) + len(self.candidate_inflight) >= self._capacity() or self._squad_wait_reason(squad) or not squad.get('order_id') or o.stopped.is_set() or o.budget_exhausted:
            return
        candidates = []
        for u in members:
            a = self.agents[u['id']]
            if not self._candidate_ready(u,squad):continue
            if handover_waiting_member(o, u['id']):
                a['status'] = 'handover_pending'
                continue
            if (squad.get('cooperation_plan', {}).get('schema') == 'combat-coordination/v1'
                    and not a.get('local_behavior_grant')):
                # A missing/expired delegation in the new contract must not
                # silently reopen the unrestricted legacy personal menu.
                a['status'] = 'awaiting_local_grant'
                self._finish_survival(dict(uid=u['id'], survival_handoff=survival_handoff(o.world, u, o.team, squad)),
                                      'personal_no_local_grant')
                continue
            if (u['id'] in self.inflight or any(row['uid'] == u['id'] for row in self.candidate_inflight.values()) or any(item['uid']==u['id'] for item in self.receipts.values())
                    or now < a['next_at'] or o.clock() < a.get('next_wall_at', 0)): continue
            committed_throw = (a.get('anti_armor_stage') == 'throw' and u.get('antiarmor_charge_remaining', 0) > 0)
            explosive_ready = bool(native_breach_opportunities(u) or self._grenade_opportunities(u, self._context_contacts())
                                   or native_satchel_opportunities(u, self._context_contacts())
                                   or (a.get('anti_armor_stage') == 'approach' and u.get('combat', {}).get('throw_rules', {}).get('satchel', {}).get('danger_reason') == ''))
            # A persistent loop can be reviewed once while pressure continues.
            # Preparation never grants execution authority: the result still
            # waits in the survival gate above. Immediate explosion escape and
            # a committed throw remain uninterrupted even at request time.
            review_wake = a.get('episode_wake') or a.get('fire_effect_wake') or a.get('attack_position_wake') or a.get('weapon_wake') or a.get('survival_review_wake') or a.get('local_behavior_wake')
            episode_review = (review_wake and u.get('survival_reason') != 'incoming_explosive'
                              and not committed_throw)
            # A failed native shelter may prepare one replacement while a
            # hard action finishes. Its result still waits for native readiness.
            if self._survival_busy(u, committed_throw=committed_throw) and not explosive_ready and not episode_review and not a.get('survival_review_wake'):
                self._defer(a, a, 'survival_before_request')
                continue
            a.pop('deferred_reason', None)
            if (a.get('local_behavior_grant') and a['last_review'] >= 0
                    and not review_wake and not any(a.get(key) for key in
                        ('assignment_wake', 'anti_armor_wake', 'grenade_wake', 'breach_wake'))):
                continue
            personal = a.get('engine_execution', {})
            ready_to_throw = (a.get('anti_armor_stage') == 'throw' and a.get('anti_armor_throw_ready', True)
                              and not u.get('survival_reason')
                              and u.get('suppression', 0) < (.72 if u.get('antiarmor_charge_remaining', 0) > 0 else .35))
            if personal.get('status') in ('active', 'suspended') and now < personal.get('until', 0) and not ready_to_throw:
                if not review_wake:
                    continue
            # Effective actions do not require paid periodic reaffirmation.
            if a['last_review'] >= 0 and a['assignment']['role'] in (
                    'observe', 'approach', 'support', 'reload', 'recover', 'acquire_fire', 'blocked') \
                    and not a.get('anti_armor_wake') and not a.get('grenade_wake') and not a.get('breach_wake') and not a.get('assignment_wake') and not review_wake:
                continue
            if a['last_review'] >= 0 and a['assignment']['role'] == 'observe' and not squad.get('duties', {}).get(u['id']) and not review_wake:
                continue
            if (a.get('last_choice') == 'report_blocked' and a.get('reported_task_version') == a['task_version']
                    and now-a.get('reported_at', -100) < 10 and not review_wake):
                continue
            candidates.append(u)
        if not candidates: return
        unit = min(candidates, key=lambda u: (self.agents[u['id']].get('candidate_attempt_serial',-1),
            self.agents[u['id']]['last_review']))
        a = self.agents[unit['id']]
        if o.request_count >= o.config.get('max_requests', 100): return
        self._schedule_candidate(unit, squad)

    def _launch_model(self, unit, squad, result):
        o = self.owner
        now = o.world.get('time', 0.)
        a = self.agents[unit['id']]
        shared = o.config.get('shared_request_budget')
        choices = dict(CHOICES)
        hold_caps = unit.get('combat', {}).get('personal_action_capabilities', {})
        hold_capability = hold_caps.get('hold_fire_position', {}) if isinstance(hold_caps, dict) else {}
        if not isinstance(hold_capability, dict) or not (hold_capability.get('supported') is True and hold_capability.get('available') is True):
            choices.pop('hold_fire_position')
        if a.get('reported_task_version') == a['task_version'] and now-a.get('reported_at', -100) < 15:
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
        from equipment_review import capture_sample, annotate_approaches
        self.capture_samples[unit['id']] = capture_sample(o.world, unit, squad, result,
                                                        context.get('battlefield_equipment', []))
        annotate_approaches(context.get('equipment_opportunities', []), o.world, [unit], squad,
                            {unit['id']: self.capture_samples[unit['id']]})
        sites = {row['id']: self._site_facts(unit, a['assignment'], a, row, now)
                 for row in result.get('options', []) if row.get('id')}
        from battlefield_equipment import equipment_route_fact
        from close_engagement import site_facts as close_engagement_site
        for row in sites.values():
            row['close_engagement'] = close_engagement_site(
                unit, row, context['teammate_reports'], o.world, now=now)
            fact = equipment_route_fact(unit, row.get('position'), context.get('equipment_goal'),
                                        context.get('battlefield_equipment', []))
            if fact:
                row['equipment_task_approach'] = fact
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
            choices['approach_satchel'] = CHOICES['approach_satchel']
            choices['prone_approach'] = '反坦克低姿接近：选择反坦克接近点，卧姿匍匐一段；路线暴露但仍可推进时用'
        throw_sites = [row for row in sites.values() if row.get('kind') == 'anti_armor_throw_site']
        if throw_sites:
            context['anti_armor_throw_sites'] = [dict(id=row['id'], target_distance=row.get('target_distance'),
                path_length=round(row.get('path_length', 0), 3), potential_attackers=row.get('potential_attackers', 0))
                for row in throw_sites]
            choices['approach_satchel'] = CHOICES['approach_satchel']
        if (not (anti_armor_sites or throw_sites)
                or unit.get('suppression', 0) >= .35 or unit.get('satchel_ready_in', 1) > 0):
            choices.pop('approach_satchel', None)
        focus_targets = sorted(set(context['execution_evidence'].get('engageable_visible_targets') or []))
        if not focus_targets: choices.pop('focus_fire', None)
        satchel_targets = sorted({row['target_id'] for row in native_satchel_opportunities(unit, visible_tanks)})
        if not satchel_targets: choices.pop('satchel', None)
        grenade_targets = sorted({row['target_id'] for row in context['grenade_opportunities']})
        if not grenade_targets: choices.pop('grenade', None)
        breach_targets = sorted({row['target_id'] for row in context['cover_breach_opportunities']})
        if not breach_targets: choices.pop('breach_cover', None)
        options, criteria = self._action_options(choices, sites, focus_targets, satchel_targets, grenade_targets, breach_targets)
        permission = local_grant(squad, unit['id'], now)
        if squad.get('cooperation_plan', {}).get('schema') == 'combat-coordination/v1' and not permission:
            a['status'] = 'awaiting_local_grant'
            self._finish_survival(dict(uid=unit['id'], survival_handoff=survival_handoff(o.world, unit, o.team, squad)), 'personal_no_local_grant')
            return
        if permission:
            options, criteria = local_action_options(options, sites, permission)
            context['local_behavior_grant'] = copy.deepcopy(permission)
            if not options:
                a['status'] = 'no_delegated_local_options'
                self._finish_survival(dict(uid=unit['id'], survival_handoff=survival_handoff(o.world, unit, o.team, squad)), 'personal_no_local_options')
                return
        handoff = survival_handoff(o.world, unit, o.team, squad)
        if handoff and not any(row.get('intent') not in ('continue_task', 'report_blocked') for row in options.values()):
            # A legality menu with no replacement is a fact, not another paid
            # choice. Escalate this one episode without inventing an action.
            self._finish_survival(dict(uid=unit['id'], survival_handoff=handoff), 'personal_no_replacement_options')
            a.update(status='no_replacement_options', reviewed_survival_token=handoff['token'],
                     survival_review_wake=False, assignment_wake=False, next_at=now+self._review_interval(unit['id']))
            return
        if shared is not None and not shared.claim():
            o.budget_exhausted = True
            return
        a['anti_armor_wake'] = False
        a['grenade_wake'] = False
        a['breach_wake'] = False
        a['assignment_wake'] = False
        a['weapon_wake'] = False
        if a.get('local_behavior_wake'):
            binding = squad.get('cooperation_plan', {}).get('bindings', {}).get(unit['id'], {})
            a['reviewed_local_behavior'] = (local_grant_identity(permission), binding.get('review_id'), binding.get('review_reason'))
            a['local_behavior_wake'] = False
        if a.get('episode_wake'):
            a['reviewed_episode_id'] = a['episode_id']
            a['episode_wake'] = False
            episode = o.unit_history.get(unit['id'], {}).get('local_execution_watch', {}).get('episode', {})
            if episode.get('episode_id') == a['reviewed_episode_id']:
                episode['personal_requested'] = True
        if a.get('fire_effect_wake'):
            a['reviewed_fire_effect_id'] = a['fire_effect_id']
            a['fire_effect_wake'] = False
            episode = o.unit_history.get(unit['id'], {}).get('fire_effect_watch', {}).get('episode', {})
            if episode.get('episode_id') == a['reviewed_fire_effect_id']:
                episode['personal_requested'] = True
        if a.get('attack_position_wake'):
            a['reviewed_attack_position_id'] = a['attack_position_id']
            a['attack_position_wake'] = False
            episode = o.unit_history.get(unit['id'], {}).get('attack_position_watch', {}).get('episode', {})
            if episode.get('episode_id') == a['reviewed_attack_position_id']:
                episode['personal_requested'] = True
        handoff = survival_handoff(o.world, unit, o.team, squad)
        if a.get('survival_review_wake'):
            a['reviewed_survival_token'] = a['survival_review_token']
            a['survival_review_wake'] = False
        future = Future()
        request = dict(uid=unit['id'], local_decision_id=uuid.uuid4().hex, weapon=unit.get('weapon'),
                       token=self._token(unit['id']), order_id=squad.get('order_id'),
                       started=o.clock(), future=future, survival_handoff=handoff,
                       choices=choices, options=options, sites=sites, local_grant=copy.deepcopy(permission),
                       focus_targets=focus_targets, satchel_targets=satchel_targets, grenade_targets=grenade_targets, breach_targets=breach_targets,
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
        context['action_definitions'] = choices
        context = model_view(context, 'personal')
        from task_modes import mode_id
        questions = {'action': dict(type='choice', instructions=combat_instructions(
            'personal', context, clear=mode_id(o.world) == 'clear_exit'), criteria=criteria)}
        from coordinate_prompt import prepare
        coordinate_binding = None
        if o.config.get('coordinate_protocol', True):
            context, questions, coordinate_binding = prepare(context, questions, 'personal')
        o._record('soldier-model-request', unit_id=unit['id'], local_decision_id=request['local_decision_id'], context=context, choices=criteria,
                  action_options=options, questions=questions)
        def ask():
            try:
                baseline = next((key for key, option in options.items() if option['intent'] == 'continue_task'), next(iter(options)))
                response = (dict(answers={'action': dict(choice=baseline)}) if o.model == 'mock' else
                    o.game.ask(context, questions))
                if o.model != 'mock' and coordinate_binding:
                    o._record('soldier-coordinate-response', unit_id=unit['id'], response=response)
                    response = coordinate_binding.decode(response)
                future.set_result(response)
            except Exception as error:
                future.set_exception(error)
        threading.Thread(target=ask, name='soldier-'+unit['id'], daemon=True).start()

    def snapshot(self):
        return dict(agents=copy.deepcopy(self.agents), calls=self.calls, accepted=self.accepted,
                    discarded=self.discarded, deferred=self.deferred, rebased=self.rebased,
                    pending=self.pending['uid'] if self.pending else None,
                    inflight_units=list(self.inflight),
                    candidate_inflight_units=[r['uid'] for r in self.candidate_inflight.values()],
                    candidate_timeouts=self.candidate_timeouts)
