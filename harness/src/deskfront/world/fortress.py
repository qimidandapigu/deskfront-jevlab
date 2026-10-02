"""One authored rescue objective layered over a connected region graph."""
import copy
import json
import math
from pathlib import Path

RECIPE = json.loads(Path(__file__).with_name('fortress.json').read_text(encoding='utf-8'))
SLOT_X=(1.32,1.38,1.26,1.44,1.50,1.56,1.62,1.68,1.18,1.12,1.06,1.22,1.0,.94,.88)
SLOT_DZ=(0,-.1,.1,-.2,.2,-.3,.3,-.4,.4,-.5,.5,-.6,.6,
         -.05,.05,-.15,.15,-.25,.25,-.35,.35,-.45,.45,-.55,.55)


def outside_slots(covers,row_z,reachable=None):
    """Place the six perimeter guards in actual free space around the fort."""
    if reachable is not None:
        from .region_graph import nav_index
    separation=.1501 if reachable is not None else .15
    toward_center=1 if row_z<0 else -1
    desired=( (1.32,0),(1.33,-.205),(1.33,.205),
              (1.45,toward_center*.42),(1.55,toward_center*.20),
              (1.65,-toward_center*.20)) if row_z else tuple((r[0],r[1]) for r in RECIPE['defender_slots'])
    chosen=[]
    for index,(tx,tdz) in enumerate(desired):
        best=None;best_score=float('inf')
        for x in SLOT_X:
            for dz in SLOT_DZ:
                z=round(row_z+dz,3)
                if not (.08<=x<=1.72 and -.98<=z<=.98):continue
                if reachable is not None:
                    if nav_index([x,z]) not in reachable:continue
                # High-x interior is reserved for the captive, not a guard.
                if x>1.42 and abs(dz)<.35:continue
                if any(abs(x-a[0])<a[2]/2+.053 and abs(z-a[1])<a[3]/2+.053 for a in covers):continue
                if any(math.hypot(x-a[0],z-a[1])<separation for a in chosen):continue
                score=(x-tx)**2+(dz-tdz)**2
                if score<best_score-1e-9:best=[x,z,*RECIPE['defender_slots'][index][2:]];best_score=score
        if best is None:raise ValueError('insufficient_rescue_guard_slots')
        chosen.append(best)
    return chosen


def apply(spec, enemy_count=3):
    if not 1 <= enemy_count <= len(RECIPE['defender_slots']):
        raise ValueError('invalid_fortress_force')
    if spec.get('assembly_kind')=='region_graph_v1':
        exit_cell=spec['design_card']['exit_cell']
        anchors=[op['cell'] for op in spec['build_operations']
            if op.get('op')=='place_region' and op.get('module')=='fortress_base']
        if anchors!=[exit_cell]:raise ValueError('missing_rescue_fortress_base')
    built = copy.deepcopy(spec)
    row_z=spec['exit'][1]
    built['name'] = RECIPE['name']
    built['intent'] = RECIPE['intent']
    covers=copy.deepcopy(RECIPE['covers'])
    for cover in covers:cover[1]=round(cover[1]+row_z,3)
    built['covers'] += covers
    reachable=None
    if built['design_card'].get('navigation')=='geometry_grid_v1':
        from .region_graph import clear_grid,grid_reachable,nav_index
        reachable=grid_reachable(clear_grid(tuple(tuple(row) for row in built['covers'])),nav_index(built['entry']))
    built['defender_slots'] = outside_slots(built['covers'],row_z,reachable)
    built['defenders'] = built['defender_slots'][:enemy_count]
    built['exit'] = [RECIPE['exit'][0],row_z]
    built['rescue'] = {'captive': [RECIPE['captive'][0],row_z], 'status': 'waiting'}
    built['design_card']['mission_kind'] = 'rescue'
    if built['design_card'].get('navigation')=='geometry_grid_v1':
        from .region_graph import refresh_geometry_navigation
        refresh_geometry_navigation(built,built['exit'])
    return built
