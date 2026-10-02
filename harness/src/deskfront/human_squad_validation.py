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
    wait_for = value.get('wait_for', '')
    if not isinstance(wait_for, str):
        raise ValueError('commander_invalid_wait_condition')
    # Timing and trigger policy belong to Harness, never to free-form model text.
    out.update(stage=stage, review_after_s=20., wait_for=wait_for[:240])
    return out


