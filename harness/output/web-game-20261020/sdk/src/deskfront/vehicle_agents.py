"""Event-driven JEV vehicle-local choices; native engine owns every movement and shot."""
import copy
from concurrent.futures import Future
import json
import threading
import uuid


class VehicleAgents:
    def __init__(self, owner):
        self.owner = owner
        self.pending = {}
        self.observed = {}
        self.next_wall = {}
        self.receipts = {}
        self.calls = self.accepted = self.discarded = 0

    def reset(self):
        # Keep outstanding transport slots until completion; identity invalidates them.
        self.observed.clear()
        self.next_wall.clear()
        self.receipts.clear()

    def token(self, unit, row):
        o = self.owner
        return (o.identity, o.world.get('map_index'), o.world.get('navigation_revision'),
                unit['id'], row.get('order_id'))

    @staticmethod
    def event(unit, row):
        # Do not turn candidate refreshes, each hit, or CD expiry into model requests.
        personal = row.get('personal', {})
        low = unit.get('hp', 0) / max(1., unit.get('max_hp', 1.)) < .35
        return (row.get('order_id'), row.get('mode'),
                row.get('reason') if row.get('state') in ('blocked', 'suspended') else 'ready',
                low, personal.get('action_id') if personal.get('state') == 'failed' else None)

    def tick(self, receipts, *, active):
        o = self.owner
        units = {u['id']: u for u in o.world.get('units', [])
                 if u.get('faction') == o.team and u.get('kind') == 'tank' and u.get('hp', 0) > 0}
        orders = o.world.get('support_execution', {})
        for rid, uid in list(self.receipts.items()):
            if rid not in receipts:
                continue
            receipt = receipts[rid]
            if receipt.get('accepted') is None and receipt.get('status') not in ('unresolved', 'superseded'):
                continue
            self.receipts.pop(rid)
            if receipt.get('accepted') is True:
                self.accepted += 1
            o._record('vehicle-personal-receipt', unit_id=uid, receipt=copy.deepcopy(receipt))
        for uid, request in list(self.pending.items()):
            if not request['future'].done():
                continue
            self.pending.pop(uid)
            try:
                response = request['future'].result()
                unit, row = units.get(uid), orders.get(uid, {})
                if not active or not unit or self.token(unit, row) != request['token']:
                    self.discarded += 1
                    o._record('vehicle-personal-discarded', unit_id=uid, reason='context_changed')
                    continue
                choice = response['answers']['action']['choice']
                if choice not in request['options']:
                    raise ValueError('invalid_vehicle_choice')
                menu = request['menu']
                command = dict(action='support_order', personal=True, faction=o.team,
                    kind='vehicle', asset_id=uid, unit_ids=[uid], parent_order_id=row['order_id'],
                    action_id=request['id'], choice_id=choice, candidate_query_id=menu['id'],
                    order_id=row['order_id'], run_id=o.world['run_id'], seen_tick=int(o.world['tick']),
                    control_epoch=o.world.get('control_epochs', {}).get(o.team, 0))
                if getattr(o.game, 'session_id', None):
                    command['instance_id'] = o.game.session_id
                status, queued = o.state.submit(command, source='lm')
                o._record('vehicle-personal-decision', unit_id=uid, response=response,
                          choice=choice, command=command, http_status=status, queue_result=queued)
                # Queueing is not an engine acceptance.
                self.observed[uid] = request['event']
                if status == 202:
                    self.observed[uid] = request['event']
                    self.receipts[queued['id']] = uid
                    if choice == 'report_blocked':
                        o._wake('participation_gap', dict(unit_id=uid, reason='vehicle_local_report'))
            except Exception as error:
                self.observed[uid] = request['event']
                o._record('vehicle-personal-failed', unit_id=uid, reason=type(error).__name__)
        if not active or o.stopped.is_set() or o.budget_exhausted:
            return
        for uid, unit in units.items():
            row = orders.get(uid, {})
            menu = row.get('local_menu', {})
            if (not menu or uid in self.pending or len(self.pending) >= 2
                    or row.get('mode') == 'hold_fire'
                    or row.get('state') in ('completed', 'cancelled', 'failed')
                    or row.get('personal', {}).get('state') in ('executing', 'holding', 'suspended')
                    or unit.get('combat', {}).get('crew_shock_remaining', 0) > 0
                    or unit.get('survival_reason') == 'incoming_explosive'
                    or uid in self.receipts.values()):
                continue
            event = self.event(unit, row)
            if self.observed.get(uid) == event or o.clock() < self.next_wall.get(uid, 0.):
                continue
            budget = o.config.get('shared_request_budget')
            if budget is not None and not budget.claim():
                o.budget_exhausted = True
                return
            options = {r['id']: copy.deepcopy(r) for r in menu.get('options', [])}
            if not options:
                continue
            future = Future()
            request = dict(id=uuid.uuid4().hex, future=future, token=self.token(unit, row),
                           menu=copy.deepcopy(menu), options=options, event=event)
            self.pending[uid] = request
            self.next_wall[uid] = o.clock() + max(1., float(o.config.get('soldier_cooldown_s', 1.)))
            self.calls += 1
            o.request_count += 1
            context = dict(prompt_contract=dict(version='vehicle-local/v1', role='personal'),
                role='personal', unit_id=uid, faction=o.team,
                time=o.world.get('time'), unit=copy.deepcopy({k:unit[k] for k in
                    ('id','position','hp','max_hp','weapon','order_mode','goal','last_shot_at',
                     'focus_id','survival_reason','yaw','turret_yaw') if k in unit}),
                fire_check=copy.deepcopy(unit.get('combat', {}).get('fire_check', {})),
                contacts=copy.deepcopy(o.world.get('squad_behavior', {}).get('perception', {}).get(o.team, {}).get('contacts', [])),
                parent_support_order=copy.deepcopy({k:v for k,v in row.items() if k != 'local_menu'}),
                commander_plan=copy.deepcopy(o.plan), native_menu=copy.deepcopy(menu),
                scope='只选择给定选项，不自行输出坐标；保留小队指定攻击目标与支援任务。')
            questions = dict(action=dict(type='choice', instructions=(
                '你是这辆坦克的局部驾驶/战斗决策者。小队决定支援任务与攻击目标。'
                '从引擎验证的附近选项选择继续、短停交火、倒车拉开、附近换位或报告受阻。'
                '低血量不代表必须撤退，移动不代表停火；比较实际射界、路线和风险。'
                '不要为展示功能而换位；当前可有效射击时可继续。倒车仍可瞄准还击。'
                '候选只代表采样时可执行，开火与移动均由引擎再次验证。'),
                criteria={key:json.dumps(value, ensure_ascii=False) for key,value in options.items()}))
            o._record('vehicle-personal-request', unit_id=uid, action_id=request['id'],
                      context=context, questions=questions)
            def ask(future=future, context=context, questions=questions):
                try:
                    response = (dict(answers={'action':dict(choice='continue_task')})
                                if o.model == 'mock' else o.game.ask(context, questions))
                    future.set_result(response)
                except Exception as error:
                    future.set_exception(error)
            threading.Thread(target=ask, name='vehicle-personal-'+uid, daemon=True).start()

    def snapshot(self):
        return dict(calls=self.calls, accepted=self.accepted, discarded=self.discarded,
                    pending=list(self.pending), next_wall=copy.deepcopy(self.next_wall))
