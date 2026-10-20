"""Per-member native connectivity facts; never choose or repair a tactic."""
from strategic_regions import navigation_anchor


def build(members, regions, topology, destination_ids, goal_id=None):
    access, destinations = {}, set(destination_ids)
    for unit in members:
        anchor = navigation_anchor(unit['position'], regions, topology)
        pending = [key for key in anchor['anchor_regions'] if key in regions]
        connected = set(pending)
        while pending:
            for other in regions[pending.pop()].get('neighbors', []):
                if other in regions and other not in connected:
                    connected.add(other)
                    pending.append(other)
        active = sorted(connected & destinations)
        access[unit['id']] = dict(
            anchor_regions=list(anchor['anchor_regions']),
            reachable_destination_ids=active,
            reachable_destination_count=len(active),
            selected_goal_reachable=goal_id in connected if goal_id else None,
            status=('anchor_unresolved' if not connected else
                    'no_current_stage_destination' if not active else 'connected'),
        )
    return dict(members=access,
                basis='native sampled graph; actor-to-anchor and actual movement still require engine validation',
                policy='one disconnected member does not stop other members; local routes do not imply reaching the team goal')


def destinations(facts):
    return set().union(*(set(row['reachable_destination_ids']) for row in facts['members'].values()))
