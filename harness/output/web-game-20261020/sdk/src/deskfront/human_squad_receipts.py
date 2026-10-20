"""Engine receipt reconciliation for Deskfront squad orders."""
from background_query import receipt_unknown


def rejection_facts(receipt, command, world):
    """Classify only explicit engine codes; unknown is not a blocked path."""
    code = str(receipt.get('code') or receipt.get('message') or 'unknown')
    categories = {
        'navigation': {'unreachable', 'path_blocked', 'path_failed', 'region_not_walkable'},
        'actor_validation': {'invalid_actor', 'invalid_squad_members', 'invalid_unit_authority', 'leave_equipment_first'},
        'stale_observation': {'stale_run', 'stale_map', 'stale_observation', 'stale_map_before_dispatch', 'stale_observation_before_dispatch', 'stale_order_version',
                              'stale_soldier_assignment', 'stale_candidate_query', 'intent_expired'},
        'authority': {'stale_control_epoch', 'invalid_squad_authority', 'squad_member_already_owned',
                       'control_busy', 'handover_not_applied'},
        'protocol': {'duplicate_id', 'invalid_id', 'invalid_squad_identity', 'invalid_squad_intent',
                     'invalid_squad_region', 'invalid_assignments', 'invalid_member_route',
                     'unsupported_action', 'invalid_position', 'unknown_operation', 'unknown_faction'},
        'transport': {'command_timeout'},
        'handover': {'handover_required', 'handover_pending', 'stale_local_action_revision'},
    }
    category = next((kind for kind, codes in categories.items() if code in codes), 'unclassified')
    facts = dict(code=code, category=category, command_id=command.get('id'),
                 order_id=command.get('order_id'))
    if category == 'actor_validation':
        units = {u['id']: u for u in world.get('units', [])}
        ids = command.get('unit_ids', [])
        facts['actor_observations'] = {
            uid: ('missing_from_snapshot' if uid not in units else
                  'wrong_faction' if units[uid].get('faction') != command.get('faction') else
                  'dead' if units[uid].get('hp', 0) <= 0 else
                  'not_active' if units[uid].get('deployment_phase', 'active') != 'active' else
                  'alive') for uid in ids}
        facts['duplicate_actor_ids'] = sorted({uid for uid in ids if ids.count(uid) > 1})
        # These observations explain the context, not a guessed rejection cause.
    return facts

class SquadReceiptMixin:
    def _receipts(self, receipts):
        for ident, pending in list(self.pending_commands.items()):
            receipt = receipts.get(ident)
            if receipt is None:
                continue
            if receipt_unknown(receipt):
                unresolved=receipt.get('status')=='unresolved'
                pending['order']['pending']=not unresolved
                pending['order']['accepted']=None
                pending['order']['receipt_status']='unresolved' if unresolved else 'unknown'
                pending['order']['receipt_message']=receipt.get('message')
                if not pending.get('unknown_recorded') or unresolved:
                    self._record('human-engine-receipt-unknown',command_id=ident,command=pending['command'],
                        request_id=pending['request_id'],receipt=receipt,engine_behavior='continue_authoritative_native_assignment')
                    pending['unknown_recorded']=True
                if unresolved:
                    # No rejected/path-failed wake, mutation resend, budget
                    # reset or guessed acceptance. A fresh later review uses
                    # the observed native assignments and original guards.
                    if pending['order'] is self.last_order and pending.get('previous_order') is not None:
                        self.last_order=pending['previous_order']
                    del self.pending_commands[ident]
                continue
            pending['order']['pending'] = False
            pending['order']['accepted'] = receipt.get('accepted') is True
            tick = receipt.get('tick')
            if receipt.get('accepted') is True and type(tick) is int and tick >= 0:
                # Transport acknowledgements can arrive before the next state
                # poll. Preserve the native tick, not a fabricated squad state.
                pending['order']['accepted_tick'] = tick
                pending['order']['accepted_run_id'] = pending['command'].get('run_id')
            # Personnel become an active task only with the corresponding
            # real native order receipt; an old response cannot reassign them.
            if (receipt.get('accepted') is True
                    and pending['command'].get('run_id') == self.world.get('run_id')
                    and pending['command'].get('plan_version') == self.version
                    and pending['order'] is self.last_order):
                from copy import deepcopy
                self.equipment_assignment = deepcopy(pending['order'].get('equipment_assignment'))
                if self.equipment_assignment:
                    self.equipment_assignment['order_id'] = pending['order']['order_id']
                from coordination_handover import supersede as supersede_handover
                supersede_handover(self, pending.get('handover_request', {}).get('serial'))
            self.accepted_orders += receipt.get('accepted') is True
            if pending['command']['run_id'] == self.world.get('run_id'):
                self.run_accepted_orders += receipt.get('accepted') is True
            if not receipt.get('accepted'):
                facts = rejection_facts(receipt, pending['command'], self.world)
                facts['command_id'] = ident
                pending['order']['rejection'] = facts
                if pending['command']['run_id'] == self.world.get('run_id'):
                    self.feedback = 'engine_rejected:' + facts['code']
                    self.last_command_rejection = facts
                    if facts['category'] == 'handover':
                        from coordination_handover import defer as defer_handover, protected_members, squad as native_squad
                        command = pending['command']
                        protected = protected_members(native_squad(self).get('cooperation_plan', {}), self.world.get('time', 0))
                        previous_ids = set((pending.get('previous_order') or {}).get('assignments', {}))
                        previous_ids &= {unit['id'] for unit in self._members(self.world)}
                        changed = (set(command.get('unit_ids', [])) | set(protected) | previous_ids) - set(command.get('keep_unit_ids', []))
                        handover_request = dict(pending.get('handover_request') or {}, observation_tick=receipt.get('tick'))
                        defer_handover(self, changed, request=handover_request,
                            intent=command.get('intent'), reason=facts['code'])
                        if pending['order'] is self.last_order and 'previous_order' in pending:
                            self.last_order = pending['previous_order']
                    else:
                        self._wake('path_blocked' if facts['category'] == 'navigation' else 'command_rejected',
                                   dict(reason=self.feedback, **facts))
            self._record('human-engine-receipt', command_id=ident, command=pending['command'],
                         request_id=pending['request_id'], receipt=receipt)
            del self.pending_commands[ident]

