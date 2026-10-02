"""Small, factual destination choices for a soldier's native pathfinder.

These are *destinations*, not region routes or movement commands. Topology
samples establish walkability at the endpoint; only an exact fresh native path
query establishes a sampled path to that endpoint. Missing samples stay unknown.
"""
import math

from strategic_regions import contains, memberships


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _point(value):
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(_number(v) for v in value)


def _fresh(unit, state, spatial, route_opportunities):
    stamp = spatial.get('sampled_at')
    now = state.get('time')
    if not _number(stamp) or not _number(now) or not 0 <= now - stamp <= 2:
        return 'stale' if _number(stamp) else 'unknown'
    origin = spatial.get('origin')
    if origin is not None and (not _point(origin) or math.dist(origin, unit['position']) > .15):
        return 'origin_changed'
    revision = spatial.get('navigation_revision')
    if revision is not None and revision != state.get('navigation_revision'):
        return 'navigation_changed'
    query_status = route_opportunities.get('query_status', {}) if isinstance(route_opportunities, dict) else {}
    if isinstance(query_status, dict) and query_status.get(unit['id'], 'fresh') != 'fresh':
        return str(query_status[unit['id']])
    return 'fresh'


def _topology_points(state):
    cells = (state.get('strategic_topology') or {}).get('cells') or {}
    return {key: list(point) for key, point in cells.items() if _point(point)}


def _exact_sample(position, cells, cell_id=None):
    if cell_id in cells and math.dist(position, cells[cell_id]) < 1e-6:
        return list(cells[cell_id])
    return next((list(point) for point in cells.values() if math.dist(position, point) < 1e-6), None)


def _reserved_points(unit, state, allies):
    points = []
    for ally in allies:
        if ally.get('id') == unit['id']:
            continue
        for field in ('position', 'reserved_position'):
            if _point(ally.get(field)):
                points.append(ally[field])
    # Explicit future reservations may be provided by the team's shared board.
    # An arbitrary old unit goal is not treated as an active reservation.
    reservations = state.get('position_reservations') or {}
    records = reservations.values() if isinstance(reservations, dict) else reservations if isinstance(reservations, list) else []
    for record in records:
        if isinstance(record, dict) and record.get('unit_id') != unit['id'] and _point(record.get('position')):
            points.append(record['position'])
    return points


def _available(point, reserved, selected):
    return all(math.dist(point, other) >= .09 for other in (*reserved, *selected))


def _path_fact(risk):
    if not isinstance(risk, dict) or risk.get('status') != 'sampled':
        return {'status': 'unknown'}
    out = {'status': 'sampled'}
    for field in ('travel_s', 'exposed_s', 'peak_attackers', 'endpoint_attackers'):
        value = risk.get(field)
        if _number(value) and value >= 0:
            out[field] = round(value, 2) if field.endswith('_s') else value
    return out


def _exact_risk(spatial, point):
    unreachable = False
    for field in ('remote_firing_positions', 'firing_positions', 'navigation_steps', 'route_forecasts'):
        for sample in spatial.get(field, []):
            if isinstance(sample, dict) and _point(sample.get('position')) and math.dist(point, sample['position']) < 1e-6:
                risk = sample.get('risk')
                if isinstance(risk, dict) and risk.get('status') == 'sampled':
                    return _path_fact(risk)
                if isinstance(risk, dict) and risk.get('status') == 'unreachable':
                    unreachable = True
    return {'status': 'unreachable' if unreachable else 'unknown'}


def _sample_in_region(region_id, regions, cells, near, reserved, selected, spatial=None):
    region = regions.get(region_id)
    if not isinstance(region, dict):
        return None
    samples = [point for point in cells.values() if contains(point, region) and _available(point, reserved, selected)
               and (spatial is None or _exact_risk(spatial, point)['status'] != 'unreachable')]
    return min(samples, key=lambda p: (math.dist(p, near), p)) if samples else None


