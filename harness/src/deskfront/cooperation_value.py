"""Role-specific comparisons of existing squad facts, without selecting orders.

Positions in provider requests may use display cells while route lengths and
weapon ranges retain native world units. Only angles and equality use positions
directly; ground distances explicitly convert the provider frame. Endpoint 2D
opportunity, current native attackability and measured effects stay separate.
"""
import math

SCHEMA = 'cooperation-value/v1'
MAX_MEMBERS = 16
MAX_TARGETS = 64
MAX_RELATION_ROWS = 32
FRESH_SECONDS = 1.1


def _number(value):
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) else None)


def _point(value):
    return (isinstance(value, (tuple, list)) and len(value) == 2
            and all(_number(x) is not None for x in value))


def _unit(facts, uid):
    return next((u for u in facts.get('members', [])[:MAX_MEMBERS]
                 if isinstance(u, dict) and u.get('id') == uid), {})


def _contact(facts, uid):
    return next((u for u in facts.get('contacts', [])[:MAX_TARGETS]
                 if isinstance(u, dict) and u.get('id') == uid), {})


def _evidence(facts, uid):
    return facts.get('execution_evidence', {}).get('members', {}).get(uid, {})


def _scale(facts):
    """Number of coordinate units per native world unit, when known."""
    if facts.get('prompt_contract', {}).get('version') == 'deskfront-coordinates/v1':
        scale = _number(facts.get('tactical_map', {}).get('distance_to_cells'))
        return scale if scale is not None and scale > 0 else None
    return 1.


def _distance(facts, a, b):
    scale = _scale(facts)
    return math.dist(a, b) / scale if scale and _point(a) and _point(b) else None


def _length(route):
    value = _number(route.get('route_length'))
    if value is None:
        value = _number(route.get('route_comparison', {}).get('polyline_length'))
    return round(value, 3) if value is not None and value >= 0 else None


def _age(facts, value):
    now, then = _number(facts.get('time')), _number(value)
    return now - then if now is not None and then is not None else None


def _fresh(facts, value):
    age = _age(facts, value)
    return age is not None and -.1 <= age <= FRESH_SECONDS


def _angle(a, b, target):
    if not all(_point(p) for p in (a, b, target)):
        return None
    left = [a[i] - target[i] for i in (0, 1)]
    right = [b[i] - target[i] for i in (0, 1)]
    norm = math.hypot(*left) * math.hypot(*right)
    if norm <= 1e-10:
        return None
    return round(math.degrees(math.acos(max(-1., min(1., sum(
        x * y for x, y in zip(left, right)) / norm)))), 1)


def _target_route(route, threat_id):
    return next((r for r in route.get('close_engagement', {}).get('targets', [])[:MAX_TARGETS]
                 if isinstance(r, dict) and r.get('target_id') == threat_id), {})


def _endpoint(facts, uid, route, threat_id):
    """A target-specific 2D endpoint comparison is never a native muzzle ray."""
    compared = _target_route(route, threat_id)
    approach = route.get('contact_approach') or {}
    approach = approach if approach.get('target_id') == threat_id else {}
    target, unit = _contact(facts, threat_id), _unit(facts, uid)
    endpoint = compared.get('endpoint', {})
    in_range = endpoint.get('in_weapon_range', approach.get('in_weapon_range'))
    distance = _number(endpoint.get('distance', approach.get('destination_distance')))
    basis = 'provided_same_target_comparison' if distance is not None else 'unknown'
    if distance is None:
        distance = _distance(facts, route.get('position'), target.get('position'))
        if distance is not None:
            basis = 'ground_distance_converted_to_native_world'
    weapon_range = _number(unit.get('weapon_range'))
    if type(in_range) is not bool:
        in_range = distance <= weapon_range if distance is not None and weapon_range is not None else None
    obstruction = next((r for r in route.get('endpoint_obstructions', [])[:MAX_TARGETS]
                        if isinstance(r, dict) and r.get('target_id') == threat_id), {})
    crossing = obstruction.get('crossing_hard_cover_ids', compared.get('geometry', {}).get('endpoint_crossings'))
    crossing = crossing if isinstance(crossing, list) else None
    listed_clear = threat_id in route.get('route_comparison', {}).get('in_range_2d_clear_target_ids', [])
    conflict = listed_clear and (bool(crossing) or in_range is False)
    clear = (None if conflict else True if listed_clear else
             False if in_range is False or bool(crossing) else
             True if crossing == [] and in_range is True else None)
    return dict(clear_in_range=clear, in_weapon_range=in_range,
                crossing_hard_cover_ids=crossing,
                range_fit=approach.get('range_fit', 'unknown'),
                ground_distance_native=round(distance, 3) if distance is not None else None,
                distance_basis=basis, native_muzzle='unverified',
                **({'conflicting_input': True} if conflict else {}))


