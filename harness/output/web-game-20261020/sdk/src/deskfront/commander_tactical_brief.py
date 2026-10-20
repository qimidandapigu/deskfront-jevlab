"""Optional model-declared diagram data; never a command or tactical policy.

References are resolved only from this faction's recorded commander request.
A malformed diagram is omitted without rejecting the actual commander plan.
"""
import copy
import math


MANEUVERS = {'advance', 'flank', 'bound', 'hold', 'regroup', 'engage', 'recover', 'reconnoitre'}
ACTIONS = {'move', 'attack', 'suppress', 'capture', 'support', 'hold', 'reconnoitre', 'recover'}


def _descriptor(row, own=False, equipment=False):
    capabilities = row.get('capabilities', {})
    kind = ('mortar' if equipment else
            'tank' if row.get('kind') == 'tank' or row.get('tank') is True or capabilities.get('mode') == 'vehicle' else
            'crew' if row.get('equipment_id') or row.get('equipment_role') or capabilities.get('mode') == 'equipment_crew' else
            'soldier')
    label = {'mortar': '迫击炮', 'tank': '坦克', 'crew': '炮组', 'soldier': '步兵'}[kind]
    knowledge = ('own_at_decision' if own else 'discovered_equipment' if equipment else
                 'visible_at_decision' if row.get('visible') is True else 'last_known_at_decision')
    return dict(id=row['id'], kind=kind, label=label, knowledge=knowledge,
                affiliation='own' if own else 'neutral' if row.get('faction') == 'neutral' else 'opponent')


def _targets(context):
    targets = {}
    for row in context.get('members', []):
        if isinstance(row, dict) and isinstance(row.get('id'), str):
            targets[row['id']] = _descriptor(row, own=True)
    for row in context.get('support_assets', []):
        if isinstance(row, dict) and isinstance(row.get('id'), str):
            targets[row['id']] = _descriptor(row, own=True)
    for row in context.get('contacts', []):
        if isinstance(row, dict) and isinstance(row.get('id'), str):
            targets[row['id']] = _descriptor(row)
    for row in context.get('battlefield_equipment', []):
        if not isinstance(row, dict) or not isinstance(row.get('id'), str):
            continue
        own = row.get('faction') == context.get('faction')
        targets[row['id']] = _descriptor(row, own=own, equipment=True)
        # Discovered equipment may identify unseen crew, but does not disclose
        # their location, private orders, health, or current visibility.
        for crew in row.get('crew', []):
            if isinstance(crew, dict) and isinstance(crew.get('id'), str):
                descriptor = _descriptor(dict(crew, equipment_id=row['id']), own=own)
                if not own and crew.get('visible') is not True:
                    descriptor['knowledge'] = 'known_equipment_assignment'
                if crew['id'] in targets:
                    targets[crew['id']].update(kind='crew', label='炮组')
                else:
                    targets[crew['id']] = descriptor
    return targets


def validate_tactical_brief(value, regions, context):
    """Return a bounded diagram, or None; do not parse objective/risk prose."""
    if (not isinstance(value, dict) or not isinstance(value.get('maneuver'), str)
            or value['maneuver'] not in MANEUVERS):
        return None
    steps = value.get('steps')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 3:
        return None
    targets = _targets(context)
    normalized = []
    for step in steps:
        if (not isinstance(step, dict) or not isinstance(step.get('action'), str)
                or step['action'] not in ACTIONS):
            return None
        ids = step.get('target_ids', [])
        if (not isinstance(ids, list) or len(ids) > 3
                or any(not isinstance(uid, str) or uid not in targets for uid in ids)):
            return None
        ids = list(dict.fromkeys(ids))
        region = step.get('region_id')
        if region is not None and (not isinstance(region, str) or region not in regions):
            return None
        if not ids and region is None:
            return None
        row = dict(action=step['action'], target_ids=ids,
                   targets=[copy.deepcopy(targets[uid]) for uid in ids])
        if region is not None:
            row['region_id'] = region
            descriptor = dict(id=region, kind='region', label='目标区域', knowledge='native_offered_region')
            point = regions[region].get('center')
            if (isinstance(point, (list, tuple)) and len(point) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in point)):
                descriptor['world_position'] = list(point)
            row['targets'].append(descriptor)
        normalized.append(row)
    return dict(maneuver=value['maneuver'], steps=normalized,
                source='commander_declared_plan', status='planned')


def brief_signature(value):
    """Only declared actions/targets/order count as a tactical display change."""
    if not isinstance(value, dict) or not value:
        return None
    return (value.get('maneuver'), tuple(
        (row.get('action'), tuple(sorted(row.get('target_ids', []))), row.get('region_id'))
        for row in value.get('steps', [])))
