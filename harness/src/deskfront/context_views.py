"""Model-facing tactical views; exact geometry and commands stay in the engine."""
import math
import re

def pick(row, keys):return {k:row[k] for k in keys if k in row}
def rounded(value):
    if isinstance(value,float):return round(value,3)
    if isinstance(value,dict):return {k:rounded(v) for k,v in value.items() if k not in ('destination_area','wait_area','strategic_topology','signature')}
    if isinstance(value,list):return [rounded(v) for v in value]
    return value

def objective_view(o):
    r=pick(o,('position','radius','score_to_win'))
    if o.get('flag'):r['flag']=pick(o['flag'],('owner','contested','held_seconds','remaining_seconds','required_seconds'))
    return r

def local_failure_view(row):
    if not isinstance(row,dict):return None
    result=pick(row,('phase','reason','severity','duration_s','arrived','range_gap','no_movement_s','block_reason','navigation_reason','local_failure_reason'))
    evidence=row.get('evidence') or {}
    result['evidence']=pick(evidence,('cover_cycle','cover_stance','reserved_cover_slot','native_path_active','native_fire_lane',
        'last_assigned_shot_at','range_gap_at_current_position','range_basis',
        'local_query','sampled_local_options'))
    return result

def unit_view(u):
    r=pick(u,('id','faction','kind','weapon','hp','max_hp','position','goal','suppression','ammo','reload_remaining','weapon_range','last_shot_at','last_shot_target','locomotion','posture','posture_order','in_cover','cover_id','cover_slot','cover_step','cqb_stance','order_mode'))
    from cover_evidence import cover_phase
    r['cover_phase']=cover_phase(u)
    r['combat']=pick(u.get('combat',{}),('path_active','engageable_targets','incoming_threats','fire_check','regeneration'))
    return r

def terrain_view(covers,units,limit=12):
    anchors=[u['position'] for u in units if u.get('hp',0)>0]
    distance=lambda p:min((math.dist(p,a) for a in anchors),default=math.inf)
    ordinary=[];buildings={}
    for c in covers:
        if not c.get('alive'):continue
        if c.get('kind')=='building':
            key=c['id'].rsplit('-',1)[0];buildings.setdefault(key,[]).append(c)
        else:ordinary.append(c)
    result=[]
    for c in sorted(ordinary,key=lambda c:distance(c['position'])):
        if distance(c['position'])<=1.2 and len(result)<limit:result.append(pick(c,('id','kind','position','size','height','normal','hp','max_hp','damage_stage')))
    for key,parts in buildings.items():
        lo=[min(c['position'][i]-c.get('size',[0,0])[i]/2 for c in parts) for i in (0,1)]
        hi=[max(c['position'][i]+c.get('size',[0,0])[i]/2 for c in parts) for i in (0,1)]
        center=[(a+b)/2 for a,b in zip(lo,hi)]
        if distance(center)<=1.5:result.append(dict(id=key,kind='building_summary',bounds=[lo,hi],note='整体范围摘要，不代表可通行区域；路径和射界以工具验证为准'))
    return result

def routes_view(routes):
    result={}
    for key,r in routes.items():
        ps=r.get('points',[])
        result[key]=dict(name=r.get('name',key),purpose=r.get('purpose'),waypoints=len(ps),entry=ps[0] if ps else None,end=ps[-1] if ps else None,length=sum(math.dist(a,b) for a,b in zip(ps,ps[1:])))
    return result

def commander_context(state,scenario,previous,recent,routes,feedback):
    units=[u for u in state.get('units',[]) if u.get('combat_ready',True) and u['hp']>0]
    return rounded(dict(information='完全信息，无战争迷雾；摘要几何不能代替原生查询',time=state['time'],
        mission=dict(kind=scenario['kind'],goal=scenario['goal'],details=pick(scenario.get('details',{}),('status','defenders','target'))),
        objective=objective_view(state['objective']),units=[unit_view(u) for u in units],terrain=terrain_view(state.get('covers',[]),units),
        previous_plan=previous,recent_events=recent[-6:],routes=routes_view(routes),
        execution={uid:dict(pick(r,('active_task','support_ready','early_retreat_warning','recent_damage','no_movement_seconds','no_shot_seconds','task_progress','task_execution','unproductive_seconds','fire_task_stall_seconds','unreachable_candidates')),
                            local_failure=local_failure_view(r.get('local_failure'))) for uid,r in feedback.items()}))

def question_view(questions):
    # Display-only number shortening: command coordinates remain untouched.
    def text(s):return re.sub(r'-?\d+\.\d{4,}',lambda m:str(round(float(m[0]),3)),s)
    return {uid:dict(q,instructions=text(q['instructions']),criteria={k:text(v) for k,v in q['criteria'].items()}) for uid,q in questions.items()}
