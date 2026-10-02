"""Composable region graph. The builder owns occupancy and actual connections.

Continuous ground; visible solid buildings and walls define selected routes.
No fixed layout from the old catalog is copied into this geometry.
"""
import copy
import math
from collections import deque
from functools import lru_cache
from .assembly import validate
from .authored_cards import AUTHORED_CARDS, BASE_CARDS, WORKBENCH_CARDS, CURATED_CARDS, current_dimensions

CELLS={f'c{x}r{z}':(x,z) for x in range(3) for z in range(3)}
ENTRY='c0r1'
EXIT='c2r1'
KINDS={'open':'基础双侧掩护区','books':'书堆交错掩护区','crates':'笔袋与书本掩护区','sandbags':'橡皮与文件架支援区','empty':'档案纸盒占地区','fortress_base':'救援文件堡垒基底'}
WORKSHOP_STYLE_COUNT=8
WORKSHOP_CARD_IDS=(
    'divider_mouse_corner','printer_coffee_station','tissues_cup_ruler',
    'biography_laptop_desk','cardbox_file_rack','pencil_pouch_tape',
    'citybook_tissues_phone','atlas_ruler_calculator',
)
LEGACY_SELECTABLE_MODULES=(
    'open','books','crates','sandbags','empty',
    *(f'{family}_{turn}' for family in ('advance','screen','defense','flank',
                                       'depot_advance','depot_screen','depot_defense','depot_flank')
      for turn in range(4)),
    *WORKSHOP_CARD_IDS,
)
SELECTABLE_MODULES=tuple(CURATED_CARDS)
assert len(SELECTABLE_MODULES)==26
REINFORCEMENT_OFFSETS=(
    (-.18,-.20),(.18,-.20),(-.18,.20),(.18,.20),(0,-.28),(0,.28),
    (-.11,-.29),(.11,-.29),(-.11,.29),(.11,.29),(-.15,0),(.15,0),
    (-.21,0),(.21,0),(-.22,.10),(.22,.10),(-.22,-.10),(.22,-.10),
)

# Shared with Godot through world-regions.json. The model chooses the asset and
# position; dimensions and collision height are authoritative game data.
PROP_LABELS={
    'concrete':'立式文件夹', 'drum':'胶棒',
    'bookstack':'横放书堆', 'book_city':'城市书', 'book_atlas':'地图册',
    'novel':'传记书', 'warehouse':'档案纸盒', 'crate':'笔袋',
    'desk_divider':'桌面隔板', 'printer':'打印机', 'laptop':'笔记本电脑',
    'tissues':'抽纸', 'mug':'水杯', 'mouse':'鼠标', 'ruler':'尺子',
    'file_rack':'文件架', 'stapler':'订书器', 'tape':'胶带',
    'phone':'手机', 'calculator':'计算器', 'pipe':'一束铅笔',
    'gabion':'卡片盒', 'sandbag':'橡皮掩体',
}
# A model-added or replaced item must have the same physical size as that
# stationery kind in an authored card. Older saved cards keep their recorded
# cover rows; only new edit operations read this table.
PROPS={asset:{'label':label} for asset,label in PROP_LABELS.items()}
for _asset, _prop in PROPS.items():
    _prop['width'], _prop['depth'], _prop['height'] = current_dimensions(_asset)
MAX_PROPS=12

# Same collision clearance and grid as assembly.validate / native world_choke.
NAV_STEP=.025
NAV_CLEARANCE=.0401  # Avoid float-boundary disagreement with the native .04 test.
NAV_DIRECTIONS=((1,0),(-1,0),(0,1),(0,-1))


def nav_point(node):
    return [round(node[0]*NAV_STEP,3),round(node[1]*NAV_STEP-1.15,3)]


def nav_index(point):
    return (int(math.floor(point[0]/NAV_STEP+.5)),int(math.floor((point[1]+1.15)/NAV_STEP+.5)))


