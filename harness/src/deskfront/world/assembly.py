"""Bounded spatial editing tools. Choices compile into actual engine geometry.

The builder chooses each floor/cover/deployment module independently. No raw
model coordinates or executable code cross the engine boundary.
"""
import copy
import math
from collections import deque
from functools import lru_cache

from .catalog import CATALOG


def supported(floors, x, z, hx=0, hz=0):
    xs = sorted({x-hx, x+hx} | {v for r in floors for v in (r[0], r[2]) if x-hx < v < x+hx})
    zs = sorted({z-hz, z+hz} | {v for r in floors for v in (r[1], r[3]) if z-hz < v < z+hz})
    probes = [(x, z)] if not hx and not hz else [((a+b)/2, (c+d)/2)
        for a,b in zip(xs,xs[1:]) for c,d in zip(zs,zs[1:])]
    return all(any(r[0]-1e-8 <= a <= r[2]+1e-8 and r[1]-1e-8 <= b <= r[3]+1e-8 for r in floors) for a,b in probes)


def validate(spec):
    floors, covers = spec['floors'], spec['covers']
    for i,a in enumerate(covers):
        if not supported(floors,a[0],a[1],a[2]/2,a[3]/2):
            return dict(ok=False,reason='unsupported_component',slot=f'cover_{i}')
        for j,b in enumerate(covers[:i]):
            if abs(a[0]-b[0]) < (a[2]+b[2])/2 and abs(a[1]-b[1]) < (a[3]+b[3])/2:
                return dict(ok=False,reason='overlapping_components',slots=[f'cover_{j}',f'cover_{i}'])
    points = [spec['entry'],spec['exit']]+spec['flank']+spec['support']+spec['defender_slots']+spec.get('friendlies',[])
    if spec.get('rescue'):points.append(spec['rescue']['captive'])
    cell=.025
    def index(p): return (int(math.floor(p[0]/cell+.5)),int(math.floor((p[1]+1.15)/cell+.5)))
    def walkable(i,j):
        x,z=i*cell,j*cell-1.15
        return (0 <= i <= 72 and 0 <= j <= 92 and supported(floors,x,z)
            and not any(abs(x-a[0]) < a[2]/2+.04 and abs(z-a[1]) < a[3]/2+.04 for a in covers))
    ids=[]
    for p in points:
        q=index(p)
        if not supported(floors,p[0],p[1],.034,.034) or not walkable(*q):
            return dict(ok=False,reason='blocked_route_or_deployment',point=p[:2])
        ids.append(q)
    visited={ids[0]}; queue=deque(visited)
    while queue:
        x,z=queue.popleft()
        for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
            q=x+dx,z+dz
            if q not in visited and walkable(*q):visited.add(q);queue.append(q)
    if any(q not in visited for q in ids):return dict(ok=False,reason='isolated_deployment_or_route')
    slots=spec['defender_slots']
    # Millimetre-authored coordinates can represent exactly 15 cm as
    # .14999999999999997. Ignore arithmetic noise, not real overlaps.
    if any(math.hypot(a[0]-b[0],a[1]-b[1]) < .15-1e-8 for i,a in enumerate(slots) for b in slots[:i]):
        return dict(ok=False,reason='overlapping_deployments')
    return dict(ok=True,reachable_points=len(ids),walkable_cells=len(visited),
        limitation='connectivity only; firing advantage requires native queries/playtest')


@lru_cache(maxsize=128)
def tools_for(option):
    """Finite module library, also exported to Godot for independent replay."""
    base=CATALOG[option]
    slots={}
    for i,row in enumerate(base['floors']):
        slots[f'floor_{i}']={'original':dict(op='place_floor',value=row,label='原始地块')}
        for name,delta in [('widen',.08),('wide',.16)]:
            value=[row[0],round(max(-1.1,row[1]-delta),3),row[2],round(min(1.1,row[3]+delta),3)]
            slots[f'floor_{i}'][name]=dict(op='place_floor',value=value,label=f'横向扩宽 {delta*2:.2f} 米')
    for i,row in enumerate(base['covers']):
        menu={'original':dict(op='place_cover',value=row,label='原始组件与槽位')}
        variants=[]
        for name,dx,dz in [('forward',.06,0),('back',-.06,0),('north',0,-.06),('south',0,.06)]:
            a=list(row);a[0]=round(a[0]+dx,3);a[1]=round(a[1]+dz,3);variants.append((name,a,'平移至相邻槽'))
        a=list(row);a[2],a[3]=a[3],a[2];variants.append(('rotate',a,'旋转90度'))
        if row[4] != 'sandbag':
            a=list(row);a[4]='crate' if row[4]=='bookstack' else 'bookstack';a[5]=.12 if a[4]=='crate' else .22
            variants.append(('replace',a,'替换为'+a[4]))
        # Full combined placement is checked after selection. Individual pruning
        # is cheap and conservative; it must not claim combat effectiveness.
        for name,a,label in variants:
            protected=[base['entry'],base['exit']]+base['flank']+base['support']+base['defender_slots']+[[.12,-.28],[.12,.28]]
            clear_points=not any(abs(p[0]-a[0])<a[2]/2+.055 and abs(p[1]-a[1])<a[3]/2+.055 for p in protected)
            clear_covers=not any(j!=i and abs(b[0]-a[0])<(b[2]+a[2])/2 and abs(b[1]-a[1])<(b[3]+a[3])/2 for j,b in enumerate(base['covers']))
            if clear_points and clear_covers and supported(base['floors'],a[0],a[1],a[2]/2,a[3]/2):
                menu[name]=dict(op='place_cover',value=a,label=label)
        slots[f'cover_{i}']=menu
    units=copy.deepcopy(base['defender_slots'])
    slots['deployment']={'original':dict(op='deploy',value=units,label='原阵地顺序与兵种')}
    reverse=copy.deepcopy(units);reverse[0],reverse[1]=reverse[1],reverse[0]
    slots['deployment']['rear_first']=dict(op='deploy',value=reverse,label='后卫优先部署；人数不足时优先后层')
    rifles=copy.deepcopy(units)
    for row in rifles:row[2]='rifle'
    slots['deployment']['rifles']=dict(op='deploy',value=rifles,label='同位置全步枪编成')
    return slots


def compile_operations(option, operations):
    library=tools_for(option)
    if not isinstance(operations,list) or len(operations)!=len(library):raise ValueError('incomplete_build_operations')
    selected={}
    for operation in operations:
        if not isinstance(operation,dict):raise ValueError('invalid_build_operation')
        slot=operation.get('slot');module=operation.get('module')
        if not isinstance(slot,str) or not isinstance(module,str) or slot not in library or module not in library[slot] or slot in selected:
            raise ValueError('invalid_build_module_or_duplicate_slot')
        part=library[slot][module]
        if operation.get('op')!=part['op']:raise ValueError('invalid_build_operation_type')
        selected[slot]=part
    spec=copy.deepcopy(CATALOG[option]);spec['floors']=[];spec['covers']=[]
    for slot in library:
        part=selected[slot]
        if part['op']=='place_floor':spec['floors'].append(copy.deepcopy(part['value']))
        elif part['op']=='place_cover':spec['covers'].append(copy.deepcopy(part['value']))
        else:spec['defender_slots']=copy.deepcopy(part['value'])
    spec['defenders']=spec['defender_slots'][:3]
    spec['build_operations']=copy.deepcopy(operations)
    return spec
