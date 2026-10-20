"""Read-only squad cooperation facts from native fire, ray and motion evidence.

The board identifies measured contributions and review candidates. It neither
selects a tactic nor claims that a recent shot has suppressed an opponent.
"""
import copy

from actor_roster import last_fire
from engagement_feedback import BLOCKED_REASONS


def build(world, team, members, contacts, squad, assignments, evidence, motions):
    now = world.get('time', 0)
    visible = {row['id'] for row in contacts if row.get('visible')}
    allies = {row['id'] for row in world.get('units', [])
              if row.get('faction') == team and row.get('hp', 0) > 0}
    rows, by_target, interference = {}, {}, []
    review_ids, preserve_ids = [], []
    for unit in members:
        uid = unit['id']
        fact = evidence.get(uid, {})
        ray = fact.get('firing_awareness', {})
        target = ray.get('target_id') if ray.get('target_id') in visible else None
        blocked = bool(target and ray.get('clear') is False and ray.get('reason') in BLOCKED_REASONS)
        blocker = ray.get('blocker_id') if blocked else None
        friendly = bool(blocked and ray.get('reason') in ('friendly_in_firing_lane', 'friendly_lane'))
        # Exact native blocker identity only; geometry never guesses a teammate.
        friendly_blocker = blocker if friendly and blocker in allies else None
        interruption = ('native_survival_override' if unit.get('survival_reason') or unit.get('order_mode') == 'self_preserve'
                        else 'heavy_suppression' if unit.get('suppression', 0) >= .72
                        else 'reloading' if unit.get('reload_remaining', 0) > 0
                        else 'empty_magazine' if unit.get('ammo') == 0
                        else ray.get('reason') if blocked else None)
        shot = last_fire(unit)
        recent_shot = bool(isinstance(shot, (int, float)) and 0 <= now-shot < 2.3)
        shot_target = unit.get('last_shot_target')
        shot_target = shot_target if shot_target in visible and not unit.get('support_activity') else None
        observed_target_fire = bool(recent_shot and shot_target)
        target_fire = bool(observed_target_fire and not interruption)
        # Reloading changes readiness; it cannot erase a shot already observed.
        # Neither field grants or denies another member permission to move.
        if observed_target_fire:
            by_target.setdefault(shot_target, []).append(uid)
        route = fact.get('route_progress', {})
        route_at = route.get('last_progress_at')
        advancing = bool(route.get('observed') and isinstance(route_at, (int, float))
                         and 0 <= now-route_at < 5 and motions.get(uid, {}).get('state') == 'executing')
        failure = fact.get('engagement_failure', {})
        blocked_s = failure.get('blocked_without_target_fire_s', 0) if blocked else 0
        assignment = assignments.get(uid, {})
        motion = motions.get(uid, {})
        review = ('motion_execution_failed' if motion.get('state') == 'failed'
                  else 'persistent_native_firing_obstruction' if blocked_s >= 5
                  else None)
        keep = bool(assignment.get('keep_available') and not review and not interruption
                    and (target_fire or advancing))
        if review:
            review_ids.append(uid)
        if keep:
            preserve_ids.append(uid)
        if friendly:
            interference.append(dict(shooter_id=uid, blocker_id=friendly_blocker,
                                     target_id=target, identity_status='native_reported' if friendly_blocker else 'unknown',
                                     basis='native_firing_awareness'))
        rows[uid] = dict(role=assignment.get('role'), keep_available=bool(assignment.get('keep_available')),
            motion_state=motion.get('state', 'unknown'), measured_route_advancing=advancing,
            recent_fire_observed=recent_shot, recent_fire_target_id=shot_target,
            recent_uninterrupted_target_fire=target_fire, interruption=interruption,
            blocked_target_id=target if blocked else None,
            blocker_id=friendly_blocker if friendly else blocker,
            blocked_without_target_fire_s=blocked_s,
            review_reason=review, effective_assignment_observed=keep)
    relations = []
    plan = squad.get('cooperation_plan') or {}
    for relation in plan.get('support_relations', []):
        spec = relation.get('spec', relation)
        supporters = spec.get('supporter_ids', [])
        threats = spec.get('threat_ids', [])
        measured = {target: [uid for uid in by_target.get(target, []) if uid in supporters]
                    for target in threats}
        relations.append(dict(relation_id=spec.get('relation_id'),
            supporter_ids=copy.deepcopy(supporters), assisted_member_ids=copy.deepcopy(spec.get('assisted_member_ids', [])),
            threat_ids=copy.deepcopy(threats), status=relation.get('status', 'unknown'), reason=relation.get('reason'),
            recent_observed_support_fire_by_target=measured,
            native_support_states=copy.deepcopy(relation.get('support_states', {})),
            native_maneuver_states=copy.deepcopy(relation.get('maneuver_states', {})),
            hit_or_suppression='read_native_attributed_result_else_unknown',
            support_is_movement_gate=False))
    handover = {uid: dict(local_action_active=b.get('local_action_active') is True,
                waiting=b.get('handover_waiting') is True,
                local_status=(b.get('local') or {}).get('status', 'none'))
        for uid, b in plan.get('bindings', {}).items() if uid in rows}
    return dict(members=rows, recent_fire_by_target=by_target, friendly_lane_interference=interference,
                support_relations=relations, handover=handover,
                review_member_ids=review_ids, effective_assignment_member_ids=preserve_ids,
                native_handoff={key: copy.deepcopy(squad[key]) for key in ('phase', 'reason', 'mover', 'support_ids', 'coordination', 'task_contract', 'task_review', 'assignment_execution') if key in squad},
                basis='native rays, recent observed shots and comparable route progress; assigned support, arrival and known enemy position do not prove covering fire; recent fire does not prove suppression or a future safe window; reload/readiness and uninterrupted-fire diagnostics are not movement admission; review lists are facts, not orders')
