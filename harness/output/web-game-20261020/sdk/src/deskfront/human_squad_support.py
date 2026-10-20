"""Support choices use the existing squad JEV request and native receipts."""
import copy
from actor_roster import roster


class SquadSupportMixin:
    def _support_options(self, contacts):
        rows = []
        alive = {u['id']: u for u in self.world.get('units', []) if u.get('hp', 0) > 0}
        crew = {r['equipment_id'] for r in roster(self.world, self.team) if r['mode'] == 'equipment_crew'}
        for unit in alive.values():
            if unit.get('faction') == self.team and unit.get('kind') == 'tank' and unit.get('deployment_phase', 'active') == 'active':
                rows.append(dict(id=unit['id'], kind='vehicle', unit_ids=[unit['id']], position=unit['position']))
        for gun in self.world.get('at_guns', []):
            if gun.get('id') in crew and gun.get('faction') == self.team and gun.get('kind') == 'mortar':
                rows.append(dict(id=gun['id'], kind='equipment', unit_ids=[uid for uid in gun.get('crew_ids', []) if uid in alive], position=gun['position']))
        for row in rows:
            row['choices'] = dict(support_area='支援当前阶段区域；授权引擎在已知敌情中自动瞄准', hold_fire='停止开火，保持位置')
            row['choices']['move_area' if row['kind'] == 'vehicle' else 'release_crew'] = ('前往阶段区域；移动途中仍可自卫' if row['kind'] == 'vehicle' else '撤离炮位；成员随后重新参与步兵任务')
            row['choices'].update({'engage:' + c['id']: '集中攻击已知目标 ' + c['id'] + '；失去接触或射界不成立时报告受阻' for c in contacts if c.get('visible')})
            if row['kind'] == 'vehicle':
                visible = {c['id'] for c in contacts if c.get('visible')}
                row['native_fire_options'] = copy.deepcopy([fact for fact in alive[row['id']].get('combat', {}).get('tank_fire_options', [])
                                                          if fact.get('target_id') in visible])
                row['fire_rule'] = ('direct=当前炮口可直射；breach=可先轰击挡住该敌人的可破坏障碍，'
                                    '炮弹先命中障碍，破坏前不穿墙伤人；blocked=本次原生检查不允许。'
                                    'support_area/engage均可执行合法破障；move_area移动途中也保留相同的合法自动射击，不改变移动目的地；'
                                    'hold_fire才停止开火。实际发射还会复验散射弹道、射程和友军安全。')
        return rows

    def _submit_support(self, response, request):
        for asset in request.get('support_options', []):
            choice = response.get('answers', {}).get('support_' + asset['id'], {}).get('choice')
            if choice not in asset['choices']:
                continue  # Missing answer keeps the accepted task, never invents a model choice.
            action, _, target = choice.partition(':')
            native = dict(asset_id=asset['id'], kind=asset['kind'], mode=action,
                          target_id=target, position=list(self.plan['position']))
            signature = (self.identity, self.version, choice, tuple(native['position']), tuple(asset['unit_ids']))
            previous = self.support_orders.get(asset['id'])
            observed = self.world.get('support_execution', {}).get(asset['id'], {})
            if previous and previous.get('signature') == signature and (previous.get('pending') or
                    previous.get('accepted') and observed.get('order_id') == previous['order_id']
                    and observed.get('state') not in ('cancelled', 'failed')):
                continue
            if any(p['command'].get('asset_id') == asset['id'] for p in self.pending_commands.values()):
                continue
            self.order_serial += 1
            command = dict(native, action='support_order', source='lm', faction=self.team,
                           unit_ids=asset['unit_ids'], order_id=f'{self.squad_id}:support:{self.version}:{self.order_serial}',
                           run_id=self.world['run_id'], seen_tick=int(self.world['tick']),
                           control_epoch=self.world.get('control_epochs', {}).get(self.team, 0))
            if getattr(self.game, 'session_id', None):command['instance_id'] = self.game.session_id
            code, receipt = self.state.submit(command, source='lm')
            self._record('human-support-submitted', request_serial=request['serial'], command=command,
                         raw_choice=choice, http_status=code, queue_result=receipt)
            if code != 202:raise ValueError('support_queue_rejected')
            order = dict(order_id=command['order_id'], signature=signature, pending=True, accepted=False,
                         region_id=self.plan['region_id'], choice=choice, command=copy.deepcopy(command))
            self.support_orders[asset['id']] = order
            self.pending_commands[receipt['id']] = dict(command=command, order=order,
                request_id=response.get('requestId'), submitted=self.clock())

    def _support_feedback(self):
        now = self.world.get('time', 0)
        for ident, row in self.world.get('support_execution', {}).items():
            if row.get('faction') != self.team or row.get('state') not in ('blocked', 'failed'):
                continue
            if row.get('state') == 'failed' or now - row.get('blocked_since', now) >= 3:
                key = (ident, row.get('order_id'), row.get('reason'))
                if key not in self.support_notified:
                    self.support_notified.add(key)
                    self._wake('participation_gap', dict(unit_id=ident,
                        reason='support_execution_failed' if row.get('state')=='failed' else 'persistent_native_firing_obstruction',
                        execution_reason=row.get('reason'), order_id=row.get('order_id')))
