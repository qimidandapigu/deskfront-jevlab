"""Read-only public snapshot projection for Deskfront squads."""
import copy

from human_squad_contract import EVENT_TEXT

class SquadSnapshotMixin:
    def snapshot(self):
        with self.lock:
            soldier_state = self.soldiers.snapshot()
            emotion_state = self.emotions.snapshot()
            context = self._context(self._members(self.world))
            coordination = dict(plan=copy.deepcopy(self.plan), version=self.version,
                                events=copy.deepcopy(self.events), pending=self.slots['commander'] is not None,
                                commander_calls=self.commander_calls, executor_calls=self.executor_calls,
                                source='local_rules_baseline' if self.model == 'mock' else 'deepseek_commander_jev_squad',
                                error=self.error, feedback=self.feedback, budget_exhausted=self.budget_exhausted,
                                units=soldier_state['agents'], soldier_runtime=soldier_state,
                                emotion_runtime=emotion_state,
                                strategic_regions={key: dict(center=r['center'], neighbors=r.get('neighbors', [])) for key, r in self.regions.items()},
                                current_order={k: v for k, v in (self.last_order or {}).items() if k != 'signature'},
                                execution_evidence=context['execution_evidence'],
                                stage_status=context['stage_status'],
                                engine_squad=copy.deepcopy(self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {})))
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
