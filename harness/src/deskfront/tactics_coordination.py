"""Commander-side tactical coordination state and planning.

This module owns the stateful coordination layer: commander plans, route/task
context, execution reservations and tactical options.  It deliberately does
not own the LM controller lifecycle; see :mod:`tactics_controller`.
"""
import concurrent.futures
import copy
import itertools
import math
import threading
import time

from observations import observation
from jev_client import checked_choice
from scenario import describe
from tactics_policy import (
    STYLES, ROLES, EXECUTOR_INTERVAL, COMMANDER_INTERVAL,
    COMMANDER_EVENT_COOLDOWN, fit, support_ready, row_waiting,
)

class Coordination:
    def __init__(self, game, team, model):
        self.game, self.team, self.model = game, team, model
        self.lock = threading.RLock()
        self.commander_timings=[]
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='commander')
        self.future = None; self.token = None; self.plan = {}; self.version = 0
        self.next_plan = 0; self.events = []; self.orders = {}; self.units = {}; self.world = {}
        self.reservations = {}; self.error = ''; self.commander_calls = 0; self.handoffs = 0
        self.budget_exhausted = False
        self.failures = {}
        self.last_plan_started = -100.0
        self.routes = {}
        self.authored_routes = {}
        self.scenario = dict(kind="capture",active=True,goal="夺取目标",routes={},details={})
        self.spatial_path = None
        self.validation = False
        self.plan_validation_feedback = None
        self.topology_cache = None

    def spatial(self, obs):
        if not self.spatial_path:return {}
        from spatial_queries import read_queries
        # The per-unit LM observation omits the map revision. Use the current
        # full engine snapshot for freshness validation; otherwise every new
        # revision-tagged Godot report is incorrectly discarded for JEV.
        query_state=dict(obs)
        query_state.setdefault('navigation_revision',self.world.get('navigation_revision'))
        return read_queries(self.spatial_path, query_state, obs['self'])

    def mark_failed(self, uid, order, now):
        key = (uid, order['action'], tuple(round(v, 2) for v in order.get('position', [])), order.get('target_id'))
        self.failures[key] = {'until': now + 12, 'origin': order['start_position']}
        self.event(uid + ' 无效动作暂时排除 12 秒：' + order['action'])

    def blocked(self, uid, action, fields, now, position):
        key = (uid, action, tuple(round(v, 2) for v in fields.get('position', [])), fields.get('target_id'))
        failure = self.failures.get(key)
        return bool(failure and now < failure['until'] and math.dist(position, failure['origin']) < .12)

    def move_compatible(self,u):
        """An old advance must not survive a new route as a disguised wait."""
        task=self.plan.get('tasks',{}).get(u['id'],{})
        order=self.orders.get(u['id'],{})
        if (u.get('combat',{}).get('path_active') and order.get('movement') and
                order.get('task_revision')!=task.get('task_revision')):
            return False
        if (not task.get('region_path') or not u.get('combat',{}).get('path_active') or
                order.get('intent')=='survive' or order.get('action') not in ('move','capture','attack') or
                (order.get('local_autonomy') and order.get('task_revision')==task.get('task_revision'))):return True
        from strategic_regions import catalog,memberships
        regions=catalog(self.routes,self.world)
        row=self.units.get(u['id'],{});nav=row.get('region_navigation',{})
        scope=nav.get('path_regions') or nav.get('anchor_regions') or memberships(u['position'],regions)
        if row.get('task_execution',{}).get('phase') in ('preparing','waiting','blocked','reassess'):scope=nav.get('anchor_regions') or memberships(u['position'],regions)
        return any(key in scope for key in memberships(u.get('goal',u['position']),regions))

    def close(self):self.pool.shutdown(wait=False, cancel_futures=True)

    def event(self, text):
        row = {'time': self.world.get('time', 0), 'text': text}
        self.events.append(row); self.events = self.events[-30:]
        self.game.record(dict(type='squad-event', run_id=self.world.get('run_id'), **row))

    def snapshot(self):
        from request_timing import summary
        from strategic_regions import catalog,model_catalog
        with self.lock:
            return copy.deepcopy({'strategic_regions':model_catalog(catalog(self.routes,self.world)),'commander_timing':summary(self.commander_timings),'plan': self.plan, 'version': self.version, 'events': self.events,
                'units': self.units, 'commander_calls': self.commander_calls, 'handoffs': self.handoffs, 'route_choices': self.routes,
                'error': self.error, 'budget_exhausted': self.budget_exhausted, 'pending': self.future is not None,
                'source': 'local_rules' if self.model == 'mock' else 'deepseek_commander'})

    def install(self, style, mover, members, origin):
        if style=='generated':
            previous=self.plan.get('tasks',{});tasks=copy.deepcopy(mover['tasks'])
            for uid,task in tasks.items():
                old=previous.get(uid,{})
                stage_id=mover.get('stage',{}).get('id')
                task['stage_id']=stage_id
                identity=('command','route','region_id','region_path','region_hint','stage_id','target_id','partner','support_for',
                          'start_when','wait_region_id','wait_timeout_s','on_failure','assignment','replan_when')
                old_condition=old.get('complete_when',{})
                new_condition=task.get('complete_when',{})
                same=bool(old) and all(old.get(k)==task.get(k) for k in identity) and all(
                    old_condition.get(k)==new_condition.get(k) for k in ('type','value'))
                task['task_revision']=old.get('task_revision',self.version+1) if same else self.version+1
                task['approval_revision']=self.version+1
                task['waypoint']=old.get('waypoint',0) if same else 0
                if same and old.get('_region_progress'):
                    task['_region_progress']=copy.deepcopy(old['_region_progress'])
                if same and old.get('selected_destination'):
                    task['selected_destination']=copy.deepcopy(old['selected_destination'])
                    if old.get('selected_target_position'):
                        task['selected_target_position']=copy.deepcopy(old['selected_target_position'])
                    if new_condition.get('type')=='position_reached' and not new_condition.get('position'):
                        new_condition['position']=copy.deepcopy(old['selected_destination'])
                        new_condition['radius']=old_condition.get('radius',.15)
                if not same:
                    row=self.units.setdefault(uid,{})
                    for key in ('selected_destination','selected_fire_lane_evidence','local_failure','local_maneuver_report'):
                        row.pop(key,None)
                    self.reservations.pop(uid,None)
                task['phase']='执行任务'
            self.version+=1
            self.plan=dict(style='generated',roles={u['id']:'executor' for u in members},source=origin,reason=mover['intent'],objective=mover.get('objective'),stage=mover.get('stage'),tasks=tasks)
            self.event('DeepSeek 自主计划：'+mover['intent'])
            return
        if self.scenario['kind']=='capture' and len(members) == 1 and not style.startswith('solo_'):
            style = 'solo_contest'
        roles = {u['id']: self.plan.get('roles', {}).get(u['id'], 'executor') for u in members}
        self.version += 1
        previous=self.plan.get('tasks',{})
        assignments=mover if isinstance(mover,dict) else {}
        if origin=='local_rules' and self.routes and not assignments:
            keys=list(self.routes)
            assignments={u['id']:keys[i%len(keys)] for i,u in enumerate(members)}
        tasks={}
        for u in members:
            uid=u['id'];route=assignments.get(uid,previous.get(uid,{}).get('route','adaptive'))
            if route not in self.routes:continue
            tasks[uid]=copy.deepcopy(previous[uid]) if previous.get(uid,{}).get('route')==route else dict(route=route,waypoint=0,phase='执行任务')
        reason=STYLES[style] if self.scenario['kind']=='capture' else {'covered_advance':'分段建立射位，清除守军','flank_pressure':'保持正面火力，沿指定侧路绕击','regroup':'受压换位重整，保留可行路线'}.get(style,style)
        self.plan = {'style': style, 'roles': roles, 'source': origin, 'reason': reason,'tasks':tasks}
        self.event(('本地规则：' if origin == 'local_rules' else 'DeepSeek 指挥：') + self.plan['reason'])

    def request_plan(self, state, members, previous, recent):
        # Only the engine's currently controlled, living members can receive
        # new orders. Casualties in an older plan remain historical evidence.
        living_ids=[u['id'] for u in members]
        living_set=set(living_ids)
        previous=copy.deepcopy(previous)
        previous['tasks']={uid:task for uid,task in previous.get('tasks',{}).items() if uid in living_set}
        scenario=describe(state,self.authored_routes,self.team)
        styles = {k:v for k,v in STYLES.items() if k.startswith('solo_') == (len(members) == 1)}
        if scenario['kind']=='clear_exit':styles={'covered_advance':'分段推进清除守军','flank_pressure':'正面牵制并沿侧路绕击','regroup':'受压换位重整'}
        from context_views import commander_context
        with self.lock:feedback={uid:copy.deepcopy(row) for uid,row in self.units.items() if uid in living_set}
        context=commander_context(state,scenario,previous,recent,self.routes,feedback)
        context['living_controlled_unit_ids']=living_ids
        from task_tools import board
        from strategic_regions import catalog,model_catalog
        regions=catalog(self.routes,state)
        context["strategic_regions"]=model_catalog(regions)
        from strategic_regions import memberships,navigation_anchor
        raw_units={u['id']:u for u in state['units']}
        for unit in context['units']:
            anchor=navigation_anchor(raw_units[unit['id']]['position'],regions,state.get('strategic_topology'))
            unit['current_regions']=anchor['anchor_regions']
            if anchor['mode']=='nearby_native_sample':unit['navigation_anchor']=anchor
        context['objective_regions']=memberships(state['objective']['position'],regions)
        if state.get('strategic_topology'):
            context.pop('routes',None)
            context['navigation']='区域、路线和射位由JEV从实时工具候选中选择；你决定阶段目标、攻击对象、队友配合和风险边界。region_hint只能作为方向参考，不能证明射界或强制停在该区。旧式region_id+region_path若输出会形成硬约束，通常不要输出。未知风险不能当安全。'
        from stage_execution import status
        context["stage_status"]=status(previous.get("tasks",{}),feedback)
        context["cooperation_board"]=board(state,previous.get("tasks",{}),self.routes)
        stalled=[u['id'] for u in members if feedback.get(u['id'],{}).get('unproductive_seconds',0)>=8]
        context['stagnation']=dict(unproductive_units=stalled,
            team_stalled=bool(members) and len(stalled)==len(members),
            instruction='无收益等待满8秒必须重审战术目标和职责；局部换射位/选路由JEV执行。若局部工具没有可达候选，应改变目标或分工；不得虚报掩护。')
        if self.plan_validation_feedback:
            validation_feedback=copy.deepcopy(self.plan_validation_feedback)
            validation_feedback['tasks']={uid:task for uid,task in validation_feedback.get('tasks',{}).items() if uid in living_set}
            validation_feedback['required_unit_ids']=living_ids
            context['plan_validation_feedback']=validation_feedback
        for row in context.get('execution',{}).values():
            if 'task_execution' in row:row['task_execution'].pop('signature',None)
        from threat_context import summary
        context['threat_forecast']={}
        spatial_by_unit={}
        for u in members:
            spatial=self.spatial(dict(state,self=u))
            spatial_by_unit[u['id']]=spatial
            context['threat_forecast'][u['id']]=dict(summary(spatial,include_cover=False,include_remote=False))
            if state.get('strategic_topology'):continue
            context['threat_forecast'][u['id']]['route_entries']=spatial.get('route_entries',{})
            # Compare subsequent destinations, not just a safe entry point.
            comparisons={}
            for name,route in self.routes.items():
                risks=[p['risk'] for p in spatial.get('route_forecasts',[]) if p.get('position') in route['points'] and p.get('risk',{}).get('status')=='sampled']
                comparisons[name]=dict(queried_destinations=len(risks),worst_peak_attackers=max((r['peak_attackers'] for r in risks),default=None),worst_exposed_seconds=round(max((r['exposed_s'] for r in risks),default=0),1) if risks else None,note='从当前点到各后续节点的原生路径比较，不是整条指定路线的累计风险')
            context['threat_forecast'][u['id']]['route_comparison']=comparisons
        from region_opportunities import build as region_opportunities
        context['region_opportunities']=region_opportunities(state,members,regions,spatial_by_unit,tasks=previous.get('tasks',{}))
        from approach_corridors import build as approach_corridors
        context['approach_corridors']=approach_corridors(state,members,regions,context['region_opportunities'])
        from tactical_map_view import build as tactical_map_view
        context['tactical_map']=tactical_map_view(state)
        from plan_feasibility import build as plan_feasibility
        from objective_timing import build as objective_timing
        context['plan_feasibility']=plan_feasibility(
            state,previous,regions,context['region_opportunities'],feedback,members=members)
        context['objective_timing']=objective_timing(state,members,feedback,spatial_by_unit)
        if self.model!='mock':
            from commander_plan import INSTRUCTIONS,validate
            from task_modes import instructions,contract
            context["task_contract"]=contract(state)
            from context_views import rounded
            from commander_view import build as commander_view
            context=commander_view(rounded(context))
            context["task_contract"]=contract(state)
            from request_timing import measured_ask
            response=measured_ask(self.game,context,{'plan':dict(type='json',instructions=instructions(INSTRUCTIONS,state))},self.commander_timings)
            value=response['answers']['plan']['value']
            try:plan=validate(value,members,state,self.routes)
            except ValueError as error:
                self.plan_validation_feedback=dict(error=str(error),tasks={uid:{k:t.get(k) for k in ('region_id','region_path','wait_region_id','command','partner','start_when','complete_when')} for uid,t in value.get('tasks',{}).items() if isinstance(t,dict)})
                raise
            self.plan_validation_feedback=None
            self.game.record(dict(type='commander-result',requestId=response['requestId'],context=context,answers=response['answers'],usage=response.get('usage'),resolvedModel=response.get('resolvedModel')))
            return 'generated',plan
        questions = {
            'strategy': {'type': 'choice', 'instructions': '你是小队指挥官。根据真实战况选择下一阶段打法，不直接控制动画。保持有效计划，受阻或受压才调整。', 'criteria': styles},
        }
        deployments={}
        if scenario['routes']:
            # Choose a complete allocation so independent answers cannot overbook a route.
            lanes=list(scenario['routes'])
            for assignment in itertools.permutations(lanes,min(len(lanes),len(members))):
                mapping={u['id']:assignment[i] if i<len(assignment) else 'adaptive' for i,u in enumerate(members)}
                deployments['formation_'+str(len(deployments))]=mapping
                if len(deployments)>=12:break
            deployments['adaptive']={u['id']:'adaptive' for u in members}
            questions['deployment']={'type':'choice','instructions':'选择整队分工；路线任务保持到完成或明确重评。绕侧与正面射位分开分配，避免全部挤同一路。',
                'criteria':{k:'；'.join(uid+' → '+scenario['routes'].get(lane,{'name':'自由接敌／自保'})['name'] for uid,lane in assignment.items()) for k,assignment in deployments.items()}}
        response = self.game.ask(context, questions, role='commander')
        style = checked_choice(response['answers']['strategy'], questions['strategy']['criteria'])
        self.game.record({'type': 'commander-result', 'requestId': response['requestId'], 'context': context,
                          'answers': response['answers'], 'usage': response.get('usage'), 'resolvedModel': response.get('resolvedModel')})
        return style, deployments[checked_choice(response['answers']['deployment'],questions['deployment']['criteria'])] if deployments else None

    def update(self, s, acks):
        with self.lock:
            s=copy.deepcopy(s)
            if self.spatial_path:
                try:
                    import json
                    from pathlib import Path
                    topo=json.loads(Path(str(self.spatial_path)+'.topology.json').read_text(encoding='utf-8'))
                    if topo['run_id']==s['run_id'] and topo['revision']==s.get('navigation_revision'):
                        self.topology_cache=topo
                except (OSError,ValueError,KeyError):pass
                cached=self.topology_cache
                if cached and cached.get('run_id')==s['run_id']:s['strategic_topology']=cached
                s['navigation_pending']=not cached or cached.get('run_id')!=s['run_id'] or cached.get('revision')!=s.get('navigation_revision')
            self.scenario=describe(s,self.authored_routes,self.team)
            self.routes=self.scenario['routes']
            if self.scenario['kind']=='clear_exit':s['objective']['flag']={}
            self.world = copy.deepcopy(s)
            if s.get('winner'):return
            members = [u for u in s.get('units', []) if u['faction'] == self.team and u['hp'] > 0 and u['kind'] == 'infantry' and u.get('combat_ready', True)]
            from task_modes import mode_id
            token = (s.get('run_id'), s.get('control_epochs', {}).get(self.team), tuple(sorted(u['id'] for u in members)),mode_id(s))
            if token != self.token:
                same_run=self.token is not None and token[:2]==self.token[:2] and token[3:]==self.token[3:]
                self.token=token;self.version+=1;self.next_plan=0
                if same_run:
                    living={u['id'] for u in members}
                    for collection in (self.orders,self.reservations,self.units,self.plan.get('tasks',{}),self.plan.get('roles',{})):
                        for uid in list(collection):
                            if uid not in living:collection.pop(uid,None)
                    for task in self.plan.get('tasks',{}).values():
                        if task.get('partner') and task['partner'] not in living:
                            task['partner']='';task['partner_lost']=True
                    self.event('成员变化：保留存活成员任务，后台重规划')
                    if self.model=='mock' and len(members)==1:self.plan['style']='solo_contest'
                else:
                    self.plan={};self.orders={};self.reservations={};self.units={};self.failures={}
            if not self.scenario['active'] or not members or s.get('paused') or s.get('winner') or s.get('control', {}).get(self.team) != 'lm':return
            if self.future and self.future.done():
                future, old_token = self.future, self.future_token; self.future = None
                try:
                    style, mover = future.result()
                    if old_token == token and getattr(self,'future_navigation_revision',s.get('navigation_revision'))==s.get('navigation_revision'):
                        self.install(style, mover, members, 'deepseek_commander'); self.error = ''; self.next_plan = time.monotonic() + COMMANDER_INTERVAL
                    else:self.event('旧指挥计划已丢弃：局次、控制权、成员或导航发生变化')
                except Exception as error:
                    self.game.record(dict(type='commander-plan-rejected',error_type=type(error).__name__,reason=str(error)[:160] if isinstance(error,(ValueError,KeyError,TypeError)) else 'provider_or_request_failed'))
                    if str(error) == 'request-budget':
                        self.budget_exhausted = True; self.error = '本局模型调用额度已用完，请启动新局'
                    elif isinstance(error,(ValueError,KeyError,TypeError)):self.error = '指挥计划校验失败：'+str(error)[:160]
                    else:self.error = '指挥模型调用失败，保留有效任务与本地保护'
                    self.next_plan = time.monotonic() + 10
            if self.model == 'mock' and not self.plan:
                mover = min(members, key=lambda u:(u.get('weapon') != 'smg', u['id']))['id']
                self.install('covered_advance', mover, members, 'local_rules')
            elif self.model != 'mock' and not s.get('navigation_pending') and not self.future and time.monotonic() >= max(self.next_plan, self.last_plan_started + COMMANDER_EVENT_COOLDOWN) and (self.plan or not self.spatial_path or all(self.spatial(dict(s,self=u)) for u in members)):
                self.future_token = token; self.commander_calls += 1; self.last_plan_started = time.monotonic()
                self.future_navigation_revision=s.get('navigation_revision')
                self.future = self.pool.submit(self.request_plan, copy.deepcopy(s), copy.deepcopy(members), copy.deepcopy(self.plan), copy.deepcopy(self.events[-6:]))
            for u in members:
                uid = u['id']; row = self.units.setdefault(uid, {}); order = self.orders.get(uid)
                task=self.plan.get('tasks',{}).get(uid)
                if task:
                    # Areas are live geometry, not copies from an earlier map revision.
                    from strategic_regions import catalog
                    regions=catalog(self.routes,s)
                    if task.get('region_id') in regions:task['destination_area']=regions[task['region_id']]
                    if task.get('wait_region_id') in regions:task['wait_area']=regions[task['wait_region_id']]
                    if task.get('region_path'):
                        from region_routing import next_region_step
                        step=next_region_step(u['position'],task,s.get('strategic_topology',{}),regions,[p for owner,p in self.reservations.items() if owner!=uid])
                        task['region_cursor']=step.get('index',0)
                        row['region_navigation']={k:v for k,v in step.items() if k not in ('path_cells','safety')}
                        if step['status']=='blocked':
                            row['stage_blocker']=step['reason'];self.next_plan=min(self.next_plan,time.monotonic())
                        else:row.pop('stage_blocker',None)
                    else:
                        row.pop('region_navigation',None)
                        row.pop('stage_blocker',None)
                    from task_tools import board
                    fact=board(s,{uid:task},self.routes)[uid]
                    old_fact=row.get('dynamic_task',{})
                    row['dynamic_task']=fact
                    changed=old_fact and (old_fact.get('target_status')!=fact['target_status'] or old_fact.get('navigation_revision')!=fact['navigation_revision'])
                    if changed:
                        self.next_plan=min(self.next_plan,time.monotonic())
                        row['last_task_change']=dict(time=s['time'],target_status=fact['target_status'],reason='target_or_navigation_changed')
                    if fact['target_status'] in ('dead','missing'):
                        if task.get('complete_when',{}).get('type')=='target_dead':
                            task['phase']='目标已失效，等待重新分工'
                            self.next_plan=min(self.next_plan,time.monotonic())
                if task and task.get('command'):
                    from commander_plan import progress
                    target=task.get('target_id')
                    target_invalid=bool(target) and not any(v['id']==target and v['hp']>0 and v['faction']!=self.team for v in s['units'])
                    completed=progress(task,u,s)['achieved'] and task.get('command') not in ('support','hold','occupy')
                    if target_invalid or completed:
                        reason='target_no_longer_alive' if target_invalid else 'task_completed'
                        if task.get('phase')!='任务已完成，等待下一阶段':self.event(uid+' 当前任务结束，保持区域内行动：'+reason)
                        task['phase']='任务已完成，等待下一阶段'
                        row['completed_task']=dict(reason=reason,time=s['time'],target_id=target)
                        self.next_plan=min(self.next_plan,time.monotonic())
                        if target_invalid:
                            row['retired_task']=dict(reason=reason,time=s['time'],target_id=target)
                            self.plan['tasks'].pop(uid,None)
                            self.reservations.pop(uid,None)
                            row.pop('selected_destination',None)
                            task=None

                if task and task['route'] in self.routes:
                    points=self.routes[task['route']]['points']
                    if task['waypoint']<len(points) and math.dist(u['position'],points[task['waypoint']])<.12:
                        task['waypoint']+=1
                        self.event(uid+' 完成路线节点 '+str(task['waypoint']))
                    task['phase']='任务到位' if task['waypoint']>=len(points) else '执行任务'
                    row['persistent_task']=copy.deepcopy(task)
                if task and task.get('command'):
                    from task_execution import evaluate
                    old_status=row.get('task_execution',{})
                    status=evaluate(task,u,s,self.plan.get('tasks',{}),old_status,support_ready)
                    row['task_execution']=status
                    if status['phase'] in ('blocked','reassess') and old_status.get('phase')!=status['phase']:
                        self.event(uid+' 协作受阻：'+status['reason'])
                        self.next_plan=min(self.next_plan,time.monotonic())
                if task and task.get('complete_when'):
                    from commander_plan import progress
                    status=progress(task,u,s)
                    if task.get('command')=='support' and task.get('complete_when',{}).get('type')=='position_reached':
                        from task_tools import board
                        evidence=board(s,{uid:task},self.routes)[uid]
                        status['position_achieved']=status['achieved']
                        status['achieved']=status['achieved'] and evidence['support_ready']
                        status['fire_evidence']=evidence

                    if status['achieved'] and not row.get('task_progress',{}).get('achieved'):self.next_plan=min(self.next_plan,time.monotonic())
                    row['task_progress']=status
                samples=row.setdefault('health_samples', [])
                if not samples or samples[-1][0]!=s['time']:samples.append([s['time'],u['hp']])
                samples[:]=[sample for sample in samples if s['time']-sample[0]<=4]
                row['recent_damage']=round(sum(max(0,a[1]-b[1]) for a,b in zip(samples,samples[1:])),1)
                threats=u.get('combat',{}).get('incoming_threats',[])
                row['early_retreat_warning']=bool(u.get('suppression',0)>=.35 or row['recent_damage']>=15 or (u['hp']/u.get('max_hp',100)<.65 and threats))
                row['active_task']=dict(action=order['action'],intent=order.get('intent'),destination=order.get('destination',order.get('position')),phase=order['phase']) if order else None
                if 'progress_position' not in row or math.dist(row['progress_position'], u['position']) > .025:
                    row['progress_position'] = list(u['position']); row['last_progress_time'] = s['time']
                row['no_movement_seconds'] = round(max(0, s['time'] - row['last_progress_time']), 1)
                row['no_shot_seconds'] = round(max(0, s['time'] - u.get('last_shot_at', -10)), 1)
                on_objective=math.dist(u['position'],s['objective']['position'])<=s['objective'].get('radius',.17)
                targets=[v for v in s['units'] if v['hp']>0 and v['faction']!=self.team]
                distance=min((math.dist(u['position'],v['position']) for v in targets),default=0)
                target_key=tuple(sorted(v['id'] for v in targets))
                if row.get('progress_targets')!=target_key:
                    row['progress_targets']=target_key;row['approach_origin']=list(u['position'])
                origin=row.setdefault('approach_origin',list(u['position']))
                # Compare both soldier positions against the SAME enemy snapshot.
                # Enemy movement alone must not reset the inactivity clock.
                before=min((math.dist(origin,v['position']) for v in targets),default=0)
                closing=math.dist(origin,u['position'])>=.04 and before-distance>.08
                if closing:row['approach_origin']=list(u['position'])
                productive=(on_objective and self.scenario['kind']=='capture') or u.get('combat',{}).get('regeneration',{}).get('active') or row['no_shot_seconds']<3 or closing
                if productive:row['last_productive_time']=s['time']
                row.setdefault('last_productive_time',s['time'])
                row['unproductive_seconds']=round(s['time']-row['last_productive_time'],1)
                if task and task.get('command') in ('support','eliminate'):
                    if 'fire_task_since' not in row:row['fire_task_since']=s['time']
                    row['fire_task_stall_seconds']=round(max(0,s['time']-max(row['fire_task_since'],u.get('last_shot_at',-10))),1)
                else:
                    row.pop('fire_task_since',None);row.pop('fire_task_stall_seconds',None)
                visits=row.setdefault('recent_positions',[])
                if not visits or s['time']-visits[-1]['time']>=2:visits.append(dict(time=s['time'],position=list(u['position'])))
                visits[:]=[v for v in visits if s['time']-v['time']<20]
                row['path_stalled'] = bool(u.get('combat', {}).get('path_active') and row['no_movement_seconds'] >= 6)
                if task and task.get('command'):
                    from local_failure import assess
                    prior=row.get('local_failure')
                    local=assess(task,u,s,row,prior)
                    row['local_failure']=local
                    if local['action']!='continue' and (not prior or prior.get('reason')!=local['reason']):
                        self.event(uid+' 局部诊断提示：'+local['reason'])
                else:row.pop('local_failure',None)
                if row['unproductive_seconds']>=12 and (not task or task.get('command') not in ('support','eliminate','flank')):
                    self.next_plan=min(self.next_plan,time.monotonic())
                row.update(role=self.plan.get('roles', {}).get(uid, 'executor'), technique={'peek': '探头交火', 'hide': '缩回隐蔽', 'crouch': '低姿交火'}.get(u.get('cqb_stance'), u.get('locomotion', '观察')),
                           support_ready=support_ready(u, s['time']), actual_position=u['position'])
                if not order:continue
                ack = acks.get(order.get('command_id'))
                if order['phase'] == 'submitted':
                    if not ack:continue
                    if not ack.get('accepted'):
                        order['phase'] = 'rejected'; row['phase'] = '引擎拒绝'; self.reservations.pop(uid, None)
                        self.event(uid + ' 指令未执行：' + ack.get('message', 'rejected')); continue
                    order['phase'] = 'executing'; row['phase'] = '执行中'
                    self.game.record({'type': 'squad-receipt', 'unit_id': uid, 'command_id': order['command_id'], 'receipt': ack, 'plan_version': order['version']})
                if order['phase'] != 'executing':continue
                if order['action'] == 'attack':
                    combat = u.get('combat', {})
                    if (not combat.get('engageable_targets') and not combat.get('path_active')
                            and row['no_movement_seconds'] >= 4 and row['no_shot_seconds'] >= 4):
                        order['phase'] = 'blocked'; row['phase'] = '攻击未推进，重新选路'
                        row['interrupt'] = '攻击没有射界也没有路径，改选移动路点或其他目标'
                        self.mark_failed(uid, order, s['time'])
                        self.next_plan = min(self.next_plan, time.monotonic() + 2)
                    continue
                if not order['movement']:continue
                combat = u.get('combat', {})
                destination = order.get('position', u.get('goal', u['position']))
                if not combat.get('path_active'):
                    success = math.dist(u['position'], destination) < .055 and (order['action'] != 'cover' or u.get('in_cover'))
                    order['phase'] = 'arrived' if success else 'blocked'; row['phase'] = '已到位' if success else '推进受阻'
                    self.reservations.pop(uid, None)
                    moved = math.dist(u['position'], order['start_position']) > .04
                    if not success:
                        self.event(uid + ' 路线未完成，重新选择')
                        self.mark_failed(uid, order, s['time'])
                    elif moved:self.event(uid + (' 到位，等待实际火力接替' if self.plan.get('roles', {}).get(uid) == 'maneuver' else ' 已到达支援射位'))
                    if success and moved and self.plan.get('roles', {}).get(uid) == 'maneuver':row['await_handoff'] = True
                    if not success:self.next_plan = min(self.next_plan, time.monotonic() + 2)
                elif s['time'] - order['time'] > 12:
                    row['interrupt'] = '持续未到位，停靠后重新选位'; self.next_plan = min(self.next_plan, time.monotonic() + 2)
                elif order.get('requires_support') and not any(support_ready(v, s['time']) for v in members if v['id'] != uid):
                    row['interrupt'] = '掩护中断，就近寻找保护'

    def options(self, obs):
        with self.lock:
            u = obs['self']; uid = u['id']; result = {}
            task=self.plan.get('tasks',{}).get(uid)
            role = self.plan.get('roles', {}).get(uid, 'executor'); combat = u.get('combat', {})
            allies = obs['allies']; support = [v['id'] for v in allies if support_ready(v, obs['time'])]
            solo = not any(v['hp'] > 0 and v.get('combat_ready', True) for v in allies)
            owner = obs['objective'].get('flag', {}).get('owner')
            urgent = bool(owner and owner != self.team and obs['objective'].get('flag', {}).get('remaining_seconds', 30) <= 10)
            allowed = u.get('available_actions', [])
            spatial = self.spatial(obs)
            region_choices=dict(query_status='unknown_no_topology',options=[])
            if self.world.get('strategic_topology'):
                from strategic_regions import catalog
                from region_opportunities import build as region_opportunities
                from region_destinations import build as region_destinations
                regions=catalog(self.routes,self.world)
                opportunities=region_opportunities(self.world,[u],regions,{uid:spatial},tasks=self.plan.get('tasks',{}))
                query_state=dict(self.world,position_reservations={owner:dict(unit_id=owner,position=position)
                    for owner,position in self.reservations.items() if owner!=uid})
                region_choices=region_destinations(u,query_state,regions,opportunities,spatial,task,allies)
            self.units.setdefault(uid,{})['region_choices']=region_choices
            from cover_evidence import cover_phase
            cover_state=cover_phase(u)
            occupied_cover=cover_state!='none'
            fire_check = combat.get('fire_check', {})
            fire_blocked = fire_check.get('status') == 'blocked' and 0 <= obs['time']-fire_check.get('time', -10) <= 3
            block_row=self.units.setdefault(uid,{})
            block_key=(fire_check.get('reason'),fire_check.get('target_id'),fire_check.get('blocker'))
            if not fire_blocked:block_row.pop('fire_obstruction',None)
            elif block_row.get('fire_obstruction',{}).get('key')!=block_key:
                block_row['fire_obstruction']=dict(key=block_key,since=obs['time'])
            ally_grace=fire_blocked and fire_check.get('reason')=='ally_blocks_muzzle' and obs['time']-block_row['fire_obstruction']['since']<1.5
            def add(key, action, intent, description, score, **fields):
                if action != 'wait' and action not in allowed:return
                if self.blocked(uid, action, fields, obs['time'], u['position']):return
                result[key] = {'command': dict(action=action, intent=intent, **fields), 'description': description, 'score': score}
            add('continue_task', 'wait', 'observe', '继续当前有效动作；探头、射击、缩回、装填由游戏执行', 10)
            if cover_state in ('hiding','peeking','moving_with_reserved_cover'):
                result['continue_task']['description']='已占用掩体，当前'+cover_state+'；暂时无射线或在探头点移动不等于罚站；结合最近实际开火、失效诊断决定保持还是换位'
            elif not combat.get('path_active') and not combat.get('engageable_targets') and u.get('reload_remaining', 0) <= 0:
                result['continue_task']['description'] = '原地等待，不产生推进或火力；仅在没有安全可行行动时选择'
            if not fit(u) or self.units.get(uid, {}).get('interrupt'):
                add('protect', 'cover', 'survive', '受伤或执行受阻，可就近寻找保护；不是唯一选择', 70)
            if combat.get('path_active') and not occupied_cover:
                result['continue_task']['description'] = '维持现有路径；检查 execution_feedback，路径存在不代表仍有进展'
                if self.orders.get(uid,{}).get('intent')=='survive' and self.units.get(uid,{}).get('no_movement_seconds',0)<2:
                    result['continue_task']['description']='正在执行撤离且仍有位移；通常继续到遮挡位置，避免每次决策换目的地。若路径受阻或伤害明显加速，可重新选择更近遮挡点'
            elif fire_blocked:
                result['continue_task']['description'] = '当前开火已被执行层拦截：' + fire_check.get('reason','') + ('；队友暂时挡住枪口，可短等让路，最多1.5秒；仍受阻就换射位' if ally_grace else '；必须换射位或换可射目标，重复到当前点不能恢复射界')
            add('halt', 'hold', 'observe', '停止当前移动，在当前位置观察或自动交火；无射界时不会推进', 15)
            idle=self.units.get(uid,{}).get('unproductive_seconds',0)
            if idle>=6:
                for key in ('halt','continue_task'):
                    result[key]['description']+='；已连续'+str(idle)+'秒无移动/火力/回血/占点收益，重复等待不能完成任务，应考虑其他候选或改变任务'
            posture_order=next((v.get('posture_order','auto') for v in self.world.get('units',[]) if v['id']==uid),'auto')
            for posture,label in [('auto','恢复自动姿态'),('stand','站立以提高移动速度和射击高度'),('crouch','蹲姿兼顾遮挡和移动'),('prone','卧姿降低暴露但移动很慢')]:
                if posture!=posture_order:
                    add('posture_'+posture,'posture','survive',label+'；姿态持续到再次修改，强压制可能触发紧急保护',25,posture=posture)
            inside = math.dist(u['position'], obs['objective']['position']) <= obs['objective']['radius']
            defenders = [v for v in allies if math.dist(v['position'], obs['objective']['position']) <= obs['objective']['radius'] and fit(v)]
            if inside:add('hold_flag', 'hold', 'capture', '圈内守住并自动交火；无需全队聚集', 95)
            if not occupied_cover:
                add('seek_cover', 'cover', 'support', '在当前位置附近找保护，不保证获得射界或向旗点推进', 55)
            for target in combat.get('engageable_targets', []):
                if fire_blocked and target == fire_check.get('target_id'):continue
                if u.get('weapon') == 'rocket' and target in spatial.get('blocked_shots', []):continue
                enemy = next((v for v in obs['enemies'] if v['id'] == target), None)
                if not enemy:continue
                score = 105 if u.get('weapon') == 'rocket' and enemy['kind'] == 'tank' else 75 if role != 'maneuver' else 52
                cover_warning=('；注意：当前已占掩体，游戏的显式 attack 可能在缩回无射线时追敌并释放掩体；维持原掩体循环可选继续当前动作' if occupied_cover else '')
                add('attack_' + target, 'attack', 'support' if role == 'support' else 'engage', '对 ' + target + ' 交火'+cover_warning, score, target_id=target)
                if enemy.get('in_cover') and math.dist(u['position'], enemy['position']) <= .65 and u.get('in_cover'):
                    add('grenade_' + target, 'grenade', 'engage', '投雷打击固守目标；引擎检查库存与释放条件', 79, target_id=target)
            # No pretend paths: only the existing engine's cached, low-exposure short steps.
            hint = combat.get('flag_hint', {})
            style = self.plan.get('style', 'covered_advance')
            # Recovery is slow; healthy members need not wait for full healing.
            regrouping = not urgent and style == 'regroup' and any(v.get('suppression', 0) >= .65 for v in [u] + allies)
            if regrouping and u.get('in_cover'):
                add('regroup_hold', 'hold', 'support', '重整阶段：守住现有射位，等待受压队友恢复', 85)
            if style == 'hold_perimeter' and defenders and u.get('in_cover'):
                add('perimeter_hold', 'hold', 'support', '已有队友占点：守住外围掩体与接近路线', 85)
            if not inside and not hint.get('pending', True):
                for i, p in enumerate(hint.get('advance_options', [])):
                    pos = p['position']; exposure = p.get('exposure', 1)
                    if any(owner != uid and math.dist(other, pos) < .09 for owner, other in self.reservations.items()):continue
                    if any(math.dist(v['position'], pos) < .08 for v in allies):continue
                    add('advance_' + str(i), 'move', 'advance', f'引擎短路点 {pos}；暴露指标 {exposure:.2f}；实际掩护 {support}', 80 - i * 3, position=pos)
                    if 'advance_' + str(i) in result:
                        result['advance_' + str(i)]['requires_support'] = exposure > .12 and not (urgent or solo)
                if obs['enemies']:
                    add('flank', 'flank', 'flank', '调用原生局部绕侧查询；无可达侧位时游戏会转找掩体，不保证绕侧成功', 86)
            if not combat.get('engageable_targets') and not inside:
                for enemy in sorted((v for v in obs['enemies'] if v['hp'] > 0 and v.get('combat_ready', True)), key=lambda v: math.dist(v['position'], u['position']))[:2]:
                    if fire_blocked and enemy['id'] == fire_check.get('target_id'):continue
                    if enemy['kind'] == 'tank' and u.get('weapon') != 'rocket':continue
                    add('approach_' + enemy['id'], 'attack', 'engage', '接近 ' + enemy['id'] + ' 直到引擎判定可交战；可能离开掩体并暴露，不是原地射击', 65, target_id=enemy['id'])
            if not inside:
                add('contest_flag', 'capture', 'capture', '进圈争夺：由引擎寻路，可能暴露；结合倒计时与队友火力决定是否值得冒险', 110)
            for i, point in enumerate(spatial.get('firing_positions', [])):
                pos = point['position']
                if any(owner != uid and math.dist(other,pos)<.09 for owner,other in self.reservations.items()):continue
                add('firing_' + str(i), 'move', 'advance', f"原生寻路验证射位 {pos}；站姿射线可达目标 {point['targets']}；可能威胁 {point['threats']}；路径长 {point['distance']:.2f}。非命中或安全保证", 82, position=pos)
                key='firing_'+str(i)
                visited=any(math.dist(v['position'],pos)<.09 for v in self.units.get(uid,{}).get('recent_positions',[]) if obs['time']-v['time']>4)
                if key in result and visited:
                    result[key]['description']+='；警告：20秒内曾到过附近，需有敌情变化或实际射击收益才返回，避免往返'
                    result[key]['score']-=20
            # JEV selects a destination region. The native engine owns the
            # full path and movement; no region sequence or first step is a
            # model action. The endpoint is a sampled walkable topology point.
            for i, area in enumerate(region_choices.get('options',[])):
                pos=area['position']
                if math.dist(u['position'],pos)<=.055 or any(owner!=uid and math.dist(other,pos)<.09
                    for owner,other in self.reservations.items()):continue
                path=area.get('path_evidence',{})
                description=('选择下一战术区域 '+str(area['region_id'])+'；区域内候选落点 '+str(pos)+
                    '；来源 '+str(area.get('source'))+'；可射目标样本 '+str(area.get('targets',[]))+
                    '；射界 '+str(area.get('fire_evidence','unknown'))+'；到该精确点的原生路径证据 '+str(path)+
                    '。由游戏引擎寻路与移动；未知不代表安全或不可达，抵达后须复核实际火力')
                candidate_key='region_goal_'+str(i)
                add(candidate_key,'move','advance',description,72,position=list(pos))
                if candidate_key in result:
                    result[candidate_key].update(destination=list(pos),region_goal=area['region_id'],
                        requires_native_validation=True,
                        fire_lane_evidence=area.get('fire_evidence')=='sampled_standing_ray',
                        fire_lane_scope='remote_coarse_sample' if area.get('source')=='remote_firing' else 'unknown')
            for i, point in enumerate(spatial.get('withdrawal_positions', [])):
                pos=point['position']
                if any(owner != uid and math.dist(other,pos)<.09 for owner,other in self.reservations.items()):continue
                add('withdraw_' + str(i), 'move', 'survive', f"拉开距离至 {pos}；最近敌人距离 {point['nearest_enemy']:.2f}；落点可射目标 {point['targets']}；潜在威胁 {point['threats']}。移动时不能开火，沿途风险未保证", 83, position=pos)
            previous_move=self.orders.get(uid,{})
            destination=previous_move.get('destination')
            if destination and previous_move.get('task_revision')==(task or {}).get('task_revision') and previous_move.get('intent')=='advance' and obs['time']-previous_move.get('time',0)<8 and math.dist(u['position'],destination)>.08:
                add('resume_position','move','advance','继续自己上次选择的射位 '+str(destination)+'；保持短期目标避免反复改点，但威胁变化时可选择交火或撤离',81,position=destination)
            for i, point in enumerate(spatial.get('shelter_positions', [])):
                pos=point['position']
                if any(owner!=uid and math.dist(other,pos)<.09 for owner,other in self.reservations.items()):continue
                add('shelter_' + str(i), 'move', 'survive', f"短途脱离火线至 {pos}；路径长 {point['distance']:.2f}；端点威胁由 {spatial.get('current_threats',[])} 降为 {point['threats']}；沿途3点威胁合计 {point['route_threat_samples']}（抽样非安全保证）。允许暂时失去射界以脱战回血", 90, position=pos)
            if not self.plan.get('tasks',{}).get(uid):
                for lane,data in self.routes.items():
                    point=next((p for p in data['points'] if math.dist(p,u['position'])>.12),None)
                    if point is None or any(owner!=uid and math.dist(other,point)<.09 for owner,other in self.reservations.items()):continue
                    if any(math.dist(v['position'],point)<.08 for v in allies):continue
                    add('route_'+lane,'move','advance',data['name']+'；可选路线入口 '+str(point),65,position=point)
            if self.scenario['kind']=='clear_exit':
                for key in ('hold_flag','contest_flag','perimeter_hold'):result.pop(key,None)
                mission=self.scenario['details']
                if mission and not any(v['id'] in mission['defenders'] and v['hp']>0 for v in obs['enemies']):
                    add('secure_exit','move','advance','守军已清除，前往出口',120,position=mission['target'])
            from task_tools import route_step
            next_route=route_step(task,self.routes) if task else None
            region_step=None;region_scope=[];regions={}
            if task and task.get('region_path'):
                from strategic_regions import catalog,memberships
                from region_routing import next_region_step
                regions=catalog(self.routes,self.world)
                region_step=next_region_step(u['position'],task,self.world.get('strategic_topology',{}),regions,[p for owner,p in self.reservations.items() if owner!=uid])
                task['region_cursor']=region_step.get('index',0)
                region_scope=region_step.get('path_regions') or region_step.get('anchor_regions') or memberships(u['position'],regions)
                if self.units.get(uid,{}).get('task_execution',{}).get('phase') in ('preparing','waiting','blocked','reassess'):
                    region_scope=region_step.get('anchor_regions') or memberships(u['position'],regions)
                self.units.setdefault(uid,{})['region_navigation']={k:v for k,v in region_step.items() if k not in ('path_cells','safety')}
                if region_step['status']=='ready':
                    step_key='rejoin_region' if region_step['reason']=='origin_anchor_bridge' else 'stage_approach'
                    add(step_key,'move','advance','返回附近导航采样点，再恢复区域任务；尚未到位、需原生验证' if step_key=='rejoin_region' else '沿指挥指定区域序列进入 '+str(region_step['next_region'])+'；仅为下一短步，可先交火或撤离再继续；连通不等于安全',85,position=region_step['position'])
                    if step_key in result:
                        for key in ('requires_precise_arrival','bridge_max_path_length','navigation_anchor'):
                            if key in region_step:result[step_key][key]=region_step[key]
                elif region_step['status']=='blocked':
                    self.units.setdefault(uid,{})['stage_blocker']=region_step['reason']
                    self.next_plan=min(self.next_plan,time.monotonic())
                # Native chase/capture can silently run a different global route.
                for key in list(result):
                    if key=='flank' or key.startswith(('approach_','advance_')):result.pop(key)
                if region_step['status']!='arrived' or math.dist(u['position'],obs['objective']['position'])>.3 or task.get('command') not in ('occupy','hold'):
                    result.pop('contest_flag',None)
            if task and not task.get('region_path') and next_route is None and (task.get('region_id') or task.get('complete_when',{}).get('type')=='position_reached'):
                from strategic_regions import catalog,contains
                area=catalog(self.routes,self.world).get(task.get('region_id'))
                choices=[p for p in spatial.get('firing_positions',[]) if area and contains(p['position'],area)]
                if choices:
                    for i,p in enumerate(choices[:3]):
                        add('assigned_firing_'+str(i),'move','advance','任务区域内可选射位；目标 '+str(p.get('targets',[]))+'；威胁 '+str(p.get('threats',[])),90,position=p['position'])
                elif area and not contains(u['position'],area):
                    from stage_execution import approach
                    step=approach(u['position'],area,self.world.get('strategic_topology',{}))
                    if step:
                        add('stage_approach','move','advance','当前阶段短途接近点；原生通路连通，未保证火力安全，结合威胁选择或先自保',85,position=step)
                        self.units.setdefault(uid,{}).pop('stage_blocker',None)
                    else:
                        self.units.setdefault(uid,{})['stage_blocker']='no_connected_local_step'
                        self.next_plan=min(self.next_plan,time.monotonic())
                elif not area and not task.get('region_id') and task.get('complete_when',{}).get('position'):
                    add('assigned_position','move','advance',task['assignment'],90,position=task['complete_when']['position'])
            if fire_blocked and not ally_grace:
                for key in list(result):
                    cmd=result[key]['command']
                    if cmd.get('action')=='move' and math.dist(cmd['position'],u['position'])<.055:
                        result.pop(key)
                for key,candidate in result.items():
                    if key.startswith('firing_'):candidate['description']+='；用于解除当前枪口遮挡，到位后仍需验证实际开火'
            if task and next_route is not None and task.get('complete_when',{}).get('type')!='recovered':
                route=self.routes[task['route']];index=task['waypoint']
                if index<len(route['points']):
                    p=route['points'][index]
                    if not any(owner!=uid and math.dist(other,p)<.09 for owner,other in self.reservations.items()):
                        # A route is strategic guidance, never an exclusive movement whitelist.
                        add('task_waypoint','move','advance',route['name']+'，持续任务第 '+str(index+1)+' 步，前往 '+str(p)+'；这是方向任务，可先选择有效射位、遮断威胁或接替队友，再恢复推进',115,position=p)
            if task and self.plan.get('stage'):
                if task.get('command') not in ('occupy','hold'):
                    result.pop('contest_flag',None)
                    for key in list(result):
                        if key.startswith('advance_'):result.pop(key)
                from stage_execution import segment_candidates
                unavailable=segment_candidates(result,u['position'],self.world.get('strategic_topology',{}))
                self.units.setdefault(uid,{})['unreachable_candidates']=unavailable
                if unavailable:self.next_plan=min(self.next_plan,time.monotonic())
            if region_step:
                from region_routing import local_move_allowed
                for key,item in list(result.items()):
                    cmd=item['command']
                    if cmd.get('action')=='move' and cmd.get('intent')!='survive':
                        if not local_move_allowed(u['position'],cmd['position'],region_scope,regions,origin_bridge=item.get('navigation_anchor')) or not any(r in region_scope for r in memberships(item.get('destination',cmd['position']),regions)):
                            result.pop(key)
            if task and task.get('command') not in ('recover',):
                from local_maneuver import build_local_maneuvers
                from strategic_regions import catalog
                maneuver_task=dict(task)
                if not maneuver_task.get('region_id') and maneuver_task.get('region_hint'):
                    maneuver_task['region_id']=maneuver_task['region_hint']
                assigned_enemy=next((enemy for enemy in obs['enemies'] if enemy['id']==task.get('target_id') and enemy['hp']>0),None)
                selected_target=task.get('selected_target_position')
                target_changed=bool(assigned_enemy and selected_target and
                                    math.dist(assigned_enemy['position'],selected_target)>.18)
                local_options,local_report=build_local_maneuvers(
                    u,maneuver_task,spatial,catalog(self.routes,self.world),
                    self.world.get('strategic_topology',{}),
                    {owner:position for owner,position in self.reservations.items() if owner!=uid},
                    enemies=obs['enemies'],current_destination=None if target_changed or self.units.get(uid,{}).get('path_stalled') else task.get('selected_destination'),limit=4)
                row=self.units.setdefault(uid,{})
                row['local_maneuver_report']=local_report
                from local_failure import assess
                previous=row.get('local_failure')
                failure=assess(task,u,self.world,row,previous,
                                candidates=None if local_report.get('reason')=='spatial_query_unavailable' else local_options)
                row['local_failure']=failure
                for key,candidate in local_options.items():
                    if candidate['command']['action'] in allowed:
                        result[key]=candidate
            else:
                self.units.setdefault(uid,{}).pop('local_maneuver_report',None)
            from task_execution import constrain
            constrain(result,self.units.get(uid,{}).get('task_execution',{}))
            from threat_context import annotate
            annotate(result,spatial)
            if task and task.get('command'):
                for candidate in result.values():
                    if candidate['command'].get('target_id')==task.get('target_id') and task.get('target_id'):candidate['description']+='；指挥指定目标' 
            # Lack of progress is evidence for JEV, not an instruction to charge.
            if idle>=8 and fit(u) and not row_waiting(self.units.get(uid,{})) and u.get('reload_remaining',0)<=0 and not combat.get('regeneration',{}).get('active'):
                actionable=any(k.startswith('attack_') for k in result) or any(k.startswith('local_') and v.get('native_step_risk',{}).get('status')=='sampled' and not v['native_step_risk'].get('peak_attackers') for k,v in result.items()) or any('firing_'+str(i) in result and p.get('risk',{}).get('status')=='sampled' and p['risk'].get('peak_attackers')==0 and not p.get('threats') for i,p in enumerate(spatial.get('firing_positions',[])))
                if actionable:
                    for key in ('halt','continue_task'):
                        if key in result:result[key]['description']+='；提醒：已有可尝试的交火/换位候选，继续等待可能无收益，请结合风险自行权衡'
            if not self.move_compatible(u):
                result['continue_task']=dict(command=dict(action='hold',intent='observe'),description='旧移动终点已不属于当前批准区域或推进许可；先停靠并重新选择',score=10)
            from idle_guard import constrain_idle_routes
            constrain_idle_routes(result,task,u,self.units.get(uid,{}),cover_state)
            return result

    def payload(self, obs):
        """Build the provider-facing tactical payload (compatibility wrapper)."""
        from tactics_payload import build_payload
        return build_payload(self, obs)

    def commit(self, s, u, decision, current, command_id):
        with self.lock:
            uid = u['id']; row = self.units.setdefault(uid, {})
            row.update(selected=current['description'], phase='保持当前动作' if decision['action'] == 'wait' else '等待回执',
                       candidates=[{'id': k, 'description': v['description']} for k,v in self.options(observation(s, u, [])).items()])
            if decision['action'] == 'wait':return
            role = {'move':'maneuver','capture':'maneuver','flank':'maneuver','attack':'support','cover':'protect','retreat':'protect','hold':'hold'}.get(decision['action'], 'executor')
            self.plan.setdefault('roles', {})[uid] = role
            row['role'] = role
            row['role_source'] = 'jev_action' if self.model != 'mock' else 'local_rules'
            self.reservations.pop(uid, None); row.pop('interrupt', None)
            task=self.plan.get('tasks',{}).get(uid,{})
            if current.get('requires_native_validation') and current.get('destination'):
                task['selected_destination']=copy.deepcopy(current['destination'])
                target=next((v for v in s['units'] if v['id']==task.get('target_id') and v['hp']>0),None)
                if target:task['selected_target_position']=copy.deepcopy(target['position'])
                row['selected_destination']=copy.deepcopy(current['destination'])
                row['selected_fire_lane_evidence']=bool(current.get('fire_lane_evidence'))
                if (task.get('complete_when',{}).get('type')=='position_reached' and
                        (current.get('fire_lane_evidence') or task.get('command') in ('occupy','hold','flank'))):
                    task['complete_when']['position']=copy.deepcopy(current['destination'])
                    task['complete_when']['radius']=.15
            self.orders[uid] = dict(action=decision['action'], intent=decision.get('intent'), movement=decision['action'] in ('move', 'cover', 'flank', 'retreat', 'capture'), start_position=list(u['position']), phase='submitted', command_id=command_id,
                                    time=s['time'], version=self.version, requires_support=current.get('requires_support', False), target_id=decision.get('target_id'),
                                    destination=current.get('destination',decision.get('position')),risk=current.get('risk'),
                                    task_revision=task.get('task_revision'),local_autonomy=bool(current.get('requires_native_validation')),
                                    **({'position': decision['position']} if 'position' in decision else {}))
            if 'position' in decision:self.reservations[uid] = decision['position']


