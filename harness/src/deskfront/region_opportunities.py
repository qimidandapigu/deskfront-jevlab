"""Compact region and route opportunities from fresh native query evidence.

No tactical decision is made here. The queried candidate set is local and
truncated by the engine: no sample means unknown, never that a region is safe
or unusable. Target/threat unions and risk ranges may describe different points.
"""
from collections import deque
import math

from strategic_regions import memberships, navigation_anchor


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _point(value):
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(_number(v) for v in value)


def _summarize(kind, samples, sampled_at):
    risks = [p.get('risk', {}) for p in samples]
    measured = [r for r in risks if r.get('status') == 'sampled']
    exposures = [r['exposed_s'] for r in measured if _number(r.get('exposed_s')) and r['exposed_s'] >= 0]
    travels = [r['travel_s'] for r in measured if _number(r.get('travel_s')) and r['travel_s'] >= 0]
    target_key = 'targets_from_peek' if kind == 'cover_firing' else 'targets'
    threat_key = 'peek_threats' if kind == 'cover_firing' else 'threats'
    targets = sorted({target for p in samples for target in p.get(target_key, []) if isinstance(target, str)})
    threats = sorted({target for p in samples for target in p.get(threat_key, []) if isinstance(target, str)})
    result = dict(kind=kind, samples=len(samples), targets=targets, threats=threats,
                exposed_s=[round(min(exposures),2),round(max(exposures),2)] if exposures else None,
                min_travel_s=round(min(travels),2) if travels else None,
                risk_samples=len(measured),
                risk_status='sampled' if len(measured)==len(samples) else 'partial' if measured else 'unknown',
                sampled_at=sampled_at, risk_scope='native_path_to_sample_not_chosen_region_route')
    if kind == 'cover_firing':
        available = [p for p in samples if p.get('available') is True and p.get('reachable') is True]
        result['available_samples'] = len(available)
        result['available_targets'] = sorted({target for p in available for target in p.get('targets_from_peek', [])
                                               if isinstance(target, str)})
    return result


def _candidate_paths(starts, goal, regions, limit=2):
    """Enumerate connected, simple region paths; ordering is not a safety score."""
    backwards={key:[] for key in regions}
    for key,region in regions.items():
        for neighbor in region.get('neighbors', []):
            if neighbor in backwards:backwards[neighbor].append(key)
    distance={goal:0};todo=deque([goal])
    while todo:
        key=todo.popleft()
        for previous in backwards[key]:
            if previous not in distance:distance[previous]=distance[key]+1;todo.append(previous)
    sources=sorted(key for key in starts if key in distance)
    if not sources:return []
    max_hops=min(len(regions)-1,min(distance[key] for key in sources)+3)
    queue=deque([[source] for source in sources]);found=[];expanded=0
    while queue and expanded<2000 and len(found)<32:
        path=queue.popleft();expanded+=1;last=path[-1]
        if last==goal:
            found.append(path);continue
        for neighbor in sorted(regions[last].get('neighbors', [])):
            if neighbor in distance and neighbor not in path and len(path)+distance[neighbor]<=max_hops:
                queue.append(path+[neighbor])
    found.sort(key=lambda path:(len(path),path))
    selected=[]
    while found and len(selected)<limit:
        if not selected:selected.append(found.pop(0));continue
        used_heads={path[1] if len(path)>1 else path[0] for path in selected}
        used_regions=set().union(*(set(path) for path in selected))
        found.sort(key=lambda path:(path[1] in used_heads if len(path)>1 else path[0] in used_heads,
                                    -len(set(path)-used_regions),len(path),path))
        selected.append(found.pop(0))
    return selected


