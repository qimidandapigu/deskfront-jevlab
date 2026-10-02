"""Compact, read-only evidence for a commander's current or next plan.

Range gaps are straight-line distances only. Region firing opportunities are
bounded native samples, not a proof of a reachable route, future line of fire,
hit probability, or safety. This module never chooses or changes an order.
"""
import math

from strategic_regions import memberships


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _point(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(_number(v) for v in value))


def _range_fact(unit, enemy):
    if not _point(unit.get('position')) or not _point(enemy.get('position')):
        return dict(id=enemy['id'], status='position_unknown')
    distance=math.dist(unit['position'], enemy['position'])
    reach=unit.get('weapon_range')
    return dict(id=enemy['id'], distance=round(distance, 3),
                range_gap=round(max(0, distance-reach), 3) if _number(reach) and reach>0 else None)


def _area_fire(region_id, uid, opportunities, assigned_target=None):
    """One area's observed samples; lack of a sample is explicitly unknown."""
    query=opportunities.get('query_status',{}).get(uid,'unknown')
    area=opportunities.get('regions',{}).get(region_id,{})
    rows=area.get('opportunities',{}).get(uid,[]) if query=='fresh' else []
    firing=sorted({target for row in rows if row.get('kind')=='firing'
                   for target in row.get('targets',[]) if isinstance(target,str)})
    peeking=sorted({target for row in rows if row.get('kind')=='cover_firing'
                   for target in row.get('available_targets',[]) if isinstance(target,str)})
    remote=sorted({target for row in rows if row.get('kind')=='remote_firing'
                   for target in row.get('targets',[]) if isinstance(target,str)})
    fire_samples=sum(row.get('samples',0) for row in rows if row.get('kind')=='firing')
    peek_samples=sum(row.get('available_samples',0) for row in rows if row.get('kind')=='cover_firing')
    status=('unknown_query_'+query if query!='fresh' else
            'sampled_target_candidate' if assigned_target and assigned_target in firing+peeking else
            'sampled_remote_target_candidate' if assigned_target and assigned_target in remote else
            'sampled_other_target_candidate' if firing or peeking or remote else
            'unknown_no_target_sample')
    return dict(region=region_id,status=status,
                firing_targets=firing,available_peek_targets=peeking,remote_targets=remote,
                firing_samples=fire_samples,available_peek_samples=peek_samples)


def _nearby_fire_regions(unit, uid, regions, opportunities, limit=4):
    if opportunities.get('query_status',{}).get(uid)!='fresh' or not _point(unit.get('position')):
        return [],0
    rows=[]
    for region_id, area in opportunities.get('regions',{}).items():
        item=_area_fire(region_id,uid,opportunities)
        if not item['firing_targets'] and not item['available_peek_targets'] and not item['remote_targets']:
            continue
        center=regions.get(region_id,{}).get('center')
        distance=math.dist(unit['position'],center) if _point(center) else math.inf
        rows.append((distance,region_id,item))
    rows.sort(key=lambda row:(row[0],row[1]))
    displayed=[]
    for _,_,item in rows[:limit]:
        summary=dict(region=item['region'],firing_targets=item['firing_targets'],
                     peek_targets=item['available_peek_targets'])
        if item['remote_targets']:summary['remote_targets']=item['remote_targets']
        displayed.append(summary)
    return displayed,max(0,len(rows)-limit)


def _members(state, tasks, opportunities, feedback, members):
    by_id={u['id']:u for u in state.get('units',[]) if u.get('hp',0)>0 and u.get('combat_ready',True)}
    if members is not None:
        ids={u['id'] if isinstance(u,dict) else u for u in members}
    else:
        ids=set(tasks)|set(opportunities.get('query_status',{}))|set(feedback)
    return [by_id[uid] for uid in sorted(ids) if uid in by_id]


