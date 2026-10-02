"""Preserve engine query provenance when making the per-soldier view."""
from lm_controller import observation as native_observation


def observation(state, unit, memory):
    result = native_observation(state, unit, memory)
    if 'navigation_revision' in state:
        result['navigation_revision'] = state['navigation_revision']
    for field in ('cover_slot', 'cover_step', 'posture_order'):
        if field in unit:
            result['self'][field] = unit[field]
    return result