def build(unit, state, regions, route_opportunities, spatial, task, allies):
    """Return up to four distinct-region destination candidates, never orders.

    ``spatial`` is the one soldier's native query. ``route_opportunities`` is
    the compact shared region-facts output; its paths/first steps are ignored.
    The caller must send a selected destination to the native path validator.
    """
    spatial = spatial or {}
    task = task or {}
    route_opportunities = route_opportunities or {}
    cells = _topology_points(state)
    if not cells or not _point(unit.get('position')):
        return dict(query_status='unknown', options=[], reason='no_native_topology_or_unit_position')
    status = _fresh(unit, state, spatial, route_opportunities)
    reserved = _reserved_points(unit, state, allies)
    chosen = []
    selected_points = []
    selected_regions = set()
    hint = task.get('region_hint') or task.get('region_id')
    flag = (state.get('objective') or {}).get('position')
    flag_regions = memberships(flag, regions) if _point(flag) else []
    if _point(flag) and not flag_regions:
        # The flag may lie between topology samples. A nearby *sample inside
        # the capture radius* is a possible destination; the flag center itself
        # is never promoted to a walkable point merely because it has a region.
        capture_radius = (state.get('objective') or {}).get('radius')
        if _number(capture_radius) and capture_radius > 0:
            nearby = min(cells.values(), key=lambda p: (math.dist(p, flag), p))
            if math.dist(nearby, flag) <= capture_radius:
                flag_regions = memberships(nearby, regions)

    def add(region_id, point, source, targets=(), risk=None, fire='unknown'):
        if region_id not in regions or region_id in selected_regions or not _available(point, reserved, selected_points):
            return False
        path = _path_fact(risk) if risk is not None else _exact_risk(spatial, point) if status == 'fresh' else {'status': 'unknown'}
        chosen.append(dict(region_id=region_id, position=list(point), source=source,
                           targets=sorted(set(targets)), fire_evidence=fire,
                           path_evidence=path,
                           tags=[tag for tag, yes in (('commander_hint', region_id == hint),
                                                       ('objective', region_id in flag_regions)) if yes]))
        selected_regions.add(region_id)
        selected_points.append(point)
        return True

    # At most two distinct, fresh, *native-reachable* distant firing samples.
    # Keep room for the commander's current area and the flag. A standing ray
    # is evidence for the exact sampled endpoint only, never for its region.
    if status == 'fresh':
        remote = []
        target = task.get('target_id')
        for sample in spatial.get('remote_firing_positions', []):
            point = sample.get('position') if isinstance(sample, dict) else None
            risk = sample.get('risk') if isinstance(sample, dict) else None
            if not _point(point) or not isinstance(risk, dict) or risk.get('status') != 'sampled':
                continue
            sample_point = _exact_sample(point, cells, sample.get('cell_id'))
            if sample_point is None or not _available(sample_point, reserved, selected_points):
                continue
            if sample.get('reachable') is False:
                continue
            targets = [name for name in sample.get('targets', []) if isinstance(name, str)]
            if not targets:
                continue
            if _number(sample.get('observed_at')) and abs(sample['observed_at'] - spatial['sampled_at']) > 2:
                continue
            for region_id in memberships(sample_point, regions):
                remote.append((target not in targets if target else False,
                               risk.get('travel_s', math.inf) if _number(risk.get('travel_s')) else math.inf,
                               region_id, sample_point, targets, risk))
        remote.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
        count = 0
        for _, _, region_id, point, targets, risk in remote:
            if add(region_id, point, 'remote_firing', targets, risk, 'sampled_standing_ray'):
                count += 1
            if count >= 2:
                break

    for region_id, source, near in ((hint, 'commander_hint', regions.get(hint, {}).get('center') if hint in regions else None),
                                    *((key, 'objective', flag) for key in flag_regions)):
        if region_id in selected_regions or region_id not in regions:
            continue
        near = near if _point(near) else unit['position']
        point = _sample_in_region(region_id, regions, cells, near, reserved, selected_points,
                                  spatial if status == 'fresh' else None)
        if point is not None:
            add(region_id, point, source)

    # A shared region fact may supply additional goals, but its aggregated
    # firing/risk summaries cannot be transferred to an arbitrary point.
    routes = route_opportunities.get('route_options', {}) if isinstance(route_opportunities, dict) else {}
    rows = routes.get(unit['id'], []) if isinstance(routes, dict) else []
    for row in rows:
        if len(chosen) >= 4:
            break
        region_id = row.get('goal_region') if isinstance(row, dict) else None
        if region_id not in regions or region_id in selected_regions:
            continue
        near = regions[region_id].get('center')
        point = _sample_in_region(region_id, regions, cells, near if _point(near) else unit['position'], reserved,
                                  selected_points, spatial if status == 'fresh' else None)
        if point is not None:
            add(region_id, point, 'region_opportunity')

    return dict(query_status=status, options=chosen[:4],
                basis='Endpoint walkability: native topology sample. Objective destination is sampled within capture radius, not assumed at flag center. Native path evidence applies only to the exact fresh point; unknown is not unreachable. Firing: approximate standing ray to stationary target, not hit/safety guarantee. Current teammate positions and explicit reservations are excluded; unreported future goals remain unknown.')
