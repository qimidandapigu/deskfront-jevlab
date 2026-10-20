"""Read-only comparison of direct attack and using a discovered weapon.

Only consumes existing native samples and accepted plans. It never queries the
engine, chooses an actor, rejects a plan, or wakes a model lane.
"""
import copy
import math

from battlefield_equipment import _number, _point


def _assignment(squad, uid):
    return squad.get('assignment_tokens', {}).get(uid) or squad.get('order_id')


def capture_sample(world, unit, squad, result, equipment):
    """Remember at most two native checked approaches per known weapon."""
    guns = {g['id']: g for g in equipment if g.get('capturable') is True}
    rows = []
    verified = (result.get('status') == 'fresh' and bool(world.get('run_id'))
                and result.get('run_id') == world.get('run_id') and result.get('unit_id') == unit['id']
                and result.get('navigation_revision') == world.get('navigation_revision')
                and world.get('navigation_revision') is not None
                and _number(result.get('sampled_at')) and _point(result.get('unit_position')))
    if verified:
        for row in result.get('options', []):
            gun = guns.get(row.get('equipment_id'))
            if (gun and row.get('kind') == 'equipment_approach' and row.get('purpose') == 'capture'
                    and _point(row.get('position')) and _number(row.get('path_length'))
                    and row['path_length'] >= 0 and _point(gun.get('position'))
                    and sum(r['equipment_id'] == gun['id'] for r in rows) < 2):
                rows.append(dict(equipment_id=gun['id'], position=copy.deepcopy(row['position']),
                                 gun_position=copy.deepcopy(gun['position']), path_length=row['path_length']))
    return dict(run_id=result.get('run_id'), navigation_revision=result.get('navigation_revision'),
                assignment=result.get('assignment_token') or result.get('order_id'), time=result.get('sampled_at'),
                origin=copy.deepcopy(result.get('unit_position')),
                status='fresh' if verified else 'unverified_query', rows=rows)


def annotate_approaches(opportunities, world, members, squad, samples):
    """Attach cost evidence, never an executable cached destination or choice."""
    units = {u['id']: u for u in members if u.get('hp', 0) > 0}
    now = world.get('time', 0)
    for opportunity in opportunities:
        for candidate in opportunity['candidates']:
            uid = candidate['id']
            unit, sample = units.get(uid), samples.get(uid)
            if not unit or not sample:
                continue
            age = now - sample['time'] if _number(sample.get('time')) else -1
            valid = (bool(world.get('run_id')) and sample.get('run_id') == world.get('run_id')
                     and world.get('navigation_revision') is not None
                     and sample.get('navigation_revision') == world.get('navigation_revision')
                     and bool(_assignment(squad, uid))
                     and sample.get('assignment') == _assignment(squad, uid)
                     and 0 <= age <= 3 and _point(sample.get('origin'))
                     and _point(unit.get('position')) and math.dist(sample['origin'], unit['position']) <= .04)
            if not valid:
                candidate['approach_sample'] = dict(status='stale_revalidation_required')
                continue
            if sample.get('status') != 'fresh':
                candidate['approach_sample'] = dict(status='query_unavailable_not_unreachable')
                continue
            gun = next((g for g in world.get('at_guns', []) if g.get('id') == opportunity['equipment_id']), {})
            rows = [r for r in sample['rows'] if r['equipment_id'] == opportunity['equipment_id']
                    and gun.get('capturable') is True and _point(gun.get('position'))
                    and math.dist(r['gun_position'], gun['position']) < .001]
            if not rows:
                candidate['approach_sample'] = dict(status='no_local_sample_not_unreachable')
                continue
            # Keep both samples, not a hidden tactical ranking. These costs are
            # from a recent query; final admission and safety still need checks.
            candidate['approach_sample'] = dict(status='recent_native_paths', age_s=round(age, 1),
                paths=[dict(path_length=round(r['path_length'], 3),
                            end_distance=round(math.dist(r['position'], gun['position']), 3),
                            inside_capture_radius=(math.dist(r['position'], gun['position']) <= gun['capture_radius']
                                                   if _number(gun.get('capture_radius')) else None)) for r in rows])


class EquipmentReview:
    def __init__(self):
        self.identity = None
        self.time = -1
        self.episodes = {}

    def apply(self, opportunities, world, members, contacts, plan, execution, squad, samples):
        """Enrich an existing opportunity with actual progress, not policy."""
        now = world.get('time', 0)
        mission = world.get('world_growth', {}).get('mission', {})
        identity = (world.get('run_id'), mission.get('operation_id'), mission.get('index'))
        if identity != self.identity or now < self.time:
            self.identity, self.episodes = identity, {}
        self.time = now
        goal = plan.get('equipment_goal') or {}
        ids = {o['equipment_id'] for o in opportunities}
        self.episodes = {key: value for key, value in self.episodes.items() if key in ids}
        by_unit = {u['id']: u for u in members if u.get('hp', 0) > 0}
        annotate_approaches(opportunities, world, members, squad, samples)
        for opportunity in opportunities:
            equipment_id = opportunity['equipment_id']
            target_ids = tuple(sorted(a['id'] for a in opportunity['visible_armor']))
            for armor in opportunity['visible_armor']:
                for weapon in armor['own_weapon_comparison']:
                    uid = weapon['unit_id']
                    unit, facts = by_unit.get(uid, {}), execution.get('members', {}).get(uid, {})
                    shot = unit.get('last_shot_at')
                    weapon['seconds_since_actual_fire'] = (round(now-shot, 1)
                        if _number(shot) and 0 <= shot <= now else None)
                    targets = unit.get('combat', {}).get('engageable_targets')
                    weapon['target_engageable'] = armor['id'] in targets if isinstance(targets, list) else None
                    for key in ('fire_block_reason', 'seconds_without_strategic_progress'):
                        if key in facts:weapon[key] = copy.deepcopy(facts[key])
            episode = self.episodes.get(equipment_id)
            if goal.get('equipment_id') != equipment_id or goal.get('phase') != 'defer' or not target_ids:
                self.episodes.pop(equipment_id, None)
                continue
            if not episode or episode['targets'] != target_ids:
                episode = dict(since=now, targets=target_ids, count=0, last_request=None, fired=False)
                self.episodes[equipment_id] = episode
            request_id = plan.get('request_id')
            if request_id and request_id != episode['last_request']:
                episode['count'] += 1
                episode['last_request'] = request_id
            episode['fired'] |= any(_number(u.get('last_shot_at')) and episode['since'] < u['last_shot_at'] <= now
                                    and u.get('last_shot_target') in target_ids for u in by_unit.values())
            elapsed = round(max(0, now-episode['since']), 1)
            opportunity['defer_review'] = dict(objective='eliminate_visible_armor',
                accepted_defer_plans=episode['count'], observed_for_s=elapsed,
                actual_fire_at_these_targets_since_defer=episode['fired'],
                repeated_without_observed_fire=(episode['count'] >= 2 and elapsed >= 10 and not episode['fired']))
        return opportunities
