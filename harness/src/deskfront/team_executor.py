"""One JEV request per squad round; each answer and receipt remains independent."""
import copy
import time
from lm_controller import validate_decision, ProviderError
from observations import observation
from jev_client import checked_choice
from threat_context import summary
from context_views import unit_view, terrain_view, objective_view, rounded, question_view, local_failure_view


def provider_failure_summary(error):
    message=str(error)
    if message.startswith('400 '):
        return 'JEV 服务商返回 HTTP 400：请求格式或模型路由不被接受；此局保留当前命令'
    if message.startswith('402 '):
        return 'JEV 服务商返回 HTTP 402：当前接入方式额度不足；此局无法收到新动作'
    if message.startswith('429 '):
        return 'JEV 服务商返回 HTTP 429：请求受限；此局暂时无法收到新动作'
    if 'timeout' in message.lower() or 'timed out' in message.lower():
        return 'JEV 请求超时：此局保留当前命令，不重复排队'
    if message in ('request-budget', 'session_stopped', 'request-aborted', 'request-cancelled'):
        return 'JEV 请求已结束：' + message
    return 'JEV 请求失败；查看本局 decision-error 记录确认服务商原因'


def build_round(coordinator, state, members, memory):
    local={};questions={};policies={}
    shared_keys=('stage_status','strategic_regions','tactical_map','cooperation_board','squad_task','team_execution','recent_execution_events','route_choices','recovery_rules','disengagement_guidance','mission','scenario')
    for u in members:
        observed=observation(state,u,memory.get(u['id'],[]))
        observed['navigation_revision']=state.get('navigation_revision')
        p=coordinator.payload(observed)
        context=p['state']
        if not policies:policies={k:context[k] for k in shared_keys if k in context}
        local[u['id']]={k:v for k,v in context.items() if k not in shared_keys and k not in ('allies','enemies','covers','bounds','objective','run_id','tick','time')}
        policies['execution_policy']=p['questions']['tactic']['instructions']
        questions[u['id']]=dict(p['questions']['tactic'], instructions='你就是 '+u['id']+'，阵营 '+u['faction']+'，武器 '+str(u.get('weapon','unknown'))+'。本题仅选择本兵动作，不控制其他编号。支援队友不等于跟随队友；依据本人任务中的目标和真实射界选位。'+p['questions']['tactic']['instructions'])
    return dict(state=dict(run_id=state['run_id'],tick=state['tick'],time=state['time'],bounds=state['bounds'],objective=state['objective'],
        units=[u for u in state['units'] if u['hp']>0 and u.get('combat_ready',True)],
        covers=[c for c in state.get('covers',[]) if c.get('alive')],shared=policies,executors=local,
        coordination='共享观测，逐兵回答。已有实际火力才算掩护；位置冲突只拒绝冲突成员，不覆盖其他成员。'),questions=questions)


def decode_round(payload, response):
    decisions={};errors={}
    for uid,context in payload['state']['executors'].items():
        try:
            choice=checked_choice(response['answers'][uid],context['command_candidates'])
            decisions[uid]=dict(copy.deepcopy(context['command_candidates'][choice]),reason='JEV 单兵决策：'+choice,_choice_key=choice)
        except (KeyError,TypeError,ValueError,ProviderError):errors[uid]='invalid_unit_answer'
    return decisions,errors


def compact_state(state, questions=None):
    result={k:state[k] for k in ('run_id','tick','time','bounds','objective')}
    fields=('id','faction','weapon','hp','position','goal','suppression','ammo','reload_remaining','weapon_range','last_shot_at','last_shot_target','locomotion')
    result['units']=[unit_view(u) for u in state['units']]
    result['objective']=objective_view(state['objective'])
    result['terrain']=terrain_view(state['covers'],state['units'])
    shared=state['shared']
    result['stage_status']=shared.get('stage_status')
    result['strategic_regions']=shared.get('strategic_regions',{})
    result['tactical_map']=shared.get('tactical_map',{'status':'unknown','rows':[]})
    result['cooperation_board']=shared.get('cooperation_board',{})
    result['plan']={k:v for k,v in shared.get('squad_task',{}).items() if k!='role'}
    result['rules']={k:shared.get(k) for k in ('recovery_rules','disengagement_guidance','mission')}
    result['rules']['execution_policy']=shared.get('execution_policy')
    result['team_execution']={uid:{k:r[k] for k in ('role','support_ready','actual_position','active_task','early_retreat_warning','recent_damage') if k in r} for uid,r in shared.get('team_execution',{}).items()}
    result['executors']={}
    result['controlled_unit_ids']=list(state['executors'])
    if len(result['controlled_unit_ids'])==1:result['self_id']=result['controlled_unit_ids'][0]
    for uid,local in state['executors'].items():
        feedback=local.get('execution_feedback',{})
        spatial=local.get('spatial_tools',{})
        combat=local.get('self',{}).get('combat',{})
        task=local.get('persistent_task') or {}
        result['executors'][uid]=dict(identity=dict(unit_id=uid,faction=local.get('self',{}).get('faction'),weapon=local.get('self',{}).get('weapon')),
            task=task,assignment_binding=dict(actor_id=uid,support_for=task.get('support_for') or (task.get('partner') if task.get('command')=='support' else '') or '',target_id=task.get('target_id') or '',start_when=task.get('start_when','immediate')),
            targets=local.get('target_comparison',[]),fire_status=local.get('fire_status',[]),
            region_choices=local.get('region_choices',{'query_status':'unknown_no_recent_query','options':[]}),
            feedback=dict({k:feedback[k] for k in ('active_task','selected_destination','selected_fire_lane_evidence','no_movement_seconds','no_shot_seconds','early_retreat_warning','recent_damage','last_execution_rejection','task_progress','task_execution','fire_task_stall_seconds','unreachable_candidates','stage_blocker','dynamic_task','last_task_change','unproductive_seconds') if k in feedback},
                          local_failure=local_failure_view(feedback.get('local_failure')),
                          local_maneuver={k:feedback.get('local_maneuver_report',{}).get(k) for k in ('reason','target_id','fire_lane_status','options') if k in feedback.get('local_maneuver_report',{})}),
            spatial=summary(spatial),micro_combat=local.get('micro_combat',{}),
            objective_timing=local.get('objective_timing',{}),
            region_navigation=feedback.get('region_navigation'),
            # Combat state already appears once in shared units.
            )
    for row in result['executors'].values():
        if 'task_execution' in row['feedback']:row['feedback']['task_execution']={k:v for k,v in row['feedback']['task_execution'].items() if k!='signature'}
    if questions is not None:
        from executor_view import build
        result=build(result,questions)
    return rounded(result)