def _current_native(facts, uid, threat_id):
    unit, evidence = _unit(facts, uid), _evidence(facts, uid)
    targets = evidence.get('engageable_visible_targets')
    attackable = threat_id in targets if isinstance(targets, list) else None
    result = dict(attackable=attackable, basis='current_snapshot_native_attackable_list'
                  if attackable is not None else 'unknown', snapshot_time=facts.get('time'),
                  muzzle_check={'status': 'unknown'})
    ray = evidence.get('firing_awareness') or {}
    if ray.get('target_id') == threat_id:
        displacement = _distance(facts, ray.get('position'), unit.get('position'))
        same_pose = bool(ray.get('posture')) and ray.get('posture') == unit.get('posture')
        pose_fresh = _fresh(facts, ray.get('sampled_at')) and displacement is not None and displacement <= .04 and same_pose
        current_revision = _number(facts.get('tactical_map', {}).get('navigation_revision'))
        ray_revision = _number(ray.get('navigation_revision'))
        navigation = ('unknown' if current_revision is None or ray_revision is None else
                      'matched' if current_revision == ray_revision else 'mismatched')
        valid = pose_fresh and navigation == 'matched'
        status = ('stale_or_pose_changed' if not pose_fresh else 'stale_navigation_revision'
                  if navigation == 'mismatched' else 'navigation_revision_unknown'
                  if navigation == 'unknown' else 'current_native_sample')
        result['muzzle_check'] = dict(status=status, navigation_scope=navigation,
            age_s=round(_age(facts, ray.get('sampled_at')), 3) if _age(facts, ray.get('sampled_at')) is not None else None,
            clear=ray.get('clear') if valid and type(ray.get('clear')) is bool else None,
            reason=ray.get('reason') if valid else None)
    # Rocket readiness and geometry are distinct; cooldown does not negate a
    # valid geometry sample, and fireable does not mean an actual launch.
    option = next((r for r in evidence.get('rocket_fire_options', [])[:MAX_TARGETS]
                   if isinstance(r, dict) and r.get('target_id') == threat_id), None)
    if option:
        valid = _fresh(facts, option.get('time'))
        result['rocket_check'] = dict(status='current_native_sample' if valid else 'stale',
            fireable=option.get('fireable') if valid else None,
            ready=option.get('ready') if valid else None,
            mode=option.get('mode') if valid else None)
    return result


