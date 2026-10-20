"""Conservative equivalence/known-cost frontier for complete squad proposals.

This is bounded proposal cleanup, not a tactical chooser. It compares only
the same participants, roles, threats, purpose, permissions and observed
physical route semantics. Different endpoints, approaches, range fits,
current/unknown firing facts and side-position kinds are incomparable.
Unknown costs never become zero. The retained value is the original complete
candidate; no binding, deadline or native relation is patched after Choice.
"""
import copy
import json
import math


def _freeze(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _cost(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _route_parts(row):
    """Separate only comparable reported path costs from all other evidence.

    Endpoint and complete authored region sequence are mandatory. Without
    them, a route cannot be established as semantically equivalent merely
    because its opportunity summary looks similar.
    """
    if not row.get('region_path') or not isinstance(row.get('position'), (list, tuple)):
        return None, None
    semantic = copy.deepcopy(row)
    costs = [_cost(semantic.pop('route_length', None))]
    comparison = semantic.get('route_comparison')
    if isinstance(comparison, dict):
        costs.extend(_cost(comparison.pop(key, None)) for key in (
            'polyline_length', 'extra_length_vs_shortest', 'max_goal_distance_increase'))
        # Ratio describes the same length basis and is not an extra benefit.
        costs.append(_cost(comparison.pop('length_ratio_vs_shortest', None)))
        # Alternative-menu diagnostics do not change this route's semantics.
        comparison.pop('shorter_same_target_checks', None)
    else:
        costs.extend([None] * 4)
    return semantic, tuple(costs)


def _parts(candidate, routes):
    semantic = {key: copy.deepcopy(candidate.get(key)) for key in (
        'intent', 'hold_contract', 'equipment', 'parallel', 'support_is_movement_gate',
        'plan_deadline_s', 'unavailable_member_ids', 'unavailable_reason', 'flank_evidence')}
    semantic['bindings'] = {}
    costs = []
    for uid, binding in sorted(candidate.get('bindings', {}).items()):
        item = copy.deepcopy(binding)
        route_id = item.pop('route_id', None)
        if binding.get('keep_assignment'):
            # A kept binding is native accepted work, not a replaceable route.
            item['route_id'] = route_id
        else:
            row, row_costs = _route_parts(routes.get(uid, {}).get(route_id, {}))
            if row is None: return None, None
            item['route'] = row
            costs.extend(row_costs)
        semantic['bindings'][uid] = item
    relations = []
    for relation in candidate.get('support_relations', []):
        item = copy.deepcopy(relation)
        # Route IDs are private menu handles. Their physical route, region,
        # actor guards and all relation permissions remain in the signature.
        item.pop('route_ids', None)
        relations.append(item)
    semantic['support_relations'] = relations
    return _freeze(semantic), tuple(costs)


def _dominates(left, right):
    if len(left) != len(right): return False
    # Unknown on either side is comparable only to the same unknown state;
    # known-vs-unknown cannot establish a lower cost or justify pruning.
    if any((a is None) != (b is None) for a, b in zip(left, right)): return False
    known = [(a, b) for a, b in zip(left, right) if a is not None]
    return bool(known) and all(a <= b for a, b in known) and any(a < b for a, b in known)


def reduce_equivalent(candidates, routes):
    """Remove proved equivalent/dominated variants, retaining original specs.

    Input is bounded by the existing 32-candidate builder, so <= 496 pair
    comparisons. This makes no native query, model call, score or selection.
    """
    groups, removed = {}, {}
    for key, candidate in candidates.items():
        signature, costs = _parts(candidate, routes)
        if signature is None: continue
        frontier = groups.setdefault(signature, [])
        same = next(((other, vector) for other, vector in frontier if vector == costs), None)
        dominating = next(((other, vector) for other, vector in frontier if _dominates(vector, costs)), None)
        if same or dominating:
            other, _ = same or dominating
            removed[key] = dict(retained=other, reason='equivalent_observed_semantics' if same else 'known_cost_dominated_same_semantics')
            continue
        obsolete = [other for other, vector in frontier if _dominates(costs, vector)]
        for other in obsolete:
            removed[other] = dict(retained=key, reason='known_cost_dominated_same_semantics')
        frontier[:] = [(other, vector) for other, vector in frontier if other not in obsolete]
        frontier.append((key, costs))
    # Resolve references when a later better representative replaces a former
    # representative, while preserving the survivor's exact original value.
    for row in removed.values():
        while row['retained'] in removed:
            row['retained'] = removed[row['retained']]['retained']
    kept = {key: value for key, value in candidates.items() if key not in removed}
    return kept, dict(input_count=len(candidates), retained_count=len(kept),
        removed=removed, policy='same_semantics_known_cost_frontier_no_tactical_quota',
        unknown_is_zero=False)
