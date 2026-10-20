"""Bounded, grounded whole-squad proposals for one JEV Choice.

This module proposes complete bindings from existing native route facts. It
does not choose a plan, compute a native path, or mutate accepted work. There
is no Cartesian product of member answers and no dependence on enemy orders.
"""
import copy
import math

SCHEMA = 'combat-coordination/v1'
MAX_CANDIDATES = 32
MAX_PAIR_PROBES = 48
LOCAL_OPTIONS = {
    'fire_support': ['continue_role', 'hold_fire', 'local_reposition', 'opportunity_action'],
    'maneuver': ['continue_role', 'covered_advance', 'local_reposition', 'opportunity_action'],
    'area_hold': ['continue_role', 'hold_fire', 'local_reposition', 'opportunity_action'],
}

INSTRUCTIONS = '''# 本轮完整配合合同
intent每个选项是一套完整方案，同时绑定行动类型、全部成员职责与路线、区域任务目的及装备人员；一次Choice选择整套，不混搭不同候选。cooperation_candidates记录真实候选，没有声称路线安全、已经形成火力或已成功。
小队选择配合与有限自主范围，算法在已选区域/走廊内维护射距、射界、目标保持和动作衔接。个人JEV按重要事件比较一段局部打法、任务变体与道具取舍；不需逐步批准小队已选任务，不可改队友职责、长期目标或越出授权范围。投雷能否安全仍由原生复验。
fire_support表示到所选射位区建立并维护火力，不机械追近指挥坐标；maneuver表示沿已选通路连续机动，重武器机动也不等于近身攻击；area_hold先到所选区域再保持。步枪中距、冲锋枪借遮挡接近、火箭安全射距是比较收益的软习惯，不能假造原生能力或禁用合法动作。
advance/cover/bound/flank/hold/regroup均按本轮完整候选比较；没有侧路不凭空侧击，一人或能力不足时用其他完整方案。支援关系是并行协作，不以队友近期是否开火、弹药或装填作为移动硬许可。一人失败只影响真实依赖分支。
continue_order保留全部已接受任务、人员、区域、游标与原截止；revise_order只替换候选明确修改的成员，keep_assignment完整保持其他成员。候选被拒绝保留原任务。改变装备人员只在整套候选明确列出时生效，原生接受前不宣称已夺炮。
hold/cover/regroup的目的、关注与复核条件已在整套候选中明确；continue不偷偷改目的、不续期。模型迟到时已有动作继续，真实危险和身份/导航复验由原生处理。support_*是独立支援实体任务，不给步兵补分工。仅回答本题一个合法完整方案。
support_relations明确谁针对哪些已知威胁帮助谁；comparison只有预计机会，原生关系状态才说明到位、射界、实际发射或关系失效，发射不等于压制。关系不是移动许可。allow_support_gap=false时个人不能改打无关目标或临时离开支援；机会不兼容交既有小队复评。handover中的受保护成员仅keep_assignment，不能在模型选择后暗中拆开整套计划；新战略也默认等本兵短动作边界。
'''


def _number(value, fallback=0.):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else fallback


def _point_key(row):
    point = row.get('position')
    return tuple(point) if isinstance(point, (list, tuple)) and len(point) == 2 else None


def _physical_key(unit):
    """Identity is a final tie breaker only after comparable physical facts."""
    return (tuple(_number(x) for x in (unit.get('position') or [])),
            _number(unit.get('weapon_range')), str(unit.get('weapon', '')),
            -_number(unit.get('hp'), 1), _number(unit.get('suppression')),
            _number(unit.get('reload_remaining')), unit.get('id', ''))


def _route_key(row):
    return (_point_key(row) or (), tuple(str(x) for x in row.get('region_path', [])),
            str(row.get('region_id', '')), str(row.get('approach_region', '')))


def _route_measures(row):
    """Endpoint opportunity and route geometry remain separate evidence."""
    fact = row.get('contact_approach') or {}
    fit = {'preferred': 0, 'long_edge': 1, 'too_close': 3, 'out_of_range': 4, 'unknown': 2}.get(fact.get('range_fit'), 2)
    blocked = row.get('firing_position', {}).get('status') == 'native_blocked_at_endpoint'
    observed_length = _number(row.get('route_length', row.get('route_comparison', {}).get('polyline_length')), None)
    length = observed_length if observed_length is not None else 100.
    checks = row.get('endpoint_obstructions', [])
    obstructed = sum(bool(check.get('crossing_hard_cover_ids')) for check in checks if isinstance(check, dict))
    clear = set(row.get('route_comparison', {}).get('in_range_2d_clear_target_ids', []))
    samples, exposed = 0., 0.
    for target in row.get('close_engagement', {}).get('targets', []):
        geo = target.get('geometry', {})
        count = max(0., _number(geo.get('samples')))
        samples += count
        exposed += max(0., count - _number(geo.get('crossing_samples')))
        if target.get('endpoint', {}).get('in_weapon_range') is True and geo.get('endpoint_crossings') == [] and target.get('target_id'):
            clear.add(target['target_id'])
    if fact.get('in_weapon_range') is True:
        for check in checks:
            if check.get('target_id') == fact.get('target_id') and check.get('crossing_hard_cover_ids') == []:
                clear.add(fact['target_id'])
    endpoint = 3 if blocked else 0 if clear else 2 if obstructed else 1
    return dict(fit=fit, blocked=blocked, length=length, obstructed=obstructed,
                clear_targets=sorted(clear), endpoint=endpoint, samples=samples, exposed=exposed,
                exposure=exposed / samples if samples else .5,
                observed_length=observed_length, gain=_number(fact.get('distance_gain')),
                goal_limited=row.get('route_reaches_team_goal') is False if not fact and not samples else False)