def _fire(facts, uid):
    board = facts.get('cooperation_board', {}).get('members', {}).get(uid, {})
    effect = _evidence(facts, uid).get('fire_effectiveness') or {}
    window = effect.get('window') or {}
    valid_effect = effect.get('complete') is True and _fresh(facts, effect.get('observed_at'))
    # The effect window is not necessarily attributed to recent_fire_target_id.
    # Never assign its aggregate damage to that enemy or call fire suppression.
    measured = any((_number(window.get(key)) or 0) > 0
                   for key in ('damage', 'pressure_events', 'cover_damage'))
    return dict(recent_fire_target_id=board.get('recent_fire_target_id'),
        recent_fire_observed=board.get('recent_fire_observed') if type(board.get('recent_fire_observed')) is bool else None,
        uninterrupted_target_fire=board.get('recent_uninterrupted_target_fire') if type(board.get('recent_uninterrupted_target_fire')) is bool else None,
        interruption=board.get('interruption'),
        current_effect_window='measured_effect_target_attribution_unknown' if valid_effect and measured else
                              'no_measured_effect_in_current_window' if valid_effect else 'unknown_or_stale',
        measured_damage=window.get('damage') if valid_effect else None,
        measured_pressure_events=window.get('pressure_events') if valid_effect else None)


def _relevance(facts, mover_id, route, threat_id):
    target = _contact(facts, threat_id)
    if not target:
        return dict(status='unknown', basis='target_not_in_supplied_contacts')
    if target.get('visible') is False or target.get('dead') is True or (
            _number(target.get('hp')) is not None and _number(target.get('hp')) <= 0):
        return dict(status='irrelevant', basis='target_explicitly_not_current_or_alive')
    compared = _target_route(route, threat_id)
    geometry = compared.get('geometry', {})
    count, blocked = _number(geometry.get('samples')), _number(geometry.get('crossing_samples'))
    samples = dict(total=int(count), obstructed=int(blocked)) if (
        count is not None and blocked is not None and 0 <= blocked <= count) else None
    endpoint = _endpoint(facts, mover_id, route, threat_id)
    if endpoint['clear_in_range'] is True:
        return dict(status='supported', basis='mover_same_target_endpoint_2d_opportunity',
                    route_samples=samples, scope='endpoint_only_not_enemy_attack_or_safety')
    if samples and samples['total'] > samples['obstructed']:
        return dict(status='supported', basis='mover_same_target_open_2d_route_samples',
                    route_samples=samples, scope='sampled_waypoint_estimate_only_no_segment_indices_or_enemy_range')
    return dict(status='unknown', basis='no_open_window_in_same_target_2d_samples' if samples else
                'target_specific_route_samples_not_supplied', route_samples=samples,
                scope='no_full_route_or_enemy_attack_inference')


def assistance_evidence(facts, mover_id, mover_route, supporter_id, support_route, threat_id):
    """Compare one explicit supporter, mover and known target; no hidden order."""
    mover_route, support_route = mover_route or {}, support_route or {}
    supporter, mover, contact = _unit(facts, supporter_id), _unit(facts, mover_id), _contact(facts, threat_id)
    relevance = _relevance(facts, mover_id, mover_route, threat_id)
    allowed = supporter.get('weapon_profile', {}).get('can_target_tanks')
    if not isinstance(allowed, bool):
        allowed = supporter.get('weapon') in ('rifle', 'smg', 'pistol', 'rocket', 'cannon')
    if (contact.get('kind') == 'tank' or contact.get('tank') is True) and not allowed:
        relevance = dict(status='irrelevant', basis='supporter_native_weapon_cannot_attack_tank')
    native = _current_native(facts, supporter_id, threat_id)
    future = _endpoint(facts, supporter_id, support_route, threat_id)
    fire = _fire(facts, supporter_id)
    old_target = fire['recent_fire_target_id']
    switch = old_target != threat_id if old_target else None
    moved = _distance(facts, supporter.get('position'), support_route.get('position'))
    shared = (_point(mover_route.get('position')) and _point(support_route.get('position'))
              and tuple(mover_route['position']) == tuple(support_route['position']))
    risks = []
    if shared: risks.append('shared_endpoint_requires_native_spacing')
    if switch is True and fire['recent_fire_observed'] is True:
        risks.append('switches_away_from_recent_fire_target')
    if moved is not None and moved > .04 and fire['recent_fire_observed'] is True:
        risks.append('movement_may_interrupt_current_fire')
    if future['clear_in_range'] is not True:
        risks.append('support_endpoint_opportunity_unconfirmed')
    if _evidence(facts, supporter_id).get('needs_recovery') is True:
        risks.append('supporter_currently_needs_recovery')
    return dict(supporter_id=supporter_id, mover_id=mover_id, threat_id=threat_id,
        relevance=relevance, current_native=native, endpoint_2d=future,
        mover_endpoint_2d=_endpoint(facts, mover_id, mover_route, threat_id),
        route_costs=dict(supporter=_length(support_route), mover=_length(mover_route), unit='native_world'),
        establishment_eta='unknown_without_native_route_timing',
        angles=dict(current_deg=_angle(mover.get('position'), supporter.get('position'), contact.get('position')),
                    endpoint_deg=_angle(mover_route.get('position'), support_route.get('position'), contact.get('position'))),
        target_switch=switch, current_fire=fire, risks=risks,
        actual_assistance_effect='unverified', movement_admission='independent_of_support_fire')


