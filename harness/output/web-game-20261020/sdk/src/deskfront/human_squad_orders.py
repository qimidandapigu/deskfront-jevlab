"""Translation of validated JEV choices into engine squad orders."""
import math
import copy
import json

from squad_region_choices import split_approach
from firing_position_contract import repeated_failed_assignment


def relation_identity(relations):
    """Execution meaning only; predicted effects and admission guards are facts."""
    rows = []
    for relation in relations or []:
        row = {key: copy.deepcopy(relation[key]) for key in (
            'supporter_ids', 'assisted_member_ids', 'threat_ids', 'route_ids', 'region_ids',
            'local_permissions', 'review_on') if key in relation}
        for key in ('supporter_ids', 'assisted_member_ids', 'threat_ids', 'review_on'):
            if key in row: row[key] = sorted(row[key])
        rows.append(json.dumps(row, sort_keys=True, separators=(',', ':')))
    return tuple(sorted(rows))

class SquadOrderMixin:
    def _submit_task_review(self, intent, response, request):
        """Acknowledge an actual model review without replacing member work."""
        if not request.get('squad_task_contract') or intent not in ('hold','cover','regroup'):return False
        selection = response.get('_cooperation_selection')
        if selection and selection.get('intent') == 'continue_order' and not selection.get('hold_contract'):
            return False  # Legacy hold without a contract stays unchanged, not relabelled.
        from squad_task_contract import selected_hold, make_review
        context=request['context']
        contract=selected_hold(response,request,context,intent)
        review=make_review(response,request,context,intent)
        if not contract or not review:raise ValueError('explicit_hold_review_required')
        if any(p['command'].get('action')=='squad_order' for p in self.pending_commands.values()):
            raise ValueError('hold_review_awaiting_engine_receipt')
        engine=self.world.get('squad_behavior',{}).get('squads',{}).get(self.squad_id,{})
        last=self.last_order or {}
        assignments=copy.deepcopy(engine.get('assignments',last.get('assignments',{})))
        if not assignments or engine.get('order_id')!=last.get('order_id'):raise ValueError('hold_review_order_changed')
        if set(assignments)!={u['id'] for u in self._members(self.world)}:raise ValueError('hold_review_member_scope_changed')
        command=dict(action='squad_order',source='lm',faction=self.team,squad_id=self.squad_id,
            order_id=last['order_id'],plan_version=self.version,keep_unit_ids=list(assignments),
            unit_ids=list(assignments),intent=intent,assignments=assignments,
            position=copy.deepcopy(last['position']),radius=last['radius'],
            task_contract=contract,task_review=review,run_id=self.world['run_id'],seen_tick=int(self.world['tick']),
            control_epoch=self.world.get('control_epochs',{}).get(self.team,0))
        if last.get('cooperation_plan'):
            command['cooperation_plan'] = copy.deepcopy(last['cooperation_plan'])
        if getattr(self.game,'session_id',None):command['instance_id']=self.game.session_id
        status,receipt=self.state.submit(command,source='lm')
        self._record('human-task-review-submitted',request_serial=request['serial'],command=command,
            http_status=status,queue_result=receipt,request_id=response.get('requestId'))
        if status!=202:raise ValueError('engine_review_queue_rejected:'+str(receipt.get('error',status)))
        # The normal native receipt lane confirms or rejects the review.
        self.pending_commands[receipt['id']]=dict(command=command,request_id=response.get('requestId'),
            submitted=self.clock(),order=copy.deepcopy(last))
        return True

    def _submit(self, intent, members, response, request):
        assignments = {}
        answers = response.get('answers', {})
        selection = response.get('_cooperation_selection')
        if request.get('cooperation_contract'):
            unavailable = set((selection or {}).get('unavailable_member_ids', []))
            if not selection or set(selection.get('bindings', {})) != {u['id'] for u in members} - unavailable:
                raise ValueError('complete_squad_plan_member_scope_changed')
            if not unavailable <= {u['id'] for u in members}:
                raise ValueError('complete_squad_plan_unavailable_scope_changed')
            current_assignments = self._accepted_assignments()
            live_grants = self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {}).get('cooperation_plan', {}).get('bindings', {})
            for uid in unavailable:
                keepable = current_assignments.get(uid, {}).get('keep_available') and live_grants.get(uid, {}).get('status') not in ('failed', 'expired', 'cancelled', 'completed')
                if request.get('member_region_choices', {}).get(uid) or keepable:
                    raise ValueError('complete_squad_plan_omitted_available_member:' + uid)
            if unavailable:
                self._record('human-plan-members-unavailable', unit_ids=sorted(unavailable),
                             reason='model_selected_explicit_native_route_limitation')
                members = [u for u in members if u['id'] not in unavailable]
            for uid, row in selection['bindings'].items():
                if row.get('keep_assignment') and live_grants.get(uid, {}).get('status') in ('failed', 'expired', 'cancelled', 'completed'):
                    raise ValueError('cooperation_member_no_longer_keepable:' + uid)
        if answers.get('intent', {}).get('choice') == 'continue_order':
            if not self._order_matches_plan():
                raise ValueError('engine_order_changed_while_deciding')
            self._submit_task_review(intent,response,request)
            from coordination_handover import supersede as supersede_handover
            supersede_handover(self, request.get('serial'))
            self.kept_orders += 1
            self._record('human-order-kept', request_serial=request['serial'],
                         reason='explicit_continue_order', order_id=self.last_order['order_id'])
            return
        accepted = request.get('accepted_assignments', {})
        current = self._accepted_assignments()
        keep_ids = []
        for u in members:
            uid = u['id']
            if answers.get('route_' + uid, {}).get('choice') != 'keep_assignment':
                continue
            old, live = accepted.get(uid, {}), current.get(uid, {})
            if not old.get('keep_available') or not live.get('keep_available') or old.get('order_id') != live.get('order_id'):
                raise ValueError('accepted_assignment_changed:' + uid)
            keep_ids.append(uid)
        region_choices = request.get('member_region_choices', {})
        # No native anchor means no verifiable assignment for this member.
        # Keep the member visible to both models, but never manufacture a
        # route to the shared goal. Other validated members can still act.
        excluded = [u['id'] for u in members if u['id'] not in keep_ids and u['id'] in region_choices and not region_choices[u['id']]]
        members = [u for u in members if u['id'] not in excluded]
        if excluded:
            if request.get('cooperation_contract'):
                raise ValueError('complete_squad_plan_route_unavailable')
            self._record('human-members-without-route', unit_ids=excluded, reason='no_native_route_candidate')
        if not members:
            raise ValueError('no_member_has_native_route_candidate')
        for u in members:
            if u['id'] in keep_ids:
                # Copy the actual accepted command, not its projected summary
                # or a regenerated menu route to the same endpoint.
                engine = self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {})
                assignments[u['id']] = copy.deepcopy(engine.get('assignments',
                    (self.last_order or {}).get('assignments', {}))[u['id']])
                continue
            fallback = 'fire_support' if u.get('weapon') in ('rocket', 'cannon') else 'maneuver' if u.get('weapon') == 'smg' else 'establish_fire'
            selected = response.get('answers', {}).get('role_' + u['id'], {}).get('choice')
            allowed = {'establish_fire', 'maneuver', 'fire_support'}
            old_assignment = current.get(u['id'], {})
            role = selected if selected in allowed else old_assignment.get('role') if old_assignment.get('role') in allowed else fallback
            assignments[u['id']] = dict(role=role,
                source='jev' if selected in allowed else 'retained' if old_assignment.get('role') in allowed else 'weapon_fallback')
            options = region_choices.get(u['id'], {})
            if options:
                route_key = response.get('answers', {}).get('route_' + u['id'], {}).get('choice')
                old = (self.last_order or {}).get('assignments', {}).get(u['id'], {})
                chosen = options.get(route_key)
                if request.get('cooperation_contract') and chosen is None:
                    raise ValueError('complete_squad_plan_route_not_offered:' + u['id'])
                if chosen is None:
                    # A moving unit rewrites the prefix of its region path;
                    # retain the same sampled endpoint before considering a
                    # new option.  Otherwise a provider timeout can move it
                    # to the first menu item simply because the old path
                    # cursor changed.
                    if old.get('endpoint_id'):
                        chosen = next((row for row in options.values()
                                       if row.get('endpoint_id') == old.get('endpoint_id')), None)
                if chosen is None:
                    chosen = next((row for row in options.values()
                                   if row['region_id'] == old.get('region_id')
                                   and row['region_path'] == old.get('region_path')), None)
                if chosen is None:
                    chosen = next((row for row in options.values()
                                   if row['region_id'] == self.plan['region_id']), next(iter(options.values())))
                assignments[u['id']].update(region_id=chosen['region_id'],
                    region_path=chosen['region_path'], position=chosen['position'],
                    route_positions=chosen['route_positions'],
                    endpoint_id=chosen.get('endpoint_id',''),
                    endpoint_basis=chosen.get('endpoint_basis',''),
                    approach_region=chosen.get('approach_region', chosen['region_id']),
                    route_id=route_key if route_key in options else 'fallback',
                    route_source='jev' if route_key in options else 'retained_or_fallback')
                # Preserve the sampled prefix's meaning through native receipts;
                # reaching a nine-point transport segment is not final arrival.
                assignments[u['id']].update({key: copy.deepcopy(chosen[key]) for key in (
                    'team_goal_region', 'route_target_region', 'remaining_region_hops',
                    'route_reaches_team_goal') if key in chosen})
        light = [u for u in members if u.get('weapon') not in ('rocket', 'cannon')]
        # Composition quality is feedback, never permission to rewrite valid JEV choices.
        self._record('human-role-composition', intent=intent,
                     has_mover=any(row['role']=='maneuver' for row in assignments.values()),
                     has_fire_base=any(row['role']=='establish_fire' for row in assignments.values()),
                     living_members=len(members), diagnostic_only=True)
        if intent == 'flank' and not request.get('squad_task_contract'):
            answers = response.get('answers', {})
            mover_id = answers.get('flank_mover', {}).get('choice')
            base_id = answers.get('flank_fire_base', {}).get('choice')
            if mover_id == 'not_applicable':
                mover_id = None
            if base_id == 'not_applicable':
                base_id = None
            continued = answers.get('intent', {}).get('choice') == 'revise_order'
            if continued and self.last_order:
                previous = self.last_order.get('assignments', {})
                # Pair identity belongs to the accepted assignment, not a P
                # number in a newly sampled route menu. Unused pair parameters
                # must preserve the previous named members on continuation.
                mover_id = mover_id or next((uid for uid, row in previous.items()
                    if row.get('role') == 'maneuver' and row.get('source') == 'jev_flank_member'), None)
                base_id = base_id or next((uid for uid, row in previous.items()
                    if row.get('role') == 'establish_fire' and row.get('source') == 'jev_flank_member'), None)
            explicit_routes = continued
            if isinstance(mover_id, str) and isinstance(base_id, str) and not continued:
                explicit_routes = (answers.get('route_' + mover_id, {}).get('choice') in region_choices.get(mover_id, {})
                    and answers.get('route_' + base_id, {}).get('choice') in region_choices.get(base_id, {}))
            def chosen_route(uid):
                assignment = assignments.get(uid, {})
                return next((row for row in region_choices.get(uid, {}).values()
                    if row.get('region_id') == assignment.get('region_id')
                    and row.get('region_path') == assignment.get('region_path')), None)
            mover_route = chosen_route(mover_id) if isinstance(mover_id, str) else None
            base_route = chosen_route(base_id) if isinstance(base_id, str) else None
            named_pair = (isinstance(mover_id, str) and isinstance(base_id, str)
                          and mover_id != base_id and mover_id in {u['id'] for u in light}
                          and base_id in {u['id'] for u in light})
            if named_pair:
                # The specific JEV member choices take precedence over its
                # generic per-member role answers. Never replace its routes.
                if mover_id not in keep_ids: assignments[mover_id].update(role='maneuver', source='jev_flank_member')
                if base_id not in keep_ids: assignments[base_id].update(role='establish_fire', source='jev_flank_member')
            self._record('human-flank-selection-audit', request_serial=request['serial'],
                         mover_id=mover_id, fire_base_id=base_id,
                         selected_routes={uid: row.get('route_id') for uid, row in assignments.items()},
                         selected_regions={uid: row.get('region_id') for uid, row in assignments.items()},
                         named_pair=named_pair, explicit_routes=explicit_routes,
                         region_paths_split=split_approach(mover_route, base_route),
                         diagnostic_only=True)
        # A fresh order id cannot turn the same proven blocked endpoint into
        # an effective firing site. Return the fact to JEV; never pick a
        # substitute route or role on its behalf.
        for unit in members:
            uid = unit['id']
            if uid in keep_ids:
                continue
            failure = repeated_failed_assignment(unit, assignments.get(uid, {}), current.get(uid, {}), self.world.get('time', 0))
            if failure:
                self._record('human-firing-position-rejected', request_serial=request['serial'],
                             unit_id=uid, evidence=failure, engine_behavior='no_replacement_order_submitted')
                raise ValueError('firing_site_still_native_blocked:' + uid + ':choose_changed_endpoint_or_nonfire_task')
        # Canonicalize only the comparison signature. The wire always carries
        # this request's selected remaining path; only native acceptance can
        # decide whether old task identity/cursor/deadline may be retained.
        signature_assignments = copy.deepcopy(assignments)
        for uid, row in list(signature_assignments.items()):
            old = current.get(uid, {})
            path, old_path = row.get('region_path', []), old.get('region_path', [])
            if (old.get('keep_available') and path and old_path
                    and len(path) <= len(old_path) and old_path[-len(path):] == path
                    and all(row.get(k) == old.get(k) for k in ('role', 'region_id', 'endpoint_id', 'approach_region', 'position'))):
                signature_assignments[uid] = copy.deepcopy(old)
        # Region paths are navigation progress, not command identity: the
        # native anchor rewrites them as a soldier crosses each cell.  Using
        # the full path here used to cancel/reissue the same order every time
        # a prefix disappeared.  Keep the stable destination/approach site;
        # fall back to a rounded point for legacy choices without site_id.
        def route_identity(row):
            endpoint = row.get('endpoint_id')
            if endpoint:
                return ('endpoint', row.get('region_id'), endpoint,
                        row.get('approach_region', row.get('region_id')), tuple(row.get('region_path', [])))
            point = row.get('position')
            if isinstance(point, (list, tuple)) and len(point) == 2:
                return ('point', row.get('region_id'), round(float(point[0]), 3), round(float(point[1]), 3), tuple(row.get('region_path', [])))
            return ('region', row.get('region_id'))
        from equipment_assignment import assignment_key
        selected_equipment = request.get('selected_equipment_assignment')
        signature = (tuple((uid, row['role'], route_identity(row)) for uid, row in signature_assignments.items()), self.identity, tuple(sorted(u['id'] for u in members)), self.plan['region_id'],
                     tuple(self.plan['position']), intent, assignment_key(selected_equipment))
        if selection:
            # Migrating an equivalent old order must actually acquire its new
            # native cooperation grant once; later equivalent reviews keep it.
            from combat_coordination_candidates import native_contract
            selected_contract = native_contract(selection, assignments, intent,
                (self.last_order or {}).get('cooperation_plan'))
            signature += (tuple((uid, row['mode'], tuple(row['local_options']))
                                for uid, row in selected_contract['bindings'].items()),
                          relation_identity(selected_contract.get('support_relations')))
        native_cooperation = self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {}).get('cooperation_plan', {})
        explicit_terminal_retry = bool(selection) and any(
            not row.get('keep_assignment') and native_cooperation.get('bindings', {}).get(uid, {}).get('status')
                in ('failed', 'expired', 'cancelled', 'completed')
            for uid, row in selection.get('bindings', {}).items())
        if (self.last_order and self.last_order.get('signature') == signature
                and not explicit_terminal_retry and (self._order_matches_plan() or self.last_order.get('pending'))):
            if self._order_matches_plan():self._submit_task_review(intent,response,request)
            if self._order_matches_plan():
                from coordination_handover import supersede as supersede_handover
                supersede_handover(self, request.get('serial'))
            self.kept_orders += 1
            self._record('human-order-kept', request_serial=request['serial'], reason='unchanged_persistent_intent',
                         order_id=self.last_order['order_id'])
            return
        if any(p['command'].get('action') == 'squad_order' for p in self.pending_commands.values()):
            # Do not put conflicting orders behind a command lacking a real engine receipt.
            self.revision['executor'] += 1
            self._record('human-order-deferred', reason='awaiting_engine_receipt')
            return
        from coordination_handover import protected_members, defer as defer_handover
        protected = protected_members(native_cooperation, self.world.get('time', 0))
        # Removing a protected member is also a reassignment. Considering only
        # the new assignment keys would omit the very actor being removed.
        changed_protected = sorted(set(protected) - set(keep_ids))
        if changed_protected:
            # Store intent metadata only, never this answer's old routes or
            # coordinates. All dependent members keep their accepted work.
            defer_handover(self, changed_protected, request=request, intent=intent)
            return
        self.order_serial += 1
        command = dict(action='squad_order', source='lm', faction=self.team, squad_id=self.squad_id,
                       order_id=f'{self.squad_id}:{self.version}:{self.order_serial}',
                       plan_version=self.version, keep_unit_ids=keep_ids,
                       unit_ids=[u['id'] for u in members], intent=intent, assignments=assignments,
                       position=list(self.plan['position']), radius=self.plan['radius'],
                       run_id=self.world['run_id'], seen_tick=int(self.world['tick']),
                       control_epoch=self.world.get('control_epochs', {}).get(self.team, 0))
        if selection:
            command['cooperation_plan'] = selected_contract
        if request.get('squad_task_contract') and intent in ('hold','cover','regroup'):
            from squad_task_contract import selected_hold, make_review
            contract=selected_hold(response,request,request['context'],intent)
            review=make_review(response,request,request['context'],intent)
            if not contract or not review:raise ValueError('explicit_hold_task_required')
            command.update(task_contract=contract,task_review=review)
            for uid,area in contract.get('member_areas',{}).items():
                if uid in assignments:assignments[uid]['task_area']=copy.deepcopy(area)
        if getattr(self.game, 'session_id', None):
            command['instance_id'] = self.game.session_id
        status, receipt = self.state.submit(command, source='lm')
        self._record('human-order-submitted', request_serial=request['serial'], request_id=response.get('requestId'),
                     raw_choice=response.get('answers'), command=command, http_status=status, queue_result=receipt)
        if status != 202:
            raise ValueError('engine_queue_rejected:' + str(receipt.get('error', status)))
        previous_order = self.last_order
        self.last_order = dict(order_id=command['order_id'], intent=intent, region_id=self.plan['region_id'],
                               position=command['position'], radius=command['radius'], assignments=assignments,
                               signature=signature, pending=True, accepted=False,
                               equipment_assignment=copy.deepcopy(selected_equipment))
        self.last_order.update(plan_version=self.version, navigation_revision=self.world.get('navigation_revision'))
        if command.get('cooperation_plan'):
            self.last_order['cooperation_plan'] = copy.deepcopy(command['cooperation_plan'])
        self.pending_commands[receipt['id']] = dict(command=command, request_id=response.get('requestId'),
            submitted=self.clock(), order=self.last_order, previous_order=previous_order,
            handover_request=dict(serial=request.get('serial'), started=request.get('started', self.clock()),
                                  started_game=request.get('started_game', self.world.get('time', 0))))

