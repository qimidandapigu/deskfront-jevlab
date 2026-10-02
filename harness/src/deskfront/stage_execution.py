"""Current-stage evidence and short native-topology approach proposals."""
import math
from collections import deque

def approach(position,area,topology,max_distance=.25):
    from strategic_regions import contains
    cells=topology.get('cells',{})
    if not cells or contains(position,area):return None
    start=min(cells,key=lambda k:math.dist(position,cells[k]))
    if math.dist(position,cells[start])>.12:return None
    goals={k for k,p in cells.items() if contains(p,area)}
    adj={k:[] for k in cells}
    for a,b in topology.get('edges',[]):adj[a].append(b);adj[b].append(a)
    todo=deque([start]);parents={start:None};end=None
    while todo:
        k=todo.popleft()
        if k in goals:end=k;break
        for n in adj[k]:
            if n not in parents:parents[n]=k;todo.append(n)
    if end is None:return None
    path=[]
    while end is not None:path.append(cells[end]);end=parents[end]
    path.reverse();distance=math.dist(position,path[0]);selected=None
    for a,b in zip(path,path[1:]):
        distance+=math.dist(a,b)
        if distance>max_distance:break
        selected=b
    return selected

def status(tasks,feedback):
    done=[uid for uid in tasks if feedback.get(uid,{}).get('task_progress',{}).get('achieved')]
    blocked=[uid for uid in tasks if feedback.get(uid,{}).get('task_execution',{}).get('phase') in ('blocked','reassess') or feedback.get(uid,{}).get('stage_blocker')]
    return dict(phase='completed' if tasks and len(done)==len(tasks) else 'blocked' if blocked else 'executing',completed_units=done,blocked_units=blocked,transition='request_commander_review; never automatically execute future intent')


def segment_candidates(options,position,topology):
    blocked=[]
    for key in list(options):
        item=options[key];cmd=item['command']
        if cmd.get('action')!='move' or cmd.get('intent')=='survive' or math.dist(position,cmd['position'])<=.3:continue
        destination=list(item.get('destination',cmd['position']))
        step=approach(position,dict(center=destination,radius=.06),topology)
        if step is None:
            blocked.append(key);options.pop(key);continue
        item['command']=dict(cmd,position=step)
        item['destination']=destination
        # The destination forecast describes the original full path. The next
        # annotate pass must independently query/match the actual short step.
        if item.get('path_risk'):
            item['final_destination_risk']=dict(item.pop('path_risk'),scope='final_destination_scope')
        item['description']+='；分段执行：本次仅到'+str(step)+'，最终射位'+str(destination)+'；到达短步不代表已获得最终射界，后续重新检查'
    return blocked

def fire_status(unit,enemies,now):
    combat=unit.get('combat',{});check=combat.get('fire_check',{});out=[]
    for enemy in enemies:
        if enemy['hp']<=0:continue
        distance=math.dist(unit['position'],enemy['position'])
        if distance>unit.get('weapon_range',0):reason='out_of_range'
        elif check.get('target_id')==enemy['id'] and check.get('status')=='blocked' and 0<=now-check.get('time',-10)<=3:reason=check.get('reason','blocked')
        elif unit.get('reload_remaining',0)>0 or unit.get('ammo',0)<=0:reason='reloading'
        elif enemy['id'] in combat.get('engageable_targets',[]):reason='candidate_requires_muzzle_validation'
        else:reason='no_confirmed_fire_lane'
        out.append(dict(target=enemy['id'],distance=round(distance,3),range=unit.get('weapon_range'),status=reason))
    return out
