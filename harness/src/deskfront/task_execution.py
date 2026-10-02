"""Observe per-unit task dependencies; never invent a teammate's covering fire."""
import math

def evaluate(task, unit, state, tasks, previous, support_ready):
    now=state['time']
    # A fresh approved plan may reassess an unchanged assignment. In contrast,
    # repeated ticks of one plan must not revive a timed-out dependency.
    signature=repr(dict({k:task.get(k) for k in ('command','route','region_id','region_path','stage_id','task_revision','approval_revision','wait_region_id','target_id','partner','start_when','wait_timeout_s','on_failure')},
                        completion=(task.get('complete_when',{}).get('type'),task.get('complete_when',{}).get('value'))))
    row=dict(previous) if previous.get('signature')==signature else dict(signature=signature,since=now)
    partner=next((v for v in state['units'] if v['id']==task.get('partner') and v['hp']>0),None)
    condition=task.get('start_when','immediate')
    # Region-route progress bounds a fire permission just as legacy waypoints do.
    # Do not include this cursor in the signature: moving one step is not a new plan.
    stage=task.get('region_cursor',task.get('waypoint',0))
    if unit.get('order_mode')=='self_preserve':
        row.update(phase='reassess',reason='native_survival_override',on_failure='withdraw')
        return row
    if row.get('phase')=='reassess':return row
    if condition=='immediate' and row.get('phase')=='executing':
        # Permission is not re-issued every frame; retain the real start time.
        row.update(reason='immediate_task_active',wait_seconds=0)
        return row
    # Preparation has a separate bounded clock; it is not a firing failure.
    if condition!='immediate' and partner and partner.get('combat',{}).get('path_active') and row.get('phase')!='executing':
        started=row.setdefault('preparing_since',now)
        if now-started<12:
            row.update(phase='preparing',reason='partner_en_route',since=now,wait_seconds=round(now-started,1),on_failure=task.get('on_failure','reassess'))
            return row
    if condition!='immediate' and row.get('phase')=='executing' and partner:
        danger=unit['hp']<row.get('grant_hp',unit['hp'])*.85 or unit.get('suppression',0)>row.get('grant_pressure',0)+.25
        if danger:
            row.update(phase='reassess',reason='advance_risk_increased',on_failure=task.get('on_failure','reassess'))
            return row
        if task.get('command')=='occupy' and now-row.get('granted_at',now)>=3:
            origin=row.get('grant_position',unit['position'])
            advanced=math.dist(unit['position'],origin)>=.04
            flag=state.get('objective',{}).get('flag',{})
            scoring=flag.get('owner')==unit.get('faction') and flag.get('held_seconds',0)>row.get('grant_flag_seconds',0)
            if not advanced and not scoring:
                row.update(phase='reassess',reason='granted_without_progress',on_failure=task.get('on_failure','reassess'))
                return row
        if row.get('stage')==stage and now-row.get('granted_at',now)<8:
            row.update(reason='stage_permission_retained',wait_seconds=0)
            return row
        row.update(phase='waiting',since=now)
    ready=condition=='immediate'
    if condition=='partner_firing' and partner:
        ready=support_ready(partner,now)
        if task.get('target_id'):ready=ready and partner.get('last_shot_target')==task['target_id']
    if condition=='partner_arrived' and partner:
        goal=task.get('wait_position') or tasks.get(partner['id'],{}).get('complete_when',{}).get('position')
        ready=bool(goal and math.dist(partner['position'],goal)<=task.get('wait_radius',tasks.get(partner['id'],{}).get('complete_when',{}).get('radius',.15)) and not partner.get('combat',{}).get('path_active'))
        if task.get('wait_area'):
            from strategic_regions import contains
            ready=contains(partner['position'],task['wait_area']) and not partner.get('combat',{}).get('path_active')
    if ready:
        row.update(phase='executing',reason='start_condition_observed',since=now,granted_at=now,stage=stage,grant_hp=unit['hp'],grant_pressure=unit.get('suppression',0),grant_position=list(unit['position']),grant_flag_seconds=state.get('objective',{}).get('flag',{}).get('held_seconds',0))
    elif row.get('phase')=='executing':
        row.update(phase='blocked',reason='support_lost',since=now)
    elif not partner and condition!='immediate':row.update(phase='blocked',reason='partner_unavailable')
    elif now-row['since']>=task.get('wait_timeout_s',5):row.update(phase='reassess',reason='dependency_timeout')
    elif row.get('phase')!='blocked':row.update(phase='waiting',reason=condition)
    row.update(on_failure=task.get('on_failure','reassess'),wait_seconds=round(now-row['since'],1))
    return row

def constrain(options,status):
    if status.get('phase') not in ('preparing','waiting','blocked','reassess'):return
    # Hold only the dependent advance; retain shooting, protection and local repositioning.
    for key in ('task_waypoint','assigned_position','stage_approach','contest_flag'):
        options.pop(key,None)
    for key in ('continue_task','halt'):
        if key in options:options[key]['description']+='；协作条件未成立，应建立射界/集结/自保；超时须重选，不能当成已有掩护'