def _route_score(row, role, policy='engagement'):
    """Order a bounded proposal; JEV still compares and selects the plan.

    A covered intermediate route and a route improving endpoint engagement
    are different useful alternatives. Neither geometry proves native fire or
    safety, and no unknown ray is promoted to clear.
    """
    m = _route_measures(row)
    disconnected = row.get('limitation') == 'disconnected_from_team_goal'
    if role == 'maneuver':
        if policy == 'covered':
            return (disconnected, m['goal_limited'], m['blocked'], m['exposure'], m['endpoint'], m['fit'], -m['gain'], m['length'])
        return (disconnected, m['goal_limited'], m['blocked'], m['endpoint'], m['fit'], -m['gain'], m['length'], m['exposure'])
    if policy == 'fast_support':
        return (m['blocked'], m['endpoint'], m['length'], m['fit'], m['exposure'], -m['gain'])
    if policy == 'covered':
        return (m['blocked'], m['fit'], m['exposure'], m['endpoint'], m['length'], -m['gain'])
    return (m['blocked'], m['endpoint'], m['fit'], m['obstructed'], m['length'], m['exposure'], -m['gain'])


def _comparison(bindings, routes):
    """Small factual summary; full per-target evidence stays in route rows."""
    clear, blocked, samples, exposed, length, count, lengths_known = set(), [], 0., 0., 0., 0, True
    for uid, binding in bindings.items():
        if binding.get('keep_assignment'): continue
        row = routes.get(uid, {}).get(binding.get('route_id'), {})
        m = _route_measures(row)
        clear.update(m['clear_targets'])
        if m['obstructed']: blocked.append(uid)
        samples += m['samples']; exposed += m['exposed']; count += 1
        if m['observed_length'] is None: lengths_known = False
        else: length += m['observed_length']
    return dict(route_length_sum=round(length, 3) if lengths_known else None, endpoint_2d_clear_in_range_target_ids=sorted(clear),
                endpoint_2d_obstructed_member_ids=blocked,
                route_2d_unobstructed_samples=[round(exposed), round(samples)],
                native_fire='read_each_route_firing_position', sampled_members=count)


def _allocate(units, routes, roles, *, fixed=None, keep=None, accepted=None, prefer_goal=False, policy='engagement'):
    """Linear greedy proposal with endpoint reservations; no member product."""
    selected, occupied = {}, set()
    fixed, keep, accepted = fixed or {}, set(keep or []), accepted or {}
    for unit in units:
        uid = unit['id']
        if uid in keep:
            selected[uid] = dict(role=accepted[uid].get('role'), route_id='keep_assignment', keep_assignment=True)
            point = _point_key(accepted[uid])
            if point is not None: occupied.add(point)
    # Forced pair endpoints reserve before remaining members take positions.
    # A scarce useful route reserves before a flexible member; geometry and
    # capability determine this order, never the member's name or input order.
    ordered = sorted((u for u in units if u['id'] not in keep), key=lambda u: (
        u['id'] not in fixed, len(routes.get(u['id'], {})),
        min((_route_score(row, roles[u['id']], policy) for row in routes.get(u['id'], {}).values()), default=()),
        _physical_key(u)))
    for unit in ordered:
        uid = unit['id']; role = roles[uid]
        options = routes.get(uid, {})
        keys = [fixed[uid]] if uid in fixed else sorted(options, key=lambda key: (
            options[key].get('route_reaches_team_goal') is False if prefer_goal else False,
            _route_score(options[key], role, policy), _route_key(options[key]), key))
        key = next((key for key in keys if key in options and _point_key(options[key]) not in occupied), None)
        # One sampled point for a shared region does not mean the entire team
        # must wait. Prefer distinct points, then expose the genuine shared
        # endpoint and let native local spacing/admission determine capacity.
        # No offset point or alternative route is invented here.
        shared_endpoint = key is None
        if key is None: key = next((key for key in keys if key in options), None)
        if key is None: return None
        row = options[key]
        point = _point_key(row)
        # The provider projection intentionally omits route_positions; its
        # private native counterpart is retained on the request and consumed
        # by _submit. The projected path is enough to bind an existing option.
        if point is None or not row.get('region_id') or not row.get('region_path'):
            return None
        occupied.add(point)
        selected[uid] = dict(role=role, route_id=key, region_id=row['region_id'], keep_assignment=False)
        if shared_endpoint: selected[uid]['endpoint_reservation'] = 'shared_native_endpoint_requires_runtime_spacing'
    return selected


def _route_shortlist(options, role):
    """Preserve fast establishment, range fit and covered-travel tradeoffs."""
    policies = ('engagement', 'fast_support', 'covered') if role == 'fire_support' else ('engagement', 'covered', 'fast_support')
    ordered = []
    for policy in policies:
        if options:
            key = min(options, key=lambda key: (_route_score(options[key], role, policy), _route_key(options[key]), key))
            if key not in ordered: ordered.append(key)
    for key in sorted(options, key=lambda key: (_route_score(options[key], role), _route_key(options[key]), key)):
        if key not in ordered: ordered.append(key)
        if len(ordered) >= 3: break
    return ordered[:3]


def _can_support_threat(unit, contact):
    """Mirror a hard native target capability, not a preferred squad role.

    Rifle, SMG and pistol may select tanks using native armour coefficients.
    A rifle member may still maneuver while a rocket member supports it.
    """
    tank = contact.get('kind') == 'tank' or contact.get('tank') is True
    allowed = unit.get('weapon_profile', {}).get('can_target_tanks')
    if not isinstance(allowed, bool):
        allowed = unit.get('weapon') in ('rifle', 'smg', 'pistol', 'rocket', 'cannon')
    return not tank or allowed


def _support_targets(unit, row, contacts):
    known = {c['id'] for c in contacts if c.get('visible') and c.get('id') and _can_support_threat(unit, c)}
    return set(_route_measures(row)['clear_targets']) & known


