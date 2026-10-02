"""Authoritative world observation and model-facing context projections for Deskfront squads."""
import copy
import json
import math
from pathlib import Path

from auto_regions import generate
from human_squad_validation import _position
from strategic_regions import navigation_anchor

class SquadContextMixin:
    def _execution_evidence(self, members, contacts):
        now = self.world.get('time', 0)
        visible = [c for c in contacts if c.get('visible')]
        rows = {}
        for u in members:
            history = self.unit_history.get(u['id'], {})
            weapon_range = u.get('weapon_range')
            distances = {c['id']: math.dist(u['position'], c['position']) for c in visible}
            in_range = [key for key, distance in distances.items() if weapon_range is not None and distance <= weapon_range]
            limited = bool(visible) and weapon_range is not None and not in_range
            if limited and history.get('range_limited_since') is None:
                history['range_limited_since'] = now
            elif not limited:
                history['range_limited_since'] = None
            last_shot = u.get('last_shot_at', -1)
            last_hit = u.get('last_hit_at', -1)
            rows[u['id']] = dict(firing_awareness=copy.deepcopy(u.get("combat", {}).get("firing_awareness", {})) if u.get("combat", {}).get("firing_awareness", {}).get("target_id") in distances else {}, fire_block_reason=u.get("combat", {}).get("fire_block_reason", ""), weapon_range=weapon_range,
                nearest_visible_contact_distance=round(min(distances.values()), 3) if distances else None,
                visible_contacts_in_weapon_range=in_range,
                engageable_visible_targets=[target for target in u.get('combat', {}).get('engageable_targets', []) if target in distances],
                has_fired_this_run=last_shot >= 0,
                seconds_since_last_shot=round(max(0, now - last_shot), 1) if last_shot >= 0 else None,
                seconds_since_last_hit=round(max(0, now - last_hit), 1) if last_hit >= 0 else None,
                recent_fire_observed=last_shot >= 0 and 0 <= now - last_shot <= 5,
                seconds_without_measured_progress=round(max(0, now - history.get('progress_at', now)), 1),
                stationary_seconds=round(max(0, now - history.get('stationary_at', now)), 1),
                observation_window_s=round(max(0, now - history.get('observed_since', now)), 1),
                outside_visible_enemy_range_for_s=round(now - history['range_limited_since'], 1) if history.get('range_limited_since') is not None else None,
                range_status='all_visible_contacts_outside_weapon_range' if limited else 'visible_contact_in_range_not_proof_of_clear_shot' if in_range else 'no_visible_contact_or_unknown_range',
                wounded=u.get('hp', 100) < .6 * u.get('max_hp', 100),
                needs_recovery=u.get('suppression', 0) >= .35 or bool(u.get('survival_reason')))
        return dict(members=rows, basis='self weapon range and reported shots; visible faction contacts only; distance alone does not prove firing line or safety; lack of measured movement/fire/cover gain is a review signal, not proof of useless waiting')

    def _order_matches_plan(self):
        engine = self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {})
        return bool(self.last_order and self.last_order.get('accepted') and engine
                    and engine.get('order_id') == self.last_order['order_id']
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
        firing = any(u.get('last_shot_at', -100) >= 0 and now-u['last_shot_at'] <= 5 for u in members)
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
        """Native connected components, with explicitly unverified short actor-to-sample bridges."""
        common = None
        for unit in members:
            anchor = navigation_anchor(unit['position'], self.regions, self.topology)
            todo = list(anchor['anchor_regions'])
            if not todo:
                return {}, 'unit_navigation_anchor_unresolved:' + unit['id']
            found = set(todo)
            while todo:
                for other in self.regions[todo.pop()].get('neighbors', []):
                    if other in self.regions and other not in found:
                        found.add(other)
                        todo.append(other)
            common = found if common is None else common & found
        return {k: self.regions[k] for k in sorted((common or set()) & self._active_destination_ids())}, ''

    def _context(self, members):
        from task_modes import mode_id
        clear_mode = mode_id(self.world) == 'clear_exit'
        now = self.world.get('time', 0)
        contacts = self.world.get('squad_behavior', {}).get('perception', {}).get(self.team, {}).get('contacts', [])
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
        safe_squad = {k: squad[k] for k in ('order_id', 'intent', 'phase', 'reason', 'goal', 'progress', 'protection', 'duties', 'fire_positions', 'mover', 'support_ids', 'assignments') if k in squad}
        distances = {u['id']: round(math.dist(u['position'], self.plan['position']), 3)
                     for u in members} if self.plan else {}
        evidence = self._execution_evidence(members, known)
        member_rows = []
        for unit in members:
            row = {key: unit[key] for key in ('id', 'position', 'hp', 'max_hp', 'weapon', 'ammo',
                'suppression', 'in_cover', 'posture', 'reload_remaining', 'survival_reason',
                'goal', 'weapon_range', 'last_shot_at', 'emotion') if key in unit}
            weapon = self.world.get('weapons', {}).get(unit.get('weapon'), {})
            # Capacity and reload duration come from this engine snapshot. A
            # missing weapon configuration stays unknown, not a rifle default.
            for source, target in (('magazine', 'magazine_capacity'), ('reload', 'reload_duration_s')):
                if source in weapon:
                    row[target] = weapon[source]
            member_rows.append(row)
        # Vehicles remain under native navigation, but the squad must know
        # whether its fire-support asset is behind the line and actually firing.
        support_assets = [{key: unit[key] for key in ('id', 'kind', 'weapon', 'position',
                           'goal', 'weapon_range', 'last_shot_at', 'hp', 'order_mode') if key in unit}
                          | {'engagement_position': copy.deepcopy(unit.get('combat', {}).get('engagement_position', {}))}
                          for unit in self.world.get('units', []) if unit.get('faction') == self.team
                          and unit.get('kind') == 'tank' and unit.get('hp', 0) > 0]
        equipment = [{key: gun[key] for key in ('id', 'kind', 'faction', 'position', 'hp',
                     'phase', 'capturable', 'capture_radius', 'capture_seconds', 'required_crew',
                     'capture_team', 'capture_progress', 'crew_alive') if key in gun}
                     for gun in self.world.get('at_guns', []) if gun.get('kind') == 'mortar'
                     and (gun.get('faction') == self.team or self.team in gun.get('seen_by', []))]
        mission = ('清除本段全部守军，完成后自动进入下一段；不要求占旗或抵达出口。' if self.team == 'green'
                   else '守住当前阵地并阻止绿色小队；没有旗帜任务。') if clear_mode else '进入并守住旗圈；交战清除阻碍，恢复后继续任务。自保约束执行方式，但不得无限期观察或等待回血'
        generated = self.world.get('world_growth', {}).get('mission', {}) if clear_mode else {}
        generated_stage = {key: generated[key] for key in ('index', 'target', 'entry', 'enemies_remaining') if key in generated}
        return dict(time=now, faction=self.team, squad_id=self.squad_id,
                    mission=mission,
                    generated_stage=generated_stage,
                    mission_status=self._mission_status(members),
                    objective={} if clear_mode else {k: v for k, v in self.world.get('objective', {}).items() if k in ('position', 'radius')},
                    members=member_rows,
                    support_assets=support_assets,
                    battlefield_equipment=equipment,
                    ammunition_rules=dict(ammo_field='current_magazine_rounds', reserve='unlimited',
                        reload_result='refill_magazine', basis='engine_unit_reload_rule',
                        note='枪械装填结束后补满弹匣，没有有限总备弹；容量和装填时长来自本局武器配置，缺失则未知；手雷数量另算。'),
                    contacts=known, engine_squad=safe_squad, current_plan=copy.deepcopy(self.plan),
                    target_distance=distances, all_near_target=bool(distances) and max(distances.values()) <= self.plan['radius'],
                    execution_evidence=evidence,
                    stage_status=dict(stage=self.plan.get('stage'), elapsed_s=round(now - self.stage_started, 1) if self.stage_started is not None else 0,
                        same_region_s=round(now - self.region_started, 1) if self.region_started is not None else 0,
                        consecutive_same_region_renewals=self.region_renewals, arrived_at=self.arrived_at,
                        seconds_since_arrival=round(now - self.arrived_at, 1) if self.arrived_at is not None else None,
                        review_due=self.stage_review_at is not None and now >= self.stage_review_at,
                        review_in_s=round(max(0, self.stage_review_at - now), 1) if self.stage_review_at is not None else None,
                        waiting_for=self.plan.get('wait_for'), engine_order_matches_plan=self._order_matches_plan()),
                    soldier_reports=self.soldiers.snapshot()['agents'],
                    recent_events=copy.deepcopy(self.events[-12:]), feedback=self.feedback,
                    navigation_note='native sampled cells and validated edges; near-sample actor bridge and final destinations still require engine path validation; walkable is not safe')

    def _executor_context(self, context):
        """Project the live snapshot into the small view JEV needs to execute.

        The full context remains the controller's authoritative record and is
        kept on the request for receipts/debugging.  It is a poor model input,
        though: soldier-agent reports, old event payloads, raw route rows and
        engine assignment details repeat information already present in the
        questions.  Sending those copies was the main reason executor calls
        reached 20--32k prompt tokens.  Keep the facts that can change the
        choice, and leave route identity/coordinates available for the answer
        validator through the request's full member_region_choices.
        """
        keep = (
            'time', 'faction', 'squad_id', 'mission', 'generated_stage',
            'mission_status', 'objective', 'members', 'support_assets',
            'battlefield_equipment', 'contacts', 'current_plan',
            'target_distance', 'all_near_target', 'stage_status',
            'flank_path_feasibility', 'mode_objective',
        )
        view = {key: copy.deepcopy(context[key]) for key in keep if key in context}

        # Per-member fields needed for role and route selection.  Emotion and
        # last goal are maintained by their own channels or the engine order.
        member_fields = (
            'id', 'position', 'hp', 'max_hp', 'weapon', 'ammo', 'suppression',
            'in_cover', 'posture', 'reload_remaining', 'survival_reason',
            'weapon_range', 'magazine_capacity', 'reload_duration_s',
        )
        view['members'] = [
            {key: row[key] for key in member_fields if key in row}
            for row in context.get('members', [])
        ]

        evidence = context.get('execution_evidence', {})
        evidence_fields = (
            'weapon_range', 'nearest_visible_contact_distance',
            'visible_contacts_in_weapon_range', 'engageable_visible_targets',
            'has_fired_this_run', 'seconds_since_last_shot',
            'seconds_since_last_hit', 'seconds_without_measured_progress',
            'stationary_seconds', 'outside_visible_enemy_range_for_s',
            'range_status', 'wounded', 'needs_recovery',
        )
        view['execution_evidence'] = {
            'members': {
                uid: {key: row[key] for key in evidence_fields if key in row}
                for uid, row in evidence.get('members', {}).items()
            },
            'basis': '实测射程、可见目标、开火和位移；距离本身不证明射界或安全',
        }

        engine = context.get('engine_squad', {})
        engine_fields = (
            'order_id', 'intent', 'phase', 'reason', 'goal', 'progress',
            'protection', 'duties', 'mover', 'support_ids',
        )
        view['engine_squad'] = {key: copy.deepcopy(engine[key]) for key in engine_fields if key in engine}
        plan = context.get('current_plan', {})
        plan_fields = ('region_id', 'position', 'radius', 'stage', 'objective',
                       'risk', 'wait_for', 'review_after_s')
        view['current_plan'] = {key: copy.deepcopy(plan[key]) for key in plan_fields if key in plan}

        # The full route rows are still retained for command validation, but
        # the model only needs their tactical facts; route descriptions are
        # already present in the per-route questions below.
        route_fields = (
            # The questions contain the full path and endpoint description.
            # Keep only the compact facts needed to compare choices here.
            'region_id', 'flankable', 'approach_region', 'side',
            'route_length', 'contact_approach', 'support_screen',
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

        view['ammunition_rules'] = {
            'ammo_field': 'current_magazine_rounds',
            'reserve': 'unlimited',
            'reload_result': 'refill_magazine',
        }
        view['recent_events'] = [
            {key: event[key] for key in ('time', 'kind', 'unit_id', 'reason', 'text') if key in event}
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
            'mission_status', 'objective', 'support_assets',
            'battlefield_equipment', 'target_distance', 'all_near_target',
            'stage_status', 'mode_objective', 'feedback',
            'recent_region_failures', 'replan_constraint',
        )
        view = {key: copy.deepcopy(context[key]) for key in keep if key in context}

        member_fields = (
            'id', 'position', 'hp', 'max_hp', 'weapon', 'ammo', 'suppression',
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
        contact_fields = ('id', 'position', 'visible', 'last_seen', 'kind', 'weapon')
        view['contacts'] = [
            {key: copy.deepcopy(row[key]) for key in contact_fields if key in row}
            for row in context.get('contacts', [])
        ]

        evidence = context.get('execution_evidence', {})
        evidence_fields = (
            'weapon_range', 'nearest_visible_contact_distance',
            'visible_contacts_in_weapon_range', 'engageable_visible_targets',
            'has_fired_this_run', 'recent_fire_observed',
            'seconds_since_last_shot', 'seconds_since_last_hit',
            'seconds_without_measured_progress', 'stationary_seconds',
            'outside_visible_enemy_range_for_s', 'range_status',
            'wounded', 'needs_recovery', 'fire_block_reason',
        )
        view['execution_evidence'] = {
            'members': {
                uid: {key: copy.deepcopy(row[key]) for key in evidence_fields if key in row}
                for uid, row in evidence.get('members', {}).items()
            },
            # This is a stable rule already covered by the prompt; retaining a
            # short label prevents the model from treating distance as safety.
            'basis': '实测射程、目视接触、开火和推进；距离不等于射界或安全',
        }

        engine = context.get('engine_squad', {})
        engine_fields = ('order_id', 'intent', 'phase', 'reason', 'goal',
                         'progress', 'protection', 'duties', 'mover', 'support_ids')
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
                        'risk', 'wait_for', 'review_after_s')
            if key in context.get('current_plan', {})
        }
        view['ammunition_rules'] = {
            'ammo_field': 'current_magazine_rounds',
            'reserve': 'unlimited',
            'reload_result': 'refill_magazine',
        }
        view['recent_events'] = [
            {key: copy.deepcopy(event[key]) for key in ('time', 'kind', 'unit_id', 'reason', 'text')
             if key in event}
            for event in context.get('recent_events', [])[-4:]
        ]
        view['regions'] = {
            region_id: {
                key: copy.deepcopy(region[key])
                for key in ('center', 'neighbors', 'radius', 'walkability', 'purpose')
                if key in region
            }
            for region_id, region in context.get('regions', {}).items()
        }
        view['navigation_note'] = '区域来自原生采样；引擎最终复验通路、掩体和落点'
        return rounded(view)

