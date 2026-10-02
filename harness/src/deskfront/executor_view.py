"""Single-unit decision brief. Action criteria remain the candidate evidence source."""
import copy
from context_views import pick


TASK_FIELDS=('actor_id','command','target_id','support_for','partner','start_when','wait_timeout_s',
    'on_failure','assignment','complete_when','replan_when','region_hint','region_id','region_path',
    'wait_region_id','phase','selected_destination')


def build(state, questions):
    # Work on a copy: native commands and validation/receipt payloads are untouched.
    out=copy.deepcopy(state)
    controlled=set(out.get('controlled_unit_ids',[]))
    for u in out.get('units',[]):
        if u['id'] in controlled:continue
        compact=pick(u,('id','faction','kind','weapon','hp','max_hp','position','goal','suppression',
            'ammo','reload_remaining','weapon_range','last_shot_at','last_shot_target','locomotion','posture'))
        compact['combat']=pick(u.get('combat',{}),('path_active','engageable_targets','incoming_threats'))
        u.clear();u.update(compact)
    plan=out.get('plan',{}).get('plan',{})
    out['plan']=pick(plan,('objective','stage','reason'))
    out['teammate_tasks']={uid:pick(t,('command','target_id','support_for','partner','start_when','region_hint','phase'))
        for uid,t in plan.get('tasks',{}).items() if uid not in controlled}
    out['cooperation_board']={uid:pick(row,('target_status','phase','command','partner','actual_target',
        'support_ready','arrival_status','arrival_basis','fire_evidence'))
        for uid,row in out.get('cooperation_board',{}).items()}
    # Own task and teammate board already report these facts.
    out.pop('team_execution',None)
    out.get('rules',{}).pop('execution_policy',None)  # instructions contain it verbatim
    for uid,row in out.get('executors',{}).items():
        row['task']=pick(row.get('task',{}),TASK_FIELDS)
        feedback=row.get('feedback',{})
        feedback['task_execution']=pick(feedback.get('task_execution',{}),('phase','reason','wait_seconds','granted_at'))
        feedback.pop('dynamic_task',None)
        feedback['local_maneuver']=pick(feedback.get('local_maneuver',{}),('reason','target_id','fire_lane_status'))
        # Only strip duplicated candidate reports when real action criteria are
        # supplied. Unknown freshness and current exposure remain explicit.
        if not questions.get(uid,{}).get('criteria'):continue
        spatial=row.get('spatial',{})
        for key in ('remote_firing_positions','remote_firing_search','firing_positions',
                    'withdrawal_positions','shelter_positions','cover_firing_positions'):
            spatial.pop(key,None)
        goals=row.get('region_choices',{})
        row['region_choices']=pick(goals,('query_status','basis'))
        row['region_choices']['evidence_source']='动作选项给出可选区域及区域内落点；JEV选目标区域，游戏引擎负责寻路。精确落点的路径证据不能推广到整个区域；未知不代表安全。'
    return out