def _relation_options(facts, mover_id, mover_route, supporter_id, support_route, contacts):
    """Only compare the selected supporter's opportunity against this mover.

    A target union across the squad is not a support relationship. Missing
    muzzle/route evidence remains unknown, and is not a reason to delete a
    legal option. These facts are proposal data, never native spec identity.
    """
    from cooperation_value import assistance_evidence
    by_id = {u['id']: u for u in facts.get('members', [])}
    opportunities = _support_targets(by_id[supporter_id], support_route, contacts)
    rows = []
    for contact in contacts:
        threat_id = contact['id']
        if threat_id not in opportunities: continue
        evidence = assistance_evidence(facts, mover_id, mover_route,
            supporter_id, support_route, threat_id)
        if evidence.get('relevance', {}).get('status') == 'irrelevant': continue
        rows.append((contact, evidence))
    return rows


def _pair_evidence_key(facts, mover_id, mover_route, supporter_id, support_route, contacts, *, preferred=()):
    """Use explicit dimensions, not a summed tactical utility or probability.

    Relevant geometric windows and current native opportunity come before
    physical tie breakers. Fast establishment and range-fit policies are
    separately offered below; neither is collapsed into one magic score.
    """
    rows = _relation_options(facts, mover_id, mover_route, supporter_id, support_route, contacts)
    current = set(facts.get('execution_evidence', {}).get('members', {}).get(
        supporter_id, {}).get('engageable_visible_targets', []))
    def key(item):
        contact, evidence = item
        return (evidence.get('relevance', {}).get('status') != 'supported',
            contact['id'] not in preferred, contact['id'] not in current,
            tuple(contact.get('position') or []), contact['id'])
    return min((key(row) for row in rows), default=(True, True, True, (), ''))[:3]


def _pair_tradeoffs(facts, pair, routes, contacts):
    """Separate known dimensions used only to justify an extra partner.

    Unknown measurements stay None. No weighted utility or probability sum
    is computed, and this vector does not choose an executing plan.
    """
    mover, supporter, side_id, front_id = pair[:4]
    side, front = routes[mover][side_id], routes[supporter][front_id]
    options = _relation_options(facts, mover, side, supporter, front, contacts)
    if not options: return None, (None,) * 5
    contact, evidence = min(options, key=lambda item: (
        item[1].get('relevance', {}).get('status') != 'supported',
        item[1].get('current_native', {}).get('attackable') is not True,
        tuple(item[0].get('position') or []), item[0]['id']))
    attackable = evidence.get('current_native', {}).get('attackable')
    native = (0 if attackable else 1) if isinstance(attackable, bool) else None
    relevance = 0 if evidence.get('relevance', {}).get('status') == 'supported' else None
    measured = _route_measures(front)
    fit = {'preferred': 0, 'long_edge': 1, 'too_close': 2, 'out_of_range': 3}.get(
        evidence.get('endpoint_2d', {}).get('range_fit'))
    target = next((row for row in front.get('close_engagement', {}).get('targets', [])
        if row.get('target_id') == contact['id']), {})
    geometry = target.get('geometry', {})
    samples, blocked = _number(geometry.get('samples'), None), _number(geometry.get('crossing_samples'), None)
    exposure = ((samples - blocked) / samples if samples is not None and samples > 0
        and blocked is not None and 0 <= blocked <= samples else None)
    return contact['id'], (native, relevance, measured['observed_length'], fit, exposure)


def _meaningful_extra_partner(facts, pair, previous, routes, contacts):
    """A third pass needs a new, concretely useful tradeoff, not more labels."""
    if not previous or any(old[1] == pair[1] for old in previous): return False
    threat, value = _pair_tradeoffs(facts, pair, routes, contacts)
    old = [_pair_tradeoffs(facts, old, routes, contacts) for old in previous]
    old_values = [vector for target, vector in old if target == threat]
    # Another known threat can be a meaningful alternative only with positive
    # evidence, not simply because a contact ID differs.
    if not old_values:
        return bool(threat) and value[1] == 0 and value[0] == 0
    # Do not add a known dominated partner. Missing on either side prevents
    # dominance; it does not grant the missing fact a favorable value.
    for old in old_values:
        if all((a is None) == (b is None) for a, b in zip(old, value)):
            known = [(a, b) for a, b in zip(old, value) if a is not None]
            if known and all(a <= b for a, b in known): return False
    # At least one actual current/route dimension must improve on *all*
    # previously represented partners. Merely a different ID is insufficient.
    return any(v is not None and all(old[i] is not None and v < old[i] for old in old_values)
        for i, v in enumerate(value))


def _pair_probes(units, routes, kept, contacts=()):
    """Round robin movers, then partners, then route variants; <= 48 probes.

    No actor permutation or route Cartesian product is expanded. The bounded
    diagonal variant list only deepens a pair after every offered pair got its
    first probe. Pair preference uses actual available support opportunity.
    """
    movable = [u for u in units if u['id'] not in kept and routes.get(u['id'])]
    partners = {}
    for mover in movable:
        partners[mover['id']] = sorted((u for u in movable if u['id'] != mover['id']), key=lambda u: (
            not any(_support_targets(u, row, contacts) for row in routes[u['id']].values()),
            min((_route_score(row, 'fire_support', 'fast_support') for row in routes[u['id']].values()), default=()),
            -_number(u.get('weapon_range')), _physical_key(u)))
    pairs = []
    for depth in range(max((len(x) for x in partners.values()), default=0)):
        for mover in movable:
            if depth < len(partners[mover['id']]):
                pairs.append((mover, partners[mover['id']][depth]))
                if len(pairs) >= MAX_PAIR_PROBES: break
        if len(pairs) >= MAX_PAIR_PROBES: break
    short = {(u['id'], role): _route_shortlist(routes[u['id']], role) for u in movable for role in ('maneuver', 'fire_support')}
    variants = ((0, 0), (0, 1), (1, 0), (1, 1), (0, 2), (2, 0), (1, 2), (2, 1), (2, 2))
    out, seen = [], set()
    for si, fi in variants:
        for mover, supporter in pairs:
            side, front = short[mover['id'], 'maneuver'], short[supporter['id'], 'fire_support']
            if si >= len(side) or fi >= len(front): continue
            row = (mover['id'], supporter['id'], side[si], front[fi])
            if row in seen: continue
            seen.add(row); out.append(row)
            if len(out) >= MAX_PAIR_PROBES: return out, len(movable) * max(0, len(movable)-1)
    return out, len(movable) * max(0, len(movable)-1)


