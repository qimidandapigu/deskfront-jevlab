"""Bounded recording from the host's existing spectator sample. No requests."""
import copy
import math

UNIT_KEYS=('id','faction','kind','weapon','position','hp','max_hp','state','suppression',
           'cover_id','target_id','lm_reason','order_mode','tactical_role')

class BattleMapRecorder:
    def __init__(self, record, interval=.5):
        self.record, self.interval = record, interval
        self.last_key, self.last_time = None, None

    def sample(self, current):
        stamp=current.get('time')
        if not isinstance(stamp,(int,float)) or not math.isfinite(stamp):return False
        if not isinstance(current.get('bounds'),list) or not isinstance(current.get('units'),list):return False
        mission=current.get('world_growth',{}).get('mission',{})
        key=(current.get('run_id'),mission.get('index'),current.get('navigation_revision'),current.get('map_index'))
        if not key[0]:return False
        if key==self.last_key and self.last_time is not None and stamp-self.last_time<self.interval:return False
        snapshot={k:copy.deepcopy(current[k]) for k in ('run_id','map_index','tick','time','bounds','covers',
                  'navigation_revision','remaining_routes','debug_visualize') if k in current}
        if 'remaining_routes' in snapshot:snapshot.pop('debug_visualize',None)
        elif 'debug_visualize' in snapshot:
            value=snapshot['debug_visualize']
            value['units']=[{k:v for k,v in row.items() if k!='trail'} for row in value.get('units',[])]
        snapshot['world_growth']={'mission':{k:mission[k] for k in ('index','status') if k in mission}}
        objective=current.get('objective')
        if isinstance(objective,dict):snapshot['objective']={'position':copy.deepcopy(objective.get('position'))}
        elif isinstance(objective,list):snapshot['objective']=copy.deepcopy(objective)
        snapshot['units']=[{k:copy.deepcopy(u[k]) for k in UNIT_KEYS if k in u} for u in current['units']]
        self.record({'type':'battle-map-snapshot','schema':'deskfront-battle-map/v1',
                     'game_time':stamp,'run_id':key[0],'snapshot':snapshot})
        self.last_key,self.last_time=key,stamp
        return True
