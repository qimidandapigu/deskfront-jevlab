"""Bounded Harness handoff bookkeeping; never executes or replays an order.

Protection comes from a real native accepted short action. Calculating a model
answer does not acquire execution ownership. Waiting keeps only intent metadata;
the next full candidate is rebuilt from a fresh observation at the boundary.
"""
import copy

TERMINAL = {'completed', 'failed', 'cancelled', 'expired', 'rejected'}


def squad(owner):
    return owner.world.get('squad_behavior', {}).get('squads', {}).get(owner.squad_id, {})


def protected_members(execution, now):
    rows = execution.get('bindings', {}) if isinstance(execution, dict) else {}
    result = {}
    for uid, row in rows.items():
        if not isinstance(row, dict) or row.get('status') in TERMINAL:
            continue
        local = row.get('local', {})
        active = row.get('local_action_active') is True
        # Compatibility with older frozen native snapshots. Never infer a
        # protected action from a model request, pending receipt or role label.
        if 'local_action_active' not in row:
            active = isinstance(local, dict) and local.get('status') == 'active'
        until = local.get('until', row.get('until')) if isinstance(local, dict) else row.get('until')
        if active and isinstance(until, (int, float)) and not isinstance(until, bool) and now < until:
            result[uid] = dict(assignment_id=row.get('assignment_id', row.get('assignment_token')),
                local_action_revision=row.get('local_action_revision'), until=until,
                action_id=local.get('action_id', local.get('id')) if isinstance(local, dict) else None)
    return result


def context(owner):
    protected = protected_members(squad(owner).get('cooperation_plan', {}), owner.world.get('time', 0))
    waiting = getattr(owner, 'pending_handover', None) or {}
    return dict(protected_member_ids=sorted(protected), pending_member_ids=list(waiting.get('member_ids', [])),
                by_member=protected, waiting_intent=copy.deepcopy(waiting) if waiting else None,
                basis='native accepted finite local action; model calculation is not an action lock')


def defer(owner, member_ids, *, request=None, intent=None, reason='native_local_action_active'):
    now, wall = owner.world.get('time', 0), owner.clock()
    previous = getattr(owner, 'pending_handover', None) or {}
    request = request or {}
    protected = protected_members(squad(owner).get('cooperation_plan', {}), now)
    # An unchanged pending episode cannot slide its original expiry. A new
    # answer replaces only the latest intent description, never old coordinates.
    deadline = min(float(request.get('started_game', now)) + float(owner.config.get('handover_timeout_s', 8.)),
                   min((protected[uid]['until'] for uid in member_ids if uid in protected), default=now+8.))
    wall_deadline = float(request.get('started', wall)) + float(owner.config.get('timeout', 10.)) + 1
    if previous and previous.get('identity') == owner.identity:
        deadline = min(deadline, previous['until'])
        wall_deadline = min(wall_deadline, previous['wall_until'])
    owner.pending_handover = dict(member_ids=sorted(set(member_ids)), intent=intent,
        request_serial=request.get('serial'), plan_version=owner.version, identity=copy.deepcopy(owner.identity),
        since=previous.get('since', now), until=deadline, wall_until=wall_deadline,
        revision=owner.revision['executor'], reason=reason)
    tick = request.get('observation_tick')
    old_tick = previous.get('wait_for_tick', 0)
    if type(tick) is int and tick >= 0:
        owner.pending_handover['wait_for_tick'] = max(tick, old_tick)
    elif old_tick:
        owner.pending_handover['wait_for_tick'] = old_tick
    owner._record('human-handover-waiting', **{key: copy.deepcopy(value) for key, value in
                  owner.pending_handover.items() if key != 'identity'}, engine_behavior='continue_accepted_work_no_partial_plan')


def waiting_member(owner, uid):
    pending = getattr(owner, 'pending_handover', None) or {}
    native = squad(owner).get('cooperation_plan', {}).get('bindings', {}).get(uid, {})
    return uid in pending.get('member_ids', []) or native.get('handover_waiting') is True


def update(owner):
    pending = getattr(owner, 'pending_handover', None)
    if not pending:
        return
    now = owner.world.get('time', 0)
    alive = {unit['id'] for unit in owner._members(owner.world)}
    invalid = pending.get('identity') != owner.identity or not set(pending['member_ids']) <= alive
    expired = now >= pending['until'] or owner.clock() >= pending['wall_until']
    # Native may reject an interleaving action before its snapshot arrives.
    # An older observation cannot prove that the rejected action has ended.
    observed_tick = owner.world.get('tick')
    if (not invalid and not expired and pending.get('wait_for_tick', 0) > 0
            and (type(observed_tick) is not int or observed_tick < pending['wait_for_tick'])):
        return
    protected = protected_members(squad(owner).get('cooperation_plan', {}), now)
    if not invalid and not expired and any(uid in protected for uid in pending['member_ids']):
        return
    owner.pending_handover = None
    owner.revision['executor'] += 1
    owner._record('human-handover-ready', reason='scope_invalid' if invalid else 'original_deadline' if expired else 'native_boundary',
                  member_ids=pending['member_ids'], original_until=pending['until'],
                  engine_behavior='rebuild_complete_candidate_from_current_facts_no_stale_command_replay')


def blocks_periodic(owner):
    pending = getattr(owner, 'pending_handover', None) or {}
    # Different new facts can request a complete keep-assignment alternative.
    return bool(pending and owner.revision['executor'] <= pending['revision']
                and not owner.pending_commander_plan)


def supersede(owner, serial):
    """An accepted newer complete plan replaces an older waiting intention."""
    pending = getattr(owner, 'pending_handover', None) or {}
    if (pending and type(serial) is int and type(pending.get('request_serial')) is int
            and serial >= pending['request_serial']):
        owner.pending_handover = None
        owner._record('human-handover-superseded', request_serial=serial,
                      previous_request_serial=pending['request_serial'], engine_behavior='accepted_latest_complete_plan')