class TeamExecutor:
    def __init__(self,controller,member_id=None):
        self.member_id=member_id
        self.c=controller;self.pending=None;self.next_at=0;self.receipts={};self.rounds=0;self.consecutive_errors=0;self.fatal_error=''
        self.structural_errors=0
    def invoke(self,payload,call_id):
        c=self.c;started=time.monotonic()
        try:
            response=c.coordination.game.ask(compact_state(payload['state'],payload['questions']),question_view(payload['questions']))
            c.call_log.update(call_id,phase='returned',provider_response=response,quickplay_request_id=response.get('requestId'),resolved_model=response.get('resolvedModel'),usage=response.get('usage'),latency_ms=round((time.monotonic()-started)*1000))
            return response
        except Exception as error:
            if str(error)=='request-budget':c.coordination.budget_exhausted=True
            summary=provider_failure_summary(error)
            c.coordination.error=summary
            # Keep the UI and JSONL useful without copying provider URLs or
            # credentials. The bounded class/message makes HTTP 400 and
            # timeout failures distinguishable from a quota exhaustion.
            c.call_log.update(call_id,phase='error',error=summary,
                              error_type=type(error).__name__)
            raise
    def tick(self,s,acks,age):
        c=self.c;now=time.monotonic();team=c.coordination.team
        if self.fatal_error:c.status='error';return
        active={u['id']:u for u in s.get('units',[]) if u['hp']>0 and u['faction']==team and u.get('combat_ready',True) and (self.member_id is None or u['id']==self.member_id)}
        c.run_id=s.get('run_id','')
        for uid,row in c.units.items():
            if self.member_id is not None and uid!=self.member_id:continue
            if uid not in active:row['phase']='inactive'
            elif row.get('command_id') in acks:
                ack=acks[row['command_id']];row.update(receipt=ack,phase='executing' if ack.get('accepted') else 'rejected')
        for command_id,(call_id,uid) in list(self.receipts.items()):
            if command_id in acks:
                detail=c.call_log.get(call_id);executions=detail.get('unit_executions',{})
                executions[uid].update(receipt=acks[command_id],status='applied' if acks[command_id].get('accepted') else 'rejected')
                c.call_log.update(call_id,unit_executions=executions);del self.receipts[command_id]
        eligible=age<=3 and not s.get('paused') and not s.get('winner') and s.get('control',{}).get(team)=='lm' and bool(active)
        c.status='running' if eligible else 'paused' if s.get('paused') else 'idle'
        if self.pending and self.pending['future'].done():
            task=self.pending;self.pending=None
            try:
                response=task['future'].result()
                self.consecutive_errors=0;c.metrics.pop('last_error',None)
                if getattr(c.coordination,'error','').startswith('JEV '):c.coordination.error=''
                c.metrics['responses']=c.metrics.get('responses',0)+1
                c.metrics['tokens']=c.metrics.get('tokens',0)+(response.get('usage') or {}).get('totalTokens',0)
                stale=not eligible or task['run']!=s['run_id'] or task['epoch']!=s.get('control_epochs',{}).get(team,0) or now-task['started']>5
                if 'task_revisions' not in task:
                    stale=stale or task['version']!=c.coordination.version
                if stale:c.call_log.update(task['id'],phase='discarded',discard_reason='run_control_plan_or_freshness_changed')
                else:
                    decisions,errors=decode_round(task['payload'],response);executions={}
                    for uid in task['members']:
                        if uid not in active:executions[uid]=dict(status='inactive');continue
                        if 'task_revisions' in task and task['task_revisions'].get(uid)!=c.coordination.plan.get('tasks',{}).get(uid,{}).get('task_revision'):
                            executions[uid]=dict(status='discarded',reason='unit_task_changed');continue
                        if uid in errors:executions[uid]=dict(status='rejected',reason=errors[uid]);continue
                        try:
                            # Refresh the unit independently; dead/stale members do not stop others.
                            with c.state.lock:live=copy.deepcopy(c.state.state)
                            u=next((u for u in live['units'] if u['id']==uid and u['hp']>0),None)
                            if u is None or live.get('paused') or live.get('winner') or live['run_id']!=task['run'] or live.get('control_epochs',{}).get(team,0)!=task['epoch']:
                                executions[uid]=dict(status='inactive');continue
                            # The candidate key belongs to Harness receipt matching,
                            # not to the game's strict action schema.
                            raw_decision=dict(decisions[uid])
                            key=raw_decision.pop('_choice_key',None)
                            decision=validate_decision(raw_decision,live,u)
                            details=task['payload']['state']['executors'][uid].get('command_details',{})
                            selected=dict(key=key,candidate=details[key]) if key in details else None
                            c._submit(live,u,decision,c.origin,time.monotonic(),task['tick'],selection=selected)
                            self.structural_errors=0
                            r=copy.deepcopy(c.execution_records[(uid,task['tick'])]);executions[uid]=r
                            if r.get('command_id'):self.receipts[r['command_id']]=(task['id'],uid)
                        except (ValueError,KeyError,TypeError) as error:
                            executions[uid]=dict(status='rejected',reason='unit_validation_failed',
                                validation_error=str(error)[:120] if isinstance(error,ValueError) else type(error).__name__)
                            if not isinstance(error,ValueError) or str(error)=='invalid_decision_fields':
                                self.structural_errors+=1
                                if self.structural_errors>=3:self.fatal_error='执行协议连续失败3次，停止本局；请检查executor验证日志'
                    c.call_log.update(task['id'],phase='resolved',unit_executions=executions)
                    c.coordination.game.record(dict(type='team-round-resolved',call_id=task['id'],request_id=response.get('requestId'),executions=executions))
            except Exception:
                c.metrics['team_errors']=c.metrics.get('team_errors',0)+1
                c.metrics['last_error']=getattr(c.coordination,'error','') or 'team_request_failed'
                self.consecutive_errors+=1
                if self.consecutive_errors>=3:self.fatal_error=(self.member_id or '整队')+'请求连续失败3次，已结束测试，避免无新指令持续停留；'+(getattr(c.coordination,'error','') or '请检查服务商请求')
                self.next_at=now+2
            # next_at is measured from request start; successful responses add no cooldown.
            self.next_at=max(self.next_at,task['started']+.5)
        if c.used>=c.config['max_requests']:c.coordination.budget_exhausted=True
        if self.fatal_error or not eligible or self.pending or now<self.next_at or c.coordination.budget_exhausted:return
        members=[active[k] for k in sorted(active) if c.units.get(k,{}).get('phase')!='submitted' and (self.member_id is None or k==self.member_id)]
        if not members:return
        # Rotate validation order so the same unit does not always win conflicts.
        offset=self.rounds%len(members);members=members[offset:]+members[:offset]
        payload=build_round(c.coordination,s,members,c.memory)
        call_id=c.call_log.start(unit_id=self.member_id or 'squad',faction=team,run_id=s['run_id'],tick=s['tick'],model=c.config['model'],provider=c.provider,request=dict(state=compact_state(payload['state'],payload['questions']),questions=question_view(payload['questions'])))
        revisions={u['id']:c.coordination.plan.get('tasks',{}).get(u['id'],{}).get('task_revision') for u in members}
        self.pending=dict(id=call_id,payload=payload,members=[u['id'] for u in members],run=s['run_id'],tick=s['tick'],epoch=s.get('control_epochs',{}).get(team,0),version=c.coordination.version,task_revisions=revisions,started=now,future=c.pool.submit(self.invoke,payload,call_id))
        self.rounds+=1;c.used+=1;c.metrics['team_requests']=c.metrics.get('team_requests',0)+1
        self.next_at=now+.5


class IndependentExecutor:
    """One pending request per soldier; retain shared observation and commander tasks."""
    def __init__(self,controller,unit_id=None):
        self.member_id=unit_id
        self.c=controller;self.workers={}
    @property
    def in_flight(self):return sum(w.pending is not None for w in self.workers.values())
    @property
    def fatal_error(self):return next((w.fatal_error for w in self.workers.values() if w.fatal_error),'')
    def tick(self,s,acks,age):
        for u in s.get('units',[]):
            if u['hp']>0 and u['faction']==self.c.coordination.team:
                self.workers.setdefault(u['id'],TeamExecutor(self.c,u['id']))
        for worker in self.workers.values():worker.tick(s,acks,age)
