"""Decision-facing command brief; detailed query candidates stay with JEV."""
from context_views import pick, rounded


def build(context):
    out=pick(context,('information','time','mission','objective','objective_regions',
        'stage_status','stagnation','recent_events','objective_timing','plan_validation_feedback',
        'living_controlled_unit_ids'))
    out['evidence_limits']='JEV选择下一战术区域和区域内落点；具体路径由游戏引擎寻路并验证。区域连通不等于整路安全；远端射位是粗采样，不保证区域内任意点可射击。未知不是不可达。'
    out['units']=[]
    for u in context.get('units',[]):
        row=pick(u,('id','faction','kind','weapon','hp','max_hp','position','current_regions',
                    'suppression','ammo','reload_remaining','weapon_range','posture'))
        row['combat']=pick(u.get('combat',{}),('engageable_targets','incoming_threats','regeneration'))
        out['units'].append(row)
    previous=context.get('previous_plan',{})
    living=set(context['living_controlled_unit_ids']) if 'living_controlled_unit_ids' in context else None
    out['previous_plan']=pick(previous,('objective','stage','reason'))
    out['previous_plan']['tasks']={uid:pick(t,('actor_id','command','target_id','support_for','partner',
        'start_when','wait_timeout_s','on_failure','assignment','complete_when','replan_when','region_hint',
        'region_id','region_path','wait_region_id')) for uid,t in previous.get('tasks',{}).items() if living is None or uid in living}
    # Keep feasibility evidence in one place, rather than copying range/fire facts
    # into the board, raw query forecasts and execution reports as well.
    out['plan_feasibility']=context.get('plan_feasibility',{})
    out['approach_corridors']=context.get('approach_corridors',
        {'status':'unknown','corridors':[]})
    out['tactical_map']=context.get('tactical_map',
        {'status':'unknown','rows':[]})
    out['execution']={}
    board=context.get('cooperation_board',{})
    for uid,row in context.get('execution',{}).items():
        if living is not None and uid not in living:continue
        value=pick(row,('recent_damage','no_movement_seconds','unproductive_seconds','early_retreat_warning'))
        value['task']=pick(row.get('task_execution',{}),('phase','reason','wait_seconds'))
        value['progress']=pick(row.get('task_progress',{}),('achieved',))
        failure=row.get('local_failure') or {}
        if failure.get('phase')!='not_applicable':
            value['failure']=pick(failure,('phase','reason','severity','duration_s','block_reason','navigation_reason'))
        value['cooperation']=pick(board.get(uid,{}),('target_status','arrival_status','arrival_basis','fire_evidence'))
        out['execution'][uid]=value
    opportunities=context.get('region_opportunities',{})
    out['maneuver_options']={}
    for uid,routes in opportunities.get('route_options',{}).items():
        if living is not None and uid not in living:continue
        grouped={}
        for route in routes:
            region=route['goal_region']
            entry=grouped.setdefault(region,dict(region=region,tags=route.get('goal_tags',[]),
                connected_options=0,first_steps=[],whole_route_risk='unknown'))
            entry['connected_options']+=1
            step=route.get('first_step',{})
            fact=pick(step,('status','reason','risk'))
            if fact not in entry['first_steps']:entry['first_steps'].append(fact)
        out['maneuver_options'][uid]=dict(query_status=opportunities.get('query_status',{}).get(uid,'unknown'),
            sampled_at=opportunities.get('sampled_at',{}).get(uid),goals=list(grouped.values()),
            omitted_goals=opportunities.get('omitted_route_goals',{}).get(uid),
            unreachable_goals=opportunities.get('unreachable_route_goals',{}).get(uid))
    out['current_threats']={uid:pick(row,('sampled_at','current_threats','blocked_shots'))
        for uid,row in context.get('threat_forecast',{}).items() if living is None or uid in living}
    # Compact map legend permits validated region hints without dumping adjacency
    # lists or colliders. Occupancy is snapshot fact, not future reservation.
    facts=opportunities.get('regions',{})
    out['strategic_regions']={key:dict(center=row.get('center'),
        **pick(facts.get(key,{}),('allies','enemies','objective_center')))
        for key,row in context.get('strategic_regions',{}).items()}
    return rounded(out)