def _first_step(unit, path, topology, regions, spatial, allies):
    from region_routing import local_move_allowed, next_region_step
    from strategic_regions import contains
    task={'region_id':path[-1],'region_path':path}
    navigation=next_region_step(unit['position'],task,topology,regions,
                                [ally['position'] for ally in allies if ally['id']!=unit['id']])
    result={'status':navigation['status']}
    if navigation['status']=='blocked':
        result['reason']=navigation.get('reason','unknown')
    elif navigation['status']=='ready':
        position=navigation['position']
        # The native actor treats a destination within ~.055 as already
        # arrived. A route hint at that distance can be selected every model
        # round yet never move the unit. Prefer a farther, natively queried
        # sample in the same next region and checked corridor; otherwise mark
        # this leg unusable instead of presenting a no-op move as progress.
        if math.dist(unit['position'],position)<=.055+1e-8:
            target=navigation.get('next_region')
            scope=navigation.get('path_regions') or []
            candidates=[]
            for point in spatial.get('navigation_steps',[]):
                p=point.get('position');risk=point.get('risk',{})
                if not _point(p) or not isinstance(risk,dict) or risk.get('status')!='sampled':continue
                distance=math.dist(unit['position'],p)
                if not .055+1e-8<distance<=.25+1e-8:continue
                if target not in regions or not contains(p,regions[target]):continue
                if any(ally['id']!=unit['id'] and math.dist(ally['position'],p)<.09 for ally in allies):continue
                if not local_move_allowed(unit['position'],p,scope,regions,
                                          origin_bridge=navigation.get('navigation_anchor')):continue
                candidates.append((math.dist(p,position),distance,list(p)))
            if not candidates:
                return dict(status='too_close',reason='inside_native_arrival_tolerance_no_farther_queried_step',
                            distance=round(math.dist(unit['position'],position),3))
            position=min(candidates)[2]
        result['position']=position
        matched=next((point.get('risk',{}) for point in spatial.get('navigation_steps',[])
                      if _point(point.get('position')) and math.dist(position,point['position'])<1e-6),None)
        risk=matched if isinstance(matched,dict) else {}
        result['risk']={k:round(v,2) if k in ('travel_s','exposed_s') and _number(v) else v
                        for k,v in risk.items() if k in ('status','travel_s','exposed_s','peak_attackers')}
        if result['risk'].get('status') not in ('sampled','unreachable'):result['risk']={'status':'unknown'}
    return result


def _route_options(state, living, regions, facts, fresh_spatial, tasks=None):
    topology=state.get('strategic_topology') or {}
    if not topology.get('cells') or not topology.get('edges'):
        return {},{},{}
    output={};omitted={};unreachable={}
    for unit in living:
        uid=unit['id'];anchor=navigation_anchor(unit['position'],regions,topology)
        task=(tasks or {}).get(uid,{})
        fire_role=task.get('command') in ('support','eliminate','flank')
        target=task.get('target_id')
        starts=anchor['anchor_regions']
        if not starts:
            output[uid]=[];omitted[uid]=0;unreachable[uid]=[];continue
        goals={}
        for key,region in facts.items():
            tags=[]
            if region['objective_center']:tags.append('objective')
            sites=region['opportunities'].get(uid,[])
            if any(site['kind'] in ('firing','remote_firing') and site['targets'] for site in sites):tags.append('sampled_firing')
            if any(site['kind']=='cover_firing' and site.get('available_targets') for site in sites):tags.append('sampled_peek')
            if region['enemies']:tags.append('enemy_present')
            if key==task.get('region_hint'):tags.append('commander_hint')
            if target and target in region['enemies']:tags.append('assigned_enemy')
            if target and any(target in site.get('targets',[]) or target in site.get('available_targets',[]) for site in sites):tags.append('assigned_fire_sample')
            if tags:goals[key]=tags
        # Always show the objective if it exists; then current, observed firing
        # opportunities and enemy positions. This is a bounded display order,
        # not a recommendation that any such region is safe to enter.
        def goal_order(item):
            key,tags=item
            if fire_role:
                return (0 if 'commander_hint' in tags else
                        1 if 'assigned_fire_sample' in tags else
                        2 if 'sampled_firing' in tags or 'sampled_peek' in tags else
                        3 if 'assigned_enemy' in tags else 4,key)
            return (0 if 'commander_hint' in tags else 1 if 'objective' in tags else 2 if 'sampled_firing' in tags or 'sampled_peek' in tags else 3,
                    key)
        ordered=sorted(goals.items(),key=goal_order)
        reachable=[];unreachable[uid]=[]
        for goal,tags in ordered:
            paths=_candidate_paths(starts,goal,regions)
            if paths:reachable.append((goal,tags,paths))
            else:unreachable[uid].append(goal)
        omitted[uid]=max(0,len(reachable)-3)
        rows=[];step_cache={}
        for goal,tags,paths in reachable[:3]:
            for path in paths:
                first_leg=tuple(path[:2]);step=step_cache.get(first_leg)
                if step is None:
                    step=_first_step(unit,path,topology,regions,fresh_spatial.get(uid,{}),living)
                    step_cache[first_leg]=step
                # Occupancy and sampled firing facts already live under
                # regions[key]. Repeating them on every path makes model
                # context grow with routes times regions and invites the
                # model to combine unrelated sample advantages.
                rows.append(dict(goal_region=goal,goal_tags=tags,
                                 region_path=path,first_step=step))
        output[uid]=rows
    return output,omitted,unreachable


