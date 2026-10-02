"""Small model-facing forecasts; never infer safety for an unqueried destination."""
import math
from context_views import rounded

def summary(spatial, include_cover=True, include_remote=True):
    if not spatial:return {'status':'unknown_no_recent_query'}
    result={k:spatial[k] for k in ('sampled_at','nearest_enemy','preferred_distance',
        'current_threats','blocked_shots','threat_forecast') if k in spatial}
    if include_cover and spatial.get('cover_firing_positions'):
        result['cover_selection']='reference_only; native cover command cannot select a listed slot'
        result['cover_firing_positions']=[dict(
            slot=p.get('slot_key'),position=p.get('position'),peek=p.get('peek_position'),
            available=p.get('available'),hard=p.get('hard'),native_peek_gate=p.get('native_peek_gate'),
            targets=p.get('targets_from_peek',[]),blocked=p.get('blocked_targets',[]),
            anchor_threats=p.get('anchor_threats',[]),peek_threats=p.get('peek_threats',[]),
            path_risk={k:v for k,v in p.get('risk',{}).items() if k in ('status','travel_s','exposed_s','peak_attackers')})
            for p in spatial['cover_firing_positions'][:6]]
    if include_remote and spatial.get('remote_firing_search'):
        result['remote_firing_search']={k:spatial['remote_firing_search'].get(k) for k in
            ('status','sampled_cells','clear_ray_cells','path_queries','returned')}
    if include_remote and spatial.get('remote_firing_positions'):
        result['remote_firing_positions']=[dict(position=p.get('position'),targets=p.get('targets',[]),
            sector=p.get('sector'),focus_target_id=p.get('focus_target_id'),
            risk={k:v for k,v in p.get('risk',{}).items() if k in ('status','travel_s','exposed_s','peak_attackers')},
            basis='全图粗采样站姿枪口射线；敌人移动后需复核')
            for p in spatial['remote_firing_positions'][:6]]
    return rounded(result)

def annotate(options, spatial):
    points=list(spatial.get('route_forecasts',[]))
    for group in ('firing_positions','remote_firing_positions','shelter_positions','withdrawal_positions','navigation_steps'):
        points.extend(spatial.get(group,[]))

    def forecast(position, scope):
        # Engine float serialization may differ by a few ulps. Do not substitute
        # a nearby sample: two sides of a wall can have different exposure.
        point=next((p for p in points if 'risk' in p and position and
                    math.dist(position,p['position'])<=1e-5),None)
        risk=dict(point['risk']) if point else dict(status='unknown',reason='destination_not_queried')
        return dict(scope=scope,position=list(position),
                    origin=risk.get('origin',spatial.get('origin')),
                    observed_at=risk.get('observed_at',spatial.get('sampled_at')),
                    forecast=risk)

    def describe(scoped):
        risk=scoped['forecast']
        if risk.get('status')=='sampled':
            return ('路径预测：约%.1fs到达/%.1fs暴露，途中最多%d敌、终点%d敌射界' %
                (risk.get('travel_s',0),risk.get('exposed_s',0),risk.get('peak_attackers',0),risk.get('endpoint_attackers',0)))
        if risk.get('status')=='unknown':return '路径威胁未知（未查询），不代表安全'
        return '路径预测：'+risk.get('status','unknown')

    for candidate in options.values():
        command=candidate['command']
        if command.get('action')!='move':continue
        position=command.get('position')
        if not position:continue
        candidate['path_risk']=forecast(position,'current_step')
        text=describe(candidate['path_risk'])
        destination=candidate.get('destination')
        if destination and math.dist(position,destination)>1e-5:
            candidate['final_destination_risk']=forecast(destination,'final_destination_scope')
            text='当前短步'+text+'；最终射位（完整原生路径，非本次短步）'+describe(candidate['final_destination_risk'])
        candidate['description']=candidate.get('description','')+'；'+text
