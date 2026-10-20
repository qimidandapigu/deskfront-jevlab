"""Bounded region/route options grounded in the current native nav graph.

These are choices for the squad Agent, not proof of a safe route. Godot checks
the selected endpoint and computes the actor path again before moving.
"""
import heapq
import math

from strategic_regions import navigation_anchor
from engagement import band, range_fit
from route_choice_evidence import execution_polyline


# Native member_routes.gd accepts at most nine authored waypoint positions.
# Connectivity search must not confuse that wire limit with disconnection.
MAX_ROUTE_POSITIONS = 9
MAX_ALTERNATE_SEARCHES = 8


def _shortest(regions, starts, goal, blocked_edge=None, *, origin=None):
    """Shortest center polyline in the supplied graph, independent of wire caps.

    Costs only use the supplied graph. Parent pointers keep long chains linear
    in storage; no per-depth state or exponential route enumeration is needed.
    This does not query or choose a native movement path.
    """
    queue = []
    best = {}
    parents = {}
    for start in sorted(set(starts)):
        if start not in regions:
            continue
        cost = math.dist(origin, regions[start]['center']) if origin is not None else 0.
        best[start] = cost
        parents[start] = None
        heapq.heappush(queue, (cost, start))
    while queue:
        cost, current = heapq.heappop(queue)
        if cost > best.get(current, math.inf):
            continue
        if current == goal:
            path = []
            while current is not None:
                path.append(current)
                current = parents[current]
            return list(reversed(path))
        for neighbor in sorted(regions[current].get('neighbors', [])):
            if neighbor not in regions or (current, neighbor) == blocked_edge:
                continue
            candidate = cost + math.dist(regions[current]['center'], regions[neighbor]['center'])
            if candidate < best.get(neighbor, math.inf):
                best[neighbor] = candidate
                parents[neighbor] = current
                heapq.heappush(queue, (candidate, neighbor))
    return None


def _alternate_edges(regions, primary):
    """Try real branch exits first, with a fixed number of graph searches."""
    edges = list(zip(primary, primary[1:]))
    if len(edges) <= MAX_ALTERNATE_SEARCHES:
        return edges
    candidates = [edges[0]]
    for index, edge in enumerate(edges):
        previous = primary[index - 1] if index else None
        if any(neighbor in regions and neighbor not in (previous, edge[1])
               for neighbor in regions[edge[0]].get('neighbors', [])):
            candidates.append(edge)
    # Widely separated probes also cover distinct start anchors. Long chains
    # never trigger one alternative search per edge.
    candidates.extend(edges[round(index * (len(edges) - 1) / (MAX_ALTERNATE_SEARCHES - 1))]
                      for index in range(MAX_ALTERNATE_SEARCHES))
    return list(dict.fromkeys(candidates))[:MAX_ALTERNATE_SEARCHES]


def _paths(regions, starts, goal, limit=2, *, origin=None):
    primary = _shortest(regions, starts, goal, origin=origin)
    if primary is None:
        return []
    found = [primary]
    if limit <= 1:
        return found
    # A different connected route is useful to the squad, but never spend
    # exponential work enumerating every path in a generated region graph.
    for edge in _alternate_edges(regions, primary):
        alternate = _shortest(regions, starts, goal, edge, origin=origin)
        if alternate is not None and alternate not in found:
            found.append(alternate)
            if len(found) >= limit:
                break
    return found


def _native_segment(regions, path, endpoint):
    """Return an executable prefix, never a shortcut to the remote endpoint."""
    points = [list(regions[item]['center']) for item in path]
    if points and math.dist(points[-1], endpoint) > .001:
        points.append(list(endpoint))
    if len(points) <= MAX_ROUTE_POSITIONS:
        return list(path), list(endpoint), points, False
    if len(path) <= MAX_ROUTE_POSITIONS:
        # A final region center is not required before another native sample
        # in that same region. Keep the selected endpoint within the cap.
        return list(path), list(endpoint), points[:-2] + [list(endpoint)], False
    prefix = path[:MAX_ROUTE_POSITIONS]
    # Centers are native navigation samples. A far endpoint must not be
    # appended after a truncated path and misrepresented as a final short leg.
    points = [list(regions[item]['center']) for item in prefix]
    return list(prefix), list(points[-1]), points, True