def _angle(a, b, target):
    if not all(isinstance(p, (list, tuple)) and len(p) == 2 for p in (a, b, target)): return None
    x, y = (a[0]-target[0], a[1]-target[1]), (b[0]-target[0], b[1]-target[1])
    norm = math.hypot(*x) * math.hypot(*y)
    if norm <= 1e-10: return None
    return math.degrees(math.acos(max(-1., min(1., (x[0]*y[0]+x[1]*y[1])/norm))))


def _flank_evidence(mover, supporter, side, front, contacts):
    """Same-threat side-angle evidence; distinct region names alone are weak."""
    from squad_region_choices import split_approach
    separated = split_approach(side, front)
    common = set(_route_measures(side)['clear_targets']) & _support_targets(supporter, front, contacts)
    evidence = []
    for contact in contacts:
        if contact['id'] not in common: continue
        endpoint = _angle(side.get('position'), front.get('position'), contact.get('position'))
        current = _angle(mover.get('position'), supporter.get('position'), contact.get('position'))
        if endpoint is None or endpoint < 35.: continue
        existing = current is not None and current >= 35. and endpoint-current < 10.
        # A short route can exploit an already useful side position. A move
        # claiming to establish one needs a changed angle or separate approach.
        if not existing and not (separated or current is not None and endpoint-current >= 10.): continue
        evidence.append(dict(threat_id=contact['id'], endpoint_angle_deg=round(endpoint, 1),
            current_angle_deg=round(current, 1) if current is not None else None,
            kind='use_existing_side_position' if existing else 'establish_side_position',
            distinct_approach=separated, native_effect='unverified'))
    return evidence


def _preserved_relations(facts, bindings):
    """Keep a dependent relation whole; never splice it around a kept actor."""
    execution = facts.get('cooperation_execution') or {}
    old = execution.get('support_relations', [])
    out = []
    for row in old:
        spec = row.get('spec', row)
        participants = set(spec.get('supporter_ids', [])) | set(spec.get('assisted_member_ids', []))
        touched = participants & {uid for uid, b in bindings.items() if b.get('keep_assignment')}
        if touched:
            if any(uid not in bindings or not bindings[uid].get('keep_assignment') for uid in participants): return None
            out.append(copy.deepcopy(spec))
    return out


def _support_relations(facts, bindings, routes, deadline, preferred_threats=(), assisted_pairs=()):
    preserved = _preserved_relations(facts, bindings)
    if preserved is None: return None
    contacts = sorted((c for c in facts.get('contacts', []) if c.get('visible') and c.get('id')),
        key=lambda c: (tuple(c.get('position') or []), str(c.get('kind', '')), c['id']))
    movers = [uid for uid, b in bindings.items() if not b.get('keep_assignment') and b.get('role') == 'maneuver']
    supports = [uid for uid, b in bindings.items() if not b.get('keep_assignment') and b.get('role') in ('fire_support', 'establish_fire')]
    by_id = {u['id']: u for u in facts.get('members', [])}
    out = preserved
    for uid in sorted(supports, key=lambda uid: _physical_key(by_id[uid])):
        support = routes[uid][bindings[uid]['route_id']]
        requested = {mover for mover, supporter in assisted_pairs if supporter == uid}
        # A paired proposal deliberately helps its selected mover. Additional
        # members are not silently attached merely because they also move.
        assisted = [m for m in movers if not requested or m in requested]
        options = []
        current = set(facts.get('execution_evidence', {}).get('members', {}).get(
            uid, {}).get('engageable_visible_targets', []))
        for mover in assisted:
            route = routes[mover][bindings[mover]['route_id']]
            for contact, evidence in _relation_options(facts, mover, route, uid, support, contacts):
                options.append((contact, mover, evidence))
        if not options: continue
        # Keep exactly one native aim owner/target per supporter. Selecting
        # the target compares its actual relation to this mover and existing
        # native opportunity, rather than distance from an arbitrary endpoint.
        contact, primary, evidence = min(options, key=lambda item: (
            item[2].get('relevance', {}).get('status') != 'supported',
            item[0]['id'] not in preferred_threats,
            item[0]['id'] not in current,
            _physical_key(by_id[item[1]]), tuple(item[0].get('position') or []), item[0]['id']))
        threat = contact['id']
        helped = {primary}
        # Only additional positive target-specific evidence warrants fan-out.
        # Unknown relevance remains valid for the explicitly proposed pair,
        # but is never expanded to all teammates as if help were established.
        helped.update(mover for c, mover, ev in options if c['id'] == threat
            and ev.get('relevance', {}).get('status') == 'supported')
        participants = [uid] + sorted(helped, key=lambda member: _physical_key(by_id[member]))
        number = 1
        used = {row['relation_id'] for row in out}
        while 'support_' + str(number).zfill(2) in used: number += 1
        out.append(dict(relation_id='support_' + str(number).zfill(2),
            supporter_ids=[uid], assisted_member_ids=participants[1:], threat_ids=[threat],
            route_ids={member: bindings[member]['route_id'] for member in participants},
            region_ids={member: bindings[member].get('region_id') for member in participants},
            original_deadline_s=deadline, local_permissions=dict(allow_support_gap=False),
            review_on=['relation_target_invalid', 'support_unformed', 'support_lost'],
            expected_opportunity='endpoint_2d_clear_in_range_native_fire_unverified'))
    return out


