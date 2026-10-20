"""Bound local choices to one native accepted cooperation assignment.

This module composes mechanical legal action alternatives; it never executes,
chooses a winning tactic, infers success, or grants itself an assignment.
"""
import copy
import math

MODES = {'continue_role', 'hold_fire', 'covered_advance', 'local_reposition', 'opportunity_action'}
LABELS = {
    'continue_role': '继续当前职责；不发新动作，不重新审批小队已选步骤',
    'hold_fire': '短时保持当前有效射位；由原生有界接管并复验父任务',
    'covered_advance': '沿本兵已选走廊选择带遮挡线索的接近；终点掩体不证明途中安全或隐身',
    'local_reposition': '职责内调整射位或掩体；不改队友任务和小队走廊',
    'opportunity_action': '利用一次已验证的局部火力或道具机会，实际结果另看回执',
}


def support_action_contract(plan, uid):
    """Mirror accepted native relation permissions; no geometry is inferred."""
    rows = []
    for raw in plan.get('support_relations', []):
        if not isinstance(raw, dict): continue
        spec = raw.get('spec', raw)
        if not isinstance(spec, dict) or uid not in spec.get('supporter_ids', []): continue
        targets = spec.get('threat_ids', [])
        permissions = spec.get('local_permissions', {})
        rows.append(dict(relation_id=spec.get('relation_id', raw.get('relation_id')),
                         threat_ids=sorted(value for value in targets if isinstance(value, str)) if isinstance(targets, list) else [],
                         allow_support_gap=isinstance(permissions, dict) and permissions.get('allow_support_gap') is True))
    if not rows: return None
    # Native permits stationary focus/grenade/satchel only when the target belongs to
    # every relation this member supports. One restrictive relation is enough
    # to require squad review for movement or incompatible target choices.
    common = set(rows[0]['threat_ids'])
    for row in rows[1:]: common.intersection_update(row['threat_ids'])
    return dict(allow_support_gap=all(row['allow_support_gap'] for row in rows),
                compatible_focus_target_ids=sorted(common), relations=rows,
                basis='accepted_native_relation_spec')


def grant(squad, uid, now):
    """Only a real native plan/binding can authorize local choices."""
    plan = squad.get('cooperation_plan', {})
    if not isinstance(plan, dict) or plan.get('schema') != 'combat-coordination/v1':
        return {}
    if plan.get('status') in ('failed', 'cancelled', 'completed', 'expired', 'rejected'):
        return {}
    bindings = plan.get('bindings', {})
    if not isinstance(bindings, dict):
        return {}
    binding = bindings.get(uid, {})
    if not isinstance(binding, dict) or binding.get('status') in ('failed', 'cancelled', 'completed', 'expired'):
        return {}
    plan_id = binding.get('grant_plan_id') or plan.get('plan_id')
    token = squad.get('assignment_tokens', {}).get(uid)
    until = binding.get('until', plan.get('until'))
    if (not isinstance(plan_id, str) or not plan_id or not token
            or not isinstance(until, (int, float)) or isinstance(until, bool)
            or not math.isfinite(until) or now >= until
            or 'assignment_token' in binding and binding['assignment_token'] != token):
        return {}
    options = binding.get('local_options')
    if not isinstance(options, list):
        return {}
    allowed = [value for value in options if value in MODES]
    if not allowed:
        return {}
    result = dict(schema='local-behavior/v1', grant_plan_id=plan_id,
                parent_assignment_token=copy.deepcopy(token), local_options=allowed,
                role=binding.get('role'), mode=binding.get('mode'),
                region_id=binding.get('region_id'), route_id=binding.get('route_id'),
                until=until, review_due=bool(binding.get('review_due') or plan.get('review_due')))
    contract = support_action_contract(plan, uid)
    if contract: result['support_action_contract'] = contract
    return result


def identity(value):
    if not value: return None
    contract = value.get('support_action_contract') or {}
    relations = tuple(sorted((str(row.get('relation_id')), tuple(sorted(row.get('threat_ids', []))),
                              row.get('allow_support_gap') is True) for row in contract.get('relations', [])))
    return value.get('grant_plan_id'), value.get('parent_assignment_token'), relations


def action_options(raw_options, sites, permission):
    """Attach an explicit behavior to existing legal native actions.

    Opportunity skills are exposed only if the original action builder already
    found native legal target checks. Covered advance requires positive cover
    evidence; absence of that evidence stays unknown.
    """
    offered, criteria = {}, {}
    allowed = set(permission.get('local_options', []))
    for key, original in raw_options.items():
        intent, site = original['intent'], sites.get(original.get('site_id'), {})
        support = permission.get('support_action_contract') or {}
        if support and support.get('allow_support_gap') is not True:
            compatible = (intent in ('continue_task', 'report_blocked', 'hold_fire_position')
                          or intent in ('focus_fire', 'grenade', 'satchel') and original.get('target_id') in support.get('compatible_focus_target_ids', []))
            if not compatible:
                continue
        modes = []
        if intent == 'continue_task' and 'continue_role' in allowed:
            modes.append('continue_role')
        elif intent == 'report_blocked':
            # Reporting is diagnostic, never a new autonomous behavior lease.
            offered[key], criteria[key] = copy.deepcopy(original), '报告职责内受阻；不发移动或换目标'
            continue
        elif intent == 'hold_fire_position' and 'hold_fire' in allowed:
            modes.append('hold_fire')
        elif intent in ('move_to_site', 'rush_to_site', 'prone_approach'):
            if 'local_reposition' in allowed and intent == 'move_to_site':
                modes.append('local_reposition')
            evidence = site.get('close_engagement', {})
            covered = bool(site.get('hard_cover') or site.get('cover_key')
                           or evidence.get('covered_samples', 0) > 0
                           or evidence.get('occluded_samples', 0) > 0
                           or evidence.get('route_cover_samples', 0) > 0
                           or any(target.get('geometry', {}).get('crossing_samples', 0) > 0
                                  for target in evidence.get('targets', []) if isinstance(target, dict)))
            # Advancing requires actual goal gain as well as cover evidence.
            if ('covered_advance' in allowed and covered
                    and isinstance(site.get('goal_distance_gain'), (int, float))
                    and site['goal_distance_gain'] > 0):
                modes.append('covered_advance')
        elif intent in ('occupy_cover', 'peek_fire') and 'local_reposition' in allowed:
            modes.append('local_reposition')
        elif intent in ('focus_fire', 'grenade', 'breach_cover', 'satchel', 'approach_satchel') and 'opportunity_action' in allowed:
            modes.append('opportunity_action')
        for mode in modes:
            option_id = mode + ':' + key
            row = copy.deepcopy(original)
            row['local_behavior'] = {name: copy.deepcopy(permission[name])
                                     for name in ('schema', 'parent_assignment_token', 'grant_plan_id')}
            row['local_behavior']['mode'] = mode
            offered[option_id] = row
            criteria[option_id] = LABELS[mode] + '；实际动作 ' + intent
            if row.get('site_id'):
                criteria[option_id] += '；位置 ' + row['site_id']
            if row.get('target_id'):
                criteria[option_id] += '；目标 ' + row['target_id']
    return offered, criteria

