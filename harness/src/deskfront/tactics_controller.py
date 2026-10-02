"""LM-controller adapter for the Deskfront tactical coordination layer.

The controller module owns provider calls, scheduling and execution handoff.
The stateful commander/option builder lives in :mod:`tactics_coordination`.
"""
import copy
import math
import time

from lm_controller import LMController, ProviderError
from observations import observation
from jev_client import checked_choice
from tactics_policy import EXECUTOR_INTERVAL, DecisionSchedule
from tactics_coordination import Coordination

class CoordinatedClient:
    def __init__(self, game, coordinator):self.game, self.coordinator = game, coordinator
    def build_payload(self, obs):return self.coordinator.payload(obs)
    def __call__(self, obs, trace=None):
        payload = self.build_payload(obs)
        try:
            if self.coordinator.model == 'mock':
                options = self.coordinator.options(obs); selected = max(options, key=lambda k:options[k]['score'])
                if self.coordinator.validation:
                    uid=obs['self']['id']; combat=obs['self'].get('combat',{})
                    # Diagnostic policy only: one left flanker, two firing supports.
                    if combat.get('engageable_targets'):selected=next((k for k in options if k.startswith('attack_')), 'continue_task')
                    elif combat.get('path_active'):selected='continue_task'
                    elif 'task_waypoint' in options:selected='task_waypoint'
                    elif uid.endswith('-2') and 'route_left' in options:selected='route_left'
                    else:selected=next((k for k in options if k.startswith('firing_')), 'route_center' if 'route_center' in options else 'halt')
                decision = copy.deepcopy(options[selected]['command'])
                decision['reason'] = ('固定战术能力验证（非模型）：' if self.coordinator.validation else '本地规则演练（非模型）：') + selected
                return decision, {}
            data = self.game.ask(payload['state'], payload['questions'])
            selected = checked_choice(data['answers']['tactic'], payload['state']['command_candidates'])
            decision = copy.deepcopy(payload['state']['command_candidates'][selected]); decision['reason'] = 'JEV 战术选择：' + selected
            if trace:trace(provider_response=data, quickplay_request_id=data['requestId'], resolved_model=data.get('resolvedModel'))
            usage = data.get('usage') or {}
            return decision, {'total_tokens': usage.get('totalTokens', 0)}
        except Exception as error:
            if str(error) == 'request-budget':
                with self.coordinator.lock:
                    self.coordinator.budget_exhausted = True
                    self.coordinator.error = '本局模型调用额度已用完，请启动新局'
            raise ProviderError('quickplay_tactic_failed') from error


