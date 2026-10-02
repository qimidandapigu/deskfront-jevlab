"""Ask the staged Godot engine for a bounded, per-request soldier shortlist."""
import json
import math
import time
import uuid
from pathlib import Path

from strategic_regions import memberships


def proposals(unit, assignment, regions, topology, *, visible_tanks=(), equipment=(), limit=12):
    cells = (topology or {}).get('cells', {})
    if not cells or not isinstance(assignment, dict):
        return []
    route = [key for key in assignment.get('region_path', []) if key in regions]
    target = assignment.get('region_id')
    if target in regions and target not in route:
        route.append(target)
    current = memberships(unit['position'], regions)
    # Current position and short next steps prevent a distant target-area grid
    # from leaving the soldier with no immediately useful action.
    allowed = list(dict.fromkeys([*current, *route]))
    if not allowed:
        return []
    points = []
    # Approaches remain on assigned/current regions and require native validation.
    if unit.get('weapon') != 'rocket':
        for gun in equipment:
            if not gun.get('capturable') or not isinstance(gun.get('position'), (list, tuple)):
                continue
            distance = math.dist(unit['position'], gun['position'])
            candidates = [(math.dist(point, gun['position']), math.dist(point, unit['position']), key, point)
                          for key in allowed for point in regions[key].get('cells', [])
                          if .04 <= math.dist(point, unit['position']) <= .42
                          and math.dist(point, gun['position']) < distance-.035]
            for remaining, step, key, point in sorted(candidates)[:2]:
                if any(math.dist(point, row['position']) < .055 for row in points):
                    continue
                points.append(dict(id='C'+str(len(points)+1), region_id=key, position=list(point),
                                   kind='equipment_approach', equipment_id=gun['id'],
                                   target_distance=round(remaining, 3)))
                if len(points) >= limit:
                    return points
    # Offer bounded steps toward a known tank, not an unvalidated direct rush.
    if unit.get('satchel_range', 0) > 0 and unit.get('satchel_ready_in', 1) <= 0:
        approach = []
        for tank in visible_tanks:
            tank_position = tank.get('position')
            if not isinstance(tank_position, (list, tuple)) or len(tank_position) != 2:
                continue
            current_distance = math.dist(unit['position'], tank_position)
            if current_distance <= unit['satchel_range']:
                check = unit.get('combat', {}).get('satchel_check', {})
                if check.get('target_id') != tank['id'] or check.get('reason') not in (
                    'muzzle_obstructed_or_blast_too_close', 'friendly_near_impact', 'friendly_in_firing_lane'):
                    continue
                throw_sites = []
                for region_id in allowed:
                    for point in regions[region_id].get('cells', []):
                        step = math.dist(unit['position'], point)
                        remaining = math.dist(point, tank_position)
                        if not .06 <= step <= .28 or not .24 <= remaining <= unit['satchel_range']:
                            continue
                        throw_sites.append((abs(remaining-.50)+step*.4, region_id, point, tank['id'], remaining))
                for _, region_id, point, target_id, remaining in sorted(throw_sites)[:6]:
                    if any(math.dist(point, row['position']) < .055 for row in points):
                        continue
                    points.append(dict(id='C'+str(len(points)+1), region_id=region_id,
                                       position=list(point), kind='anti_armor_throw_site',
                                       target_id=target_id, target_distance=round(remaining, 3)))
                continue
            for region_id in allowed:
                for point in regions[region_id].get('cells', []):
                    step = math.dist(unit['position'], point)
                    remaining = math.dist(point, tank_position)
                    if not .08 <= step <= .42 or remaining < .30 or current_distance-remaining < .06:
                        continue
                    approach.append((abs(remaining-.52)+step*.35, region_id, point, tank['id'], remaining))
        for _, region_id, point, target_id, remaining in sorted(approach)[:2]:
            if any(math.dist(point, row['position']) < .055 for row in points):
                continue
            points.append(dict(id='C'+str(len(points)+1), region_id=region_id,
                               position=list(point), kind='anti_armor_approach',
                               target_id=target_id, target_distance=round(remaining, 3)))
    for region_id in allowed:
        region = regions[region_id]
        members = region.get('cells', [])
        near = unit['position'] if region_id in current else region['center']
        ranked = sorted(members, key=lambda point: (math.dist(point, near), point))
        quota = 3 if region_id in current else 9 if region_id == target else 2
        for point in ranked[:quota]:
            if math.dist(point, unit['position']) < .02:
                continue
            if any(math.dist(point, other['position']) < .055 for other in points):
                continue
            points.append(dict(id='C' + str(len(points) + 1), region_id=region_id,
                               position=list(point), kind='navigation_sample'))
            if len(points) >= limit:
                return points
    return points


def query(path, state, unit, assignment, regions, topology, team, timeout=.8, visible_tanks=(), equipment=()):
    items = proposals(unit, assignment, regions, topology, visible_tanks=visible_tanks, equipment=equipment)
    if not items or not path:
        return dict(status='no_proposals', options=[])
    root = Path(path).parent
    token = uuid.uuid4().hex
    request = dict(id=token, run_id=state['run_id'], unit_id=unit['id'],
                   navigation_revision=state.get('navigation_revision'),
                   proposals=items)
    try:
        stem = 'soldier-candidates-' + team
        temporary = root / (stem + '-' + token + '.tmp')
        temporary.write_text(json.dumps(request), encoding='utf-8')
        temporary.replace(root / (stem + '-request.json'))
        marker = root / (stem + '-' + token + '.id.tmp')
        marker.write_text(token, encoding='ascii')
        marker.replace(root / (stem + '-request.id'))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                result = json.loads((root / (stem + '-response.json')).read_text(encoding='utf-8'))
                if result.get('id') == token and result.get('run_id') == state['run_id']:
                    return result
            except (OSError, ValueError):
                pass
            time.sleep(.015)
    except OSError:
        pass
    return dict(status='native_query_timeout', options=[])