def build(state, members, regions, spatial_by_unit, tasks=None):
    """Summarize at most three evidence groups per unit per region, without points.

    ``firing`` aggregates firing positions; ``disengage`` aggregates withdrawal
    and shelter positions; ``cover_firing`` aggregates actual peek slots. Units
    without fresh evidence in a region are explicitly listed in ``unknown_for``.
    Occupancy and objective-center membership come from the current snapshot.
    Query geometry is still checked live by JEV and the native move/fire tools.
    """
    living=[u for u in members if u.get('hp',0)>0 and u.get('combat_ready',True)]
    ids=[u['id'] for u in living]
    factions={u.get('faction') for u in living}
    facts={key:dict(allies=[],enemies=[],objective_center=False,opportunities={},unknown_for=list(ids))
           for key in regions}
    for unit in state.get('units',[]):
        if unit.get('hp',0)<=0 or not unit.get('combat_ready',True) or not _point(unit.get('position')):
            continue
        group='allies' if unit.get('faction') in factions else 'enemies'
        for key in memberships(unit['position'],regions):facts[key][group].append(unit['id'])
    objective=state.get('objective',{}).get('position')
    if _point(objective):
        for key in memberships(objective,regions):facts[key]['objective_center']=True

    sampled_at={};query_status={};fresh_spatial={}
    for unit in living:
        uid=unit['id'];spatial=spatial_by_unit.get(uid,{}) or {}
        stamp=spatial.get('sampled_at');now=state.get('time')
        sampled_at[uid]=stamp if _number(stamp) else None
        if not _number(stamp) or not _number(now) or not 0<=now-stamp<=2:
            query_status[uid]='stale' if _number(stamp) else 'unknown'
            continue
        origin=spatial.get('origin')
        if origin is not None and (not _point(origin) or math.dist(origin,unit['position'])>.15):
            query_status[uid]='origin_changed'
            continue
        query_status[uid]='fresh'
        fresh_spatial[uid]=spatial
        groups={}
        for field,kind in (('firing_positions','firing'),('remote_firing_positions','remote_firing'),('withdrawal_positions','disengage'),('shelter_positions','disengage'),('cover_firing_positions','cover_firing')):
            for candidate in spatial.get(field,[]):
                point=candidate.get('position')
                if not _point(point):continue
                token=('slot',candidate['slot_key']) if kind=='cover_firing' and isinstance(candidate.get('slot_key'),str) else tuple(round(v,6) for v in point)
                for key in memberships(point,regions):
                    group=groups.setdefault((key,kind),{})
                    # Duplicate shelter/withdraw points describe one tested
                    # location. Prefer a measured path over a missing forecast.
                    if token not in group or (group[token].get('risk',{}).get('status')!='sampled'
                                             and candidate.get('risk',{}).get('status')=='sampled'):
                        group[token]=candidate
        for (key,kind),samples in groups.items():
            facts[key]['opportunities'].setdefault(uid,[]).append(_summarize(kind,list(samples.values()),stamp))
        for row in facts.values():
            if uid in row['opportunities']:row['unknown_for'].remove(uid)
    routes,omitted,unreachable=_route_options(state,living,regions,facts,fresh_spatial,tasks)
    return dict(basis='当前区域驻军与目标中心来自快照；机会来自原生局部候选与有界全图粗射位抽样。remote_firing只代表采样点站姿枪口射线和至该点的原生路径，敌人移动后可能失效；targets/threats是多射位并集，不能与最小风险视为同一射位；连通/射线不保证命中或安全。unknown_for表示未查询到新鲜样本，不代表该区不可用。',
                route_basis='每兵最多3个有意义目标区、每区2条连通区域序列；只验证区域相邻和首短步的采样通路。first_step.risk仅在原生navigation_steps精确匹配且新鲜时表示该短步暴露；整条区域路线暴露未知。射位及拥挤查看regions各区事实；远端射位的原生路径不证明所列区域序列经过同一路径。occupancy仅为当前快照，不含未来预约；候选无安全推荐分。',
                route_options=routes,omitted_route_goals=omitted,unreachable_route_goals=unreachable,
                time=state.get('time'),sampled_at=sampled_at,query_status=query_status,regions=facts)
