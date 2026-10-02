"""Small, read-only team approach corridors from native connected regions.

The three labels describe geometry relative to the team's advance vector.
They are not named tactics, movement orders, firing guarantees, or safety
recommendations. Full-route exposure is unknown without a native route query.
"""
import heapq
import math

from strategic_regions import memberships, navigation_anchor


def _point(value):
    return (isinstance(value,(list,tuple)) and len(value)==2 and
            all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in value))


def _path(start, goal, regions, origin, forward, forbidden=()):
    """Fewest region hops, then least centerline deviation; no tactical score."""
    if start not in regions or goal not in regions:return None
    blocked=set(forbidden)-{start,goal}
    queue=[(0,0.0,(start,))];best={}
    while queue:
        hops,deviation,path=heapq.heappop(queue);key=path[-1]
        if key in best and best[key]<(hops,deviation):continue
        if key==goal:return list(path)
        for neighbor in sorted(regions[key].get('neighbors',[])):
            if neighbor not in regions or neighbor in blocked or neighbor in path:continue
            center=regions[neighbor].get('center')
            lateral=abs(_lateral(center,origin,forward)) if _point(center) else 0
            candidate=(hops+1,deviation+lateral)
            if neighbor not in best or candidate<best[neighbor]:
                best[neighbor]=candidate
                heapq.heappush(queue,(candidate[0],candidate[1],path+(neighbor,)))
    return None


def _projection(point, origin, forward):
    if not _point(point):return None
    return (point[0]-origin[0])*forward[0]+(point[1]-origin[1])*forward[1]


def _lateral(point, origin, forward):
    if not _point(point):return 0
    return forward[0]*(point[1]-origin[1])-forward[1]*(point[0]-origin[0])


def _far_fire(path, members, regions, origin, forward, distance, opportunities):
    evidence=opportunities or {}
    facts=evidence.get('regions',{})
    status=evidence.get('query_status',{})
    targets=set();sampled_regions=set();remote_regions=set()
    for key in path:
        region=regions.get(key,{})
        progress=_projection(region.get('center'),origin,forward)
        if progress is None or progress<distance*.6:continue
        row=facts.get(key,{})
        for member in members:
            uid=member['id']
            if status.get(uid)!='fresh':continue
            for site in row.get('opportunities',{}).get(uid,[]):
                if site.get('kind')=='firing':available=site.get('targets',[])
                elif site.get('kind')=='remote_firing':
                    available=site.get('targets',[])
                    if available:remote_regions.add(key)
                elif site.get('kind')=='cover_firing':available=site.get('available_targets',[])
                else:continue
                if available:
                    sampled_regions.add(key)
                    targets.update(target for target in available if isinstance(target,str))
    return dict(status='sampled_remote_coarse' if remote_regions and sampled_regions==remote_regions else
                'sampled_mixed' if remote_regions else 'sampled_local' if sampled_regions else 'unknown',
                targets=sorted(targets),regions=sorted(sampled_regions))


def build(state, members, regions, region_opportunities=None):
    """Return up to three distinct connected corridors toward the objective.

    Input regions must come from the current native topology. ``extra_hops``
    and ``detour_ratio`` compare region-graph hops, not metres or travel time.
    A side corridor is selected to represent a reachable lateral branch with
    limited extra hops; no predicted success or safety score is calculated.
    """
    topology=state.get('strategic_topology') or {}
    basis=('区域由当前原生通行拓扑产生；center/left/right 只表示相对推进方向的几何走廊，'
           'via_region_hint 是中途区域，非命令。extra_hops/detour_ratio 比较区域跳数，'
           '不是实际行走距离。整条路线风险未知；射界只来自新鲜局部或远端粗抽样，'
           '缺样本不代表不能射击，抽样射界不保证按本走廊走后仍可射击。')
    empty=dict(status='unknown',corridors=[],basis=basis)
    if not topology.get('cells') or not topology.get('edges') or not regions or any('cells' not in r for r in regions.values()):
        return dict(empty,reason='native_connected_regions_unavailable')
    living=[u for u in members if u.get('hp',0)>0 and _point(u.get('position'))]
    goal_position=state.get('objective',{}).get('position')
    if not living or not _point(goal_position):return dict(empty,reason='origin_or_objective_unknown')
    centroid=[sum(u['position'][i] for u in living)/len(living) for i in (0,1)]
    representative=min(living,key=lambda u:(math.dist(u['position'],centroid),u['id']))
    origin=representative['position']
    sources=navigation_anchor(origin,regions,topology)['anchor_regions']
    goals=memberships(goal_position,regions) or navigation_anchor(goal_position,regions,topology)['anchor_regions']
    if not sources or not goals:return dict(empty,reason='origin_or_objective_outside_sampled_regions')
    direction=[goal_position[i]-origin[i] for i in (0,1)]
    distance=math.hypot(*direction)
    if distance<=1e-8:return dict(empty,reason='team_already_at_objective')
    forward=[v/distance for v in direction]
    primary=[];start=destination=None
    for a in sorted(sources):
        for b in sorted(goals):
            candidate=_path(a,b,regions,origin,forward)
            if candidate and (not primary or (len(candidate),candidate)<(len(primary),primary)):
                primary=candidate;start=a;destination=b
    if not primary:return dict(empty,reason='objective_disconnected')
    base_hops=len(primary)-1
    max_extra=4
    min_lateral=max(float(topology.get('step',.075))*.75,distance*.18)
    def present(side,path,via,offset):
        hops=len(path)-1
        return dict(side=side,via_region_hint=via,region_path=path,hop_count=hops,
                    extra_hops=hops-base_hops,
                    detour_ratio=round(hops/base_hops,2) if base_hops else None,
                    signed_lateral_offset=round(offset,3),
                    sampled_far_fire=_far_fire(path,living,regions,origin,forward,distance,region_opportunities),
                    risk_status='unknown_full_route')
    middle=primary[len(primary)//2]
    primary_offset=_lateral(regions[middle].get('center'),origin,forward)
    # "center" names the shortest connected baseline, even if walls shift
    # its midpoint away from the straight line to the objective.
    corridors=[present('center',primary,middle,primary_offset)]
    for side,sign in (('left',1),('right',-1)):
        variants=[]
        for via,region in regions.items():
            if via in (start,destination):continue
            offset=_lateral(region.get('center'),origin,forward)
            progress=_projection(region.get('center'),origin,forward)
            if sign*offset<min_lateral or progress is None or not .1*distance<=progress<=.9*distance:
                continue
            first=_path(start,via,regions,origin,forward)
            if first is None:continue
            last=_path(via,destination,regions,origin,forward,forbidden=first[:-1])
            if last is None:continue
            path=first+last[1:]
            extra=len(path)-len(primary)
            if extra>max_extra or any(existing['region_path']==path for existing in corridors):continue
            variants.append((extra,-abs(offset),len(path),path,via,offset))
        if variants:
            _,_,_,path,via,offset=min(variants)
            corridors.append(present(side,path,via,offset))
    return dict(status='ready',origin_region=start,origin_unit=representative['id'],
                objective_region=destination,corridors=corridors,basis=basis)