@lru_cache(maxsize=128)
def clear_grid(geometry):
    """Rasterize actual selected geometry, without altering any prop."""
    nodes={(i,j) for i in range(2,71) for j in range(6,87)}
    for x,z,w,d,asset,height in geometry:
        lo_x=math.floor((x-w/2-NAV_CLEARANCE)/NAV_STEP+1e-7)+1
        hi_x=math.ceil((x+w/2+NAV_CLEARANCE)/NAV_STEP-1e-7)
        lo_z=math.floor((z-d/2-NAV_CLEARANCE+1.15)/NAV_STEP+1e-7)+1
        hi_z=math.ceil((z+d/2+NAV_CLEARANCE+1.15)/NAV_STEP-1e-7)
        nodes.difference_update((i,j) for i in range(lo_x,hi_x) for j in range(lo_z,hi_z))
    return frozenset(nodes)


def cell_nodes(nodes,cell,boundary=False):
    x,z=CELLS[cell];margin=0 if boundary else 1
    return {p for p in nodes if x*24+margin<=p[0]<=(x+1)*24-margin
            and 4+z*28+margin<=p[1]<=4+(z+1)*28-margin}


def grid_path(nodes,start,end):
    if start not in nodes or end not in nodes:return []
    queue=deque([start]);previous={start:None}
    while queue:
        node=queue.popleft()
        if node==end:
            result=[]
            while node is not None:result.append(node);node=previous[node]
            return result[::-1]
        for dx,dz in NAV_DIRECTIONS:
            other=(node[0]+dx,node[1]+dz)
            if other in nodes and other not in previous:previous[other]=node;queue.append(other)
    return []


def grid_reachable(nodes,start):
    if start not in nodes:return set()
    queue=deque([start]);seen={start}
    while queue:
        node=queue.popleft()
        for dx,dz in NAV_DIRECTIONS:
            other=node[0]+dx,node[1]+dz
            if other in nodes and other not in seen:seen.add(other);queue.append(other)
    return seen


def largest_component(nodes):
    remaining=set(nodes);largest=set()
    while remaining:
        first=min(remaining);queue=deque([first]);component={first};remaining.remove(first)
        while queue:
            node=queue.popleft()
            for dx,dz in NAV_DIRECTIONS:
                other=node[0]+dx,node[1]+dz
                if other in remaining:remaining.remove(other);component.add(other);queue.append(other)
        if len(component)>len(largest):largest=component
    return largest


def port_component(nodes,cell,neighbours):
    """Use a real interior component serving the selected sides of this desk."""
    remaining=set(nodes);eligible=[];x,z=CELLS[cell]
    required=[]
    for other in neighbours:
        ox,oz=CELLS[other]
        required.append((0,(x+1)*24 if ox>x else x*24) if ox!=x else
                        (1,4+(z+1)*28 if oz>z else 4+z*28))
    while remaining:
        component=largest_component(remaining);remaining-=component
        if all(any(point[axis]==boundary for point in component) for axis,boundary in required):
            eligible.append(component)
    return eligible[0] if eligible else set()


def compact_path(nodes):
    if len(nodes)<3:return [nav_point(p) for p in nodes]
    result=[nodes[0]]
    for a,b,c in zip(nodes,nodes[1:],nodes[2:]):
        if (b[0]-a[0],b[1]-a[1])!=(c[0]-b[0],c[1]-b[1]):result.append(b)
    result.append(nodes[-1])
    return [nav_point(p) for p in result]