def split_approach(side, front):
    """Whether two selected region routes establish different final approaches.

    The region graph is only a coarse promise; Godot still verifies each actor
    path. A different start cell or an extra detour after the target is not a
    flank of the front route.
    """
    if not side or not front or not side.get('flankable') or front.get('flankable'):
        return False
    side_path, front_path = side['region_path'], front['region_path']
    if not side_path or not front_path or side_path == front_path:
        return False
    return side.get('approach_region') != front.get('approach_region')


def _contact_approach(unit, destination, contacts, now):
    # Only the caller's faction-filtered contacts are available here. Keep one
    # actor-relative contact across the route menu so distance gains compare
    # against the same known enemy; no hidden world positions or LOS claims.
    if not contacts:
        return None
    contact = min(contacts, key=lambda row: math.dist(unit['position'], row['position']))
    current_distance = math.dist(unit['position'], contact['position'])
    destination_distance = math.dist(destination, contact['position'])
    last_seen = contact.get('last_seen')
    age = max(0., now - last_seen) if isinstance(now, (int, float)) and isinstance(last_seen, (int, float)) else None
    weapon_range = unit.get('weapon_range')
    in_range = destination_distance <= weapon_range if isinstance(weapon_range, (int, float)) and weapon_range > 0 else None
    return dict(target_id=contact.get('id'), visible=bool(contact.get('visible')),
        age_s=round(age, 1) if age is not None else None,
        destination_distance=round(destination_distance, 3),
        distance_gain=round(current_distance - destination_distance, 3),
        in_weapon_range=in_range, firing_line='unverified',
        preferred_band=band(unit), range_fit=range_fit(unit,destination_distance))


def _support_screen(destination, support_assets, contacts):
    """Coarse relative position only; neither cover nor a safe route is implied."""
    for asset in support_assets:
        if not _position_pair(asset.get('position')):
            continue
        target_id = asset.get('engagement_position', {}).get('target_id')
        contact = next((row for row in contacts if row.get('id') == target_id), None)
        if contact is None:
            visible = [row for row in contacts if row.get('visible') and _position_pair(row.get('position'))]
            if not visible:
                continue
            contact = min(visible, key=lambda row: math.dist(asset['position'], row['position']))
        if not _position_pair(contact.get('position')):
            continue
        gap = math.dist(asset['position'], contact['position']) - math.dist(destination, contact['position'])
        return dict(asset_id=asset.get('id'), target_id=contact.get('id'),
                    ahead_by=round(gap, 3), position='ahead' if gap >= .12 else 'behind_or_level',
                    basis='已知敌人和候选落点的几何关系；不保证射界或路径安全')
    return None


def _position_pair(value):
    return isinstance(value, (tuple, list)) and len(value) == 2 and all(isinstance(v, (int, float)) for v in value)


