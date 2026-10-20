"""Measured execution facts, separate from strategic outcome and new proposals."""
import math


def _point(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(v, (int, float)) and math.isfinite(v) for v in value))


def _assignment_identity(assignment):
    # Menu IDs, source labels and order IDs are not physical route identity.
    return (assignment.get('role'), tuple(assignment.get('position', [])),
            tuple(tuple(p) for p in assignment.get('route_positions', [])))


def observe_route_progress(history, unit, motion, assignment, cursor, now):
    """Return true only after comparable native samples establish movement.

    The engine's progress_at equals since on start: neither it nor a new order,
    shorter replacement route, or incremented cursor alone proves progress.
    """
    old = history.get('route_observation', {})
    position, destination = unit.get('position'), motion.get('destination')
    remaining = motion.get('remaining_length')
    if (not _point(position) or not _point(destination)
            or not isinstance(remaining, (int, float)) or not math.isfinite(remaining)):
        history['route_observation'] = dict(observed=False, state=motion.get('state', 'unobserved'))
        return False
    assignment_key = _assignment_identity(assignment)
    identity = (motion.get('source'), tuple(destination), motion.get('since'),
                motion.get('navigation_revision'), assignment_key)
    # Equivalent engine-retained orders keep since, destination and assignment.
    # A new physical attempt, navigation revision, source or task resets only
    # the comparison baseline, never the last real progress timestamp.
    same = old.get('identity') == identity
    alive_state = motion.get('state') in ('executing', 'holding', 'completed')
    moved = bool(_point(old.get('position')) and math.dist(position, old['position']) >= .002)
    progressed = bool(same and alive_state and moved
                      and remaining <= old.get('best_remaining', remaining) - .01)
    # Cursor increments caused by skipping an unreachable waypoint are not
    # arrivals. Only a measured arrival near the previous waypoint qualifies.
    cursor_advanced = bool(not same and alive_state and moved
        and assignment_key == old.get('assignment_identity')
        and motion.get('order_id') == old.get('order_id')
        and motion.get('navigation_revision') == old.get('navigation_revision')
        and isinstance(cursor, int) and isinstance(old.get('cursor'), int)
        and cursor > old['cursor'] and _point(old.get('destination'))
        and math.dist(position, old['destination']) <= .12)
    progressed = progressed or cursor_advanced
    # Sparse Harness snapshots may miss the start of a waypoint. The native
    # executor already samples remaining length; accept that sample only when
    # it records a real post-start reduction. Re-reading its timestamp does
    # not refresh our progress clock, and start_motion itself earns no credit.
    native_at, started, length = (motion.get('progress_at'), motion.get('since'),
                                  motion.get('route_length'))
    native_progress = bool(alive_state and all(isinstance(v, (int, float)) and math.isfinite(v)
        for v in (native_at, started, length)) and started < native_at <= now
        and length - remaining >= .01
        and native_at > history.get('route_progress_at', -1))
    measured_at = now if progressed else native_at if native_progress else None
    progressed = progressed or native_progress
    switches = history.get('route_replacements', 0)
    if old.get('observed') and assignment_key != old.get('assignment_identity'):
        switches += 1
    history['route_replacements'] = switches
    row = dict(observed=True, identity=identity, assignment_identity=assignment_key,
               order_id=motion.get('order_id'), source=motion.get('source'),
               navigation_revision=motion.get('navigation_revision'),
               state=motion.get('state'), reason=motion.get('reason', ''),
               destination=list(destination), cursor=cursor,
               remaining_length=max(0., remaining), sampled_at=now,
               best_remaining=(remaining if progressed or not same else old['best_remaining']),
               position=(list(position) if progressed or not same else old['position']))
    history['route_observation'] = row
    if progressed:
        history['route_progress_at'] = measured_at
    return progressed


def progress_evidence(history, now):
    row = history.get('route_observation', {})
    since = history.get('observed_since', now)
    last = history.get('route_progress_at')
    public = {key: row[key] for key in ('observed', 'order_id', 'source', 'state', 'reason',
              'remaining_length', 'cursor', 'sampled_at') if key in row}
    public.update(observed=bool(row.get('observed')), last_progress_at=last,
        seconds_without_progress=round(max(0., now - (last if last is not None else since)), 1),
        assignment_replacements=history.get('route_replacements', 0),
        basis='comparable remaining-route samples with movement, or native post-start route reduction; start/reissue is not progress')
    return dict(route_progress=public,
        seconds_without_strategic_progress=round(max(0., now-history.get('strategic_progress_at', since)), 1),
        seconds_without_strategic_approach=round(max(0., now-history.get('strategic_approach_at', since)), 1))
