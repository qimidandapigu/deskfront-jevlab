"""Validate an engine-owned failed-shelter handoff; never choose an action.

Native owns detection, the persistent token, hard-danger readiness and closure.
The Harness only joins that fact to the current observation and coalesces work.
Old or incomplete snapshots do not grant a safety exception.
"""
import copy


def _dict(value):
    return value if isinstance(value, dict) else {}


def current(world, unit, team, squad):
    """Return a current *pending* handoff, or unknown as an empty dict."""
    combat = unit.get('combat', {})
    cover = combat.get('cover_execution', {}) if isinstance(combat, dict) else {}
    row = cover.get('review_handoff') if isinstance(cover, dict) else None
    if not isinstance(row, dict) or row.get('state') != 'pending':
        return {}
    if (not isinstance(row.get('token'), str) or not row['token']
            or type(row.get('decision_allowed')) is not bool
            or type(row.get('execution_allowed')) is not bool
            or not isinstance(row.get('blocked_reason'), str)
            or unit.get('hp', 0) <= 0):
        return {}
    scope = row.get('scope')
    if not isinstance(scope, dict):
        return {}
    mission = _dict(_dict(world.get('world_growth')).get('mission'))
    # These keys exist in the new native snapshot. Missing identity remains
    # unknown; a default must not turn an old observation into authorization.
    tokens = _dict(squad.get('assignment_tokens'))
    epochs = _dict(world.get('control_epochs'))
    if (not all(key in world for key in ('run_id', 'map_index', 'navigation_revision'))
            or team not in epochs or unit.get('id') not in tokens
            or not isinstance(unit.get('weapon'), str) or not unit['weapon']
            or unit.get('faction') != team
            or _dict(world.get('control')).get(team) not in ('lm', 'agent')
            or row['decision_allowed'] is not True):
        return {}
    expected = dict(run_id=world['run_id'], map_index=world['map_index'],
        mission_operation_id=mission.get('operation_id', ''), mission_index=mission.get('index', -1),
        navigation_revision=world['navigation_revision'], control_epoch=epochs[team],
        assignment_token=tokens[unit['id']], weapon=unit['weapon'])
    if any(key not in scope or type(scope[key]) is not type(value) or scope[key] != value
           for key, value in expected.items()):
        return {}
    return copy.deepcopy(row)


def matches(request_handoff, current_handoff):
    """Readiness may change during preparation; the failure identity may not."""
    return bool(request_handoff and current_handoff
        and request_handoff.get('token') == current_handoff.get('token')
        and request_handoff.get('scope') == current_handoff.get('scope'))


def can_execute(request_handoff, current_handoff):
    # The token is sent to native too. This observation-side check never
    # replaces native acceptance/candidate/physics validation at application.
    return (matches(request_handoff, current_handoff)
            and current_handoff.get('execution_allowed') is True
            and current_handoff.get('blocked_reason') == '')


def notify(owner, unit, squad):
    """Give one failure episode a bounded personal review before escalation.

    This is scheduling ownership only. Native movement and safety continue;
    neither a model Future nor a candidate query holds an action lock.
    """
    row = current(owner.world, unit, owner.team, squad)
    if not row or row.get('decision_allowed') is not True:
        entry = getattr(owner, 'survival_reviews', {}).get(unit['id'])
        if entry and entry.get('state') == 'personal':
            entry['state'] = 'closed'
        return
    history = owner.unit_history.setdefault(unit['id'], {})
    reviews = getattr(owner, 'survival_reviews', None)
    if reviews is None:
        reviews = owner.survival_reviews = {}
    entry = reviews.get(unit['id'])
    if entry and entry['token'] == row['token'] and entry['scope'] == row['scope']:
        if entry.get('state') == 'personal' and (owner.world.get('time', 0) >= entry['until']
                or owner.clock() >= entry['wall_until']):
            finish(owner, unit['id'], row['token'], 'personal_review_deadline')
        return
    history['survival_review_notified_token'] = row['token']
    cover = unit.get('combat', {}).get('cover_execution', {})
    now, wall = owner.world.get('time', 0), owner.clock()
    reviews[unit['id']] = dict(token=row['token'], scope=copy.deepcopy(row['scope']), state='personal',
        since=now, until=now+float(owner.config.get('survival_review_timeout_s', 12.)),
        wall_until=wall+float(owner.config.get('timeout', 10.))+float(owner.config.get('soldier_candidate_timeout_s', 2.))+1.,
        revision=owner.revision['executor'], reason=cover.get('reason', 'shelter_ineffective'))
    owner._record('survival-review-owned', unit_id=unit['id'], episode_id=row['token'],
        until=reviews[unit['id']]['until'], owner='personal', execution_locked=False)
    if not owner.config.get('soldier_agents', True):
        finish(owner, unit['id'], row['token'], 'personal_review_disabled')


def finish(owner, uid, token, reason, *, accepted=False):
    entry = getattr(owner, 'survival_reviews', {}).get(uid)
    if not entry or entry['token'] != token or entry.get('state') != 'personal':
        return
    entry['state'] = 'accepted' if accepted else 'escalated'
    owner._record('survival-review-finished', unit_id=uid, episode_id=token,
                  reason=reason, state=entry['state'], original_until=entry['until'])
    if not accepted:
        owner._wake('survival_review_due', dict(unit_id=uid, episode_id=token, reason=reason))


def blocks_duplicate_periodic(owner):
    """Coalesce periodic same-cause reassignment, not independent new facts."""
    if owner.pending_commander_plan:
        return False
    for entry in getattr(owner, 'survival_reviews', {}).values():
        if (entry.get('state') == 'personal' and owner.world.get('time', 0) < entry['until']
                and owner.clock() < entry['wall_until']
                and owner.revision['executor'] <= entry['revision']):
            return True
    return False