def _endpoint_samples(region, unit_id, limit=4):
    """Return native points inside a destination region for this member.

    A region is a planning area, not a single shared destination.  Older
    menus collapsed every route to ``region['center']``; when two members
    selected the same option they consequently stood on the same point.  The
    auto-region builder already carries the native walkable cells, so expose a
    small, deterministic subset of those cells as actual endpoint choices.
    The rotation is only menu ordering (never a hidden assignment): JEV still
    selects the visible option and the engine validates the selected point.
    """
    raw = [point for point in region.get('cells', []) if _position_pair(point)]
    if not raw and _position_pair(region.get('center')):
        raw = [region['center']]
    unique = []
    for point in raw:
        point = [float(point[0]), float(point[1])]
        if not any(math.dist(point, existing) < .025 for existing in unique):
            unique.append(point)
    if not unique:
        return []
    center = region.get('center') if _position_pair(region.get('center')) else unique[0]
    # Prefer points near the authored region center, then spread the menu by
    # walking through the remaining native samples.  No point is invented.
    unique.sort(key=lambda point: (math.dist(point, center), point[0], point[1]))
    if len(unique) > limit:
        step = max(1, len(unique) // limit)
        unique = unique[::step][:limit]
    # Stable per-member rotation makes the same visible choice (for example
    # P1) land on different native cells for different soldiers when possible.
    token = sum((index + 1) * ord(char) for index, char in enumerate(str(unit_id)))
    offset = token % len(unique)
    return unique[offset:] + unique[:offset]


def build(units, regions, topology, goal_id, *, limit=6, contacts=(), now=None, destination_ids=None,
          support_assets=()):
    if goal_id not in regions:
        return {}
    # The commander authorizes the goal. The squad can use its immediate
    # neighbors for a distinct approach or nearby support position.
    goal = regions[goal_id]['center']
    center = [sum(unit['position'][axis] for unit in units) / len(units)
              for axis in (0, 1)] if units else list(goal)
    forward = (goal[0] - center[0], goal[1] - center[1])
    length = math.hypot(*forward)

    def side_offset(region_id):
        if length < .08 or region_id not in regions:
            return 0.
        point = regions[region_id]['center']
        return ((forward[0] * (point[1] - goal[1])
                 - forward[1] * (point[0] - goal[0])) / length)

    neighbors = [key for key in regions[goal_id].get('neighbors', []) if key in regions]
    # Spend the bounded option budget on spatially distinct approaches first.
    destinations = [goal_id] + sorted(neighbors, key=lambda key: (-abs(side_offset(key)), key))
    if destination_ids is not None:
        destinations = [key for key in destinations if key in destination_ids]
    result = {}
    for unit in units:
        anchor = navigation_anchor(unit['position'], regions, topology)
        starts = anchor.get('anchor_regions', [])
        direct = _shortest(regions, starts, goal_id, origin=unit['position'])
        if direct is None:
            # A member in another component cannot receive the team goal.
            # Expose actual local samples for JEV to choose; never invent a
            # bridge or stop requests for the members that can advance.
            local = {}
            for start in starts:
                for endpoint in _endpoint_samples(regions[start], unit['id'], limit=2):
                    key = 'P' + str(len(local) + 1)
                    local[key] = dict(region_id=start, region_path=[start], position=endpoint,
                        route_positions=[endpoint], endpoint_id=f"{start}@{endpoint[0]:.3f},{endpoint[1]:.3f}",
                        endpoint_basis='native_region_cell', approach_region=start,
                        relation='本地位置；本通路不到指挥目标', side='本地', flankable=False,
                        route_length=round(math.dist(unit['position'], endpoint), 3),
                        route_reaches_team_goal=False, limitation='disconnected_from_team_goal',
                        team_goal_region=goal_id, route_target_region=start, remaining_region_hops=None,
                        basis='native sampled anchor; actual local path requires engine validation')
                    if len(local) >= limit:
                        break
                if len(local) >= limit:
                    break
            result[unit['id']] = local
            continue
        direct_length = (math.dist(unit['position'], regions[direct[0]]['center'])
                         + sum(math.dist(regions[a]['center'], regions[b]['center'])
                               for a, b in zip(direct, direct[1:])))
        # A graph path may be connected yet make a soldier run back across the
        # cleared map before reaching the same nearby objective. Do not offer
        # that as a "flank" merely because it approaches from another side.
        # Preserve short lateral moves even when the actor is already at the
        # commander's center; only remove the conspicuous back-map loops.
        detour_limit = max(.75, direct_length * 1.85 + .25)
        # A flank may add a short lateral approach, but it must remain an
        # approach to the known fight.  Before this guard, a connected rear
        # neighbour could be advertised as a flank merely because it had a
        # different region id; JEV then selected a route that increased the
        # distance to the nearest contact by a whole desk or more.  This is a
        # menu constraint, not a hidden reassignment: the commander goal and
        # all native points inside that goal remain available, while only
        # conspicuous backtracking lateral candidates are omitted.
        contact_guard = None
        if contacts:
            contact = min(contacts, key=lambda row: math.dist(unit['position'], row['position']))
            if _position_pair(contact.get('position')):
                contact_guard = dict(position=contact['position'],
                                     current_distance=math.dist(unit['position'], contact['position']),
                                     max_backtrack=max(.24, min(.45, direct_length * .35)))
        options = {}
        # Keep endpoint identity separate from the coarse region identity.  A
        # region with one native sample necessarily has one endpoint; a larger
        # region gives JEV several real points to choose from.
        unit_destinations = list(destinations)
        if unit.get('position_role') == 'fire_support':
            # Offer holding near the current line as a real choice, alongside
            # the commander's region and lateral routes. No route is invented.
            unit_destinations = list(dict.fromkeys([goal_id] + starts + neighbors))
            if destination_ids is not None:
                unit_destinations = [key for key in unit_destinations if key in destination_ids]
        endpoint_by_destination = {
            destination: _endpoint_samples(regions[destination], unit['id'])
            for destination in unit_destinations if destination in regions}
        for destination in unit_destinations:
            for path_index, path in enumerate(_paths(regions, starts, destination, origin=unit['position'])):
                if len(options) >= limit:
                    break
                # Going through the commander's goal and then walking back to
                # a neighbor is not a useful neighboring approach.
                if destination != goal_id and goal_id in path[:-1]:
                    continue
                path_length = (math.dist(unit['position'], regions[path[0]]['center'])
                               + sum(math.dist(regions[a]['center'], regions[b]['center'])
                                     for a, b in zip(path, path[1:])))
                if path_length > detour_limit + 1e-8:
                    continue
                key = 'P' + str(len(options) + 1)
                endpoint_pool = endpoint_by_destination.get(destination) or [list(regions[destination]['center'])]
                # Different route variants also expose different points when
                # the region has enough native samples.  This preserves the
                # route choice while preventing every member's endpoint from
                # collapsing to the same center.
                endpoint = list(endpoint_pool[path_index % len(endpoint_pool)])
                side_region = path[-2] if destination == goal_id and len(path) > 1 else destination
                lateral = side_offset(side_region)
                # The direct path is never a flank merely because the whole
                # squad approaches the goal diagonally on the map.
                # A neighboring endpoint reached *through* the goal is not a
                # side approach; it has already followed the front route.
                flankable = abs(lateral) >= .09 and (destination != goal_id or path_index > 0)
                if contact_guard is not None and (destination != goal_id or path_index > 0):
                    retreat = math.dist(endpoint, contact_guard['position']) - contact_guard['current_distance']
                    if retreat > contact_guard['max_backtrack']:
                        continue
                full_path = path
                path, endpoint, route_positions, intermediate = _native_segment(regions, path, endpoint)
                actual_destination = path[-1]
                if intermediate:
                    # This is progress on the authored route, not arrival at
                    # its distant final approach or a validated firing site.
                    side_region = path[-2] if len(path) > 1 else actual_destination
                    flankable = False
                    lateral = side_offset(side_region)
                if any(row['region_path'] == path and row['position'] == endpoint for row in options.values()):
                    continue
                key = 'P' + str(len(options) + 1)
                split_at = next((path[i-1] for i in range(1, min(len(path), len(options.get('P1', {}).get('region_path', []))))
                                 if path[i] != options['P1']['region_path'][i]), None) if options else None
                # Estimate only the exposed segment, including its selected
                # endpoint. This is not the native collision-aware path or
                # evidence that the remaining team route has been traversed.
                execution_points = execution_polyline(unit['position'], route_positions, endpoint)
                full_length = sum(math.dist(a, b) for a, b in zip(execution_points, execution_points[1:]))
                options[key] = dict(region_id=actual_destination, region_path=path,
                                    position=endpoint,
                                    route_positions=route_positions,
                                    endpoint_id=f"{actual_destination}@{endpoint[0]:.3f},{endpoint[1]:.3f}",
                                    endpoint_basis='native_region_cell' if regions[actual_destination].get('cells') else 'region_center',
                                    endpoint_separation='成员菜单按稳定顺序轮换原生采样点；实际占位仍由引擎校验',
                                    relation='沿通路前往目标的中途区；尚未到指挥目标' if intermediate else
                                             ('侧翼通路至指挥目标区' if flankable else '指挥目标区')
                                             if destination == goal_id else ('侧翼邻区' if flankable else '目标邻区'),
                                    flankable=flankable, lateral_offset=round(lateral, 3),
                                    approach_region=side_region,
                                    side='中途' if intermediate else '左侧' if lateral > .09 else '右侧' if lateral < -.09 else '正面',
                                    split_from_primary_at=split_at,
                                    route_length=round(full_length, 3),
                                    route_reaches_team_goal=actual_destination == goal_id,
                                    team_goal_region=goal_id, route_target_region=destination,
                                    remaining_region_hops=len(full_path)-len(path),
                                    contact_approach=_contact_approach(unit, endpoint, contacts, now),
                                    support_screen=_support_screen(endpoint, support_assets, contacts),
                                    basis='原生连通区域；实际逐兵路径仍由引擎检查')
                if intermediate:
                    options[key]['limitation'] = 'intermediate_route_segment'
            if len(options) >= limit:
                break
        result[unit['id']] = options
    return result
