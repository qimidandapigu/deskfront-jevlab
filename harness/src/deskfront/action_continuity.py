"""Keep effective native movement/position; never disguise a stalled route as success."""
import math

def keep_move(unit, decision, feedback):
    if decision.get('action')!='move' or len(decision.get('position',[]))!=2:return False
    p=decision['position'];combat=unit.get('combat',{})
    if feedback.get('path_stalled') or feedback.get('interrupt'):return False
    if combat.get('path_active'):
        return math.dist(unit.get('goal',unit['position']),p)<.055 and feedback.get('no_movement_seconds',0)<3
    return math.dist(unit['position'],p)<.055
