"""Execute a commander's explicit region sequence on native navigation samples.

This module never chooses a tactical route or claims that a traversable route is
safe. ``next_region_step`` mutates only ``task['_region_progress']``. Preserve
that field when retaining the same task; changing ``region_path`` resets it.
"""
from collections import deque
import math

from strategic_regions import contains, memberships, navigation_anchor


def local_move_allowed(origin, destination, allowed_regions, regions, origin_bridge=None):
    """Check the short command corridor; this is not a fire-safety check."""
    distance = math.dist(origin, destination)
    bridge = bool(origin_bridge and origin_bridge.get('mode')=='nearby_native_sample' and
                  not origin_bridge.get('observed_regions') and distance<=.12+1e-8 and
                  math.dist(destination,origin_bridge.get('anchor_position',destination))<=1e-8)
    entered=False
    samples = max(1, math.ceil(distance/.025))
    for i in range(samples+1):
        point = [origin[j]+(destination[j]-origin[j])*i/samples for j in (0,1)]
        if any(contains(point, regions[key]) for key in allowed_regions if key in regions):
            entered=True
        elif not bridge or entered or memberships(point,regions):
            # Only an initial unclassified gap may be bridged. A different
            # observed region or a later hole in the corridor is never ignored.
            return False
    return True


def validate_region_path(path, destination, regions, position=None, topology=None):
    """Return an explicit, connected sequence; never silently invent missing legs.

    The first region may contain the unit or be adjacent to its current region.
    ``position`` is optional for validating a plan that is already in progress.
    """
    if not isinstance(path, list) or not path or len(path) > 64:
        raise ValueError('region_path must contain 1..64 region IDs')
    if any(not isinstance(key, str) or key not in regions for key in path):
        raise ValueError('region_path contains an unknown region')
    if path[-1] != destination:
        raise ValueError('region_path must end at region_id')
    for left, right in zip(path, path[1:]):
        if left == right or right not in regions[left].get('neighbors', []):
            raise ValueError('region_path has a disconnected leg: '+left+' -> '+right)
    if position is not None:
        current = navigation_anchor(position,regions,topology)['anchor_regions']
        if not current:
            raise ValueError('unit is outside sampled regions; cannot validate route entry')
        if not any(key == path[0] or path[0] in regions[key].get('neighbors', []) for key in current):
            raise ValueError('region_path must begin at the current or an adjacent region')
    return list(path)