def build(facts, questions):
    """Build a small slate; every model option contains a complete binding."""
    from combat_prompt import route_facts
    from squad_task_contract import PURPOSES, REVIEW_TRIGGERS
    units = sorted((u for u in facts.get('members', []) if u.get('id') and _number(u.get('hp'), 1) > 0), key=_physical_key)
    # Members in provider context can include support-only actors. Original
    # route questions are the authoritative list of movable infantry here.
    route_uids = {name[6:] for name in questions if name.startswith('route_')}
    route_uids.update(name[5:] for name in questions if name.startswith('role_'))
    units = [u for u in units if u['id'] in route_uids]
    routes = {u['id']: route_facts(facts, u['id']) for u in units}
    accepted = facts.get('accepted_assignments', {})
    offered = questions.get('intent', {}).get('criteria', {})
    result = {}
    unavailable = []
    seen = set()
    old_intent = facts.get('engine_squad', {}).get('intent')

    def add(intent, bindings, label, *, hold=None, equipment=None, basis='endpoint_engagement', flank=None, assisted_pairs=()):
        if intent not in offered or bindings is None or len(result) >= MAX_CANDIDATES: return
        if set(bindings) != {u['id'] for u in units}: return
        deadline = min(45., max(12., 8. + max((
            _number(routes[uid].get(row['route_id'], {}).get('route_length'))
            for uid, row in bindings.items()), default=0.) / .09))
        relations = _support_relations(facts, bindings, routes, deadline,
            [row['threat_id'] for row in flank or []], assisted_pairs)
        if relations is None: return
        if intent in ('bound', 'flank'):
            roles_present = {row.get('role') for row in bindings.values() if not row.get('keep_assignment')}
            if not {'maneuver', 'fire_support'} <= roles_present or not relations: return
        fingerprint = (intent, tuple((uid, row.get('role'), row.get('route_id'), row.get('keep_assignment'))
                                   for uid, row in sorted(bindings.items())),
                       tuple(sorted((hold or {}).items())), (equipment or {}).get('actor'),
                       tuple((equipment or {}).get('supports', [])),
                       tuple((tuple(rel.get('supporter_ids', [])), tuple(rel.get('assisted_member_ids', [])),
                              tuple(rel.get('threat_ids', []))) for rel in relations))
        if fingerprint in seen: return
        seen.add(fingerprint)
        value = dict(intent=intent, label=label, bindings=copy.deepcopy(bindings),
                     unavailable_member_ids=list(unavailable),
                     unavailable_reason='no_native_route_and_no_keepable_accepted_task' if unavailable else '',
                     parallel=True, support_is_movement_gate=False, plan_deadline_s=deadline,
                     support_relations=relations)
        value['proposal_basis'] = basis
        value['comparison'] = _comparison(bindings, routes)
        if flank: value['flank_evidence'] = copy.deepcopy(flank)
        if hold: value['hold_contract'] = copy.deepcopy(hold)
        if equipment: value['equipment'] = copy.deepcopy(equipment)
        elif questions.get('equipment_actor', {}).get('criteria') and intent not in ('continue_order', 'revise_order'):
            value['equipment'] = dict(actor='unassigned', supports=[])
        key = 'plan_' + str(max((int(key[5:]) for key in result), default=0) + 1).zfill(2)
        value['candidate_id'] = key
        result[key] = value

    execution = (facts.get('cooperation_execution') or {}).get('bindings', {})
    terminal = {'failed', 'expired', 'cancelled', 'completed'}
    can_keep = {uid for uid in route_uids if 'keep_assignment' in questions.get('route_' + uid, {}).get('criteria', {})
                and accepted.get(uid, {}).get('keep_available') is True
                and execution.get(uid, {}).get('status') not in terminal}
    unavailable = sorted(uid for uid in route_uids if not routes.get(uid) and uid not in can_keep)
    units = [unit for unit in units if unit['id'] not in unavailable]
    active_uids = {unit['id'] for unit in units}
    if unavailable and not units: return {}
    old_task = facts.get('engine_squad', {}).get('task_contract', {})
    old_hold = None
    if old_task.get('purpose') in PURPOSES and old_task.get('review_on') in REVIEW_TRIGGERS:
        focus = old_task.get('focus', {})
        focus_key = focus.get('kind', 'mission_area') + (':' + str(focus['id']) if focus.get('id') else '')
        old_hold = dict(purpose=old_task['purpose'], review=old_task['review_on'], focus=focus_key)
    if 'continue_order' in offered and can_keep == active_uids and not unavailable:
        add('continue_order', _allocate(units, routes, {}, keep=can_keep, accepted=accepted),
            '完整继续已有任务；全部成员、区域目的与原期限保持', hold=old_hold)

    role_modes = {
        'advance': lambda i: 'maneuver', 'cover': lambda i: 'fire_support',
        'hold': lambda i: 'establish_fire', 'regroup': lambda i: 'establish_fire',
    }
    # Existing tasks are retained only by explicit keep bindings. New plans
    # remain possible for a member whose local samples do not reach the goal;
    # the limitation stays visible rather than fabricating a bridge.
    protected = set((facts.get('handover') or {}).get('protected_member_ids', []))
    protected.update(uid for uid, row in execution.items() if row.get('local_action_active') is True)
    # Explicit native protection cannot be made false by merely omitting the
    # keep route. A full plan with no legal keep is unavailable until handoff.
    if protected & active_uids - can_keep: return result
    compulsory_keep = {u['id'] for u in units if (not routes[u['id']] or u['id'] in protected) and u['id'] in can_keep}
    for intent, role_fn in role_modes.items():
        if intent not in offered: continue
        roles = {u['id']: role_fn(i) for i, u in enumerate(units)}
        bindings = _allocate(units, routes, roles, keep=compulsory_keep, accepted=accepted,
            prefer_goal=intent in ('hold', 'cover') and not facts.get('contacts'))
        if intent in ('hold', 'cover', 'regroup'):
            visible = sorted((row for row in facts.get('contacts', []) if row.get('visible') and row.get('id')),
                key=lambda row: (tuple(row.get('position') or []), row['id']))
            purposes = {'hold': ['defend_area', 'maintain_fire' if visible else 'wait_contact'],
                        'cover': ['screen_task', 'maintain_fire' if visible else 'wait_contact'],
                        'regroup': ['recover_then_review', 'screen_task']}[intent]
            for purpose in purposes:
                trigger = ('threat_or_recovery_changed' if purpose == 'recover_then_review' else
                           'ally_or_equipment_changed' if purpose == 'screen_task' else
                           'fire_or_position_invalid' if purpose == 'maintain_fire' else 'contact_or_route_changed')
                focus = 'contact:' + visible[0]['id'] if purpose == 'maintain_fire' and visible else 'mission_area'
                add(intent, bindings, intent + '；' + PURPOSES[purpose],
                    hold=dict(purpose=purpose, review=trigger, focus=focus))
        else: add(intent, bindings, intent + '；按所列完整职责并行执行，不互等射击')
        # A second physically different full plan preserves a real choice
        # between endpoint utility and covered travel. No extra native query,
        # actor Cartesian product or tactical preference is introduced.
        if intent in ('advance', 'cover'):
            alternative = _allocate(units, routes, roles, keep=compulsory_keep, accepted=accepted,
                prefer_goal=intent in ('cover',) and not facts.get('contacts'), policy='covered')
            if intent == 'cover':
                purpose = 'maintain_fire' if visible else 'wait_contact'
                trigger = 'fire_or_position_invalid' if visible else 'contact_or_route_changed'
                focus = 'contact:' + visible[0]['id'] if visible else 'mission_area'
                add(intent, alternative, '沿途遮挡与终点收益另作比较；' + PURPOSES[purpose],
                    hold=dict(purpose=purpose, review=trigger, focus=focus), basis='covered_travel')
            else:
                add(intent, alternative, '沿途遮挡不同的完整分工；终点仍按所列阻挡与射程复验', basis='covered_travel')

    by_id = {u['id']: u for u in units}
    if 'revise_order' in offered and old_intent in set(role_modes) | {'flank', 'bound'} and (
            old_intent not in ('hold', 'cover', 'regroup') or old_hold is not None):
        for index, unit in enumerate(sorted(units, key=lambda unit: (unit['id'] in can_keep, _physical_key(unit)))[:3]):
            uid = unit['id']; keeps = can_keep - {uid}
            if uid in protected: continue
            if keeps != active_uids - {uid}: continue
            roles = {uid: accepted.get(uid, {}).get('role') or role_modes.get(old_intent, lambda i: 'fire_support')(index)}
            add('revise_order', _allocate(units, routes, roles, keep=keeps, accepted=accepted),
                '仅重选' + uid + '；其余成员原任务原期限保持', hold=old_hold)

    # Equipment alternatives are complete plans, not independent actor/support
    # answers mixed with unrelated role/route selections. Eligibility is from
    # the original native-aware equipment question and is rechecked later.
    actor_options = questions.get('equipment_actor', {}).get('criteria', {})
    if actor_options:
        previous_equipment = facts.get('equipment_assignment') or {}
        for key, value in list(result.items()):
            if value['intent'] != 'revise_order': continue
            actor = previous_equipment.get('actor_id') if previous_equipment.get('status') == 'assigned' else 'unassigned'
            supports = previous_equipment.get('support_ids', [])
            if actor not in actor_options or any(uid not in value['bindings'] for uid in supports):
                result.pop(key)
            else:
                value['equipment'] = dict(actor=actor, supports=list(supports))
        base_plans = [value for value in result.values() if value['intent'] not in ('continue_order', 'revise_order')]
        for value in base_plans:
            value['equipment'] = dict(actor='unassigned', supports=[])
        base_plan = next((p for p in base_plans if p['intent'] in ('advance', 'bound')), next(iter(base_plans), None))
        if base_plan:
            for actor in sorted((key for key in actor_options if key != 'unassigned' and key in by_id), key=lambda uid: _physical_key(by_id[uid]))[:3]:
                if actor in compulsory_keep: continue
                if actor not in base_plan['bindings']: continue
                supports = [uid for uid in sorted(base_plan['bindings'], key=lambda member: _physical_key(by_id[member])) if uid != actor
                            and 'support' in questions.get('equipment_support_' + uid, {}).get('criteria', {})]
                add(base_plan['intent'], base_plan['bindings'], '装备执行者' + actor + '；其余按所列路线屏护',
                    hold=base_plan.get('hold_contract'), equipment=dict(actor=actor, supports=supports))
    # One fair budget supports both paired tactics. First cover actors and
    # meaningful partners, then deepen route variants. The model still makes
    # one whole-plan choice; no runtime tactical selector is added here.
    by_id = {u['id']: u for u in units}
    contacts = sorted((c for c in facts.get('contacts', []) if c.get('visible') and c.get('id')),
        key=lambda c: (tuple(c.get('position') or []), c['id']))
    probes, possible_pairs = _pair_probes(units, routes, compulsory_keep, contacts) if {'bound', 'flank'} & set(offered) else ([], 0)
    pair_counts, valid, pair_quality = {}, [], {}
    for mover_id, base_id, side_id, front_id in probes:
        pair_counts.setdefault(mover_id, {}).setdefault(base_id, 0)
        pair_counts[mover_id][base_id] += 1
        side, front = routes[mover_id][side_id], routes[base_id][front_id]
        if not _relation_options(facts, mover_id, side, base_id, front, contacts): continue
        pair_quality[mover_id, base_id, side_id, front_id] = _pair_evidence_key(
            facts, mover_id, side, base_id, front, contacts)
        valid.append((mover_id, base_id, side_id, front_id,
            _flank_evidence(by_id[mover_id], by_id[base_id], side, front, contacts)))

    # Keep alternatives by mover and support establishment/range policy.
    # Selection visits every mover before offering its second support variant.
    offered_partners = {'bound': {}, 'flank': {}}
    count_bound = count_flank = 0
    for variant, policy in enumerate(('engagement', 'fast_support', 'current_support')):
        for mover in units:
            mover_id = mover['id']
            matching = [p for p in valid if p[0] == mover_id]
            def ordered(intent):
                return sorted(matching, key=lambda p: (
                    pair_quality[p[:4]][:2],
                    pair_quality[p[:4]][2] if policy == 'current_support' else False,
                    any(old[1] == p[1] for old in offered_partners[intent].get(mover_id, [])) if policy == 'current_support' else False,
                    _route_score(routes[p[1]][p[3]], 'fire_support', 'fast_support' if policy == 'fast_support' else 'engagement'),
                    _route_score(routes[p[0]][p[2]], 'maneuver'),
                    _physical_key(by_id[p[1]]), _route_key(routes[p[0]][p[2]]), _route_key(routes[p[1]][p[3]])))
            if 'bound' in offered and (count_bound < 6 or variant == 2):
                for m, support, side_id, front_id, angle in ordered('bound'):
                    if variant == 2 and not _meaningful_extra_partner(facts,
                            (m, support, side_id, front_id), offered_partners['bound'].get(m, []), routes, contacts): continue
                    # Other members keep maneuvering; an additional supporter
                    # is proposed in the opposite oriented pair, not ID parity.
                    roles = {u['id']: 'maneuver' for u in units}; roles[support] = 'fire_support'
                    before = len(result)
                    add('bound', _allocate(units, routes, roles, fixed={m: side_id, support: front_id},
                        keep=compulsory_keep, accepted=accepted, policy=policy),
                        support + '支援' + m + '并行推进；关联威胁与通路见关系',
                        basis=('support_range_fit', 'fast_support_establishment', 'current_or_alternate_partner_support')[variant],
                        assisted_pairs=[(m, support)])
                    if len(result) > before:
                        count_bound += 1
                        offered_partners['bound'].setdefault(m, []).append((m, support, side_id, front_id)); break
            if 'flank' in offered and variant < 2 and count_flank < 4:
                for m, support, side_id, front_id, angle in ordered('flank'):
                    if not angle: continue
                    roles = {u['id']: 'fire_support' for u in units}; roles[m] = 'maneuver'
                    before = len(result)
                    kind = angle[0]['kind']
                    add('flank', _allocate(units, routes, roles, fixed={m: side_id, support: front_id},
                        keep=compulsory_keep, accepted=accepted, policy=policy),
                        m + ('利用已有侧位' if kind == 'use_existing_side_position' else '机动建立侧位') +
                        '；' + support + '针对共同威胁支援；效果待原生验证', basis=kind, flank=angle,
                        assisted_pairs=[(m, u['id']) for u in units if u['id'] != m])
                    if len(result) > before:
                        count_flank += 1
                        offered_partners['flank'].setdefault(m, []).append((m, support, side_id, front_id)); break

    for value in result.values():
        value['probe_coverage'] = dict(pair_probes=len(probes), possible_ordered_pairs=possible_pairs,
            visited_ordered_pairs=sum(len(x) for x in pair_counts.values()), per_mover=copy.deepcopy(pair_counts),
            unprobed_pairs_are_unknown=True)
        for uid, binding in value['bindings'].items():
            native = execution.get(uid, {})
            token = native.get('assignment_id', native.get('assignment_token'))
            if not isinstance(token, str): token = accepted.get(uid, {}).get('assignment_token')
            # A real accepted legacy assignment may predate a cooperation
            # grant. Its observed token remains authoritative; lack of a
            # local revision is unknown, never invented revision zero.
            if isinstance(token, str): binding['expected_assignment_id'] = token
            elif not native and not accepted.get(uid): binding['expected_assignment_id'] = ''
            revision = native.get('local_action_revision')
            if (isinstance(revision, (int, float)) and not isinstance(revision, bool)
                    and math.isfinite(revision) and revision >= 0 and revision == int(revision)):
                binding['expected_local_action_revision'] = int(revision)
    from cooperation_frontier import reduce_equivalent
    from cooperation_value import build_plan_facts
    result, reduction = reduce_equivalent(result, routes)
    for value in result.values():
        value['comparison']['role_facts'] = build_plan_facts(
            facts, value['bindings'], routes, value['support_relations'])
        value['candidate_reduction'] = copy.deepcopy(reduction)
    return result


