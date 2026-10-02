"""Facts about whether fresh region-route options continue an earlier choice.

The caller owns the decision. This module does not choose a route, extend a
task lease, or turn a remembered path into a movement command.
"""
import math


def _valid_time(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def _route(value):
    if not isinstance(value,dict):return None
    goal=value.get('goal_region');path=value.get('region_path')
    if not isinstance(goal,str) or not goal or not isinstance(path,(list,tuple)) or not 1<=len(path)<=64:
        return None
    if any(not isinstance(region,str) or not region for region in path) or len(set(path))!=len(path):
        return None
    if path[-1]!=goal:return None
    return goal,tuple(path)


def remember(choice, now, task_revision):
    """Copy a JEV-selected route identity for comparison on a later observation."""
    route=_route(choice)
    if route is None:raise ValueError('invalid_region_route_choice')
    if not _valid_time(now):raise ValueError('invalid_route_choice_time')
    goal,path=route
    return dict(goal_region=goal,region_path=list(path),selected_at=now,
                task_revision=task_revision)


def _relation(previous, candidate):
    old_goal,old_path=previous;goal,path=candidate
    if goal!=old_goal:return 'goal_changed'
    if path==old_path:return 'same'
    if len(path)<len(old_path) and old_path[-len(path):]==path:return 'forward'
    if len(path)>len(old_path) and path[-len(old_path):]==old_path:return 'backtrack'
    return 'different_route'


def _blocked(option):
    step=option.get('first_step',{})
    if not isinstance(step,dict):return False
    risk=step.get('risk',{})
    return step.get('status') in ('blocked','too_close') or (isinstance(risk,dict) and risk.get('status')=='unreachable')


def assess(previous, options, now):
    """Annotate every option; report route continuity without choosing one.

    Proper suffix means forward progress: A,B,C -> B,C. A longer path that
    ends in the previous path means backtracking: B,C -> A,B,C. A turn onto a
    different branch is neither continuation nor necessarily a mistake.
    ``first_step_blocked`` is only the tool's current observation; the game
    still validates any eventual command. The saved task revision is surfaced
    unchanged so the caller can compare it with the current approved task.
    """
    candidates=options if isinstance(options,list) else []
    old=_route(previous)
    stamp=previous.get('selected_at') if isinstance(previous,dict) else None
    if previous is None:base='unselected'
    elif old is None or not _valid_time(stamp):base='invalid_previous'
    elif not _valid_time(now):base='invalid_now'
    elif now<stamp:base='clock_reset'
    else:base=None
    annotations=[];matching=[];available=[];backtracks=[];same_goal=[]
    for index,raw in enumerate(candidates):
        value=dict(raw) if isinstance(raw,dict) else {'invalid_option':True}
        route=_route(raw)
        relation=('invalid' if route is None else 'new' if base is not None
                  else _relation(old,route))
        blocked=_blocked(raw) if isinstance(raw,dict) else False
        value['continuation']=relation
        value['first_step_blocked']=blocked
        annotations.append(value)
        if relation in ('same','forward'):
            matching.append(index)
            if not blocked:available.append(index)
        if relation=='backtrack':backtracks.append(index)
        if route is not None and old is not None and route[0]==old[0]:same_goal.append(index)
    if base is not None:status=base
    elif any(annotations[i]['continuation']=='forward' for i in available):status='forward_available'
    elif available:status='continuation_available'
    elif matching:status='continuation_blocked'
    elif backtracks:status='backtrack_detected'
    elif same_goal:status='route_missing'
    elif any(_route(raw) is not None for raw in candidates):status='goal_missing'
    else:status='candidates_invalid'
    result=dict(status=status,options=annotations,matching_indices=matching,
                available_continuation_indices=available,backtrack_indices=backtracks)
    if base is None:
        result['age_s']=round(now-stamp,2)
        result['task_revision']=previous.get('task_revision')
    return result