def derive_navigation(graph,centers,covers,main,alternate,entry_cell,exit_cell,exit_target=None,strict_cells=None):
    """Resolve clear anchors and real paths through the model's selected edges.

    Current cards connect chosen edges using only those desks. Legacy cards
    retain native whole-map detours through actually open space; neither path
    changes props or removes a closed wall.
    """
    nodes=clear_grid(tuple(tuple(row) for row in covers));components={};anchors={}
    strict_cells=set(graph) if strict_cells is None else strict_cells
    legacy_reachable=largest_component(nodes) if set(graph)-strict_cells else nodes
    for cell in graph:
        component=(port_component(cell_nodes(nodes,cell,True),cell,graph[cell]) if cell in strict_cells
                   else largest_component(cell_nodes(legacy_reachable,cell,True)))
        if not component:raise ValueError('blocked_region_connection:'+cell)
        components[cell]=component;cx,cz=nav_index(centers[cell])
        anchors[cell]=min(component,key=lambda p:((p[0]-cx)**2+(p[1]-cz)**2,p[0],p[1]))
    crossings={}
    for cell in graph:
        for other in graph[cell]:
            if (other,cell) in crossings:crossings[cell,other]=list(reversed(crossings[other,cell]));continue
            corridor=cell_nodes(nodes,cell,True)|cell_nodes(nodes,other,True)
            route=grid_path(corridor,anchors[cell],anchors[other])
            if not route and (cell not in strict_cells or other not in strict_cells):
                route=grid_path(nodes,anchors[cell],anchors[other])
            if not route:raise ValueError('blocked_region_connection:'+cell+'__'+other)
            crossings[cell,other]=route
    endpoints=[];endpoint_ids=[]
    for cell,target in ((entry_cell,[.06,centers[entry_cell][1]]),(exit_cell,exit_target or [1.72,centers[exit_cell][1]])):
        preferred=nav_index(target)
        node=min(components[cell],key=lambda p:((p[0]-preferred[0])**2+(p[1]-preferred[1])**2,p[0],p[1]))
        endpoints.append(target if node==preferred else nav_point(node));endpoint_ids.append(node)
    def stitched(regions):
        route=grid_path(components[entry_cell],endpoint_ids[0],anchors[entry_cell])
        for a,b in zip(regions,regions[1:]):route.extend(crossings[a,b][1:])
        tail=grid_path(components[exit_cell],anchors[exit_cell],endpoint_ids[1])
        if not route or not tail:raise ValueError('blocked_region_endpoint')
        route.extend(tail[1:]);return compact_path(route)
    friendly_slots=[]
    for offset in (-.28,.28):
        target=nav_index([.12,endpoints[0][1]+offset])
        candidates=[node for node in components[entry_cell]
                    if all(math.dist(nav_point(node),point)>=.15 for point in friendly_slots)]
        if not candidates:raise ValueError('insufficient_friendly_slots')
        node=min(candidates,key=lambda p:((p[0]-target[0])**2+(p[1]-target[1])**2,p[0],p[1]))
        friendly_slots.append(nav_point(node))
    return dict(anchors={key:nav_point(value) for key,value in anchors.items()},
        entry=endpoints[0],exit=endpoints[1],main_route=stitched(main),flank=stitched(alternate or main),friendly_slots=friendly_slots,
        walkable_slots=set().union(*components.values()))


def refresh_geometry_navigation(spec,exit_target=None):
    """Recompute routes after an explicit objective recipe adds its geometry."""
    chosen=regions(spec['build_operations']);entry_cell,exit_cell=ports(spec['build_operations'])
    edges=[op['edge'] for op in spec['build_operations'] if op.get('op')=='connect_regions']
    graph=adjacency(chosen,edges)
    centers={cell:LIBRARY['cells'][cell][chosen[cell]]['center'] for cell in graph}
    main=spec['design_card']['main_regions'];alternate=spec['design_card']['flank_regions']
    strict_cells={cell for cell in graph if LIBRARY['cells'][cell][chosen[cell]].get('layout') or chosen[cell]=='fortress_base'}
    navigation=derive_navigation(graph,centers,spec['covers'],main,alternate,entry_cell,exit_cell,exit_target,strict_cells)
    for key in ('entry','exit','main_route','flank','friendly_slots'):spec[key]=navigation[key]
    spec['support']=[navigation['anchors'][cell] for cell in main[1:-1]][:2] or [navigation['anchors'][entry_cell]]
    spec['design_card']['region_anchors']=navigation['anchors']