class Binding:
    schema = SCHEMA
    def __init__(self, candidates, units, original_questions):
        self.candidates = copy.deepcopy(candidates)
        self.units = tuple(units)
        self.available = bool(candidates)
        self.original_questions = copy.deepcopy(original_questions)

    def decode(self, response):
        out = copy.deepcopy(response); answers = out.setdefault('answers', {})
        answer = answers.get('intent', {})
        key = answer.get('choice') if answer.get('type') == 'choice' else None
        if key not in self.candidates: raise ValueError('complete_squad_plan_not_offered')
        selected = self.candidates[key]
        # Provider-supplied independent member answers have no authority.
        for name in list(answers):
            if name.startswith(('role_', 'route_', 'task_', 'equipment_')) or name in ('hold_purpose', 'hold_review', 'hold_focus'):
                answers.pop(name)
        answer['choice'] = selected['intent']
        for uid, row in selected['bindings'].items():
            answers['route_' + uid] = dict(type='choice', choice=row['route_id'])
            if not row.get('keep_assignment'):
                answers['role_' + uid] = dict(type='choice', choice=row['role'])
        hold = selected.get('hold_contract')
        if hold:
            for name, field in (('hold_purpose', 'purpose'), ('hold_review', 'review'), ('hold_focus', 'focus')):
                answers[name] = dict(type='choice', choice=hold[field])
        equipment = selected.get('equipment')
        if equipment:
            answers['equipment_actor'] = dict(type='choice', choice=equipment['actor'])
            for name in self.original_questions:
                if name.startswith('equipment_support_'):
                    uid = name.removeprefix('equipment_support_')
                    answers[name] = dict(type='choice', choice='support' if uid in equipment['supports'] else 'not_assigned')
        out['_cooperation_selection'] = copy.deepcopy(selected)
        return out