def next_region_step(unit_position, task, topology, regions, reserved_positions=()):
    """Return ready/arrived/blocked plus the next short move and observed progress.

    A region is completed only after the unit actually enters it, in order.
    Local paths are restricted to the current region and the next required
    region. A retreat to an already visited region is allowed to retrace that
    corridor; being teleported ahead never marks intermediate regions complete.
    ``position`` is at most .25 world units along a straight grid segment.
    Occupied reservations are avoided locally; failure is reported, not replaced
    by a global shortest path. The caller must still validate the live move.
    """
    result = dict(status='blocked', position=None, risk_status='unknown',
                  safety='native sampled connectivity only; fire risk requires a separate query')
    try:
        path = validate_region_path(task.get('region_path'), task.get('region_id'), regions)
    except ValueError as error:
        return dict(result, reason='invalid_region_path', detail=str(error))
    signature = tuple(path)
    progress = task.get('_region_progress', {})
    if tuple(progress.get('signature', [])) != signature:
        progress = dict(signature=list(path), index=0, entered=[])
        task['_region_progress'] = progress
    index = max(0, min(int(progress.get('index', 0)), len(path)))
    anchor = navigation_anchor(unit_position,regions,topology)
    observed = anchor['observed_regions']
    current = anchor['anchor_regions']
    result.update(region_path=list(path), current_regions=observed,
                  anchor_regions=current, navigation_anchor=anchor)
    if not current:
        return dict(result, index=index, reason='outside_sampled_regions')

    # Advance at most one previously unvisited area per observation. Adjacent
    # sampled cells may share a boundary; this must not skip multiple tasks.
    if index < len(path) and path[index] in observed:
        progress['entered'].append(path[index])
        index += 1
        progress['index'] = index
    result.update(index=index, entered=list(progress['entered']))
    if index == len(path) and path[-1] in observed:
        return dict(result, status='arrived', reason='destination_region_entered', next_region=None)

    # Returning after a local retreat keeps earlier observed progress, while
    # still taking the explicit corridor back to the last required region.
    required_index = min(index, len(path)-1)
    previous_indexes = [i for i in range(min(index, len(path))) if path[i] in current]
    if previous_indexes:
        start_index = max(previous_indexes)
        target_index = min(start_index+1, required_index)
        source = path[start_index]
        target = path[target_index]
    else:
        target = path[required_index]
        # Before entering the first region, a single adjacent approach is
        # permitted. Later, rejoin the last visited region after local retreat.
        if index > 0:
            target = path[index-1]
        source = next((key for key in current if key==target or target in regions[key].get('neighbors', [])), None)
        # A later, unvisited route region is never used as a shortcut backwards.
        future = set(path[index+1:]) if index < len(path) else set()
        if source in future:
            source = None
        if source is None:
            return dict(result, next_region=path[required_index], reason='outside_ordered_corridor')
    result['next_region'] = target
    allowed = {source, target}
    if not observed:
        # Re-enter only the nearby walkable sample first. Do not use the gap as
        # permission to cut straight through the next region or mark it entered.
        point=anchor['anchor_position']
        if any(isinstance(p,(list,tuple)) and len(p)==2 and math.dist(point,p)<.09 for p in reserved_positions):
            return dict(result,reason='origin_anchor_reserved')
        if not local_move_allowed(unit_position,point,allowed,regions,origin_bridge=anchor):
            return dict(result,reason='origin_anchor_crosses_other_region')
        return dict(result,status='ready',position=point,reason='origin_anchor_bridge',
                    path_regions=[source],path_cells=[anchor['anchor_cell']],
                    requires_native_validation=True,bridge_max_path_length=round(anchor['anchor_distance']+.03,6),
                    requires_precise_arrival=True,arrival_radius=.015,
                    safety='unclassified origin bridge only; native clearance and short path validation required')
    cells = topology.get('cells', {})
    permitted = {key for key, point in cells.items() if any(contains(point, regions[r]) for r in allowed)}
    if not permitted:
        return dict(result, reason='corridor_has_no_navigation_samples')
    starts = {key for key in permitted if contains(cells[key], regions[source])}
    if not starts:
        return dict(result, reason='current_region_has_no_navigation_samples')
    start = min(starts, key=lambda key: math.dist(unit_position, cells[key]))
    if math.dist(unit_position, cells[start]) > max(.12, topology.get('step', .075)*1.5):
        return dict(result, reason='no_nearby_corridor_sample')
    reserved = [point for point in reserved_positions if isinstance(point, (list, tuple)) and len(point) == 2]
    occupied = {key for key in permitted if key != start and any(math.dist(cells[key], point) < .09 for point in reserved)}
    permitted -= occupied
    goals = {key for key in permitted if contains(cells[key], regions[target])}
    adjacency = {key: [] for key in permitted}
    for left, right in topology.get('edges', []):
        if left in permitted and right in permitted:
            adjacency[left].append(right)
            adjacency[right].append(left)
    todo = deque([start]); parents = {start: None}; end = None
    while todo:
        key = todo.popleft()
        if key in goals:
            end = key
            break
        for neighbor in sorted(adjacency[key]):
            if neighbor not in parents:
                parents[neighbor] = key
                todo.append(neighbor)
    if end is None:
        return dict(result, reason='corridor_reserved_or_disconnected' if occupied else 'corridor_disconnected')
    nodes = []
    while end is not None:
        nodes.append(end); end = parents[end]
    nodes.reverse()
    points = [cells[key] for key in nodes]
    result.update(path_regions=[source, target], path_cells=nodes, path_length=round(
        math.dist(unit_position, points[0])+sum(math.dist(a,b) for a,b in zip(points,points[1:])), 4))
    # Native movement stops near a point, not precisely on it. Requiring the
    # unit to be <.02 from the grid sample deadlocks with its ~.024 arrival
    # tolerance and the Harness's .055 retained-move radius. Start from the
    # observed position and verify each proposed direct segment instead.
    selected = points[0] if local_move_allowed(unit_position, points[0], allowed, regions) else None
    path_distances = [math.dist(unit_position, points[0])]
    for left, right in zip(points, points[1:]):
        path_distances.append(path_distances[-1]+math.dist(left,right))
    if len(points) > 1:
        direction = [points[1][i]-points[0][i] for i in (0,1)]
        for i,(left, right) in enumerate(zip(points, points[1:]), 1):
            step = [right[j]-left[j] for j in (0,1)]
            if abs(direction[0]*step[1]-direction[1]*step[0]) > 1e-8 or sum(a*b for a,b in zip(direction,step)) <= 0:
                break
            if path_distances[i] > .25+1e-8:
                break
            if local_move_allowed(unit_position, right, allowed, regions):
                selected = right
    # Near an actual corner, prefer a reachable point after the corner over
    # asking the engine to correct an already-arrived position. Do not cut
    # across an unassigned/unsampled area merely to escape this tolerance.
    if selected is None or math.dist(unit_position,selected) <= .055:
        for point,distance in zip(points,path_distances):
            if distance > .25+1e-8:break
            if math.dist(unit_position,point) > .055 and local_move_allowed(unit_position,point,allowed,regions):
                selected=point
    if selected is None:
        return dict(result, reason='no_connected_short_step')
    distance=math.dist(unit_position, selected)
    if distance <= .024:
        # Bypassing the Harness's retention alone cannot overcome the native
        # arrival radius; expose the conflict instead of emitting a no-op move.
        return dict(result, reason='short_step_inside_native_arrival_tolerance',
                    requires_precise_arrival=True, arrival_radius=min(.015,distance/2))
    return dict(result, status='ready', position=list(selected), reason='ordered_region_step',
                requires_precise_arrival=distance < .055, arrival_radius=min(.015,distance/2) if distance < .055 else .024)
