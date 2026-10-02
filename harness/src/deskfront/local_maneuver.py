"""Small, evidence-labelled local route choices for an individual executor.

The commander supplies intent, not a mandatory sequence of region centres.
This module only proposes a native-queried short movement step toward a
sampled destination. It does not claim that a topology cell has a firing lane
or that a sampled threat forecast guarantees safety. The live move is still
validated by the engine before submission.
"""
from collections import deque
import math


def _point(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        return None
    return [float(value[0]), float(value[1])]


def _distance(a, b):
    return math.dist(a, b)


def _reserved(position, reservations):
    values = reservations.values() if isinstance(reservations, dict) else reservations
    return any(_point(value) is not None and _distance(position, value) < .09 for value in values)


def _graph(topology, origin):
    cells = {str(k): p for k, raw in topology.get('cells', {}).items()
             if (p := _point(raw)) is not None}
    if not cells:
        return {}, {}, {}, None
    start = min(cells, key=lambda key: (_distance(origin, cells[key]), key))
    if _distance(origin, cells[start]) > .12:
        return cells, {}, {}, None
    edges = {key: [] for key in cells}
    for pair in topology.get('edges', []):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        a, b = map(str, pair)
        if a in cells and b in cells and a != b:
            edges[a].append(b)
            edges[b].append(a)
    parents = {start: None}
    queue = deque([start])
    while queue:
        key = queue.popleft()
        for next_key in sorted(edges[key]):
            if next_key not in parents:
                parents[next_key] = key
                queue.append(next_key)
    return cells, edges, parents, start


def _path(parents, key):
    if key not in parents:
        return None
    result = []
    while key is not None:
        result.append(key)
        key = parents[key]
    return list(reversed(result))


def _route_length(path, cells, origin):
    points = [origin] + [cells[key] for key in path]
    return sum(_distance(a, b) for a, b in zip(points, points[1:]))


def _region_owners(regions):
    result = {}
    for key, region in regions.items():
        for raw in region.get('cells', []):
            point = _point(raw)
            if point is not None:
                result[tuple(round(v, 6) for v in point)] = key
    return result


def _route_regions(path, cells, owners, regions):
    # Auto-generated regions have exact sampled cell ownership. Legacy regions
    # may only provide a circle or bounds; that slower fallback is tiny here.
    from strategic_regions import memberships
    result = []
    for cell in path:
        point = cells[cell]
        region = owners.get(tuple(round(v, 6) for v in point))
        if region is None:
            region = next(iter(memberships(point, regions)), None)
        if region and (not result or result[-1] != region):
            result.append(region)
    return result


def _steps(spatial, cells, parents, origin, reservations):
    result = {}
    for raw in spatial.get('navigation_steps', []):
        if not isinstance(raw, dict):
            continue
        point = _point(raw.get('position'))
        key = str(raw.get('cell_id', ''))
        risk = raw.get('risk', {})
        if (point is None or key not in parents or key not in cells or
                _distance(point, cells[key]) > 1e-5 or
                _distance(point, origin) <= .055 or
                _distance(point, origin) > .325 or
                _reserved(point, reservations) or
                not isinstance(risk, dict) or risk.get('status') != 'sampled'):
            continue
        result[key] = (point, risk)
    return result


def _short_step(path, cells, origin, steps):
    # Use only an exact native navigation-step query on the chosen connected
    # route. The game will validate it again when the action is submitted.
    distance = _distance(origin, cells[path[0]])
    chosen = (path[0], *steps[path[0]]) if path[0] in steps and distance > .055 else None
    for left, right in zip(path, path[1:]):
        distance += _distance(cells[left], cells[right])
        if distance > .25 + 1e-8:
            break
        if right in steps:
            chosen = (right, *steps[right])
    return chosen


def build_local_maneuvers(unit, task, spatial, regions, topology, reservations=(),
                          *, enemies=(), current_destination=None, limit=4):
    """Return ``(options, report)`` for JEV without changing any game state.

    ``command.position`` is the next short step; ``destination`` is the final
    sampled goal. ``fire_lane_evidence`` is true only for a native firing point
    whose ``targets`` include the live assigned target. A topology approach
    always has unknown fire lane even when its endpoint is in weapon range.
    ``report.reason`` explains the lack of usable choices to the task manager.
    """
    task = task or {}
    spatial = spatial or {}
    regions = regions or {}
    topology = topology or {}
    origin = _point(unit.get('position'))
    report = dict(reason='no_candidate', target_id=task.get('target_id') or None,
                  fire_lane_status='unknown', options=0)
    if origin is None:
        report['reason'] = 'invalid_unit_position'
        return {}, report
    if not spatial:
        report['reason'] = 'spatial_query_unavailable'
        return {}, report
    target_id = task.get('target_id')
    live_enemies = [v for v in enemies if isinstance(v, dict) and v.get('hp', 0) > 0
                    and v.get('combat_ready', True) and _point(v.get('position')) is not None]
    target = next((v for v in live_enemies if v.get('id') == target_id), None) if target_id else None
    if target_id and target is None:
        report['reason'] = 'assigned_target_not_live'
        return {}, report
    if target is None and task.get('command') in ('support', 'flank', 'eliminate') and live_enemies:
        target = min(live_enemies, key=lambda v: _distance(origin, v['position']))
        target_id = target['id']
        report['target_id'] = target_id
    if target is not None and target.get('kind') == 'tank' and unit.get('weapon') != 'rocket':
        report['reason'] = 'weapon_cannot_damage_target'
        return {}, report

    cells, _edges, parents, start = _graph(topology, origin)
    steps = _steps(spatial, cells, parents, origin, reservations) if start else {}
    owners = _region_owners(regions)
    # BFS insertion order places each parent before its child. Cache a queried
    # native short step and route length for every reachable cell once.
    first_step = {}
    route_distance = {}
    for cell, parent in parents.items():
        route_distance[cell] = (_distance(origin, cells[cell]) if parent is None else
                                route_distance[parent] + _distance(cells[parent], cells[cell]))
        first_step[cell] = first_step.get(parent)
        if cell in steps and route_distance[cell] <= .25 + 1e-8:
            first_step[cell] = cell
    options = {}
    seen = set()
    approach_steps = set()
    limit = max(0, min(int(limit), 6))

    def add(key, goal, *, goal_cell=None, confirmed=False, risk=None, committed=False, remote=False, label=''):
        goal = _point(goal)
        if goal is None or _reserved(goal, reservations):
            return
        path = None
        if start:
            end = goal_cell if goal_cell in parents else min(parents, key=lambda cell: (_distance(cells[cell], goal), cell))
            if _distance(cells[end], goal) <= .12:
                path = _path(parents, end)
        if _distance(origin, goal) <= .25 and confirmed and isinstance(risk, dict) and risk.get('status') == 'sampled':
            step, step_risk = goal, risk
        elif path:
            selected = _short_step(path, cells, origin, steps)
            if selected is None:
                return
            _, step, step_risk = selected
        else:
            return
        if _distance(origin, step) <= .055 or _reserved(step, reservations):
            return
        if not confirmed:
            step_key = tuple(round(v, 5) for v in step)
            if step_key in approach_steps:
                return
            approach_steps.add(step_key)
        # A different route goal may share this step. Keep it as an alternative
        # only when its ultimate destination really differs.
        identity = tuple(round(v, 5) for v in step + goal)
        if identity in seen:
            return
        seen.add(identity)
        route = _route_regions(path or [], cells, owners, regions)
        risk_text = ('原生抽样：约 %.1f 秒到达、%.1f 秒处于可被攻击的射线中；预测不保证安全' %
                     (step_risk.get('travel_s', 0), step_risk.get('exposed_s', 0)))
        if confirmed:
            lane_text = ('终点全图粗采样的站姿枪口射线可达 ' if remote else '终点原生站姿射线可攻击 ') + str(target_id) + '；敌人移动、实际命中与到位后射界仍需复核'
        else:
            lane_text = '仅证实短步的原生导航与路径风险；终点射界未知，到达不等于完成支援'
        options[key] = dict(
            command=dict(action='move', intent='advance', position=step),
            destination=goal,
            fire_lane_evidence=confirmed,
            fire_lane_scope='remote_coarse_sample' if remote else 'local_native_sample' if confirmed else 'unknown',
            target_id=target_id,
            region_route=route[:8],
            route_regions_truncated=len(route) > 8,
            native_step_risk=dict(step_risk),
            requires_native_validation=True,
            description=(label + '；本次短步 ' + str(step) + '；候选终点 ' + str(goal) +
                         '；途经区域 ' + str(route[:8]) + ('（后续省略）' if len(route)>8 else '') +
                         '；目标 ' + str(target_id or '无') + '；' + lane_text + '；' + risk_text +
                          ('；建议沿原目标继续，除非通路或威胁已改变' if committed else '')),
            score=104 if committed else 96 if confirmed else 72,
        )

    firing = []
    for raw in [*spatial.get('firing_positions', []), *spatial.get('remote_firing_positions', [])]:
        if not isinstance(raw, dict) or not target_id or target_id not in raw.get('targets', []):
            continue
        if _point(raw.get('position')) is None or raw.get('risk', {}).get('status') != 'sampled':
            continue
        if raw in spatial.get('remote_firing_positions', []) and raw.get('reachable') is not True:
            continue
        firing.append(raw)
    report['native_firing_points'] = len(firing)
    if firing:
        report['fire_lane_status'] = 'native_standing_ray_at_sampled_destination'

    committed_goal = _point(current_destination)
    if committed_goal is not None and _distance(origin, committed_goal) > .08:
        match = next((p for p in firing if _distance(p['position'], committed_goal) < 1e-5), None)
        if match is not None:
            add('local_continue', match['position'], confirmed=True, risk=match['risk'],
                committed=True, remote=match in spatial.get('remote_firing_positions', []), label='继续先前选定射位')
        elif target is not None and start and any(_distance(point, committed_goal) < 1e-5 for point in cells.values()):
            add('local_continue', committed_goal, committed=True, label='继续先前选定接敌点')

    for index, point in enumerate(sorted(firing, key=lambda p: (_distance(origin, p['position']),
                                                          len(p.get('threats', []))))):
        if len(options) >= limit:
            break
        add('local_fire_' + str(index), point['position'], confirmed=True, risk=point['risk'],
            remote=point in spatial.get('remote_firing_positions', []),
            label='沿连通路线前往全图粗采样射位' if point in spatial.get('remote_firing_positions', []) else '沿连通路线前往已查询射位')

    # A native firing query covers only a small local radius. When the target
    # is farther away, select a reachable topology goal close enough to try
    # another native firing query after moving. No line-of-fire is inferred.
    if len(options) < limit and target is None and start and steps and task.get('region_id') in regions:
        from strategic_regions import contains
        area = regions[task['region_id']]
        if not contains(origin, area):
            region_goals = sorted((route_distance[cell], cell) for cell in parents
                                  if first_step[cell] is not None and contains(cells[cell], area)
                                  and not _reserved(cells[cell], reservations))
            for index, (_, cell) in enumerate(region_goals):
                if len(options) >= limit:
                    break
                next_point = steps[first_step[cell]][0]
                if tuple(round(v, 5) for v in next_point) in approach_steps:
                    continue
                add('local_region_' + str(index), cells[cell], goal_cell=cell,
                    label='沿采样通路进入战术区域 ' + task['region_id'])

    if len(options) < limit and target is not None and start and steps and task.get('command') not in ('hold', 'recover'):
        enemy_position = target['position']
        weapon_range = unit.get('weapon_range', 0)
        weapon_range = float(weapon_range) if isinstance(weapon_range, (int, float)) and not isinstance(weapon_range, bool) else 0
        if not math.isfinite(weapon_range):
            weapon_range = 0
        current_distance = _distance(origin, enemy_position)
        candidates = []
        for cell in parents if weapon_range > 0 else ():
            point = cells[cell]
            distance = _distance(point, enemy_position)
            if distance < .13 or _distance(point, origin) <= .12 or _reserved(point, reservations):
                continue
            if weapon_range > 0 and current_distance > weapon_range and distance >= current_distance - .1:
                continue
            if first_step[cell] is None:
                continue
            length = route_distance[cell]
            if weapon_range > 0:
                range_error = max(0, distance - weapon_range * .85)
                # In-range but no known ray: moving around the obstruction is
                # useful, but avoid an arbitrarily distant wander.
                if current_distance <= weapon_range and distance > weapon_range * 1.1:
                    continue
            else:
                range_error = distance
            hint = task.get('region_id')
            region_bonus = 0 if hint and owners.get(tuple(round(v, 6) for v in point)) == hint else .08
            candidates.append((range_error * 5 + length + region_bonus, cell))
        for index, (_, cell) in enumerate(sorted(candidates)):
            if len(options) >= limit:
                break
            next_point = steps[first_step[cell]][0]
            if tuple(round(v, 5) for v in next_point) in approach_steps:
                continue
            add('local_approach_' + str(index), cells[cell], goal_cell=cell,
                label='沿采样通路接近 ' + str(target_id))

    report['options'] = len(options)
    if options:
        report['reason'] = ('native_firing_or_connected_approach' if firing else
                            'connected_approach_fire_lane_unknown' if target else
                            'connected_region_approach_fire_lane_unknown')
    elif target is None and task.get('region_id') in regions:
        from strategic_regions import contains
        report['reason'] = ('already_inside_region' if contains(origin, regions[task['region_id']]) else
                            'no_connected_region_approach')
    elif target is None:
        report['reason'] = 'no_live_target_or_local_objective'
    elif not start:
        report['reason'] = 'no_nearby_sampled_navigation_origin'
    elif not steps:
        report['reason'] = 'no_reachable_native_short_step'
    elif target is not None and not (isinstance(unit.get('weapon_range'), (int, float)) and
                                      not isinstance(unit.get('weapon_range'), bool) and
                                      math.isfinite(unit['weapon_range']) and unit['weapon_range'] > 0):
        report['reason'] = 'weapon_range_unknown'
    elif firing:
        report['reason'] = 'firing_destination_has_no_sampled_short_route'
    else:
        report['reason'] = 'no_connected_approach_or_fire_lane'
    return options, report