def prepare(context, questions):
    from coordinate_prompt import unshare, share
    from combat_prompt import complete_executor_guidance, CLEAR_MODE
    from cooperation_prompt import prepare_model_view
    facts = unshare(context)
    candidates = build(facts, questions)
    state, out = copy.deepcopy(context), copy.deepcopy(questions)
    for name in list(out):
        if name.startswith(('route_', 'role_', 'task_', 'equipment_')) or name in (
                'flank_mover', 'flank_fire_base', 'hold_purpose', 'hold_review', 'hold_focus'):
            out.pop(name)
    guide = questions.get('intent', {}).get('instructions', '')
    # Compose shared factual guidance independently of the old wire's role
    # and output block, rather than discarding it at the first role heading.
    clear = CLEAR_MODE in guide if guide else facts.get('mission_status', {}).get('primary_objective', 'eliminate_opponents') == 'eliminate_opponents'
    fact_rules = complete_executor_guidance(facts, clear=clear)
    coordinate_guide = guide[guide.index('# 统一地图坐标协议'):] if '# 统一地图坐标协议' in guide else ''
    state['cooperation_candidates'] = copy.deepcopy(candidates)
    state['squad_task_contract'] = dict(version=SCHEMA, member_choice='one_complete_team_plan',
        candidate_limit=MAX_CANDIDATES, pair_probe_limit=MAX_PAIR_PROBES,
        authority='one_choice_binds_intent_all_members_routes_and_equipment',
        candidate_basis='native_route_facts_and_current_faction_contacts_only',
        accepted_only_after_native_receipt=True)
    state, criteria, comparison_guide = prepare_model_view(state, facts, candidates)
    if set(criteria) != set(candidates):
        raise ValueError('complete_squad_compact_view_candidate_scope_changed')
    out['intent'] = dict(type='choice', criteria=criteria,
        instructions=fact_rules + INSTRUCTIONS + comparison_guide + coordinate_guide)
    # The compact provider view never becomes the command. Exact complete
    # bindings and immutable native relationship specs stay in this decoder.
    return share(unshare(state)), out, Binding(candidates, [uid for uid in facts.get('member_region_choices', {})], questions)


