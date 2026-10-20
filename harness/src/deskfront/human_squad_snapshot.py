"""Read-only public snapshot projection for Deskfront squads."""
import copy

from human_squad_contract import EVENT_TEXT

class SquadSnapshotMixin:
    def _display_context(self):
        """Bounded facts only: no navigation, candidate query or full context.

        Mounted fire timestamps are copied from the controller's already
        observed shot-counter history. Reading a display never observes a new
        shot or advances a progress/range clock.
        """
        from actor_roster import select
        from human_squad_validation import _position
        from squad_cooperation import build
        now = self.world.get('time', 0)
        mounted = {}
        for gun in self.world.get('at_guns', []):
            if gun.get('faction') != self.team or gun.get('kind') != 'mortar':
                continue
            fact = dict(copy.deepcopy(self.equipment_activity.get(gun['id'], {})),
                        equipment_id=gun['id'], basis='maintained_native_shot_counter_history')
            if 'range' in gun:
                fact['range'] = gun['range']
            mounted.update({uid: fact for uid in gun.get('crew_ids', [])})
        members = [dict(unit, support_activity=mounted[unit['id']]) if unit['id'] in mounted else unit
                   for unit in select(self.world, self.team, 'tactical')]
        contacts = self.world.get('squad_behavior', {}).get('perception', {}).get(self.team, {}).get('contacts', [])
        if isinstance(contacts, dict):
            contacts = list(contacts.values())
        dead = {unit.get('id') for unit in self.world.get('units', []) if unit.get('hp', 0) <= 0}
        visible = [row for row in contacts if row.get('visible') and row.get('id') not in dead
                   and _position(row.get('position'))]
        evidence = self._execution_evidence(members, visible, read_only=True)
        squad = self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {})
        board = build(self.world, self.team, members, visible, squad,
                      self._accepted_assignments(), evidence['members'], self._motion_execution())
        status = dict(stage=self.plan.get('stage'),
            elapsed_s=round(now-self.stage_started, 1) if self.stage_started is not None else 0,
            same_region_s=round(now-self.region_started, 1) if self.region_started is not None else 0,
            consecutive_same_region_renewals=self.region_renewals, arrived_at=self.arrived_at,
            seconds_since_arrival=round(now-self.arrived_at, 1) if self.arrived_at is not None else None,
            review_due=self.stage_review_at is not None and now >= self.stage_review_at,
            review_in_s=round(max(0, self.stage_review_at-now), 1) if self.stage_review_at is not None else None,
            waiting_for=self.plan.get('wait_for'), engine_order_matches_plan=self._order_matches_plan())
        return dict(execution_evidence=evidence, cooperation_board=board, stage_status=status)

    def snapshot(self, *, lightweight=False):
        with self.lock:
            soldier_state = self.soldiers.snapshot()
            emotion_state = self.emotions.snapshot()
            context = self._display_context() if lightweight else self._context(self._tactical_members(self.world))
            from actor_roster import roster
            coordination = dict(plan=copy.deepcopy(self.plan), version=self.version,
                                events=copy.deepcopy(self.events), pending=self.slots['commander'] is not None,
                                commander_calls=self.commander_calls, executor_calls=self.executor_calls,
                                source=('local_rules_baseline' if self.model == 'mock' else
                                    'jev_autonomous_squad' if self.plan.get('source') == 'jev_autonomous'
                                    else 'deepseek_commander_jev_squad'),
                                error=self.error, feedback=self.feedback, budget_exhausted=self.budget_exhausted,
                                planning_mode=('jev_autonomous' if self.plan.get('source') == 'jev_autonomous'
                                    else 'commander' if self.plan else 'jev_selecting_goal'),
                                role_errors=copy.deepcopy(self.role_errors),
                                commander_proposal_pending=self.pending_commander_plan is not None,
                                handover=__import__('coordination_handover').context(self),
                                survival_reviews=copy.deepcopy(getattr(self, 'survival_reviews', {})),
                                units=soldier_state['agents'], soldier_runtime=soldier_state,
                                emotion_runtime=emotion_state,
                                vehicle_runtime=self.vehicles.snapshot(),
                                actor_coverage=roster(self.world, self.team),
                                support_execution=copy.deepcopy(self.world.get('support_execution', {})),
                                strategic_regions={key: dict(center=r['center'], neighbors=r.get('neighbors', [])) for key, r in self.regions.items()},
                                current_order={k: v for k, v in (self.last_order or {}).items() if k != 'signature'},
                                execution_evidence=context['execution_evidence'],
                                cooperation_board=context['cooperation_board'],
                                stage_status=context['stage_status'],
                                engine_squad=copy.deepcopy(self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {})))
            if lightweight:
                coordination['fact_sample'] = dict(run_id=self.world.get('run_id'),
                    tick=self.world.get('tick'), game_time=self.world.get('time'),
                    navigation_revision=self.world.get('navigation_revision'),
                    fields=['execution_evidence', 'cooperation_board', 'stage_status'],
                    basis='controller_world_and_maintained_histories_no_queries')
            coordination['plan'].update(reason=self.plan.get('objective', ''), goal=self.plan.get('position'))
            coordination['events'] = [dict(e, text=EVENT_TEXT.get(e['kind'], e.get('reason') or e['kind'])) for e in coordination['events']]
            return dict(configured=True, running=bool(self.thread and self.thread.is_alive()), enabled=True,
                        provider='quickplay', model=self.model, display_name=self.model, mode='human_squad',
                        controller='human_squad', squad=coordination,
                        interval=self.config.get('squad_interval', 5.), calls=self.request_count,
                        pending=sum(r is not None for r in self.slots.values()), error=self.error,
                        fatal_error=self.fatal_error, budget_exhausted=self.budget_exhausted,
                         accepted_orders=self.accepted_orders, run_accepted_orders=self.run_accepted_orders,
                         kept_orders=self.kept_orders,
                         discarded_responses=self.discarded, triggers=self.trigger_count,
                        commander_calls=self.commander_calls, executor_calls=self.executor_calls,
                        coordination=coordination)
