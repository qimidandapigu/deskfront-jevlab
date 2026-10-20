"""Additional navigation choices around observed hard cover; never select an order.

The bounded graph proves only connectivity. A clear 2D segment is not a muzzle
ray, and the existing engine still validates the model's selected route.
"""
import math

from engagement_feedback import point_obstructions
from strategic_regions import navigation_anchor
from route_choice_evidence import execution_polyline
from squad_region_choices import _shortest, _endpoint_samples, _native_segment


def augment(options, units, regions, topology, world, contacts, destination_ids=None, *, goal_id=None):
    visible = [c for c in contacts if c.get('visible') and len(c.get('position', [])) == 2]
    if not visible:
        return
    allowed = set(regions) if destination_ids is None else set(destination_ids)
    # Query geometry once per point/target, shared across members in this request.
    cache = {}
    def blockers(point, target):
        key = (tuple(point), target['id'])
        if key not in cache:
            facts = point_obstructions(world, point, [target])
            cache[key] = facts[0]['crossing_hard_cover_ids'] if facts else []
        return cache[key]
    for unit in units:
        menu = options.setdefault(unit['id'], {})
        starts = navigation_anchor(unit['position'], regions, topology)['anchor_regions']
        targets = sorted(visible, key=lambda c: math.dist(unit['position'], c['position']))[:2]
        candidates = []
        for target in targets:
            blocked = blockers(unit['position'], target)
            if not blocked:
                continue
            # Check nearby combat regions first, including beyond goal neighbours.
            nearby = sorted((rid for rid in regions if rid in allowed),
                            key=lambda rid: math.dist(regions[rid]['center'], target['position']))[:24]
            for rid in nearby:
                path = _shortest(regions, starts, rid, origin=unit['position'])
                if not path:
                    continue
                for endpoint in _endpoint_samples(regions[rid], unit['id']):
                    if blockers(endpoint, target):
                        continue
                    if any(math.dist(endpoint, row['position']) < .025 for row in menu.values()):
                        continue
                    points = [list(regions[r]['center']) for r in path]
                    if points[-1] != endpoint:
                        points.append(endpoint)
                    execution_points = execution_polyline(unit['position'], points, endpoint)
                    distance = sum(math.dist(a, b) for a, b in zip(execution_points, execution_points[1:]))
                    candidates.append((distance + math.dist(endpoint, target['position']), rid, path, endpoint, points, target, blocked, distance))
        # Two spatially distinct destinations, not many variants of one wall edge.
        selected = []
        for _, rid, path, endpoint, points, target, blocked, distance in sorted(candidates, key=lambda c: (c[0], c[1], c[3])):
            segment, segment_endpoint, segment_points, intermediate = _native_segment(regions, path, endpoint)
            if any(math.dist(segment_endpoint, p) < .2 for p in selected):
                continue
            segment_region = segment[-1]
            segment_blockers = blockers(segment_endpoint, target)
            execution_points = execution_polyline(unit['position'], segment_points, segment_endpoint)
            segment_length = sum(math.dist(a,b) for a,b in zip(execution_points,execution_points[1:]))
            key = 'P' + str(max([int(k[1:]) for k in menu if k.startswith('P') and k[1:].isdigit()] or [0]) + 1)
            menu[key] = dict(region_id=segment_region, region_path=segment, position=segment_endpoint,
                route_positions=segment_points, endpoint_id=f'{segment_region}@{segment_endpoint[0]:.3f},{segment_endpoint[1]:.3f}',
                endpoint_basis='native_region_cell', approach_region=segment[-2] if len(segment)>1 else segment_region,
                relation=('绕障通路的中途点；尚未到最终绕障终点' if intermediate else '绕障候选；终点二维连线无硬障碍，原生射界未验证'), flankable=False,
                side='需比较实际通路', route_length=round(segment_length, 3),
                route_target_region=rid, remaining_region_hops=len(path)-len(segment),
                bypass_evidence=dict(target_id=target['id'], origin_blockers=blocked,
                    endpoint_crossing_hard_cover_ids=segment_blockers, native_firing_line='unknown',
                    temporary_retreat_allowed=True),
                basis='sampled connected regions; not proof of native firing or safe travel')
            if goal_id is not None:
                menu[key].update(team_goal_region=goal_id, route_reaches_team_goal=segment_region==goal_id)
            if intermediate:
                menu[key]['limitation']='intermediate_route_segment'
            selected.append(segment_endpoint)
            if len(selected) == 2:
                break