class CoordinatedController(LMController):
    def __init__(self, state, config, game, team):
        self.coordination = Coordination(game, team, config['model'])
        self.coordination.spatial_path = config.get('spatial_path')
        self.coordination.validation = config.get('validation', False)
        if config.get('tactical_map'):
            from tactical_level import ROUTES
            self.coordination.authored_routes = copy.deepcopy(ROUTES)
            self.coordination.routes = copy.deepcopy(ROUTES)
        config = dict(config, interval=EXECUTOR_INTERVAL)
        super().__init__(state, config, client=CoordinatedClient(game, self.coordination))
        self.request_starts = {}
        self.execution_records = {}
        from team_executor import IndependentExecutor
        self.team_executor = IndependentExecutor(self)
        self.origin = 'local_rules' if config['model'] == 'mock' else 'quickplay_jev'
    def tick(self):
        with self.state.lock:s=copy.deepcopy(self.state.state);acks=copy.deepcopy(self.state.results);age=time.monotonic()-self.state.updated
        if s and age < 3:self.coordination.update(s, acks)
        if not self.coordination.scenario['active']:return
        if self.config['model']!='mock':
            try:self.team_executor.tick(s,acks,age)
            except Exception as error:
                import traceback
                self.coordination.game.record(dict(type='executor-controller-error',error_type=type(error).__name__,traceback=traceback.format_exc()))
                raise
            return
        if s and self.run_id != s.get('run_id'):self.request_starts.clear()
        self.next_due = DecisionSchedule(self.next_due, self.request_starts)
        super().tick()
        self.next_due = DecisionSchedule(self.next_due, self.request_starts)
        # The upstream controller shortens flag emergencies to 1s. Restore this
        # adapter's explicit 2s minimum without modifying the game controller.
        for uid, task in self.pending.items():
            self.request_starts[uid] = task['started']
            self.next_due[uid] = max(self.next_due.get(uid, 0), task['started'] + EXECUTOR_INTERVAL)
    def snapshot(self):
        return dict(super().snapshot(), provider='quickplay', request_scope='unit',in_flight=self.team_executor.in_flight if self.config['model']!='mock' else len(self.pending), display_name='固定战术能力验证（非模型）' if self.coordination.validation else '本地协调演练' if self.config['model'] == 'mock' else 'DeepSeek 指挥 + JEV 逐兵独立执行', squad=self.coordination.snapshot())
    def _submit(self, s, u, decision, origin, now, seen_tick=None, selection=None):
        original=copy.deepcopy(decision)
        validation=None
        options = self.coordination.options(observation(s, u, []))
        preferred=options.get((selection or {}).get('key'))
        chosen = preferred if preferred and all(decision.get(k)==value for k,value in preferred['command'].items()) else next((v for v in options.values() if all(decision.get(k) == value for k,value in v['command'].items())), None)
        semantic_valid=True
        task=self.coordination.plan.get('tasks',{}).get(u['id'],{})
        status=self.coordination.units.get(u['id'],{}).get('task_execution',{})
        if selection and selection.get('key') in ('stage_approach','contest_flag','task_waypoint','assigned_position') and status.get('phase') in ('preparing','waiting','blocked','reassess'):
            semantic_valid=False
        if task.get('region_path') and decision.get('action')=='move' and decision.get('intent')!='survive' and not (chosen and chosen.get('requires_native_validation')):
            from region_routing import local_move_allowed
            from strategic_regions import catalog,memberships
            regions=catalog(self.coordination.routes,self.coordination.world)
            nav=self.coordination.units.get(u['id'],{}).get('region_navigation',{})
            scope=nav.get('path_regions') or nav.get('anchor_regions') or memberships(u['position'],regions)
            if status.get('phase') in ('preparing','waiting','blocked','reassess'):scope=nav.get('anchor_regions') or memberships(u['position'],regions)
            metadata=chosen or {}
            semantic_valid=semantic_valid and local_move_allowed(u['position'],decision['position'],scope,regions,origin_bridge=metadata.get('navigation_anchor'))
        from action_continuity import keep_move
        precise=bool((chosen or {}).get('requires_precise_arrival') or ((selection or {}).get('candidate') or {}).get('requires_precise_arrival'))
        retained_move=semantic_valid and not precise and keep_move(u,decision,self.coordination.units.get(u['id'],{}))
        if retained_move:
            chosen=dict(command=dict(action='wait',intent='observe'),description='同一目的地仍在有效移动或已经到位，保留原生动作')
            decision=dict(chosen['command'],reason=chosen['description']);origin='harness_keep'
        if semantic_valid and decision.get('action')=='move' and self.coordination.spatial_path:
            from execution_validation import validate_move
            p=decision.get('position',[])
            with self.coordination.lock:
                conflict=any(owner!=u['id'] and math.dist(other,p)<.09 for owner,other in self.coordination.reservations.items()) if len(p)==2 else True
            validation=dict(valid=False,reason='ally_reservation_conflict') if conflict else validate_move(self.coordination.spatial_path,s,u,p)
            bridge_limit=(chosen or {}).get('bridge_max_path_length')
            if validation.get('valid') and bridge_limit is not None and validation.get('path_length',math.inf)>bridge_limit:
                validation=dict(validation,valid=False,reason='origin_bridge_requires_short_native_path')
            chosen=copy.deepcopy(chosen or (selection or {}).get('candidate') or dict(command={k:v for k,v in decision.items() if k!='reason'},description='原选定目的地通过实时原生可达校验')) if validation.get('valid') else None
        if not semantic_valid:chosen=None;validation=dict(valid=False,reason='task_or_region_corridor_changed')
        if chosen is None:
            reason=(validation or {}).get('reason','action_no_longer_available')
            chosen = options.get('continue_task',dict(command=dict(action='wait',intent='observe'),description='保留当前动作等待重选')); decision = dict(chosen['command'], reason='未下发：'+reason+'；需重新决策'); origin = 'harness_guard'
            self.coordination.units.setdefault(u['id'],{})['last_execution_rejection']=dict(time=s['time'],reason=reason,requested=original)
        elif ((decision['action'] == 'attack' and u.get('order_mode') == 'attack'
               and u.get('target_id', u.get('focus_id')) == decision.get('target_id'))
              or (decision['action'] == 'cover' and u.get('in_cover') and not self.coordination.units.get(u['id'], {}).get('interrupt')
                  and (u.get('combat', {}).get('engageable_targets') or u.get('reload_remaining', 0) > 0))):
            chosen = options.get('continue_task',dict(command=dict(action='wait',intent='observe'),description='保留当前动作等待重选'))
            decision = dict(chosen['command'], reason='模型选择与有效执行一致，保持动作不重复下发')
            origin = 'harness_keep'
        if decision.get('action')=='wait' and not self.coordination.move_compatible(u):
            chosen=dict(command=dict(action='hold',intent='observe'),description='旧路径已失效，停止旧推进并等待JEV重选')
            decision=dict(chosen['command'],reason=chosen['description']);origin='harness_cancel_stale_path'
        super()._submit(s, u, decision, origin, now, seen_tick)
        record=dict(requested=original,actual=copy.deepcopy(decision),validation=validation,origin=origin,command_id=self.units[u['id']].get('command_id'),status='not_submitted' if origin=='harness_guard' else 'retained' if origin=='harness_keep' or decision['action']=='wait' else 'submitted')
        self.execution_records[(u['id'],seen_tick if seen_tick is not None else s['tick'])]=record
        if len(self.execution_records)>512:self.execution_records.pop(next(iter(self.execution_records)))
        self.coordination.game.record(dict(type='execution-resolution',unit_id=u['id'],time=s['time'],**record))
        self.next_due[u['id']] = now + EXECUTOR_INTERVAL
        self.coordination.commit(s, u, decision, chosen, self.units[u['id']].get('command_id'))
    def close(self):
        super().close(); self.coordination.close()
