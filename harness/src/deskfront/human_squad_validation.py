"""Pure validation helpers for commander plans.

Validation is deliberately independent from controller state. The controller
continues to expose these helpers for compatibility, while this module owns the
shape checks and bounded plan normalization.
"""

import math

from human_squad_contract import STAGES

def _position(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(type(n) in (int, float) and math.isfinite(n) for n in value))


def validate_plan(value, regions):
    if not isinstance(value, dict) or value.get('region_id') not in regions:
        raise ValueError('commander_region_not_in_native_catalog')
    out = {'region_id': value['region_id']}
    for field in ('objective', 'risk'):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError('commander_missing_' + field)
        out[field] = value[field][:800]
    region = regions[out['region_id']]
    out.update(position=list(region['center']), radius=min(.3, max(.06 if out['region_id']=='objective_flag' else .1, region.get('radius', .15))))
    stage = value.get('stage', 'approach')
    if stage not in STAGES:
        raise ValueError('commander_invalid_stage')
    if 'allowed_stages' in region and stage not in region['allowed_stages']:
        raise ValueError('commander_stage_not_in_region_admission')
    wait_for = value.get('wait_for', '')
    if not isinstance(wait_for, str):
        raise ValueError('commander_invalid_wait_condition')
    # Timing and trigger policy belong to Harness, never to free-form model text.
    out.update(stage=stage, review_after_s=20., wait_for=wait_for[:240])
    return out


def current_region_stage_admission(context, exhausted_reason=''):
    """Admit phases from current facts, never choose the next tactical phase.

    The exhausted approach is retained by the controller for this region visit.
    A stage name or narrative cannot erase it. Missing native fire facts remain
    unknown; recent shot labels alone do not authorize a stationary combat phase.
    """
    mission = context.get('mission_status', {})
    allowed = set(STAGES)
    evidence = {}
    if exhausted_reason:
        allowed.clear()
        contacts = context.get('contacts', [])
        visible = {row['id'] for row in contacts if row.get('visible') is True and row.get('id')}
        native_targets = sorted({target
            for row in context.get('execution_evidence', {}).get('members', {}).values()
            for target in row.get('engageable_visible_targets', []) if target in visible})
        plan = context.get('current_plan', {})
        present = [uid for uid, distance in context.get('target_distance', {}).items()
                   if isinstance(distance, (int, float)) and distance <= plan.get('radius', .1)]
        # Arrival permits establishing local fire on a known enemy. Once an
        # idle wait expires, this needs current native engagement evidence;
        # an old shot or merely changing the stage is not such evidence.
        idle_review_due = bool(context.get('stage_status', {}).get('review_due') and mission.get('all_stationary'))
        if visible and present and (native_targets or not (idle_review_due or mission.get('wait_expired'))):
            allowed.add('engage')
            evidence['engage'] = dict(present_member_ids=present, visible_target_ids=sorted(visible),
                                      native_engageable_target_ids=native_targets)
        if mission.get('acute_recovery'):
            allowed.add('recover')
            evidence['recover'] = 'current_native_pressure_reload_or_survival'
        if mission.get('defending_flag') or context.get('defensive_mission'):
            allowed.add('hold')
            evidence['hold'] = 'current_defensive_objective'
    if mission.get('wait_expired'):
        allowed.discard('recover')
        if not (mission.get('defending_flag') or context.get('defensive_mission')):
            allowed.discard('hold')
    return dict(allowed_stages=sorted(allowed), exhausted_approach_reason=exhausted_reason,
                stage_evidence=evidence,
                deadline_policy='same_region_preserves_original_review_deadline_and_failure_history')