def module_library():
    cells={}
    for key,(x,z) in CELLS.items():
        cx=round(x*.6+.3,3);cz=round((z-1)*.7,3)
        floor=[round(x*.6,3),round(cz-.35,3),round((x+1)*.6,3),round(cz+.35,3)]
        variants={}
        for kind,label in KINDS.items():
            covers=[]
            if kind=='open':
                covers=[[round(cx-.18,3),round(cz-.14,3),.16,.08,'bookstack',.14],
                        [round(cx+.18,3),round(cz+.14,3),.16,.08,'crate',.08]]
            elif kind=='books':
                covers=[[cx,round(cz-.20,3),.24,.15,'bookstack',.14],
                        [round(cx-.18,3),round(cz+.14,3),.16,.10,'book_city',.08],
                        [round(cx+.18,3),round(cz+.20,3),.16,.10,'file_rack',.23]]
            elif kind=='crates':
                covers=[[cx,round(cz-.20,3),.22,.11,'crate',.08],
                        [round(cx-.18,3),round(cz+.14,3),.18,.10,'bookstack',.14],
                        [round(cx+.18,3),round(cz+.20,3),.16,.10,'file_rack',.23]]
            elif kind=='sandbags':
                covers=[[cx,round(cz+.22,3),.22,.045,'sandbag',.043],
                        [round(cx-.18,3),round(cz-.14,3),.18,.10,'bookstack',.14],
                        [round(cx+.18,3),round(cz-.18,3),.16,.10,'file_rack',.23]]
            if kind=='empty':covers=[[cx,cz,.38,.34,'warehouse',.18]]
            variants[kind]=dict(label=label,floors=[floor],covers=covers,center=[cx,cz])
        if key in CELLS:  # Every desk cell offers the same prepared modules.
            patterns={
                'advance':('错列书堆推进掩体',[( -.15,-.18,.16,.10,'bookstack',.14),(.15,.18,.16,.10,'bookstack',.14)]),
                'screen':('高低组合遮挡',[( -.15,-.18,.16,.10,'bookstack',.14),(.15,.18,.16,.08,'crate',.08)]),
                'defense':('双侧守备射位',[( -.15,-.18,.16,.08,'crate',.08),(.15,-.18,.16,.08,'crate',.08),(.15,.18,.16,.045,'sandbag',.043)]),
                'flank':('侧路遮挡与出射口',[( -.15,.18,.16,.10,'bookstack',.14),(.15,-.18,.16,.08,'crate',.08)])}
            patterns.update({
                'depot_advance':('笔袋收纳区',[( -.15,-.18,.16,.10,'crate',.08),(.15,.18,.16,.10,'crate',.08),(-.15,.18,.12,.045,'sandbag',.043)]),
                'depot_screen':('文件墙围合侧巷',[(-.17,-.23,.16,.09,'bookstack',.15),(.17,-.23,.16,.09,'bookstack',.15),(.15,.18,.16,.10,'crate',.08)]),
                'depot_defense':('书本与橡皮阵地',[(-.17,-.23,.16,.09,'bookstack',.15),(.17,-.23,.16,.09,'bookstack',.15),(-.15,.18,.14,.045,'sandbag',.043),(.15,.18,.14,.045,'sandbag',.043)]),
                'depot_flank':('文件夹侧巷',[(-.17,.23,.16,.09,'bookstack',.15),(.17,.23,.16,.09,'bookstack',.15),(-.15,-.18,.14,.08,'crate',.08)])})
            for family,(label,parts) in patterns.items():
                for rotation in range(4):
                    covers=[]
                    for dx,dz,w,d,asset,h in parts:
                        for _ in range(rotation):dx,dz=-dz,dx;w,d=d,w
                        covers.append([round(cx+dx,3),round(cz+dz,3),w,d,asset,h])
                    variants[f'{family}_{rotation}']=dict(label=f'{label} / 旋转{rotation*90}度',
                        family=family.removeprefix('depot_'),theme='stationery_storage' if family.startswith('depot_') else 'writing_desk',floors=[floor],covers=covers,center=[cx,cz])
        if key in CELLS:
            # Compound footprints preserve an open centre and all selected doorways.
            kits=[
                ('桌面隔板与鼠标转角',[(-.16,-.20,.23,.055,'desk_divider',.25),(-.255,-.30,.05,.07,'concrete',.13),(.18,.21,.12,.08,'mouse',.045),(-.18,.20,.16,.10,'file_rack',.23)]),
                ('打印机与咖啡工作台',[(-.14,-.20,.30,.22,'printer',.16),(.18,.20,.09,.09,'mug',.11),(-.18,.20,.16,.10,'file_rack',.23)]),
                ('抽纸、杯子与尺子区',[(-.18,-.19,.22,.14,'tissues',.12),(.18,.19,.09,.09,'mug',.11),(-.12,.22,.28,.04,'ruler',.012),(.18,-.20,.16,.10,'bookstack',.14)]),
                ('传记与电脑办公区',[(-.19,-.20,.19,.16,'novel',.08),(.13,.19,.30,.21,'laptop',.17),(-.18,.20,.12,.08,'mouse',.045)]),
                ('卡片、文件架与订书器',[(-.18,-.20,.20,.07,'gabion',.07),(.18,.20,.20,.07,'gabion',.07),(-.19,.18,.18,.13,'file_rack',.23),(.02,-.22,.11,.055,'stapler',.05)]),
                ('铅笔、笔袋与胶带区',[(-.18,-.20,.20,.10,'pipe',.055),(.18,.20,.22,.11,'crate',.08),(-.20,.21,.09,.09,'tape',.055),(.18,-.20,.16,.10,'bookstack',.14)]),
                ('城市书、抽纸与手机区',[(-.19,-.20,.16,.19,'book_city',.08),(.17,.20,.14,.22,'tissues',.12),(-.19,.20,.075,.13,'phone',.025)]),
                ('地图册、尺子与计算器区',[(-.19,-.20,.19,.16,'book_atlas',.08),(.13,.20,.28,.04,'ruler',.012),(-.15,.20,.085,.12,'calculator',.035),(.17,-.20,.16,.10,'file_rack',.23)])]
            assert len(kits)==WORKSHOP_STYLE_COUNT
            for mask in range(1,16):
                for role in ('advance','screen','defense','flank'):
                    for style,(label,parts) in enumerate(kits):
                        covers=[[round(cx+dx,3),round(cz+dz,3),w,d,asset,h] for dx,dz,w,d,asset,h in parts]
                        variants[f'workshop_{role}_{mask}_{style}']=dict(label=label,family=role,theme='stationery_workbench',ports=mask,
                            floors=[floor],covers=covers,center=[cx,cz])
            # Expose human-readable card identifiers to JEV. Their geometry is
            # identical to the authored workbench source, not a post-choice swap.
            for style,card_id in enumerate(WORKSHOP_CARD_IDS):
                variants[card_id]=copy.deepcopy(variants[f'workshop_advance_1_{style}'])
        # Preserve the historical reinforcement pass for saved legacy cards.
        # These older centre-clear shapes are no longer the current model's
        # selection vocabulary; their source geometry must remain replayable.
        for module in LEGACY_SELECTABLE_MODULES:
            if module=='empty':continue
            part=variants[module]
            effective=sum(h>=.07 and max(w,d)>=.14 for _,_,w,d,_,h in part['covers'])
            if effective>=3:continue
            for dx,dz in REINFORCEMENT_OFFSETS:
                width,depth=.16,.10
                if abs(dx)+width/2>.30 or abs(dz)+depth/2>.35:continue
                if any(abs(dx-px)<width/2+.045 and abs(dz-pz)<depth/2+.045
                       for px,pz in ((-.24,0),(.22,0),(0,0))):continue
                rx,rz=round(cx+dx,3),round(cz+dz,3)
                if any(abs(rx-cover[0])<(cover[2]+width)/2+.003
                       and abs(rz-cover[1])<(cover[3]+depth)/2+.003
                       for cover in part['covers']):continue
                part['covers'].append([rx,rz,width,depth,'file_rack',.23])
                break
            else:raise ValueError('no_cover_reinforcement_slot:'+module)
        # The selectable catalogue is authored once, before JEV chooses. No
        # post-selection material substitutions or diversity repairs occur.
        for module,card in {**BASE_CARDS,**AUTHORED_CARDS,**WORKBENCH_CARDS,**CURATED_CARDS}.items():
            variants[module]=dict(
                **{key:copy.deepcopy(value) for key,value in card.items() if key!='parts'},
                floors=[floor],center=[cx,cz],
                covers=[[round(cx+dx,3),round(cz+dz,3),w,d,asset,h]
                        for dx,dz,w,d,asset,h in card['parts']])
        variants['empty'].update(purpose='archive',theme='stationery_storage',hero_assets=['warehouse'])
        cells[key]=variants
    edges={}
    for a,(x,z) in CELLS.items():
        for dx,dz in ((1,0),(0,1)):
            b=f'c{x+dx}r{z+dz}'
            if b not in CELLS:continue
            cx=x*.6+.3;cz=(z-1)*.7
            floor=([cx+.25,cz-.10,cx+.35,cz+.10] if dx else [cx-.10,cz+.30,cx+.10,cz+.40])
            barrier=[round(cx+.3 if dx else cx,3),round(cz if dx else cz+.35,3),.025 if dx else .6,.7 if dx else .025,'concrete',.19]
            edges[a+'__'+b]=dict(a=a,b=b,floor=[round(v,3) for v in floor],barrier=barrier)
    return dict(cells=cells,edges=edges,props=PROPS)


