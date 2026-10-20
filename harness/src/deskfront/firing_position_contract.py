"""Native firing-position facts shared by presentation, review and admission.

A connected destination and a 2D clear line never establish a firing position.
Only the current actor's native check can prove this exact point ineffective.
No path, target or replacement task is selected here.
"""
import math


def _point(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(type(n) in (int, float) and math.isfinite(n) for n in value))


def has_active_breach(unit):
    """Preserve useful native wall-breaching options and in-flight operations."""
    combat = unit.get('combat') or {}
    if any(isinstance(row, dict) and row.get('mode') == 'breach' and row.get('fireable') is True
           for row in (combat.get('rocket_fire_options') or [])):
        return True
    execution = combat.get('cover_breach') or combat.get('cover_breach_execution') or unit.get('cover_breach_execution') or {}
    return execution.get('status') in ('aiming', 'launched') or execution.get('phase') in ('aiming', 'launched')


def proven_blocked_position(unit, destination, now, *, tolerance=.04):
    """Return a fact only for a native-blocked, explicitly fireless endpoint.

    Unknown/missing target lists are not evidence of no fire opportunity.
    A blocked ray to one enemy must not invalidate fire against another enemy.
    Callers separately preserve recovery, recent shots and active movement.
    """
    if has_active_breach(unit):
        return {}
    position = unit.get('position')
    if not _point(position) or not _point(destination) or math.dist(position, destination) > tolerance:
        return {}
    combat = unit.get('combat') or {}
    fact = combat.get('firing_awareness') or {}
    targets = [value for value in (combat.get('engageable_targets'), fact.get('engageable_visible_targets'))
               if isinstance(value, list)]
    if not targets or any(targets):
        return {}
    if (fact.get('clear') is not False or fact.get('reason') not in ('muzzle_cover', 'target_occluded')
            or not fact.get('target_id') or not fact.get('blocker_id')):
        return {}
    return dict(status='native_blocked_at_endpoint', position=list(position),
                destination=list(destination), target_id=fact['target_id'],
                blocker_id=fact['blocker_id'], reason=fact['reason'], sampled_at=now,
                basis='current native firing check at actor position; no effective target reported')


def describe(unit, destination, now, obstructions=()):
    fact = proven_blocked_position(unit, destination, now)
    if fact:
        return fact
    crossed = [row['target_id'] for row in obstructions
               if row.get('target_id') and row.get('crossing_hard_cover_ids')]
    return dict(status='geometry_obstructed' if crossed else 'unverified',
                crossing_targets=crossed, native_firing_line='unknown',
                basis='movement candidate; 2D obstruction is advisory, native firing position unverified')


def repeated_failed_assignment(unit, assignment, accepted, now):
    """Reject only re-committing the currently proven ineffective fire site.

    Review first establishes that recovery and productive motion do not apply.
    Moving to another endpoint remains legal, even across obstructed geometry.
    """
    reviewed = (accepted.get('unavailable_reason') == 'firing_assignment_unresolved'
                or (accepted.get('firing_review') or {}).get('review_required') is True)
    if assignment.get('role') not in ('establish_fire', 'fire_support') or not reviewed:
        return {}
    return proven_blocked_position(unit, assignment.get('position'), now)
