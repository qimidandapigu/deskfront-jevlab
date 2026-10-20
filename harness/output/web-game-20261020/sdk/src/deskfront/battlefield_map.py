"""Shared factual map for commander, squad JEV and personal JEV requests."""
import copy
import math

from tactical_map_view import build as overview


def _point(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) for v in value))


def build(world, topology, regions, members, contacts, plan, *, focus=None):
    """Expose terrain and known contacts, never the raw world enemy roster.

    The overview is deliberately coarse; physical footprints and native region
    adjacency supply the geometry it cannot resolve. Neither is a firing check.
    """
    friends = [u for u in members if u.get('hp', 0) > 0 and _point(u.get('position'))]
    team = next((u.get('faction') for u in friends), None)
    known = [c for c in contacts if c.get('visible') and c.get('id')
             and _point(c.get('position')) and c.get('hp', 1) > 0]
    units = [dict(id=u['id'], faction=u.get('faction'), hp=1, position=list(u['position']))
             for u in friends]
    own_ids = {u['id'] for u in friends}
    units += [dict(id=c['id'], faction=c.get('faction') or ('red' if team == 'green' else 'green'),
                   hp=1, position=list(c['position'])) for c in known if c['id'] not in own_ids]
    topology = topology or world.get('strategic_topology') or {}
    covers = [c for c in world.get('covers', []) if c.get('alive', True)
              and _point(c.get('position'))]
    goal = plan.get('position') if isinstance(plan, dict) else None
    map_state = dict(bounds=world.get('bounds'), strategic_topology=topology,
                     covers=covers, units=units,
                     self_id=focus.get('id') if isinstance(focus,dict) else None,
                     objective=dict(position=goal) if _point(goal) else {})
    anchor = focus.get('position') if isinstance(focus, dict) else None
    anchors = ([anchor] if _point(anchor) else [u['position'] for u in friends])
    anchors += ([goal] if _point(goal) else []) + [c['position'] for c in known]

    def distance(position):
        return min((math.dist(position, p) for p in anchors), default=0.)

    valid_regions = {key: r for key, r in (regions or {}).items() if _point(r.get('center'))}
    selected = sorted(valid_regions, key=lambda key: (distance(valid_regions[key]['center']), key))[:64]
    labels={key:f'R{i+1}' for i,key in enumerate(sorted(valid_regions))}
    links = {key: dict(center=[round(v, 4) for v in valid_regions[key]['center']],symbol=labels[key],
                       neighbors=list(valid_regions[key].get('neighbors', [])),
                       basis=valid_regions[key].get('walkability', 'unknown_requires_native_query'))
             for key in selected}
    # A connection marker is backed by an actual native cross-region edge.
    # It is not a guessed door between region centres.
    owners={tuple(p):key for key,region in valid_regions.items() for p in region.get('cells',[]) if _point(p)}
    native=topology.get('cells',{});crossings={}
    for edge in topology.get('edges',[]):
        if not isinstance(edge,(list,tuple)) or len(edge)!=2:continue
        a,b=(native.get(key) for key in edge)
        if not _point(a) or not _point(b):continue
        ra,rb=owners.get(tuple(a)),owners.get(tuple(b))
        if not ra or not rb or ra==rb:continue
        pair=tuple(sorted((ra,rb)));candidate=(math.dist(a,b),str(edge[0]),str(edge[1]))
        if pair not in crossings or candidate<crossings[pair][0]:
            crossings[pair]=(candidate,list(a),list(b))
    gates=[]
    for i,(pair,(_,a,b)) in enumerate(sorted(crossings.items())):
        if not all(rid in links for rid in pair):continue
        gates.append(dict(symbol=f'G{i+1}',id='native:'+'|'.join(pair),region_ids=list(pair),
                          position=[round((a[j]+b[j])/2,4) for j in range(2)],
                          native_edge=[a,b],basis='engine_validated_cross_region_edge_not_physical_door'))
    nearby_gates=sorted(gates,key=lambda g:(distance(g['position']),g['symbol']))[:16]
    # Send actual oriented physical boxes, not a rotated navigation AABB.
    hard = []
    for cover in covers:
        if cover.get('kind') != 'hard':
            continue
        size = cover.get('size')
        ray = cover.get('ray_size')
        if isinstance(ray, (list, tuple)) and len(ray) == 3:
            size = [ray[0], ray[2]]
        if not _point(size) or any(v <= 0 for v in size):
            continue
        hard.append(dict(id=cover.get('id'), position=list(cover['position']),
                         size=list(size), yaw=cover.get('yaw', 0) or 0,
                         height=cover.get('height')))
    local_anchors = [anchor] if _point(anchor) else [u['position'] for u in friends]

    def local_distance(cover):
        # Large obstacles matter even when their centre is distant.
        return min((math.dist(cover['position'], p) for p in local_anchors), default=0.) - math.hypot(*cover['size']) / 2

    nearby = sorted(hard, key=lambda c: (local_distance(c), str(c['id'])))[:32]
    return dict(navigation_revision=world.get('navigation_revision'),
                sampled_at=world.get('time'), overview=overview(map_state,fixed_grid=True),
                region_graph=links, omitted_region_count=max(0, len(valid_regions)-len(links)),
                gateways=nearby_gates,omitted_gateway_count=max(0,len(gates)-len(nearby_gates)),
                local_hard_covers=copy.deepcopy(nearby),
                omitted_hard_cover_count=max(0, len(hard)-len(nearby)),
                focus_unit_id=focus.get('id') if isinstance(focus, dict) else None,
                basis='共享世界坐标地图；敌人仅来自本队当前已知接触。overview按硬障碍占地绘制粗图，'
                      'local_hard_covers是实际障碍占地，size为宽/深、yaw为弧度；'
                      'region_graph为区域连接，未包含的邻区仍未知。'
                      '请结合墙体围合、入口与出口判断是否必须退回才能继续接敌；'
                      '几何上更靠近敌人不等于沿可行路线推进，也不证明射界或投弹通路。')