LIBRARY=module_library()


def regions(operations):
    chosen={}
    if not isinstance(operations,list) or len(operations)>80:raise ValueError('invalid_graph_operations')
    for op in operations:
        if not isinstance(op,dict):raise ValueError('invalid_graph_operation')
        if op.get('op')!='place_region':continue
        cell=op.get('cell');module=op.get('module');rotation=op.get('rotation',0)
        if (not isinstance(cell,str) or not isinstance(module,str) or cell not in LIBRARY['cells']
                or module not in LIBRARY['cells'][cell] or cell in chosen
                or type(rotation) is not int or rotation not in (0,90,180,270)):
            raise ValueError('invalid_region_module')
        chosen[cell]=module
    if set(chosen)!=set(CELLS):raise ValueError('incomplete_region_map')
    return {k:chosen[k] for k in CELLS}


def rotate_cover(row,center,rotation):
    x,z,width,depth,asset,height=row
    dx,dz=x-center[0],z-center[1]
    for _ in range(rotation//90):dx,dz=-dz,dx;width,depth=depth,width
    return [round(center[0]+dx,3),round(center[1]+dz,3),width,depth,asset,height]


REAR_OFFSETS=((0,0),(-.18,-.27),(.18,.27),(-.18,.27),(.18,-.27),
              (0,-.28),(0,.28),(-.18,0),(.18,0),
              (-.08,-.16),(.08,.16),(-.08,.16),(.08,-.16))


def rear_slots(centers,covers,exit_z,walkable_slots=None):
    """Reserve actual clear firing positions after the desk objects are known."""
    ordered=sorted(centers.values(),key=lambda p:(-p[0],abs(p[1]-exit_z),p[1]))
    slots=[]
    for cx,cz in ordered:
        for dx,dz in REAR_OFFSETS:
            x,z=round(cx+dx,3),round(cz+dz,3)
            if walkable_slots is not None:
                node=nav_index([x,z])
                if node not in walkable_slots:continue
                x,z=nav_point(node)
            if not (.08<=x<=1.72 and -.98<=z<=.98):continue
            if any(abs(x-a[0])<a[2]/2+.045 and abs(z-a[1])<a[3]/2+.045 for a in covers):continue
            # Leave a tiny margin below the intended .15 spacing. Exactly .15
            # rounds to opposite sides of the comparison in Python and Godot.
            if any(math.hypot(x-p[0],z-p[1])<.149 for p in slots):continue
            weapons=('rifle','rifle','smg','rocket','pistol','rifle')
            slots.append([x,z,weapons[len(slots)],'后场守备'])
            if len(slots)==6:return slots
    raise ValueError('insufficient_defender_slots')


def adjacency(chosen,connections):
    graph={k:[] for k,v in chosen.items() if v!='empty'}
    for name in connections:
        edge=LIBRARY['edges'][name];a,b=edge['a'],edge['b']
        if a not in graph or b not in graph:raise ValueError('connector_without_region')
        graph[a].append(b);graph[b].append(a)
    return graph


def path(graph,start,end,excluded=None):
    if start not in graph or end not in graph:return []
    queue=deque([(start,[start])]);seen={start}
    while queue:
        node,route=queue.popleft()
        if node==end:return route
        for other in graph[node]:
            if other not in seen and other!=excluded:seen.add(other);queue.append((other,route+[other]))
    return []


def ports(operations):
    selected=[op for op in operations if isinstance(op,dict) and op.get('op')=='set_ports']
    if not selected:return ENTRY,EXIT
    if len(selected)!=1:raise ValueError('invalid_ports')
    entry,exit=selected[0].get('entry'),selected[0].get('exit')
    if entry not in ('c0r0','c0r1','c0r2') or exit not in ('c2r0','c2r1','c2r2'):
        raise ValueError('invalid_ports')
    return entry,exit


def inspect_regions(operations):
    chosen=regions(operations)
    entry,exit=ports(operations)
    connections=[k for k,e in LIBRARY['edges'].items() if chosen[e['a']]!='empty' and chosen[e['b']]!='empty']
    graph=adjacency(chosen,connections)
    unreachable=[k for k in graph if not path(graph,entry,k)]
    main=path(graph,entry,exit)
    alternate=any(path(graph,entry,exit,k) for k in main[1:-1]) if main else False
    return dict(ok=not unreachable,reason='disconnected_regions' if unreachable else 'regions_connectable',
        unreachable=unreachable,available_connections=connections,alternate_possible=alternate,
        occupied=list(graph),suggestion='放入相邻区域将孤立区域接回入口，或移除无用孤立区域。')


def compile_graph(operations, intent='清除守军'):
    chosen=regions(operations);entry_cell,exit_cell=ports(operations)
    rotations={op['cell']:op.get('rotation',0) for op in operations if op.get('op')=='place_region'}
    connections=[];formation=None;placed=[];per_cell={};edits={}
    for op in operations:
        kind=op.get('op')
        if kind in ('place_region','set_ports'):continue
        if kind=='connect_regions':
            edge=op.get('edge')
            if not isinstance(edge,str) or edge not in LIBRARY['edges'] or edge in connections:raise ValueError('invalid_connection')
            connections.append(edge)
        elif kind=='deploy':
            if formation is not None or op.get('module') not in ('rear','distributed','forward','layered'):raise ValueError('invalid_deployment')
            formation=op['module']
        elif kind=='place_prop':
            cell=op.get('cell');asset=op.get('asset');rotation=op.get('rotation')
            x=op.get('x');z=op.get('z')
            if (cell not in CELLS or chosen[cell]=='empty'
                    or asset not in PROPS or type(rotation) is not int or rotation not in (0,90)
                    or type(x) not in (int,float) or type(z) not in (int,float)
                    or not math.isfinite(x) or not math.isfinite(z)):
                raise ValueError('invalid_prop')
            dimensions=PROPS[asset];w=dimensions['width'];d=dimensions['depth']
            if rotation==90:w,d=d,w
            cx,cz=LIBRARY['cells'][cell]['open']['center']
            if abs(x-cx)+w/2>.27 or abs(z-cz)+d/2>.32:
                raise ValueError('prop_outside_cell')
            per_cell[cell]=per_cell.get(cell,0)+1
            if len(placed)>=MAX_PROPS or per_cell[cell]>3:raise ValueError('too_many_props')
            placed.append([round(x,3),round(z,3),w,d,asset,dimensions['height']])
        elif kind=='edit_component':
            cell=op.get('cell');index=op.get('index');action=op.get('action')
            if (cell not in CELLS or chosen[cell]=='empty' or type(index) is not int
                    or index<0 or index>=len(LIBRARY['cells'][cell][chosen[cell]]['covers'])
                    or action not in ('remove','move','replace') or (cell,index) in edits):
                raise ValueError('invalid_component_edit')
            edits[(cell,index)]=op
        else:raise ValueError('invalid_graph_operation')
    if formation is None:raise ValueError('missing_deployment')
    graph=adjacency(chosen,connections)
    main=path(graph,entry_cell,exit_cell)
    if not main or any(not path(graph,entry_cell,k) for k in graph):raise ValueError('disconnected_regions')
    alternate=[]
    for node in main[1:-1]:
        alternate=path(graph,entry_cell,exit_cell,node)
        if alternate:break
    centers={k:LIBRARY['cells'][k][chosen[k]]['center'] for k in graph}
    floors=[];covers=[]
    for key,module in chosen.items():
        part=LIBRARY['cells'][key][module]
        floors+=copy.deepcopy(part['floors'])
        for index,source in enumerate(part['covers']):
            row=rotate_cover(source,part['center'],rotations[key])
            edit=edits.get((key,index))
            if edit:
                if edit['action']=='remove':continue
                x,z=edit.get('x'),edit.get('z')
                if type(x) not in (int,float) or type(z) not in (int,float) or not math.isfinite(x) or not math.isfinite(z):
                    raise ValueError('invalid_component_edit_position')
                if edit['action']=='replace':
                    asset=edit.get('asset');rotation=edit.get('rotation',0)
                    if asset not in PROPS or type(rotation) is not int or rotation not in (0,90):
                        raise ValueError('invalid_component_replacement')
                    item=PROPS[asset];row=[x,z,item['width'],item['depth'],asset,item['height']]
                    if rotation==90:row[2],row[3]=row[3],row[2]
                else:
                    rotation=edit.get('rotation',0)
                    if type(rotation) is not int or rotation not in (0,90):raise ValueError('invalid_component_rotation')
                    row[0],row[1]=x,z
                    if rotation==90:row[2],row[3]=row[3],row[2]
                if abs(x-part['center'][0])+row[2]/2>.3 or abs(z-part['center'][1])+row[3]/2>.35:
                    raise ValueError('component_outside_cell')
                row[0],row[1]=round(x,3),round(z,3)
            covers.append(row)
    floors=[[0,-1.05,1.8,1.05]]
    covers += [copy.deepcopy(e['barrier']) for k,e in LIBRARY['edges'].items() if k not in connections and chosen[e['a']]!='empty' and chosen[e['b']]!='empty']
    covers += placed
    geometric_routes=any(LIBRARY['cells'][key][module].get('layout') for key,module in chosen.items())
    geometric_routes=geometric_routes or any(
        abs(point[0]-row[0])<row[2]/2+NAV_CLEARANCE and abs(point[1]-row[1])<row[3]/2+NAV_CLEARANCE
        for point in centers.values() for row in covers)
    strict_cells={cell for cell in graph if LIBRARY['cells'][cell][chosen[cell]].get('layout') or chosen[cell]=='fortress_base'}
    navigation=derive_navigation(graph,centers,covers,main,alternate,entry_cell,exit_cell,strict_cells=strict_cells) if geometric_routes else None
    anchors=navigation['anchors'] if navigation else centers
    # Stationery now occupies the former fixed rear sockets; reserve free spots.
    exit_z=centers[exit_cell][1]
    rear=rear_slots(centers,covers,exit_z,navigation['walkable_slots'] if navigation else None)
    extra=[[anchors[k][0],anchors[k][1],'rifle','分区守备'] for k in graph if k not in (entry_cell,exit_cell)]
    if formation=='forward':extra.sort(key=lambda r:(r[0],r[1]))
    else:extra.sort(key=lambda r:(-r[0],r[1]))
    slots=rear if formation=='rear' else (extra+rear)[:6]
    if formation=='layered' and extra:
        front=min(extra,key=lambda p:p[0])
        ordered=[front,rear[0]]+[p for p in extra if p!=front]+rear[1:]
        slots=ordered[:6]
    support=[anchors[k] for k in main[1:-1]][:2] or [anchors[entry_cell]]
    entry=[.06,centers[entry_cell][1]];exit=[1.72,centers[exit_cell][1]]
    if navigation:entry=navigation['entry'];exit=navigation['exit']
    spec=dict(name='模块拼接 / '+('双路连接' if alternate else '连续推进'),intent=intent,
        floors=floors,covers=covers,defender_slots=slots,defenders=slots[:3],entry=entry,exit=exit,
        main_route=navigation['main_route'] if navigation else [centers[k] for k in main],support=support,
        flank=navigation['flank'] if navigation else [centers[k] for k in (alternate or main)],side=-1,
        design_card=dict(signature='region_graph',regions=len(graph),connections=len(connections),placed_props=len(placed),entry_cell=entry_cell,exit_cell=exit_cell,
            alternate_route=bool(alternate),main_regions=main,flank_regions=alternate),
        build_operations=copy.deepcopy(operations),assembly_kind='region_graph_v1')
    if navigation:
        spec['design_card'].update(navigation='geometry_grid_v1',region_anchors=anchors)
        spec['friendly_slots']=navigation['friendly_slots']
    return spec


def validate_graph(operations,intent='清除守军'):
    try:
        spec=compile_graph(operations,intent)
        receipt=validate(spec)
        receipt['graph']=spec['design_card']
        return receipt
    except ValueError as exc:return dict(ok=False,reason=str(exc))