def native_contract(selection, assignments, intent, previous=None):
    """Bind decoded native fields; never transport projected coordinates."""
    if not selection: return None
    if set(selection.get('bindings', {})) != set(assignments):
        raise ValueError('complete_squad_plan_member_scope_changed')
    bindings = {}
    for uid, assignment in assignments.items():
        chosen = selection['bindings'][uid]
        role = assignment.get('role')
        keep = chosen.get('keep_assignment') is True
        if not keep and role != chosen.get('role'):
            raise ValueError('complete_squad_plan_role_changed:' + uid)
        mode = 'area_hold' if intent in ('hold', 'cover', 'regroup') else 'maneuver' if role == 'maneuver' else 'fire_support'
        old_binding = (previous or {}).get('bindings', {}).get(uid, {}) if keep else {}
        bindings[uid] = dict(mode=old_binding.get('mode', mode), role=role, route_id=assignment.get('route_id', chosen.get('route_id')),
            region_id=assignment.get('region_id'), keep_assignment=keep,
            local_options=copy.deepcopy(old_binding.get('local_options', LOCAL_OPTIONS[mode])))
        for field in ('expected_assignment_id', 'expected_local_action_revision'):
            if field in chosen: bindings[uid][field] = copy.deepcopy(chosen[field])
        # A kept binding is the old complete spec with transient admission
        # guards added. It never refreshes a route or local permission budget.
        if keep and old_binding:
            for field in ('route_id', 'region_id', 'mode', 'role', 'local_options'):
                if field in old_binding: bindings[uid][field] = copy.deepcopy(old_binding[field])
    relations = []
    previous_relations = {row['relation_id']: row.get('spec', row)
        for row in (previous or {}).get('support_relations', [])}
    for projected in selection.get('support_relations', []):
        participants = projected.get('supporter_ids', []) + projected.get('assisted_member_ids', [])
        if not participants or any(uid not in bindings for uid in participants):
            raise ValueError('complete_squad_relation_member_scope_changed')
        if all(bindings[uid].get('keep_assignment') for uid in participants) and projected['relation_id'] in previous_relations:
            relation = copy.deepcopy(previous_relations[projected['relation_id']])
        else:
            relation = copy.deepcopy(projected)
            relation['route_ids'] = {uid: bindings[uid]['route_id'] for uid in participants}
            relation['region_ids'] = {uid: bindings[uid]['region_id'] for uid in participants}
        relations.append(relation)
    return dict(schema=SCHEMA, candidate_id=selection['candidate_id'], bindings=bindings,
                plan_deadline_s=selection['plan_deadline_s'],
                support_relations=relations,
                unavailable_member_ids=copy.deepcopy(selection.get('unavailable_member_ids', [])),
                unavailable_reason=selection.get('unavailable_reason', ''))
