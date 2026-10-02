"""Stable world-director contract and macro validation.

The contract is independent of director lifecycle and provider calls so tools and
tests can validate macro outputs without constructing a running world.
"""
import math
from .catalog import eligible
AXES = ('pressure', 'recovery', 'expansion', 'teaching', 'novelty')
PHASES = ('explore', 'build_up', 'peak', 'relax')
ROUTE_PREFERENCES = ('flank', 'direct', 'varied', 'none')
def eligible_choices(world):
    return eligible(world)


def validate_macro(value):
    if not isinstance(value, dict) or value.get('phase') not in PHASES:
        raise ValueError('invalid_macro_phase')
    h = value.get('hormones')
    if not isinstance(h, dict) or set(h) != set(AXES):
        raise ValueError('invalid_macro_axes')
    if any(type(h[k]) not in (int, float) or not math.isfinite(h[k]) or not 0 <= h[k] <= 1 for k in AXES):
        raise ValueError('invalid_macro_values')
    goal=value.get('next_goal')
    if not isinstance(value.get('current_analysis'),str) or not value['current_analysis'].strip():
        raise ValueError('missing_current_level_analysis')
    if (not isinstance(goal,dict) or goal.get('route_preference') not in ROUTE_PREFERENCES
            or any(not isinstance(goal.get(k),str) or not goal[k].strip()
                   for k in ('experience','tactical_problem','avoid','layout_change'))):
        raise ValueError('invalid_next_level_goal')
    return dict(phase=value['phase'], hormones=dict(h), reason=str(value.get('reason', ''))[:300],
                player_assessment=str(value.get('player_assessment', '证据不足'))[:400],
                current_analysis=value['current_analysis'][:500],
                next_goal={k:goal[k][:240] for k in ('experience','tactical_problem','avoid','layout_change')}
                | {'route_preference':goal['route_preference']})

