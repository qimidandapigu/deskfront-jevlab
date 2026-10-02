"""Read-only task facts; never manufacture firing or choose a model action."""
import math
from cover_evidence import cover_phase, recent_support

def route_step(task,routes):
    points=routes.get(task.get('route'),{}).get('points',[])
    end=task.get('complete_when',{}).get('position')
    limit=len(points)
    if end and points:limit=min(range(len(points)),key=lambda i:math.dist(points[i],end))+1
    index=task.get('waypoint',0)
    return points[index] if index<limit else None

def board(state,tasks,routes):
    from strategic_regions import catalog,memberships
    regions=catalog(routes,state)
    result={}
    for u in state.get('units',[]):
        if u['id'] not in tasks:continue
        task=tasks[u['id']];combat=u.get('combat',{});check=combat.get('fire_check') or {}
        now=state['time']
        target=task.get('target_id')
        blocked=(check.get('status')=='blocked' and
                 (not target or check.get('target_id')==target) and
                 isinstance(check.get('time'),(int,float)) and
                 0<=now-check['time']<3)
        native_targets=combat.get('engageable_targets')
        targets=native_targets if isinstance(native_targets,list) else []
        enemy=next((v for v in state['units'] if v['id']==target),None)
        phase_at_cover=cover_phase(u)
        target_status='none' if not target else 'missing' if enemy is None else 'dead' if enemy['hp']<=0 else 'engageable' if target in targets else 'temporarily_hidden' if phase_at_cover=='hiding' else 'out_of_fire_lane'
        lane=bool(target in targets if target else targets) and not blocked
        ready=recent_support(u,now,target)
        observed_regions=memberships(u['position'],regions)
        assigned_region=task.get('region_id')
        if assigned_region in regions:
            arrival='inside_assigned_region' if assigned_region in observed_regions else 'outside_assigned_region'
            arrival_observed=assigned_region in observed_regions
            arrival_basis='region_membership_only_not_firing_position'
        else:
            destination=task.get('complete_when',{}).get('position')
            radius=task.get('complete_when',{}).get('radius',.1)
            if (isinstance(destination,(list,tuple)) and len(destination)==2 and
                    isinstance(radius,(int,float)) and radius>=0):
                arrival_observed=math.dist(u['position'],destination)<=radius
                arrival='inside_assigned_position' if arrival_observed else 'outside_assigned_position'
                arrival_basis='position_radius_only_not_firing_lane'
            else:
                arrival='no_arrival_reference';arrival_observed=None
                arrival_basis='unknown'
        shot_at=u.get('last_shot_at')
        shot_age=(now-shot_at if isinstance(shot_at,(int,float)) else None)
        matching_shot=(shot_age is not None and shot_age>=0 and
                       (not target or u.get('last_shot_target')==target))
        observed_shot=matching_shot and shot_age<2.3
        if u['hp']<=0:interruption='unit_dead'
        elif u.get('order_mode')=='self_preserve':interruption='native_survival_override'
        elif blocked:interruption='recent_muzzle_block'
        elif u.get('reload_remaining',0)>0 or u.get('weapon_state')=='reload':interruption='reloading'
        elif u.get('ammo',0)<=0:interruption='empty_magazine'
        elif u.get('suppression',0)>=.95:interruption='heavy_suppression'
        elif u.get('weapon_state')=='cooldown':interruption='weapon_cooldown'
        elif phase_at_cover=='hiding':interruption='native_cover_hide'
        elif combat.get('path_active') and phase_at_cover=='none':interruption='moving_without_cover'
        else:interruption=None
        if ready:interruption=None
        if u['hp']<=0:phase='dead'
        elif u.get('order_mode')=='self_preserve':phase='interrupted'
        elif ready:phase='supporting'
        elif interruption in ('reloading','empty_magazine','weapon_cooldown'):phase='reloading'
        elif phase_at_cover=='hiding':phase='cover_hiding'
        elif phase_at_cover=='peeking':phase='cover_peeking'
        elif combat.get('path_active'):phase='moving'
        elif task.get('command')=='support' and not lane:phase='seeking_fire_lane'
        else:phase='positioned'
        fire_evidence=dict(
            assigned_target=target or None,
            native_lane='recent_muzzle_block' if blocked else
                        'unknown' if not isinstance(native_targets,list) else
                        'candidate_requires_muzzle_check' if lane else
                        'temporarily_hidden' if phase_at_cover=='hiding' else
                        'not_in_native_candidates',
            recent_assigned_shot=bool(observed_shot),
            last_assigned_shot_at=shot_at if matching_shot else None,
            assigned_shot_age_s=round(shot_age,2) if matching_shot else None,
            current_support=ready,
            interruption=interruption,
            cover_phase=phase_at_cover)
        result[u['id']]=dict(target_status=target_status,target_position=enemy.get('position') if enemy else None,navigation_revision=state.get('navigation_revision'),regions=observed_regions,destination_region=assigned_region,wait_region=task.get('wait_region_id'),time=now,phase=phase,command=task.get('command'),partner=task.get('partner'),next_waypoint=route_step(task,routes),actual_target=u.get('last_shot_target'),fire_lane=lane,support_ready=ready,cover_phase=phase_at_cover,block_reason=check.get('reason') if blocked else None,hp=u['hp'],arrival_status=arrival,arrival_observed=arrival_observed,arrival_basis=arrival_basis,fire_evidence=fire_evidence)
    return result