def build_plan_facts(facts, bindings, routes, relations):
    """Small comparison rows for a complete proposal; raw facts remain available."""
    members, selected = [], {}
    physical = lambda uid: (tuple(_unit(facts, uid).get('position') or ()), uid)
    for uid in sorted(bindings, key=physical)[:MAX_MEMBERS]:
        binding = bindings[uid]
        kept = binding.get('keep_assignment') is True
        row = (facts.get('accepted_assignments', {}).get(uid, {}) if kept else
               routes.get(uid, {}).get(binding.get('route_id'), {}))
        selected[uid] = row
        evidence, fire = _evidence(facts, uid), _fire(facts, uid)
        risks = []
        moved = _distance(facts, _unit(facts, uid).get('position'), row.get('position'))
        if not kept and moved is not None and moved > .04 and fire['recent_fire_observed'] is True:
            risks.append('movement_may_interrupt_current_fire')
        if evidence.get('needs_recovery') is True: risks.append('currently_needs_recovery')
        members.append(dict(member_id=uid, role=binding.get('role'), keep_assignment=kept,
            route_id=binding.get('route_id'), route_cost=None if kept else _length(row),
            endpoint=row.get('position'), current_attackable_target_ids=evidence.get('engageable_visible_targets'),
            current_fire=fire, risks=risks))
    relationships, total = [], 0
    for relation in relations[:MAX_RELATION_ROWS]:
        spec = relation.get('spec', relation)
        supporters = spec.get('supporter_ids', [])[:MAX_MEMBERS]
        movers = spec.get('assisted_member_ids', [])[:MAX_MEMBERS]
        threats = spec.get('threat_ids', [])[:MAX_TARGETS]
        total += len(supporters) * len(movers) * len(threats)
        if len(relationships) >= MAX_RELATION_ROWS: continue
        for supporter_id in supporters:
            if len(relationships) >= MAX_RELATION_ROWS: break
            for mover_id in movers:
                if len(relationships) >= MAX_RELATION_ROWS: break
                for threat_id in threats:
                    if len(relationships) >= MAX_RELATION_ROWS: break
                    row = assistance_evidence(facts, mover_id, selected.get(mover_id),
                                              supporter_id, selected.get(supporter_id), threat_id)
                    row['relation_id'] = spec.get('relation_id')
                    relationships.append(row)
    endpoints = {}
    for uid, row in selected.items():
        if _point(row.get('position')): endpoints.setdefault(tuple(row['position']), []).append(uid)
    return dict(schema=SCHEMA,
        units=dict(route_cost='native_world', positions='provider_coordinate_frame',
                   eta='unknown_without_native_route_timing'),
        members=members, relationships=relationships,
        shared_endpoints=[dict(position=list(point), member_ids=uids) for point, uids in endpoints.items() if len(uids) > 1],
        relation_rows_omitted=max(0, total-len(relationships)),
        interpretation='target_specific_2d_opportunity_is_not_native_muzzle_fire_enemy_intent_safety_or_proven_assistance')
