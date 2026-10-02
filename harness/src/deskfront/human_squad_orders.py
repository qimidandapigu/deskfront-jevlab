"""Translation of validated JEV choices into engine squad orders."""
import math

from squad_region_choices import split_approach

class SquadOrderMixin:
    def _submit(self, intent, members, response, request):
        assignments = {}
        region_choices = request.get('member_region_choices', {})
        for u in members:
            fallback = 'fire_support' if u.get('weapon') in ('rocket', 'cannon') else 'maneuver' if u.get('weapon') == 'smg' else 'establish_fire'
            selected = response.get('answers', {}).get('role_' + u['id'], {}).get('choice')
            allowed = {'fire_support'} if u.get('weapon') in ('rocket', 'cannon') else {'establish_fire', 'maneuver', 'fire_support'}
            old_assignment = (self.last_order or {}).get('assignments', {}).get(u['id'], {})
            role = selected if selected in allowed else old_assignment.get('role') if old_assignment.get('role') in allowed else fallback
            assignments[u['id']] = dict(role=role,
                source='jev' if selected in allowed else 'retained' if old_assignment.get('role') in allowed else 'weapon_fallback')
            options = region_choices.get(u['id'], {})
            if options:
                route_key = response.get('answers', {}).get('route_' + u['id'], {}).get('choice')
                old = (self.last_order or {}).get('assignments', {}).get(u['id'], {})
                chosen = options.get(route_key)
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
        light = [u for u in members if u.get('weapon') not in ('rocket', 'cannon')]
        if light and not any(assignments[u['id']]['role'] == 'establish_fire' for u in light):
            lead = max(light, key=lambda u: u.get('weapon_range', 0))
            assignments[lead['id']].update(role='establish_fire', source='dependency_repair')
        if intent in ('advance', 'bound', 'flank') and len(light) > 1 and not any(
                assignments[u['id']]['role'] == 'maneuver' for u in light):
            supporters = [u for u in light if assignments[u['id']]['role'] == 'establish_fire']
            candidates = [u for u in light if u not in supporters] or supporters
            mover = min(candidates, key=lambda u: (u.get('weapon') != 'smg', u.get('weapon_range', 0), u['id']))
            assignments[mover['id']].update(role='maneuver', source='dependency_repair')
        if intent == 'flank':
            answers = response.get('answers', {})
            mover_id = answers.get('flank_mover', {}).get('choice')
            base_id = answers.get('flank_fire_base', {}).get('choice')
            if mover_id == 'not_applicable':
                mover_id = None
            if base_id == 'not_applicable':
                base_id = None
            continued = answers.get('intent', {}).get('choice') == 'continue_order'
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
                assignments[mover_id].update(role='maneuver', source='jev_flank_member')
                assignments[base_id].update(role='establish_fire', source='jev_flank_member')
            self._record('human-flank-selection-audit', request_serial=request['serial'],
                         mover_id=mover_id, fire_base_id=base_id,
                         selected_routes={uid: row.get('route_id') for uid, row in assignments.items()},
                         selected_regions={uid: row.get('region_id') for uid, row in assignments.items()},
                         named_pair=named_pair, explicit_routes=explicit_routes,
                         region_paths_split=split_approach(mover_route, base_route),
                         diagnostic_only=True)
        # Region paths are navigation progress, not command identity: the
        # native anchor rewrites them as a soldier crosses each cell.  Using
        # the full path here used to cancel/reissue the same order every time
        # a prefix disappeared.  Keep the stable destination/approach site;
        # fall back to a rounded point for legacy choices without site_id.
        def route_identity(row):
            endpoint = row.get('endpoint_id')
            if endpoint:
                return ('endpoint', row.get('region_id'), endpoint,
                        row.get('approach_region', row.get('region_id')))
            point = row.get('position')
            if isinstance(point, (list, tuple)) and len(point) == 2:
                return ('point', row.get('region_id'), round(float(point[0]), 3), round(float(point[1]), 3))
            return ('region', row.get('region_id'))
        signature = (tuple((uid, row['role'], route_identity(row)) for uid, row in assignments.items()), self.identity, tuple(sorted(u['id'] for u in members)), self.plan['region_id'],
                     tuple(self.plan['position']), intent)
        if self.last_order and self.last_order.get('signature') == signature and (self._order_matches_plan() or self.last_order.get('pending')):
            self.kept_orders += 1
            self._record('human-order-kept', request_serial=request['serial'], reason='unchanged_persistent_intent',
                         order_id=self.last_order['order_id'])
            return
        if self.pending_commands:
            # Do not put conflicting orders behind a command lacking a real engine receipt.
            self.revision['executor'] += 1
            self._record('human-order-deferred', reason='awaiting_engine_receipt')
            return
        self.order_serial += 1
        command = dict(action='squad_order', source='lm', faction=self.team, squad_id=self.squad_id,
                       order_id=f'{self.squad_id}:{self.version}:{self.order_serial}',
                       unit_ids=[u['id'] for u in members], intent=intent, assignments=assignments,
                       position=list(self.plan['position']), radius=self.plan['radius'],
                       run_id=self.world['run_id'], seen_tick=int(self.world['tick']),
                       control_epoch=self.world.get('control_epochs', {}).get(self.team, 0))
        if getattr(self.game, 'session_id', None):
            command['instance_id'] = self.game.session_id
        status, receipt = self.state.submit(command, source='lm')
        self._record('human-order-submitted', request_serial=request['serial'], request_id=response.get('requestId'),
                     raw_choice=response.get('answers'), command=command, http_status=status, queue_result=receipt)
        if status != 202:
            raise ValueError('engine_queue_rejected:' + str(receipt.get('error', status)))
        self.last_order = dict(order_id=command['order_id'], intent=intent, region_id=self.plan['region_id'],
                               position=command['position'], radius=command['radius'], assignments=assignments,
                               signature=signature, pending=True, accepted=False)
        self.pending_commands[receipt['id']] = dict(command=command, request_id=response.get('requestId'),
                                                    submitted=self.clock(), order=self.last_order)