def build(state, plan, regions, region_opportunities, feedback, *, members=None):
    """Return compact per-unit facts before and after a commander plan exists.

    ``members`` should be the controlled living units. When omitted, task,
    query and feedback IDs identify them. The returned facts are advisory only.
    """
    plan=plan or {};regions=regions or {};opportunities=region_opportunities or {}
    feedback=feedback or {}
    tasks=plan.get('tasks',{}) if isinstance(plan.get('tasks'),dict) else plan
    roles=plan.get('roles',{}) if isinstance(plan.get('roles'),dict) else {}
    units=_members(state,tasks,opportunities,feedback,members)
    now=state.get('time')
    result={}
    for unit in units:
        uid=unit['id'];task=tasks.get(uid,{}) or {};row=feedback.get(uid,{}) or {}
        enemies=[other for other in state.get('units',[])
                 if other.get('hp',0)>0 and other.get('combat_ready',True)
                 and other.get('faction')!=unit.get('faction')]
        ranges=sorted((_range_fact(unit, enemy) for enemy in enemies),
                      key=lambda item:(item.get('distance',math.inf),item['id']))
        current=sorted(memberships(unit['position'],regions)) if _point(unit.get('position')) else []
        hint=task.get('region_hint') or task.get('region_id')
        nearby,omitted_regions=_nearby_fire_regions(unit,uid,regions,opportunities)
        target=next((e for e in enemies if e.get('id')==task.get('target_id')),None)
        target_distance=_range_fact(unit,target) if target else None
        center=regions.get(hint,{}).get('center') if hint else None
        hint_gap=None
        if target and _point(center) and _point(target.get('position')):
            reach=unit.get('weapon_range')
            if _number(reach) and reach>0:
                hint_gap=round(max(0,math.dist(center,target['position'])-reach),3)
        shot_at=unit.get('last_shot_at')
        shot_age=now-shot_at if _number(now) and _number(shot_at) and shot_at>=0 and now>=shot_at else None
        no_shot=row.get('no_shot_seconds')
        if not _number(no_shot):
            no_shot=shot_age
        elif _number(now) and now>=0:
            # The runtime may use a negative pre-spawn shot sentinel. Do not
            # report more idle time than the observed game has existed.
            no_shot=min(max(0,no_shot),now)
        same_target=sorted(other['id'] for other in units if other['id']!=uid and
                           task.get('target_id') and
                           (tasks.get(other['id']) or {}).get('target_id')==task.get('target_id'))
        same_area=sorted(other['id'] for other in units if other['id']!=uid and hint and
                         ((tasks.get(other['id']) or {}).get('region_hint') or
                          (tasks.get(other['id']) or {}).get('region_id'))==hint)
        value=dict(
            weapon_range=unit.get('weapon_range'),current_regions=current[:2],
            enemy_range_gaps={item['id']:item.get('range_gap') for item in ranges[:5]},
            query_status=opportunities.get('query_status',{}).get(uid,'unknown'),
            sampled_fire_regions=nearby)
        if len(ranges)>5:value['omitted_enemies']=len(ranges)-5
        if omitted_regions:value['omitted_sampled_regions']=omitted_regions
        if task:
            assignment={k:v for k,v in dict(command=task.get('command'),role=roles.get(uid),
                        target=task.get('target_id'),partner=task.get('partner'),
                        hint_region=hint,
                        current_target_gap=target_distance.get('range_gap') if target_distance else None,
                        hint_center_gap=hint_gap).items() if v is not None}
            if hint:
                sampled=_area_fire(hint,uid,opportunities,task.get('target_id'))
                assignment['hint_sample_status']=sampled['status']
                if sampled['firing_targets']:assignment['hint_firing_targets']=sampled['firing_targets']
                if sampled['available_peek_targets']:
                    assignment['hint_peek_targets']=sampled['available_peek_targets']
                if sampled['remote_targets']:
                    assignment['hint_remote_targets']=sampled['remote_targets']
            if task.get('target_id') and target is None:
                assignment['target_status']='not_live_in_snapshot'
            value['assignment']=assignment
        execution={}
        if no_shot is not None:execution['no_observed_shot_s']=round(no_shot,2)
        if unit.get('last_shot_target'):execution['last_shot_target']=unit['last_shot_target']
        if shot_age is not None:execution['last_shot_age_s']=round(shot_age,2)
        if task.get('target_id'):
            execution['recent_assigned_target_shot']=bool(target and shot_age is not None and
                                                           shot_age<2.3 and unit.get('last_shot_target')==target['id'])
        if row.get('support_ready') is not None:execution['support_ready']=row['support_ready']
        if (row.get('task_execution') or {}).get('phase'):
            execution['task_phase']=row['task_execution']['phase']
        if (row.get('local_failure') or {}).get('reason'):
            execution['local_failure']=row['local_failure']['reason']
        if execution:value['execution']=execution
        if same_target or same_area:value['overlaps']=dict(same_target=same_target,same_hint_region=same_area)
        result[uid]=value
    return dict(time=now,basis='射程差仅为当前位置或区域中心到敌人的直线距离；区域火力来自新鲜但有限的原生候选采样，remote_targets仅为远端粗采样，不证明整区可用、路线可达、枪口无遮挡或必然命中。unknown不代表不能走或不能打；同目标/同区只记录分工重叠，不判断战术优劣。',units=result)
