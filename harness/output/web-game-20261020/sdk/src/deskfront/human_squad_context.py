"""Authoritative world observation and model-facing context projections for Deskfront squads."""
import copy
from ammunition_rules import ammunition_rules
import json
import math
from pathlib import Path

from auto_regions import generate
from human_squad_validation import _position
from strategic_regions import navigation_anchor
from engagement_feedback import review as engagement_review, failed_sites
from actor_roster import last_fire, effective_range
from assignment_fire_review import review as firing_assignment_review, participation as attack_position_review
from firing_position_contract import describe as describe_firing_position
from execution_feedback import progress_evidence
from movement_stall_episode import public as local_execution_episode
from fire_effectiveness import public as fire_effectiveness
from weapon_affordance import profile as weapon_profile, at_distance as weapon_distance_value


def _rocket_evidence(unit, visible_ids, known_cover_ids, friendly_ids):
    """Project own native rocket checks; never infer safety or enemy state."""
    if unit.get('weapon') != 'rocket':
        return {}
    combat = unit.get('combat', {})
    facts = {}
    option_fields = ('source', 'time', 'navigation_revision', 'target_id', 'target_distance',
                     'mode', 'clear', 'fireable', 'target_line_clear', 'ready',
                     'release_block_reason', 'reason', 'blocker_id', 'distance',
                     'cover_hp', 'cover_damage', 'decision_reason')
    if isinstance(combat.get('rocket_fire_options'), list):
        options = []
        for raw in combat['rocket_fire_options']:
            if not isinstance(raw, dict) or raw.get('target_id') not in visible_ids:
                continue
            row = {key: copy.deepcopy(raw[key]) for key in option_fields if key in raw}
            blocker = row.get('blocker_id')
            if blocker and blocker not in visible_ids | known_cover_ids | friendly_ids:
                row.pop('blocker_id', None)
                row.pop('cover_hp', None)
                row.pop('cover_damage', None)
            options.append(row)
        # Empty native checks and an unavailable native field remain distinct.
        facts['rocket_fire_options'] = options
    raw = combat.get('rocket_impact')
    if isinstance(raw, dict):
        facts['rocket_impact'] = {}
        if raw.get('target_id') in visible_ids:
            fields = ('source', 'status', 'time', 'target_id', 'hit_kind', 'hit_id',
                      'cover_hp', 'cover_destroyed')
            row = {key: copy.deepcopy(raw[key]) for key in fields if key in raw}
            known_hits = known_cover_ids if row.get('hit_kind') == 'cover' else visible_ids | friendly_ids
            if row.get('hit_id') and row['hit_id'] not in known_hits:
                for key in ('hit_kind', 'hit_id', 'cover_hp', 'cover_destroyed'):
                    row.pop(key, None)
            facts['rocket_impact'] = row
    return facts


