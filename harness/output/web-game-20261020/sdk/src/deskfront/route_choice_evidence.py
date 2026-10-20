"""Compare offered route geometry, without selecting or rejecting any route.

All distances are native world units. These waypoint polylines are estimates,
not newly queried actor paths, travel times, or proof of a firing position.
"""
import math


def _point(value):
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
        for v in value)


def execution_polyline(origin, points, endpoint):
    """Nominal new-assignment legs, matching native member_next_goal's cursor.

    For multiple points the first is the source region, not a point the actor
    walks backwards to touch. Native near-node skipping and obstacle detours
    still make this an estimate, not an exact actor path.
    """
    legs = list(points[1:] if len(points) > 1 else points)
    if not legs or math.dist(legs[-1], endpoint) > .001:
        legs.append(endpoint)
    return [origin, *legs]


def annotate(options, units, contacts, goal):
    """Add comparable, bounded facts; preserve the exact menu and its choices."""
    visible = {c['id']: c['position'] for c in contacts
               if c.get('id') and c.get('visible') and _point(c.get('position'))}
    for unit in units:
        menu = options.get(unit['id'], {})
        if not _point(unit.get('position')):
            continue
        estimates = {}
        clear_targets = {}
        for key, row in menu.items():
            points = row.get('route_positions')
            if not points or not all(_point(p) for p in points) or not _point(row.get('position')):
                continue
            points = execution_polyline(unit['position'], points, row['position'])
            distance = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
            estimates[key] = distance
            fact = dict(polyline_length=round(distance, 3),
                        basis='waypoint_estimate_not_native_actor_path')
            if _point(goal):
                start_distance = math.dist(points[0], goal)
                fact['max_goal_distance_increase'] = round(max(
                    0., *(math.dist(p, goal) - start_distance for p in points[1:])), 3)
            weapon_range = unit.get('weapon_range')
            clear = set()
            if isinstance(weapon_range, (int, float)) and weapon_range > 0:
                for check in row.get('endpoint_obstructions', []):
                    tid = check.get('target_id')
                    if (tid in visible and check.get('crossing_hard_cover_ids') == []
                            and math.dist(row['position'], visible[tid]) <= weapon_range):
                        clear.add(tid)
            clear_targets[key] = clear
            fact['in_range_2d_clear_target_ids'] = sorted(clear)
            fact['native_firing_line'] = 'unknown'
            row['route_comparison'] = fact
        if not estimates:
            continue
        shortest = min(estimates.values())
        for key, distance in estimates.items():
            fact = menu[key]['route_comparison']
            fact['extra_length_vs_shortest'] = round(max(0., distance - shortest), 3)
            fact['length_ratio_vs_shortest'] = round(distance / shortest, 2) if shortest > .001 else None
            # Same-target geometric evidence is comparable; unknown target
            # checks are never promoted to clear. No "best route" is asserted.
            targets = clear_targets[key]
            alternatives = sorted((other for other, value in estimates.items()
                                   if value < distance - .025 and targets
                                   and targets.issubset(clear_targets[other])),
                                  key=lambda other: (estimates[other], other))
            fact['shorter_same_target_checks'] = [dict(
                position=list(menu[other]['position']),
                region_path=list(menu[other].get('region_path', [])),
                polyline_length=round(estimates[other], 3),
                shared_target_ids=sorted(targets),
                native_firing_line='unknown') for other in alternatives[:1]]
