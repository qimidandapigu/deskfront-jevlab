"""Observed flag-clock and movement facts for models, without an action rule."""
import math


def _number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def _distance(a,b):
    if not isinstance(a,(list,tuple)) or not isinstance(b,(list,tuple)) or len(a)!=2 or len(b)!=2:
        return None
    if not all(_number(v) for v in [*a,*b]):return None
    return math.dist(a,b)


def build(state, units, feedback, spatial_by_unit):
    objective=state.get('objective',{})
    position=objective.get('position')
    radius=objective.get('radius',0)
    if not _number(radius) or radius<0:radius=0
    flag=objective.get('flag',{}) or {}
    now=state.get('time')
    remaining=flag.get('remaining_seconds')
    remaining=remaining if _number(remaining) and remaining>=0 else None
    result={}
    for unit in units:
        uid=unit.get('id')
        if not isinstance(uid,str) or unit.get('hp',0)<=0:continue
        distance=_distance(unit.get('position'),position)
        circle_gap=max(0,distance-radius) if distance is not None else None
        history=feedback.get(uid,{}).get('recent_positions',[])
        previous=next((row for row in history if _number(row.get('time')) and _number(now)
                       and 3<=now-row['time']<=12 and _distance(row.get('position'),position) is not None),None)
        earlier=_distance(previous['position'],position) if previous else None
        progress=earlier-distance if earlier is not None and distance is not None else None
        spatial=spatial_by_unit.get(uid,{}) or {}
        path=spatial.get('objective_path_risk',{})
        center_eta=(path.get('travel_s') if path.get('status')=='sampled' and
                    _number(path.get('travel_s')) and path['travel_s']>=0 else None)
        shot_age=feedback.get(uid,{}).get('no_shot_seconds')
        result[uid]=dict(distance_to_flag_circle=round(circle_gap,2) if circle_gap is not None else None,
                         flag_owner=flag.get('owner'),flag_contested=flag.get('contested'),
                         enemy_hold_remaining_s=round(remaining,1) if remaining is not None and
                                                 flag.get('owner')!=unit.get('faction') else None,
                         path_to_flag_center=dict(status=path.get('status','unknown'),
                                                  travel_s=round(center_eta,1) if center_eta is not None else None,
                                                  exposed_s=round(path['exposed_s'],1) if _number(path.get('exposed_s')) else None),
                         center_eta_minus_remaining_s=round(center_eta-remaining,1) if center_eta is not None and
                                                      remaining is not None and flag.get('owner')!=unit.get('faction') else None,
                         net_flag_progress=round(progress,2) if progress is not None else None,
                         progress_window_s=round(now-previous['time'],1) if previous else None,
                         no_shot_s=shot_age if _number(shot_age) else None)
    return dict(basis='旗圈距离与过去位移是观测值；到旗中心时间来自当前原生路径抽样，和倒计时之差仅供比较，不代表必胜或必败；未知路径不等于不可达。',
                time=now,units=result)