class SquadContextMixin:
    def _equipment_assignment(self):
        from equipment_assignment import live_assignment
        return live_assignment(self.plan.get('equipment_goal'),
            getattr(self, 'equipment_assignment', None), self.version,
            self.world, self.team, self._members(self.world))

    def _equipment_goal(self):
        from equipment_assignment import effective_goal
        return effective_goal(self.plan.get('equipment_goal'), self._equipment_assignment())

    def _order_observation_pending(self):
        """A real same-run receipt is newer than the observed world snapshot."""
        last = self.last_order or {}
        accepted_tick, observed_tick = last.get('accepted_tick'), self.world.get('tick')
        return bool(last.get('accepted') is True
                    and last.get('accepted_run_id') == self.world.get('run_id')
                    and self.world.get('run_id')
                    and type(accepted_tick) is int and type(observed_tick) is int
                    and 0 <= observed_tick < accepted_tick)

    def _accepted_assignments(self):
        """Current engine commitments, independent of the newly sampled menu."""
        engine = self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {})
        last = self.last_order or {}
        matches = bool(last.get('accepted') and last.get('order_id') == engine.get('order_id'))
        assignments = engine.get('assignments', last.get('assignments', {}) if matches else {})
        motion = self._motion_execution()
        alive = {u['id']: u for u in self._members(self.world)}
        rows = {}
        for uid, assignment in assignments.items():
            if uid not in alive:
                continue
            row = copy.deepcopy(assignment)
            if uid in engine.get('task_contract', {}).get('member_areas', {}):
                row['task_area'] = copy.deepcopy(engine['task_contract']['member_areas'][uid])
            if uid in engine.get('assignment_execution', {}):
                row['assignment_execution'] = copy.deepcopy(engine['assignment_execution'][uid])
            execution = motion.get(uid, {})
            firing_review = firing_assignment_review(alive[uid], assignment,
                self.unit_history.get(uid, {}), self.world.get('time', 0), execution)
            reason = ''
            if not matches:
                reason = 'accepted_order_not_confirmed'
            elif (last.get('region_id') != self.plan.get('region_id')
                  or last.get('plan_version', self.version) != self.version
                  or engine.get('plan_version', self.version) != self.version
                  or not _position(engine.get('goal'))
                  or math.dist(engine['goal'], self.plan['position']) >= .035):
                reason = 'plan_changed'
            elif engine.get('phase') in ('lost', 'failed', 'blocked'):
                reason = 'squad_execution_failed'
            elif engine.get('navigation_revision', last.get('navigation_revision')) not in (None, self.world.get('navigation_revision')):
                reason = 'navigation_changed'
            elif uid in engine.get('retained_member_failures', {}) or (execution.get('state') == 'failed' and execution.get('order_id') == engine.get('order_id')):
                reason = 'member_execution_failed'
            elif firing_review:
                reason = 'firing_assignment_unresolved'
            row.update(order_id=engine.get('order_id'),
                       assignment_token=engine.get('assignment_tokens', {}).get(uid),
                       cursor=engine.get('member_cursors', {}).get(uid),
                       motion_state=execution.get('state', 'unknown'),
                       keep_available=not reason, unavailable_reason=reason)
            if assignment.get('role') == 'establish_fire':
                row['firing_position'] = describe_firing_position(
                    alive[uid], assignment.get('position'), self.world.get('time', 0))
            if firing_review:
                row['firing_review'] = firing_review
            rows[uid] = row
        return rows

    def _motion_execution(self):
        members = {u['id'] for u in self._members(self.world)}
        rows = self.world.get('squad_behavior', {}).get('intent_executor', {}).get('motion', {})
        fields = ('order_id', 'source', 'state', 'reason', 'since', 'until', 'ended_at',
                  'destination', 'route_length', 'remaining_length', 'progress_at', 'navigation_revision',
                  'hold_position', 'hold_until', 'arrived_at', 'review_accepted_id')
        return {uid: {key: copy.deepcopy(row[key]) for key in fields if key in row}
                for uid, row in rows.items() if uid in members}

    def _motion_feedback(self):
        squad = self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {})
        order = squad.get('order_id')
        previous = getattr(self, '_motion_notified', set())
        current = set()
        for uid, row in self._motion_execution().items():
            failed = row.get('state') == 'failed'
            due = row.get('state') == 'completed' and row.get('reason') == 'hold_review_due' and not row.get('review_accepted_id')
            if not (failed or due) or (row.get('order_id') != order and uid not in squad.get('retained_member_failures', {})):
                continue
            key = (self.world.get('run_id'), uid, order, row.get('ended_at'), row.get('reason'))
            current.add(key)
            if key not in previous:
                self._wake('task_review_due' if due else 'participation_gap', dict(unit_id=uid, reason='hold_review_due' if due else 'motion_execution_failed',
                    execution_reason=row.get('reason'), order_id=order))
        self._motion_notified = current

    def _execution_evidence(self, members, contacts, *, read_only=False):
        now = self.world.get('time', 0)
        visible = [c for c in contacts if c.get('visible')]
        visible_ids = {c['id'] for c in visible}
        known_cover_ids = {c['id'] for c in self.world.get('covers', []) if c.get('id')}
        friendly_ids = {u['id'] for u in self.world.get('units', []) if u.get('faction') == self.team}
        assignments = self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {}).get('assignments', {})
        rows = {}
        for u in members:
            history = self.unit_history.get(u['id'], {})
            if read_only:
                # Spectator publishing must not start/renew an observation
                # episode. The controller tick alone maintains this history.
                history = copy.deepcopy(history)
            weapon_range = effective_range(u)
            distances = {c['id']: math.dist(u['position'], c['position']) for c in visible}
            in_range = [key for key, distance in distances.items() if weapon_range is not None and distance <= weapon_range]
            limited = bool(visible) and weapon_range is not None and not in_range
            if limited and history.get('range_limited_since') is None:
                history['range_limited_since'] = now
            elif not limited:
                history['range_limited_since'] = None
            last_shot = last_fire(u)
            last_hit = u.get('last_hit_at', -1)
            rows[u['id']] = dict(firing_awareness=copy.deepcopy(u.get("combat", {}).get("firing_awareness", {})) if u.get("combat", {}).get("firing_awareness", {}).get("target_id") in distances else {}, fire_block_reason=u.get("combat", {}).get("fire_block_reason", ""), weapon_range=weapon_range,
                nearest_visible_contact_distance=round(min(distances.values()), 3) if distances else None,
                visible_contacts_in_weapon_range=in_range,
                engageable_visible_targets=[target for target in u.get('combat', {}).get('engageable_targets', []) if target in distances],
                has_fired_this_run=last_shot >= 0,
                seconds_since_last_shot=round(max(0, now - last_shot), 1) if last_shot >= 0 else None,
                seconds_since_last_hit=round(max(0, now - last_hit), 1) if last_hit >= 0 else None,
                recent_fire_observed=last_shot >= 0 and 0 <= now - last_shot <= 5,
                fire_basis='shared_equipment_participation' if u.get('support_activity') else 'personal_weapon',
                seconds_without_measured_progress=round(max(0, now - history.get('progress_at', now)), 1),
                stationary_seconds=round(max(0, now - history.get('stationary_at', now)), 1),
                observation_window_s=round(max(0, now - history.get('observed_since', now)), 1),
                outside_visible_enemy_range_for_s=round(now - history['range_limited_since'], 1) if history.get('range_limited_since') is not None else None,
                range_status='all_visible_contacts_outside_weapon_range' if limited else 'visible_contact_in_range_not_proof_of_clear_shot' if in_range else 'no_visible_contact_or_unknown_range',
                wounded=u.get('hp', 100) < .6 * u.get('max_hp', 100),
                needs_recovery=u.get('suppression', 0) >= .35 or bool(u.get('survival_reason')))
            # Copy engine facts; neither missing telemetry nor a risk flag chooses an action.
            # last_hit_at records a hit dealt, not damage received.
            damage_at = u.get('last_damage_at')
            rows[u['id']]['seconds_since_last_damage'] = (
                round(now - damage_at, 1) if type(damage_at) in (int, float)
                and math.isfinite(damage_at) and 0 <= damage_at <= now else None)
            regeneration = u.get('combat', {}).get('regeneration')
            if isinstance(regeneration, dict):
                rows[u['id']]['regeneration'] = {
                    key: copy.deepcopy(regeneration[key]) for key in
                    ('active', 'delay', 'remaining_delay', 'rate', 'healed', 'inactive_reason', 'blocked_reason')
                    if key in regeneration}
            fact = rows[u['id']]['firing_awareness']
            rows[u['id']].update(_rocket_evidence(u, visible_ids, known_cover_ids, friendly_ids))
            rows[u['id']].update(progress_evidence(history, now))
            rows[u['id']]['engagement_failure'] = engagement_review(history, fact, now,
                self.plan.get('region_id'), bool(self.plan and
                    math.dist(u['position'], self.plan['position']) <= self.plan.get('radius', .1)))
            rows[u['id']]['recent_failed_firing_sites'] = failed_sites(history, now)
            rows[u['id']]['local_execution_episode'] = local_execution_episode(history, now)
            rows[u['id']]['fire_effectiveness'] = fire_effectiveness(history, now)
            rows[u['id']]['attack_position_review'] = attack_position_review(history, now)
            weapon_unit = dict(u, position_role=assignments.get(u['id'], {}).get('role', u.get('position_role')))
            rows[u['id']]['weapon_profile'] = weapon_profile(weapon_unit)
            combat = u.get('combat', {})
            capabilities = combat.get('personal_action_capabilities')
            if isinstance(capabilities, dict) and isinstance(capabilities.get('hold_fire_position'), dict):
                rows[u['id']]['personal_action_capabilities'] = {
                    'hold_fire_position': {key: copy.deepcopy(capabilities['hold_fire_position'][key]) for key in (
                        'supported', 'available', 'duration_seconds', 'requires_fireable_target',
                        'preserves_assignment_route') if key in capabilities['hold_fire_position']}}
            if isinstance(combat.get('firing_hold'), dict):
                rows[u['id']]['firing_hold'] = {key: copy.deepcopy(combat['firing_hold'][key]) for key in (
                    'action_id', 'state', 'status', 'reason', 'since', 'until', 'started_at', 'ended_at',
                    'remaining', 'review_due', 'preserves_assignment_route') if key in combat['firing_hold']}
            rows[u['id']]['engagement_value'] = weapon_distance_value(weapon_unit, min(distances.values())) if distances else {}
            cover_execution = u.get('combat', {}).get('cover_execution', {})
            if not isinstance(cover_execution, dict):
                cover_execution = {}
            rows[u['id']]['cover_execution'] = {key: copy.deepcopy(cover_execution[key]) for key in (
                'phase', 'reason', 'since', 'attempt_id', 'review_required', 'cover_id',
                'anchor', 'peek', 'shot_at', 'travel', 'net_displacement',
                'last_progress_at', 'cover_key', 'review_handoff') if key in cover_execution}
            if cover_execution.get('target_id') in distances:
                rows[u['id']]['cover_execution']['target_id'] = cover_execution['target_id']
        return dict(members=rows, basis='self weapon range and reported shots; visible faction contacts only; distance alone does not prove firing line or safety; lack of measured movement/fire/cover gain is a review signal, not proof of useless waiting')

    def _order_matches_plan(self):
        if not self._members(self.world):
            assets = self._support_options([])
            execution = self.world.get('support_execution', {})
            return bool(assets) and all(
                self.support_orders.get(a['id'], {}).get('accepted') and
                self.support_orders[a['id']].get('region_id') == self.plan.get('region_id') and
                execution.get(a['id'], {}).get('order_id') == self.support_orders[a['id']]['order_id'] and
                execution[a['id']].get('state') not in ('failed', 'cancelled') for a in assets)
        engine = self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {})
        # Continuing the same native order also preserves its authority scope.
        # A casualty, mounting change or new member needs a fresh squad scope;
        # surviving members can still keep their individual accepted work.
        if 'assignments' in engine and set(engine['assignments']) != {u['id'] for u in self._members(self.world)}:
            return False
        if any(row.get('unavailable_reason') == 'firing_assignment_unresolved'
               for row in self._accepted_assignments().values()):
            return False
        if any(u['id'] in engine.get('retained_member_failures', {}) for u in self._members(self.world)):
            return False
        if any(row.get('state') == 'failed' and row.get('order_id') == engine.get('order_id')
               for row in self._motion_execution().values()):
            return False
        return bool(self.last_order and self.last_order.get('accepted') and engine
                    and engine.get('order_id') == self.last_order['order_id']
                    and self.last_order.get('plan_version', self.version) == self.version
                    and engine.get('plan_version', self.version) == self.version
                    and engine.get('navigation_revision', self.last_order.get('navigation_revision')) in (None, self.world.get('navigation_revision'))
                    and engine.get('phase') not in ('blocked', 'lost', 'failed', 'regrouped', 'cover_ready')
                    and self.last_order['region_id'] == self.plan.get('region_id')
                    and math.dist(self.last_order['position'], self.plan['position']) < .035
                    and _position(engine.get('goal')) and math.dist(engine['goal'], self.plan['position']) < .035
                    and abs(self.last_order.get('radius', .1) - self.plan['radius']) < .01)

    def _mission_status(self, members):
        now = self.world.get('time', 0)
        from task_modes import mode_id
        mode=mode_id(self.world)
        flag = self.world.get('objective', {}).get('flag', {}) if mode=='capture' else {}
        defending = flag.get('owner') == self.team
        acute = any(u.get('suppression', 0) >= .6 or u.get('reload_remaining', 0) > 0
                    or u.get('survival_reason') for u in members)
        stationary = bool(members) and all(now - self.unit_history.get(u['id'], {}).get('stationary_at', now) >= 8 for u in members)
        firing = any(last_fire(u) >= 0 and now-last_fire(u) <= 5 for u in members)
        expired = bool(self.stage_review_at is not None and now >= self.stage_review_at and stationary
                       and not firing and not acute and not defending)
        approach_stalled = bool(self.plan.get('stage') in ('approach', 'probe', 'reposition')
            and members and not defending and self.stage_review_at is not None and now >= self.stage_review_at
            and all(now - self.unit_history.get(u['id'], {}).get('approach_at', now) >= 20
                    and math.dist(u['position'], self.plan['position']) > self.plan['radius'] for u in members))
        intermediate_complete = bool(self.arrived_at is not None
            and self.plan.get('stage') in ('approach', 'probe', 'reposition')
            and self.plan.get('region_id') != 'objective_flag' and not defending)
        prolonged_pressure = bool(not defending and now-(self.region_started if self.region_started is not None else now) >= 15 and any(
            self.unit_history.get(u['id'], {}).get('pressure_since') is not None
            and now-self.unit_history[u['id']]['pressure_since'] >= 15 for u in members))
        return dict(primary_objective=('capture_and_hold_flag' if mode=='capture' else 'eliminate_opponents'), flag_owner=flag.get('owner', ''),
                    held_seconds=flag.get('held_seconds', 0), required_seconds=flag.get('required_seconds'),
                    contested=flag.get('contested', False), defending_flag=defending,
                    acute_recovery=acute, all_stationary=stationary, recent_actual_fire=firing,
                    wait_expired=expired, approach_stalled=approach_stalled, intermediate_complete=intermediate_complete,
                    prolonged_pressure=prolonged_pressure,
                    note='低血量不会自动恢复；approach_stalled表示开火或掩体调整未缩短到区域的距离，需要改选接近区域；即时自保仍有效')

    def _load_regions(self, members):
        key = (self.world.get('run_id'), self.world.get('navigation_revision'))
        if key == self._topology_key:
            return
        self.regions = {}
        raw = self.world.get('strategic_topology')
        if raw is None and self.config.get('spatial_path'):
            try:
                raw = json.loads(Path(str(self.config['spatial_path']) + '.topology.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                return
        if not isinstance(raw, dict) or raw.get('run_id') != key[0] or raw.get('revision') != key[1]:
            return
        try:
            regions, owners = generate(raw)
            if not regions:
                return
            objective = self.world.get('objective', {})
            from task_modes import mode_id
            if mode_id(self.world)=='capture' and _position(objective.get('position')) and objective.get('radius', 0) > 0:
                cells = [(key, point) for key, point in raw['cells'].items()
                         if math.dist(point, objective['position']) < objective['radius'] * .6]
                if cells:
                    key, point = min(cells, key=lambda row: math.dist(row[1], objective['position']))
                    parent = owners[key]
                    regions['objective_flag'] = dict(id='objective_flag', center=list(point), radius=.06,
                        neighbors=[parent], cells=[list(point)], sample_step=raw.get('step', .075),
                        walkability='native_sampled', purpose='进入实际旗圈并占领；不是仅接近旗点')
                    regions[parent]['neighbors'].append('objective_flag')
            self.topology = raw
            self.regions = regions
            self._topology_key = key
        except (KeyError, TypeError, ValueError):
            self.feedback = 'native_topology_invalid'

    def _active_destination_ids(self):
        """Old stage geometry is transit-only, never a new tactical destination."""
        growth = self.world.get('world_growth', {})
        left = growth.get('mission', {}).get('left')
        if not growth.get('enabled') or not isinstance(left, (int, float)):
            return set(self.regions)
        return {key for key, region in self.regions.items()
                if region['center'][0] >= left}

    def _eligible_regions(self, members):
        """Offer destinations reachable by any member, with per-member limits."""
        movable_ids = {u['id'] for u in self._members(self.world)}
        navigators = [u for u in members if u['id'] in movable_ids or u.get('kind') == 'tank']
        if not navigators:
            # A fixed mortar selects a support zone, not a walking destination.
            guns = [g for g in self.world.get('at_guns', []) if g.get('faction') == self.team and g.get('crew_ids')]
            zones = {k:r for k,r in self.regions.items() if k in self._active_destination_ids()
                     and any(_position(g.get('position')) and
                             g.get('minimum_range', 0) <= math.dist(g['position'], r['center']) <= g.get('range', 0)
                             for g in guns)}
            # Missing range remains unknown; fixture/older snapshots may still
            # identify the crew's own area for observation, never move the crew.
            if not zones:
                zones = {k:r for k,r in self.regions.items() if k in self._active_destination_ids()
                         and any(math.dist(u['position'], r['center']) <= r.get('radius', .15) for u in members)}
            return zones, '' if zones else 'no_support_zone_in_current_stage'
        from navigation_access import build, destinations
        facts = build(navigators, self.regions, self.topology, self._active_destination_ids())
        eligible = destinations(facts)
        issue = '' if eligible else 'no_member_reaches_current_stage_destination'
        if not eligible:
            unresolved = next((uid for uid, row in facts['members'].items()
                               if row['status'] == 'anchor_unresolved'), None)
            if unresolved:
                issue = 'unit_navigation_anchor_unresolved:' + unresolved
        return {k: self.regions[k] for k in sorted(eligible)}, issue

    def _context(self, members):
        from task_modes import mode_id
        clear_mode = mode_id(self.world) == 'clear_exit'
        now = self.world.get('time', 0)
        contacts = self.world.get('squad_behavior', {}).get('perception', {}).get(self.team, {}).get('contacts', [])
        search_clues = self.contact_memory.observe(self.world, self.team)
        if isinstance(contacts, dict):
            contacts = list(contacts.values())
        # Native perception may retain a last-seen contact for a few seconds
        # after a stage is cleared. Dead units are already authoritative in the
        # same snapshot, so never present them as live targets in a new plan.
        known_dead = {unit.get('id') for unit in self.world.get('units', [])
                      if unit.get('hp', 0) <= 0}
        known = []
        for contact in contacts:
            if contact.get('id') in known_dead:
                continue
            if not _position(contact.get('position')):
                continue
            last_seen = contact.get('last_seen', now if contact.get('visible') else -100)
            if not contact.get('visible') and not 0 <= now - last_seen <= 6.:
                continue
            known.append({k: contact[k] for k in ('id', 'position', 'visible', 'last_seen', 'kind', 'weapon') if k in contact})
        squad = self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {})
        safe_squad = {k: squad[k] for k in ('order_id', 'intent', 'phase', 'reason', 'goal', 'progress', 'protection', 'duties', 'fire_positions', 'mover', 'support_ids', 'coordination', 'assignments', 'task_contract', 'task_review', 'assignment_execution') if k in squad}
        distances = {u['id']: round(math.dist(u['position'], self.plan['position']), 3)
                     for u in members} if self.plan else {}
        evidence = self._execution_evidence(members, known)
        accepted = self._accepted_assignments()
        from squad_cooperation import build as cooperation_board
        cooperation = cooperation_board(self.world, self.team, members, known, safe_squad,
                                        accepted, evidence['members'], self._motion_execution())
        from navigation_access import build as navigation_access
        access = navigation_access(members, self.regions, self.topology,
                                   self._active_destination_ids(), self.plan.get('region_id'))
        reports = {uid: dict(choice=agent.get('last_choice'),
                            reported_order=agent.get('reported_order'),
                            age_s=round(now-agent['reported_at'], 1))
                   for uid, agent in self.soldiers.agents.items()
                   if uid in {u['id'] for u in members} and agent.get('last_choice') == 'report_blocked'
                   and 0 <= now-agent.get('reported_at', -100) <= 20}
        member_rows = []
        from actor_roster import roster
        actor_modes = {r['id']: r for r in roster(self.world, self.team)}
        for unit in members:
            row = {key: unit[key] for key in ('id', 'position', 'hp', 'max_hp', 'weapon', 'ammo', 'ammo_infinite',
                'suppression', 'in_cover', 'posture', 'reload_remaining', 'survival_reason',
                'goal', 'weapon_range', 'last_shot_at', 'emotion', 'support_activity') if key in unit}
            weapon = self.world.get('weapons', {}).get(unit.get('weapon'), {})
            # Capacity and reload duration come from this engine snapshot. A
            # missing weapon configuration stays unknown, not a rifle default.
            for source, target in (('magazine', 'magazine_capacity'), ('reload', 'reload_duration_s')):
                if source in weapon:
                    row[target] = weapon[source]
            member_rows.append(row)
            row['capabilities'] = actor_modes.get(unit['id'], {})
        # Vehicles remain under native navigation, but the squad must know
        # whether its fire-support asset is behind the line and actually firing.
        support_assets = [{key: unit[key] for key in ('id', 'kind', 'weapon', 'position',
                           'goal', 'weapon_range', 'last_shot_at', 'hp', 'order_mode', 'ammo_infinite') if key in unit}
                          | {'engagement_position': copy.deepcopy(unit.get('combat', {}).get('engagement_position', {}))}
                          for unit in self.world.get('units', []) if unit.get('faction') == self.team
                          and unit.get('kind') == 'tank' and unit.get('hp', 0) > 0]
        from battlefield_equipment import equipment_brief, equipment_opportunities, equipment_task, live_plan_brief
        equipment = equipment_brief(self.world, self.team, known, self.regions)
        current_plan = live_plan_brief(self.plan, self.world, self.team, members)
        from equipment_review import EquipmentReview
        if not hasattr(self, '_equipment_review'):
            self._equipment_review = EquipmentReview()
        opportunities = self._equipment_review.apply(
            equipment_opportunities(equipment, members, known, self.world.get('weapons', {})),
            self.world, members, known, current_plan, evidence, squad,
            self.soldiers.capture_samples)
        mission = ('清除本段全部守军，完成后自动进入下一段；不要求占旗或抵达出口。' if self.team == 'green'
                   else '守住当前阵地并阻止绿色小队；没有旗帜任务。') if clear_mode else '进入并守住旗圈；交战清除阻碍，恢复后继续任务。自保约束执行方式，但不得无限期观察或等待回血'
        generated = self.world.get('world_growth', {}).get('mission', {}) if clear_mode else {}
        generated_stage = {key: generated[key] for key in ('index', 'target', 'entry', 'enemies_remaining') if key in generated}
        return dict(time=now, faction=self.team, squad_id=self.squad_id,
                    visibility=dict(mode=self.world.get('squad_behavior', {}).get('visibility_mode', 'line_of_sight'),
                        note='full_map：双方步兵、炮组、坦克共享全图实时敌情，visible=true表示位置当前已知，不保证目视射线；射程、枪口遮挡、炮弹轨迹、友军安全仍由引擎复验。line_of_sight：原有目视与近期接触。'),
                    mission=mission,
                    generated_stage=generated_stage,
                    mission_status=self._mission_status(members),
                    objective={} if clear_mode else {k: v for k, v in self.world.get('objective', {}).items() if k in ('position', 'radius')},
                    members=member_rows,
                    actor_roster=list(actor_modes.values()), support_execution=copy.deepcopy(self.world.get('support_execution', {})),
                    navigation_access=access, personal_block_reports=reports,
                    support_assets=support_assets,
                    battlefield_equipment=equipment,
                    equipment_opportunities=opportunities,
                    equipment_assignment=self._equipment_assignment(),
                    equipment_task=equipment_task(self._equipment_goal(), equipment, members),
                    ammunition_rules=ammunition_rules(members),
                    contacts=known,
                    search_intelligence=dict(last_seen_contacts=search_clues[:12],
                        note='最后目视位置是搜索线索，不是实时敌人位置；年龄越大越不确定，不能据此直接开火。未见过的敌人不会出现。'),
                    engine_squad=safe_squad, motion_execution=self._motion_execution(), current_plan=current_plan,
                    accepted_assignments=accepted, cooperation_board=cooperation,
                    living_member_ids=[u['id'] for u in members],
                    target_distance=distances, all_near_target=bool(distances) and max(distances.values()) <= self.plan['radius'],
                    execution_evidence=evidence,
                    stage_status=dict(stage=self.plan.get('stage'), elapsed_s=round(now - self.stage_started, 1) if self.stage_started is not None else 0,
                        same_region_s=round(now - self.region_started, 1) if self.region_started is not None else 0,
                        consecutive_same_region_renewals=self.region_renewals, arrived_at=self.arrived_at,
                        seconds_since_arrival=round(now - self.arrived_at, 1) if self.arrived_at is not None else None,
                        review_due=self.stage_review_at is not None and now >= self.stage_review_at,
                        review_in_s=round(max(0, self.stage_review_at - now), 1) if self.stage_review_at is not None else None,
                        waiting_for=current_plan.get('wait_for'), engine_order_matches_plan=self._order_matches_plan()),
                    soldier_reports=self.soldiers.snapshot()['agents'],
                    recent_events=copy.deepcopy(self.events[-12:]), feedback=self.feedback,
                    last_command_rejection=copy.deepcopy(getattr(self, 'last_command_rejection', {})),
                    navigation_note='native sampled cells and validated edges; near-sample actor bridge and final destinations still require engine path validation; walkable is not safe')

    def _executor_context(self, context):
        """Project the live snapshot into the small view JEV needs to execute.

        The full context remains the controller's authoritative record and is
        kept on the request for receipts/debugging.  It is a poor model input,
        though: soldier-agent reports, old event payloads, raw route rows and
        engine assignment details repeat information in the shared facts.
        Sending those copies was the main reason executor calls
        reached 20--32k prompt tokens.  Keep the facts that can change the
        choice. Path and endpoint metadata are sent once in member_region_choices;
        the full native rows remain available for validation on the request.
        """
        keep = (
            'time', 'faction', 'squad_id', 'mission', 'generated_stage', 'visibility',
            'mission_status', 'objective', 'members', 'support_assets', 'actor_roster', 'support_options', 'support_execution',
            'battlefield_equipment', 'equipment_opportunities', 'equipment_task', 'equipment_assignment', 'contacts', 'search_intelligence', 'current_plan', 'living_member_ids',
            'target_distance', 'all_near_target', 'stage_status',
            'flank_path_feasibility', 'mode_objective', 'close_engagement_comparison', 'hold_relevance',
            'tactical_map', 'engagement_map',
            'navigation_access', 'personal_block_reports', 'motion_execution', 'accepted_assignments', 'cooperation_board', 'last_command_rejection',
        )
        view = {key: copy.deepcopy(context[key]) for key in keep if key in context}

        # JEV selects the per-member endpoints, whose obstruction facts are
        # supplied below. Do not resend the commander's all-region geometry
        # table: it can exceed the provider's input limit during later stages.
        if 'engagement_map' in view:
            checks = view['engagement_map'].get('region_checks', {})
            relevant = {context.get('current_plan', {}).get('region_id')}
            relevant.update(row.get('region_id') for options in context.get('member_region_choices', {}).values()
                            for row in options.values())
            view['engagement_map']['region_checks'] = {
                key: checks[key] for key in sorted(k for k in relevant if k in checks)[:12]}

        # Per-member fields needed for role and route selection.  Emotion and
        # last goal are maintained by their own channels or the engine order.
        member_fields = (
            'id', 'position', 'hp', 'max_hp', 'weapon', 'ammo', 'ammo_infinite', 'suppression',
            'in_cover', 'posture', 'reload_remaining', 'survival_reason',
            'weapon_range', 'magazine_capacity', 'reload_duration_s', 'support_activity',
        )
        view['members'] = [
            {key: row[key] for key in member_fields if key in row}
            for row in context.get('members', [])
        ]

        evidence = context.get('execution_evidence', {})
        evidence_fields = (
            'weapon_range', 'nearest_visible_contact_distance',
            'visible_contacts_in_weapon_range', 'engageable_visible_targets',
            'regeneration', 'seconds_since_last_damage',
            'has_fired_this_run', 'seconds_since_last_shot', 'fire_basis',
            'seconds_since_last_hit', 'seconds_without_measured_progress',
            'stationary_seconds', 'outside_visible_enemy_range_for_s',
            'route_progress', 'seconds_without_strategic_progress', 'seconds_without_strategic_approach',
            'range_status', 'wounded', 'needs_recovery', 'fire_block_reason',
            'firing_awareness', 'engagement_failure', 'recent_failed_firing_sites',
            'rocket_fire_options', 'rocket_impact', 'weapon_profile', 'engagement_value', 'fire_effectiveness',
            'personal_action_capabilities', 'firing_hold',
            'local_execution_episode', 'cover_execution', 'attack_position_review',
        )
        view['execution_evidence'] = {
            'members': {
                uid: {key: row[key] for key in evidence_fields if key in row}
                for uid, row in evidence.get('members', {}).items()
            },
            'basis': 'route_progress为同一已接受路线的实测推进，开始或换令不算推进；fire_effectiveness区分实际发射和已确认伤害/压制/破障。正常绕障可能暂时远离目标；距离与武器建议不证明射界或安全',
        }

        engine = context.get('engine_squad', {})
        engine_fields = (
            'order_id', 'intent', 'phase', 'reason', 'goal', 'progress',
            'protection', 'duties', 'mover', 'support_ids', 'coordination', 'task_contract', 'task_review', 'assignment_execution',
        )
        view['engine_squad'] = {key: copy.deepcopy(engine[key]) for key in engine_fields if key in engine}
        plan = context.get('current_plan', {})
        plan_fields = ('region_id', 'position', 'radius', 'stage', 'objective',
                       'risk', 'source', 'request_id', 'assessment_basis', 'wait_for', 'review_after_s', 'requires_replan', 'invalid_dependencies', 'invalid_reason', 'equipment_goal')
        view['current_plan'] = {key: copy.deepcopy(plan[key]) for key in plan_fields if key in plan}

        # The full route rows are still retained for command validation, but
        # Send path/endpoint facts once here. Question criteria refer to the
        # same keyed route rather than restating its geometry in prose.
        route_fields = (
            'region_path', 'position', 'endpoint_id', 'endpoint_basis',
            'split_from_primary_at', 'relation',
            'region_id', 'flankable', 'approach_region', 'side',
            'route_length', 'contact_approach', 'support_screen', 'equipment_approach',
            'endpoint_obstructions', 'route_reaches_team_goal', 'limitation', 'bypass_evidence', 'route_comparison',
            'team_goal_region', 'route_target_region', 'remaining_region_hops', 'firing_position', 'close_engagement',
        )
        contact_fields = (
            'target_id', 'visible', 'age_s', 'destination_distance',
            'distance_gain', 'in_weapon_range', 'firing_line', 'range_fit',
        )
        support_fields = ('asset_id', 'target_id', 'position', 'ahead_by', 'status')

        def compact_route(row):
            compact = {key: copy.deepcopy(row[key]) for key in route_fields if key in row}
            if isinstance(compact.get('contact_approach'), dict):
                fact = compact['contact_approach']
                compact['contact_approach'] = {
                    key: copy.deepcopy(fact[key]) for key in contact_fields if key in fact
                }
            if isinstance(compact.get('support_screen'), dict):
                screen = compact['support_screen']
                compact['support_screen'] = {
                    key: copy.deepcopy(screen[key]) for key in support_fields if key in screen
                }
            return compact

        view['member_region_choices'] = {
            uid: {
                route_id: compact_route(row)
                for route_id, row in options.items()
            }
            for uid, options in context.get('member_region_choices', {}).items()
        }

        view['ammunition_rules'] = copy.deepcopy(context.get('ammunition_rules', ammunition_rules(context.get('members', []))))
        view['recent_events'] = [
            {key: copy.deepcopy(event[key]) for key in ('time', 'kind', 'unit_id', 'reason', 'text', 'episode_id') if key in event}
            for event in context.get('recent_events', [])[-4:]
        ]
        if context.get('feedback'):
            view['feedback'] = context['feedback']
        view['navigation_note'] = '路线来自原生采样；引擎最终复验通路、掩体和落点'
        return view

    def _commander_context(self, context):
        """Project the authoritative snapshot into DeepSeek's planning view.

        The commander chooses a next *region and stage*, while JEV and the
        engine maintain individual assignments.  The old commander payload
        included every soldier agent's memory and movement history as well as
        the expanded engine assignments.  Those are useful for receipts, but
        they repeat the measured facts already present in members,
        execution_evidence and engine_squad.duties.  Keep the full snapshot in
        the request object for validation; only this projection crosses the
        provider boundary.
        """
        def rounded(value):
            if isinstance(value, float):
                return round(value, 3)
            if isinstance(value, dict):
                return {key: rounded(item) for key, item in value.items()}
            if isinstance(value, list):
                return [rounded(item) for item in value]
            return value

        keep = (
            'time', 'faction', 'squad_id', 'mission', 'generated_stage',
            'visibility', 'mission_status', 'objective', 'support_assets', 'actor_roster', 'support_execution',
            'battlefield_equipment', 'equipment_opportunities', 'equipment_task', 'equipment_assignment', 'search_intelligence', 'target_distance', 'all_near_target', 'living_member_ids',
            'stage_status', 'mode_objective', 'feedback',
            'recent_region_failures', 'replan_constraint', 'current_region_stage_admission', 'engagement_map',
            'tactical_map',
            'navigation_access', 'personal_block_reports', 'motion_execution', 'cooperation_board', 'last_command_rejection',
        )
        view = {key: copy.deepcopy(context[key]) for key in keep if key in context}

        member_fields = (
            'id', 'position', 'hp', 'max_hp', 'weapon', 'ammo', 'ammo_infinite', 'suppression',
            'in_cover', 'posture', 'reload_remaining', 'survival_reason',
            'weapon_range', 'magazine_capacity', 'reload_duration_s',
        )
        view['members'] = [
            {key: copy.deepcopy(row[key]) for key in member_fields if key in row}
            for row in context.get('members', [])
        ]

        # DeepSeek should see the latest contact report, not an unbounded
        # perception history.  Empty contacts remains meaningful: it means
        # that this squad currently has no visible/recent target.
        contact_fields = ('id', 'position', 'visible', 'last_seen', 'kind', 'weapon', 'equipment_id', 'equipment_role')
        view['contacts'] = [
            {key: copy.deepcopy(row[key]) for key in contact_fields if key in row}
            for row in context.get('contacts', [])
        ]

        evidence = context.get('execution_evidence', {})
        evidence_fields = (
            'weapon_range', 'nearest_visible_contact_distance',
            'visible_contacts_in_weapon_range', 'engageable_visible_targets',
            'regeneration', 'seconds_since_last_damage',
            'has_fired_this_run', 'recent_fire_observed',
            'seconds_since_last_shot', 'seconds_since_last_hit',
            'seconds_without_measured_progress', 'stationary_seconds',
            'route_progress', 'seconds_without_strategic_progress', 'seconds_without_strategic_approach',
            'outside_visible_enemy_range_for_s', 'range_status',
            'wounded', 'needs_recovery', 'fire_block_reason', 'firing_awareness', 'engagement_failure', 'recent_failed_firing_sites',
            'rocket_fire_options', 'rocket_impact', 'weapon_profile', 'engagement_value', 'fire_effectiveness',
            'personal_action_capabilities', 'firing_hold',
            'local_execution_episode', 'cover_execution', 'attack_position_review',
        )
        view['execution_evidence'] = {
            'members': {
                uid: {key: copy.deepcopy(row[key]) for key in evidence_fields if key in row}
                for uid, row in evidence.get('members', {}).items()
            },
            # This is a stable rule already covered by the prompt; retaining a
            # short label prevents the model from treating distance as safety.
            'basis': '路线推进与战略成果分开；正常绕行可暂时远离目标，沿路线移动不代表已接敌。开始或换令不算推进；距离不等于射界或安全',
        }

        engine = context.get('engine_squad', {})
        engine_fields = ('order_id', 'intent', 'phase', 'reason', 'goal',
                         'progress', 'protection', 'duties', 'mover', 'support_ids', 'coordination', 'task_contract', 'task_review', 'assignment_execution')
        view['engine_squad'] = {
            key: copy.deepcopy(engine[key]) for key in engine_fields if key in engine
        }
        # Assignments contain per-soldier endpoint coordinates and route
        # positions that belong to JEV's executor view.  Duties/protection are
        # the commander-facing facts: who is blocked, protected or unresolved.
        if isinstance(view.get('engine_squad', {}).get('duties'), dict):
            duty_fields = ('attempts', 'reason', 'role', 'unresolved_for_s')
            view['engine_squad']['duties'] = {
                uid: {key: copy.deepcopy(row[key]) for key in duty_fields if key in row}
                for uid, row in view['engine_squad']['duties'].items()
                if isinstance(row, dict)
            }
        if isinstance(view.get('engine_squad', {}).get('protection'), dict):
            view['engine_squad']['protection'] = {
                uid: {key: copy.deepcopy(row[key]) for key in ('since', 'state') if key in row}
                for uid, row in view['engine_squad']['protection'].items()
                if isinstance(row, dict)
            }

        # The full Soldier Agents snapshot remains in `request['context']` and
        # is never used as a planning input.  Its memory, movement history,
        # signatures and last receipts are execution-layer details; duties,
        # protection and execution_evidence above are the planner-facing facts.

        view['current_plan'] = {
            key: copy.deepcopy(context['current_plan'][key])
            for key in ('region_id', 'position', 'radius', 'stage', 'objective',
                        'risk', 'source', 'request_id', 'assessment_basis', 'wait_for', 'review_after_s', 'requires_replan', 'invalid_dependencies', 'invalid_reason', 'equipment_goal')
            if key in context.get('current_plan', {})
        }
        view['ammunition_rules'] = copy.deepcopy(context.get('ammunition_rules', ammunition_rules(context.get('members', []))))
        view['recent_events'] = [
            {key: copy.deepcopy(event[key]) for key in ('time', 'kind', 'unit_id', 'reason', 'text', 'episode_id')
             if key in event}
            for event in context.get('recent_events', [])[-4:]
        ]
        view['regions'] = {
            region_id: {
                key: copy.deepcopy(region[key])
                for key in ('center', 'neighbors', 'radius', 'walkability', 'purpose',
                            'reachable_member_ids', 'engagement_checks', 'allowed_stages',
                            'exhausted_approach_reason', 'stage_evidence', 'deadline_policy')
                if key in region
            }
            for region_id, region in context.get('regions', {}).items()
        }
        view['navigation_note'] = '区域来自原生采样；引擎最终复验通路、掩体和落点'
        # Offered region checks already sit beside their coordinates. Keep
        # only additional checks here, rather than paying for duplicate rows.
        if 'engagement_map' in view:
            view['engagement_map']['region_checks'] = {
                rid: rows for rid, rows in view['engagement_map'].get('region_checks', {}).items()
                if 'engagement_checks' not in context.get('regions', {}).get(rid, {})}
        return rounded(view)

