"""DeepSeek owns regions, JEV owns squad intentions, Godot owns movement.

Only native navigation topology and the faction perception view enter prompts.
Simulation time drives reviews; wall time drives network deadlines/rate limits.
An HTTP queue response is never presented as an engine acceptance.
"""
import copy
from soldier_agents import SoldierAgents
from vehicle_agents import VehicleAgents
from soldier_emotion_scheduler import SoldierEmotionScheduler
from soldier_emotions import EMOTIONS
from concurrent.futures import Future
import json
import math
from pathlib import Path
import threading
import time

from auto_regions import generate
from strategic_regions import navigation_anchor
from squad_region_choices import build as build_squad_region_choices, split_approach


from human_squad_contract import (
    CLEAR_PLAN_INSTRUCTIONS, CRITICAL_EVENTS, EVENT_ALIASES, EVENT_TEXT,
    EXECUTOR_INSTRUCTIONS, INTENTS, LOCAL_EVENTS, PLAN_EVENTS,
    PLAN_INSTRUCTIONS, STAGES,
)


def _contact_route_note(row):
    fact = row.get('contact_approach')
    if not fact:
        return '接敌收益未知：无己方已知接触'
    age = fact.get('age_s')
    seen = '目视' if fact['visible'] else ('记忆' + (f'{age}秒前' if age is not None else '，时间未知'))
    gain = fact['distance_gain']
    change = f'较当前位置接近 {gain:.3f}' if gain >= 0 else f'较当前位置远离 {-gain:.3f}'
    in_range = fact.get('in_weapon_range')
    reach = '终点在几何射程内' if in_range is True else '终点在几何射程外' if in_range is False else '武器射程未知'
    return f"对本兵最近已知敌 {fact['target_id']}（{seen}），终点距离 {fact['destination_distance']:.3f}，{change}；{reach}，射线未验证"


from human_squad_records import CallLog, SharedRequestBudget
from human_squad_validation import _position, validate_plan
from human_squad_context import SquadContextMixin
from contact_memory import ContactMemory
from human_squad_model import SquadModelMixin
from human_squad_orders import SquadOrderMixin
from human_squad_receipts import SquadReceiptMixin
from human_squad_snapshot import SquadSnapshotMixin
from human_squad_support import SquadSupportMixin
from actor_roster import select as select_actors, signature as actor_signature, last_fire
from execution_feedback import observe_route_progress

class HumanSquadController(SquadSupportMixin, SquadContextMixin, SquadModelMixin, SquadOrderMixin, SquadReceiptMixin, SquadSnapshotMixin):
    def __init__(self, state, config, game, team, *, wall_clock=time.monotonic):
        self.state, self.config, self.game, self.team = state, dict(config), game, team
        self.model = config.get('model', 'jev')
        self.origin = 'quickplay'
        self.ready = True
        self.squad_id = team + '-squad'
        self.clock = wall_clock
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.thread = None
        self.call_log = CallLog()
        self.world = {}
        self._world_source = None
        self._world_version = None
        self._world_copy = None
        self.contact_memory = ContactMemory()
        self.identity = None
        self.plan = {}
        self.pending_commander_plan = None
        self.autonomous_review_key = None
        self.commander_failures = 0
        self.role_errors = {'commander': '', 'executor': ''}
        self.version = 0
        self.regions = {}
        self.topology = None
        self._topology_key = None
        self.slots = {'commander': None, 'executor': None}
        self.next_at = {'commander': 0., 'executor': 0.}
        self.next_wall = {'commander': 0., 'executor': 0.}
        self.revision = {'commander': 0, 'executor': 0}
        self.consumed = {'commander': -1, 'executor': -1}
        self.critical = {'commander': 0, 'executor': 0}
        self.last_event_seq = 0
        self.event_keys = {}
        self.events = []
        self.feedback = ''
        self.last_command_rejection = {}
        self.error = ''
        self.fatal_error = ''
        self.budget_exhausted = False
        self.request_count = 0
        self.commander_calls = 0
        self.executor_calls = 0
        self.executor_fallbacks = 0
        self.accepted_orders = 0
        self.run_accepted_orders = 0
        self.kept_orders = 0
        self.discarded = 0
        self.trigger_count = 0
        self.pending_commands = {}
        self.last_order = None
        self.equipment_assignment = None
        self.order_serial = 0
        self.request_serial = 0
        self._member_ids = ()
        self._navigation_revision = None
        self._near_threats = set()
        self._equipment_capture_state = {}
        self.unit_history = {}
        self.failed_regions = {}
        self.region_stage_limit = {}
        self.stage_started = None
        self.region_started = None
        self.stage_review_at = None
        self.stage_review_notified = False
        self.region_renewals = 0
        self.arrived_at = None
        self.participation_notified = False
        self.soldier_escalated = set()
        self.soldiers = SoldierAgents(self)
        self.vehicles = VehicleAgents(self)
        self.emotions = SoldierEmotionScheduler(self)
        self.support_orders = {}
        self.support_notified = set()
        self.equipment_activity = {}
        self._obstruction_reviews = {}
        self._support_loss_episode = None
        self.survival_reviews = {}
        self.pending_handover = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopped.clear()
        self.thread = threading.Thread(target=self._loop, name='human-squad-' + self.team, daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)

    close = stop

    def _loop(self):
        while not self.stopped.wait(.05):
            try:
                self.tick()
            except Exception as error:
                # Do not kill the engine's persistent order on scheduler failure.
                with self.lock:
                    self.error = 'controller_error:' + type(error).__name__
                    self._record('human-controller-error', error=self.error)
                self.stopped.wait(.5)

    def _record(self, kind, **data):
        self.game.record(dict(type=kind, run_id=self.world.get('run_id'), faction=self.team,
                              squad_id=self.squad_id, game_time=self.world.get('time'), **data))

    def _event(self, kind, **fields):
        row = dict(kind=kind, time=self.world.get('time', 0), **fields)
        self.events.append(row)
        self.events = self.events[-40:]
        self._record('human-squad-event', event=row)

    def _members(self, state):
        return select_actors(state, self.team, 'movable')

    def _tactical_members(self, state):
        mounted = {}
        for gun in state.get('at_guns', []):
            if gun.get('faction') != self.team or gun.get('kind') != 'mortar':continue
            observation = self.equipment_activity.setdefault(gun['id'], dict(shots=gun.get('shots', 0), last_fire_observed_at=-1))
            shots = gun.get('shots', 0)
            if shots > observation['shots']:observation['last_fire_observed_at'] = state.get('time', 0)
            observation['shots'] = shots
            fact = dict(observation, equipment_id=gun['id'], basis='native_shared_weapon_shot_counter_observed_at_snapshot_time')
            if 'range' in gun:fact['range'] = gun['range']
            mounted.update({uid:fact for uid in gun.get('crew_ids', [])})
        return [dict(u, support_activity=mounted[u['id']]) if u['id'] in mounted else u
                for u in select_actors(state, self.team, 'tactical')]

    def _reset(self, identity, members):
        self.support_orders.clear()
        self.support_notified.clear()
        self.equipment_activity.clear()
        self.soldiers.reset()
        self.vehicles.reset()
        self.emotions.reset()
        self.identity = identity
        self.plan = {}
        self.pending_commander_plan = None
        self.autonomous_review_key = None
        self.commander_failures = 0
        self.role_errors = {'commander': '', 'executor': ''}
        self.version += 1
        self.last_order = None
        self.equipment_assignment = None
        self.run_accepted_orders = 0
        self.last_command_rejection = {}
        self.next_at = {'commander': 0., 'executor': 0.}
        # A new generated stage is a new tactical episode. Its first plan must
        # not inherit the previous stage's wall-clock model cooldown.
        self.next_wall = {'commander': 0., 'executor': 0.}
        self.consumed = {'commander': -1, 'executor': -1}
        self.revision = {'commander': 0, 'executor': 0}
        self.critical = {'commander': 0, 'executor': 0}
        self._member_ids = tuple(sorted(u['id'] for u in members))
        self.last_event_seq = 0
        self.event_keys.clear()
        self.regions = {}
        self.topology = None
        self._topology_key = None
        self._navigation_revision = self.world.get('navigation_revision')
        self._near_threats = set()
        self._equipment_capture_state = {}
        self.unit_history = {}
        self.failed_regions = {}
        self.region_stage_limit = {}
        self.stage_started = None
        self.region_started = None
        self.stage_review_at = None
        self.stage_review_notified = False
        self.region_renewals = 0
        self.arrived_at = None
        self.participation_notified = False
        self.soldier_escalated.clear()
        self._obstruction_reviews.clear()
        self._support_loss_episode = None
        self.survival_reviews.clear()
        self.pending_handover = None
        self._event('authority_changed', source='harness')

    def _wake(self, kind, event=None):
        now = self.world.get('time', 0)
        event = dict(event or {})
        event['squad_id'] = event.get('squad_id') or self.squad_id
        # Local execution failures first belong to the squad. Escalate only measured
        # persistent failures; new order IDs and reworded plans do not erase history.
        strategic = kind in PLAN_EVENTS
        if kind == 'participation_gap':
            # A soldier with a fresh progress sample must not hide another
            # member's prolonged stall during a coalesced squad episode.
            strategic = any(now - row.get('progress_at', now) >= 12 for row in self.unit_history.values()) \
                or event.get('reason') in ('prolonged_pressure_replan_route', 'local_attempt_no_contribution_5s',
                                          'persistent_native_firing_obstruction',
                                          'soldier_reports_assignment_blocked')
            if event.get('reason') in ('local_execution_cycle', 'persistent_local_execution_cycle'):
                # A stable execution episode earns one squad review, then one
                # commander escalation. No new task ID or symptom renews it.
                strategic = event['reason'] == 'persistent_local_execution_cycle'
            if event.get('reason') in ('sustained_ineffective_fire', 'persistent_squad_ineffective_fire'):
                # Shooting with no attributed effect is a local review first.
                # The observer separately verifies completed local review and
                # whole-squad stagnation before asking the commander once.
                strategic = event['reason'] == 'persistent_squad_ineffective_fire'
            if event.get('reason') == 'attack_position_without_fire':
                strategic = False  # A reached local point is not a failed strategic plan.
        obstruction_episode = None
        if kind == 'participation_gap':
            from engagement_feedback import BLOCKED_REASONS
            active_episode = self.unit_history.get(event.get('unit_id'), {}).get('local_execution_watch', {}).get('episode', {})
            if active_episode.get('active') and event.get('reason') in BLOCKED_REASONS | {
                    'native_firing_obstruction', 'persistent_native_firing_obstruction',
                    'no_effective_fire', 'prolonged_pressure_replan_route',
                    'local_attempt_no_contribution_5s', 'soldier_reports_assignment_blocked'}:
                # Keep changing ray/pressure facts visible in context, but do
                # not reopen the same loop under a different symptom label.
                return
            if event.get('reason') in BLOCKED_REASONS | {'native_firing_obstruction', 'persistent_native_firing_obstruction'}:
                uid = event.get('unit_id')
                unit = next((u for u in self._tactical_members(self.world) if u['id'] == uid), {})
                ray = unit.get('combat', {}).get('firing_awareness', {})
                if ray.get('clear') is False and ray.get('reason') in BLOCKED_REASONS and ray.get('target_id') and ray.get('blocker_id'):
                    ray_key = (ray['target_id'], ray['blocker_id'], self.world.get('navigation_revision'))
                    observed = self.unit_history.get(uid, {}).get('engagement_block', {})
                    previous = self._obstruction_reviews.get(uid, {})
                    since = observed.get('since') if observed.get('key') == ray_key else previous.get('since') if previous.get('key') == ray_key else now
                    obstruction_episode = dict(key=ray_key, since=since, levels=[])
                    if previous.get('key') == ray_key and previous.get('since') == since:
                        obstruction_episode = previous
                    # A local blocked lane need not invalidate a strategic plan.
                    # One persistent native episode earns one local and one
                    # later strategic review, even after equivalent new orders.
                    strategic = now-since >= 12
                    level = 'strategic' if strategic else 'local'
                    if level in obstruction_episode['levels']:
                        return
        if kind == 'support_restored':
            self._support_loss_episode = None
        key = (kind, event.get('squad_id'), event.get('unit_id'), event.get('target_id'), event.get('threat_id'))
        quiet_window = 1.
        if kind == 'incoming_explosive' and event.get('threat_id'):
            key = (kind, event['squad_id'], event['threat_id'])
        elif (kind == 'incoming_explosive' and _position(event.get('estimated_position'))
                and isinstance(event.get('expires_at'), (int, float))):
            # The same impact may be reported by several threatened members.
            # Different impact positions/deadlines still wake independently.
            key = (kind, event['squad_id'], tuple(round(float(v), 2) for v in event['estimated_position']),
                   round(event['expires_at'], 1))
        elif kind == 'participation_gap':
            # One stalled squad episode needs one review, not one request per
            # soldier and per symptom. Preserve a separate commander escalation.
            # Per-unit details and reasons remain in engine facts.
            key = (kind, event['squad_id'], strategic,
                   event.get('reason') == 'local_attempt_no_contribution_5s')
            quiet_window = 8.
            if event.get('reason') in ('local_execution_cycle', 'persistent_local_execution_cycle'):
                key = (kind, event['squad_id'], 'local_execution_cycle', strategic)
            if event.get('reason') in ('sustained_ineffective_fire', 'persistent_squad_ineffective_fire'):
                key = (kind, event['squad_id'], 'fire_effect_episode', strategic)
            if event.get('reason') == 'attack_position_without_fire':
                key = (kind, event['squad_id'], event.get('unit_id'), event.get('episode_id'))
            if obstruction_episode:
                key = (kind, event['squad_id'], event.get('unit_id'),
                       obstruction_episode['key'], obstruction_episode['since'], strategic)
        elif kind == 'survival_review_due':
            key = (kind, event['squad_id'], event.get('unit_id'), event.get('episode_id'))
            quiet_window = 0.  # The native-token observer performs lifetime deduplication.
        elif kind == 'path_blocked' and event.get('reason') == 'no_reachable_protection':
            key = (kind, event['squad_id'], event['reason'])
            quiet_window = 8.
        elif kind in ('cover_destroyed', 'cover_lost') and event.get('cover_id'):
            # One unusable cover can be reported repeatedly while a unit is
            # still nearby. A different cover is a new tactical fact.
            key = (kind, event['squad_id'], event.get('unit_id'), event.get('cover_id'))
            quiet_window = 6.
        elif kind == 'support_lost':
            squad = self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {})
            signature = (event.get('unit_id') or squad.get('mover'),
                         tuple(sorted(squad.get('support_ids', []))),
                         tuple(sorted(u['id'] for u in self._tactical_members(self.world))),
                         self.world.get('navigation_revision'))
            if signature == self._support_loss_episode:
                return
            key = (kind, event['squad_id'], signature)
            quiet_window = 0.
        elif kind == 'equipment_changed':
            # A crew shift, circle crossing and capture start can arrive in
            # neighbouring snapshots. They update facts immediately, while
            # one bounded review is enough; fractional progress is no wake.
            key = (kind, event['squad_id'])
            quiet_window = 3.
        elif kind == 'command_rejected':
            # Different contract failures must remain distinguishable even
            # within one scheduler frame; repeating the same cause coalesces.
            key = (kind, event['squad_id'], event.get('category'), event.get('code'))
        # Coalesce repeated reports of the same condition, while different dangers remain distinct.
        if now - self.event_keys.get(key, -1000) < quiet_window:
            return
        self.event_keys[key] = now
        if obstruction_episode:
            obstruction_episode['levels'].append('strategic' if strategic else 'local')
            self._obstruction_reviews[event['unit_id']] = obstruction_episode
        if kind == 'support_lost':
            self._support_loss_episode = signature
        if kind in LOCAL_EVENTS or kind in PLAN_EVENTS or kind == 'command_rejected':
            self.trigger_count += 1
        if kind in LOCAL_EVENTS or kind in ('plan_invalid', 'command_rejected'):
            if event.get('reason') not in ('persistent_local_execution_cycle', 'persistent_squad_ineffective_fire'):
                self.revision['executor'] += 1
        if strategic:
            self.revision['commander'] += 1
        if kind in CRITICAL_EVENTS:
            self.critical['executor'] += 1
            # A single soldier failing to find protective cover changes how the
            # squad should execute, but does not invalidate an in-flight map
            # plan. The commander is still woken for its next review.
            if strategic and not (kind == 'path_blocked' and event.get('reason') == 'no_reachable_protection'):
                self.critical['commander'] += 1
        # Retain only known event fields; unrelated hidden enemy details never enter prompts.
        clean = {k: event[k] for k in ('unit_id', 'target_id', 'squad_id', 'seq', 'reason', 'cover_id', 'estimated_position', 'eta', 'expires_at',
                                     'category', 'code', 'command_id', 'order_id', 'actor_observations', 'duplicate_actor_ids', 'blocker_id', 'episode_id') if k in event}
        self._event(kind, **clean)

    def _observe(self, members):
        # New artillery information wakes planning; it never selects a tactic.
        known_equipment = [g for g in self.world.get('at_guns', [])
                           if g.get('kind') == 'mortar'
                           and (g.get('faction') == self.team or self.team in g.get('seen_by', []))]
        equipment = [(g.get('id'), g.get('faction'), g.get('gunner_id'), g.get('guard_id'),
                      g.get('capturable'), g.get('phase'), g.get('operator_ready')) for g in known_equipment]
        # Each shot is execution evidence, not a change in crew/control or
        # capture eligibility. Current shot counts remain in the model facts.
        capture_state = {}
        for gun in known_equipment:
            if not gun.get('capturable') or not _position(gun.get('position')):
                continue
            native_candidates = {row.get('unit_id', row.get('id')): row
                                 for row in gun.get('capture_candidates', [])}
            candidates = []
            for unit in members:
                candidate = native_candidates.get(unit['id'], {})
                inside = candidate.get('within_radius')
                if not isinstance(inside, bool):
                    radius = gun.get('capture_radius')
                    inside = math.dist(unit['position'], gun['position']) <= radius if isinstance(radius, (int, float)) else None
                candidates.append((unit['id'], inside, candidate.get('eligibility_without_distance'),
                                   candidate.get('eligible'), candidate.get('reason')))
            # Neither coordinates nor every increment of progress enter this
            # signature. It tracks circle admission and capture transitions.
            capture_state[gun['id']] = (gun.get('capture_team'), gun.get('phase') == 'capturing',
                                        tuple(sorted(candidates)))
        capture_changed = self._equipment_capture_state != capture_state
        self._equipment_capture_state = capture_state
        signature = (self.identity, repr(equipment))
        if getattr(self, '_equipment_signature', None) != signature or capture_changed:
            self._equipment_signature = signature
            if equipment:
                self._wake('equipment_changed', dict(reason='known_artillery_capture_conditions_changed'
                                                      if capture_changed else 'known_artillery_state_changed'))
        ids = tuple(sorted(u['id'] for u in members))
        if self._member_ids and ids != self._member_ids:
            for uid in set(self._member_ids) - set(ids):
                self._wake('member_lost', dict(unit_id=uid))
            self._member_ids = ids
        revision = self.world.get('navigation_revision')
        if self._navigation_revision != revision:
            self._navigation_revision = revision
            self._wake('navigation_changed')
        behavior = self.world.get('squad_behavior', {})
        contacts = behavior.get('perception', {}).get(self.team, {}).get('contacts', [])
        if isinstance(contacts, dict):
            contacts = list(contacts.values())
        near = {c['id'] for c in contacts if c.get('visible') and c.get('id')
                and _position(c.get('position'))
                and any(math.dist(c['position'], u['position']) <= .35 for u in members)}
        for target in near - self._near_threats:
            self._wake('danger_close', dict(target_id=target))
        self._near_threats = near
        for event in sorted(behavior.get('events', []), key=lambda e: e.get('seq', 0)):
            seq = event.get('seq', 0)
            if seq <= self.last_event_seq:
                continue
            self.last_event_seq = seq
            if event.get('faction') != self.team or event.get('squad_id') not in (None, '', self.squad_id):
                continue
            kind = event.get('kind', 'unknown')
            if kind in ('arrived', 'squad_arrived'):
                self.arrived_at = self.world.get('time', 0)
            if kind == 'contact_acquired' and event.get('target_id') in near:
                continue  # The same observed approach was already promoted to an urgent event.
            if kind == 'cover_invalidated':
                # The native event is emitted *after* the unit leaves its old
                # cover. Exposure at that abandoned slot says nothing about
                # the unit's current protection or whether its order failed.
                # The engine already reacts to current danger. Only a real
                # physical loss is a new squad/commander fact.
                if event.get('reason') != 'destroyed':
                    continue
                kind = 'cover_destroyed'
            self._wake(EVENT_ALIASES.get(kind, kind), dict(event, squad_id=self.squad_id))

    def _update_progress(self, members):
        """Measure our own actions; do not infer inactivity from missing enemy information."""
        now = self.world.get('time', 0)
        from engagement_feedback import observe
        from fire_effectiveness import observe as observe_fire_effects
        squad = self.world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {})
        motions = self._motion_execution()
        for u in members:
            from survival_review import notify as notify_survival_review
            notify_survival_review(self, u, squad)
            observe(self.unit_history.setdefault(u['id'], {}), u, now, self.world.get('navigation_revision'))
            episode = self.unit_history[u['id']].get('engagement_block', {})
            previous = self._obstruction_reviews.get(u['id'], {})
            if not episode or (previous and (previous.get('key') != episode.get('key') or previous.get('since') != episode.get('since'))):
                self._obstruction_reviews.pop(u['id'], None)
            distance = math.dist(u['position'], self.plan['position']) if self.plan else None
            danger = bool(u.get('survival_reason') or u.get('suppression', 0) >= .55)
            old = self.unit_history.get(u['id'])
            if 'observed_since' not in old:
                old.update(observed_since=now, progress_at=now,
                    strategic_progress_at=now, strategic_approach_at=now,
                    position=list(u['position']), stationary_at=now, last_shot=last_fire(u),
                    last_hit=u.get('last_hit_at', -1),
                    covered=bool(u.get('in_cover')), region_id=self.plan.get('region_id'),
                    best_distance=distance, approach_at=now, range_limited_since=None,
                    pressure_since=now if danger else None, pressure_notified=False)
                observe_route_progress(old, u, motions.get(u['id'], {}),
                    squad.get('assignments', {}).get(u['id'], {}),
                    squad.get('member_cursors', {}).get(u['id']), now)
                observe_fire_effects(old, u, now)
                continue
            if observe_route_progress(old, u, motions.get(u['id'], {}),
                    squad.get('assignments', {}).get(u['id'], {}),
                    squad.get('member_cursors', {}).get(u['id']), now):
                measured_at = old['route_progress_at']
                old.update(progress_at=max(old['progress_at'], measured_at),
                           approach_at=max(old['approach_at'], measured_at))
            if danger:
                if old.get('pressure_since') is None:
                    old['pressure_since'] = now
                if now-old['pressure_since'] >= 15 and not old.get('pressure_notified'):
                    old['pressure_notified'] = True
                    self._wake('participation_gap', dict(unit_id=u['id'], reason='prolonged_pressure_replan_route'))
            else:
                old.update(pressure_since=None, pressure_notified=False)
            if math.dist(u['position'], old['position']) >= .06:
                old.update(position=list(u['position']), stationary_at=now)
            if old['region_id'] != self.plan.get('region_id'):
                # Changing the plan is not physical progress. Keep the stall history.
                old.update(region_id=self.plan.get('region_id'), best_distance=distance)
            elif distance is not None and (old['best_distance'] is None or distance < old['best_distance'] - .04):
                old.update(best_distance=distance, progress_at=now, approach_at=now,
                           strategic_progress_at=now, strategic_approach_at=now)
            shot = last_fire(u)
            hit = u.get('last_hit_at', -1)
            fire_effect = observe_fire_effects(old, u, now)
            if shot > old['last_shot'] or hit > old.get('last_hit', -1) or (u.get('in_cover') and not old['covered']):
                old['progress_at'] = now
                # Keep actual execution activity distinct from combat outcome.
                # Older engines without attribution retain their legacy signal;
                # a complete small-arms snapshot no longer makes every miss a
                # strategic success or claims absent telemetry means no effect.
                if not fire_effect.get('complete'):
                    old['strategic_progress_at'] = now
            if fire_effect.get('status') == 'effective' or hit > old.get('last_hit', -1):
                old['strategic_progress_at'] = now
            old.update(last_shot=shot, last_hit=hit, covered=bool(u.get('in_cover')))
            from movement_stall_episode import observe as observe_local_episode
            local_episode = observe_local_episode(old, u, now, motions.get(u['id'], {}))
            if local_episode:
                episode_state = old['local_execution_watch']['episode']
                if not episode_state['local_notified']:
                    episode_state['local_notified'] = True
                    self._wake('participation_gap', dict(unit_id=u['id'],
                        reason='local_execution_cycle', episode_id=episode_state['episode_id']))
            agent = self.soldiers.agents.get(u['id'], {})
            episode = (u['id'], agent.get('assignment', {}).get('order_id'))
            action_at = agent.get('last_action_at', -100)
            if (not local_episode and episode[1] and episode not in self.soldier_escalated
                    and agent.get('last_choice') not in (None, 'continue_task')
                    and action_at >= 0 and now - action_at >= 5
                    and old['progress_at'] <= action_at
                    and now - old['stationary_at'] >= 5
                    and not danger):
                self.soldier_escalated.add(episode)
                self._wake('participation_gap', dict(unit_id=u['id'], reason='local_attempt_no_contribution_5s'))
        self._update_attack_position_reviews(members, now, squad, motions)
        self._update_fire_effect_reviews(members, now)
        # Commander attention is for a stalled squad objective, not every
        # isolated launcher while teammates still fight or advance. Evaluate
        # after all actors so the outcome is independent of iteration order.
        measured_squad_gain = max((max(last_fire(u), u.get('last_hit_at', -1),
            self.unit_history.get(u['id'], {}).get('route_progress_at', -1)) for u in members), default=-1)
        if measured_squad_gain < now-5:
            for u in members:
                episode = self.unit_history.get(u['id'], {}).get('local_execution_watch', {}).get('episode', {})
                if (episode.get('active') and episode.get('local_notified')
                        and not episode.get('commander_notified') and now-episode['since'] >= 5):
                    episode['commander_notified'] = True
                    self._wake('participation_gap', dict(unit_id=u['id'],
                        reason='persistent_local_execution_cycle', episode_id=episode['episode_id']))
        if self.stage_review_at is not None and now >= self.stage_review_at and not self.stage_review_notified:
            self.stage_review_notified = True
            self._wake('stage_review_due')

    def _update_attack_position_reviews(self, members, now, squad, motions):
        from assignment_fire_review import observe_participation
        contacts = self.world.get('squad_behavior', {}).get('perception', {}).get(self.team, {}).get('contacts', [])
        if isinstance(contacts, dict):
            contacts = list(contacts.values())
        dead = {u.get('id') for u in self.world.get('units', []) if u.get('hp', 0) <= 0}
        contacts = [c for c in contacts if c.get('id') not in dead]
        for unit in members:
            history = self.unit_history[unit['id']]
            row = observe_participation(history, unit, squad.get('assignments', {}).get(unit['id'], {}),
                now, motions.get(unit['id'], {}), contacts, squad.get('intent'), self.plan.get('stage'))
            episode = history.get('attack_position_watch', {}).get('episode', {})
            if row.get('review_ready') and not episode.get('local_notified'):
                self._wake('participation_gap', dict(unit_id=unit['id'], reason='attack_position_without_fire',
                    episode_id=row['episode_id'], execution_reason=row['reason']))
                episode['local_notified'] = True

    def _update_fire_effect_reviews(self, members, now):
        """Schedule bounded reviews from observations; never choose a tactic."""
        from fire_effectiveness import public as fire_effectiveness
        rows = [(u, self.unit_history.get(u['id'], {})) for u in members if u.get('hp', 1) > 0]
        evidence = {u['id']: fire_effectiveness(history, now) for u, history in rows}
        # All actors need complete attribution to assert a squad-wide lack of
        # effect. Mixed launcher/equipment squads keep their existing specific
        # reviews; missing counters never force a strategic replan.
        squad_without_effect = bool(rows) and all(row.get('complete')
            and row.get('effect_free_for_s', 0) >= 8 for row in evidence.values())
        phase_needs_progress = self.plan.get('stage') in ('approach', 'probe', 'engage', 'reposition')
        completed_reviews = self.accepted_orders + self.kept_orders
        for unit, history in rows:
            row = evidence[unit['id']]
            if not row.get('review_ready'):
                continue
            episode = history['fire_effect_watch']['episode']
            if not episode['local_notified']:
                self._wake('participation_gap', dict(unit_id=unit['id'],
                    reason='sustained_ineffective_fire', episode_id=episode['episode_id']))
                episode.update(local_notified=True, local_notified_at=now,
                    local_revision=self.revision['executor'], completed_reviews=completed_reviews)
            local_completed = (completed_reviews > episode.get('completed_reviews', completed_reviews)
                and self.consumed['executor'] >= episode.get('local_revision', self.revision['executor']))
            if local_completed and 'local_completed_at' not in episode:
                episode['local_completed_at'] = now
            if (phase_needs_progress and squad_without_effect and local_completed and not episode['commander_notified']
                    and now-episode['local_completed_at'] >= 5):
                self._wake('participation_gap', dict(unit_id=unit['id'],
                    reason='persistent_squad_ineffective_fire', episode_id=episode['episode_id']))
                episode['commander_notified'] = True

    def _opening_planning(self):
        """Explicit launch gate only; ordinary player pauses never schedule models."""
        if not self.config.get('opening_gate') or self.run_accepted_orders:
            return False
        path = self.config.get('opening_release_path')
        if not path:
            return False
        try:
            released = json.loads(Path(path).read_text(encoding='utf-8'))
            return released.get('run_id') != self.world.get('run_id')
        except (OSError, ValueError, TypeError):
            return True

    def tick(self, snapshot=None):
        with self.state.lock:
            source = self.state.state if snapshot is None else snapshot
            # Only AttachedState's explicit replace-only publication contract
            # permits reuse. Legacy mutable states and explicit snapshots keep
            # their original per-call copy behavior. Scheduling still runs on
            # every tick, including receipts, deadlines and completed futures.
            version = getattr(self.state, 'observation_version', None) if snapshot is None else None
            if version is not None and source is self._world_source and version == self._world_version:
                world = self._world_copy
            else:
                world = copy.deepcopy(source)
                if version is not None:
                    self._world_source, self._world_version, self._world_copy = source, version, world
            receipts = copy.deepcopy(self.state.results)
        with self.lock:
            if not world:
                return
            self.world = world
            members = self._tactical_members(world)
            growth = world.get('world_growth', {})
            stage_revision = growth.get('revision') if growth.get('enabled') else None
            identity = (world.get('run_id'), world.get('control_epochs', {}).get(self.team, 0),
                        world.get('control', {}).get(self.team), stage_revision)
            if identity != self.identity:
                self._reset(identity, members)
            self._receipts(receipts)
            self._support_feedback()
            self._motion_feedback()
            self._observe(members)
            self._update_progress(members)
            evidence = self._context(members)['execution_evidence']['members']
            for uid, row in evidence.items():
                failure = row.get('engagement_failure', {})
                episode = self.unit_history.get(uid, {}).get('engagement_block', {})
                blocked_for = failure.get('blocked_without_target_fire_s', 0)
                if blocked_for >= 5:
                    if blocked_for >= 12:
                        episode['notified'] = True
                    self._wake('participation_gap', dict(unit_id=uid,
                        reason='persistent_native_firing_obstruction' if blocked_for >= 12 else 'native_firing_obstruction',
                        target_id=failure['target_id'], blocker_id=failure['blocker_id'],
                        **({'cover_id': failure['blocker_id']} if failure['reason'] in ('muzzle_cover', 'target_occluded') else {})))
            stalled = [uid for uid, row in evidence.items() if not row['needs_recovery']
                       and not row.get('attack_position_review')
                       and row['seconds_without_measured_progress'] >= 12
                       and row['outside_visible_enemy_range_for_s'] is not None
                       and row['outside_visible_enemy_range_for_s'] >= 12]
            if stalled and not self.participation_notified:
                self._wake('participation_gap', dict(reason='visible contacts remain outside weapon range; no measured approach/fire/cover gain: ' + ','.join(stalled)))
            self.participation_notified = bool(stalled)
            self._load_regions(members)
            for role in self.slots:
                self._check_deadline(role)
            generation=world.get('world_growth',{})
            encounter_ready=not generation.get('enabled') or generation.get('mission',{}).get('status')=='active'
            active = (encounter_ready and members and world.get('control', {}).get(self.team) == self.config.get('control_mode', 'lm')
                      and not world.get('winner') and world.get('demo', {}).get('phase', 'battle') == 'battle')
            squad = world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {})
            emotional = select_actors(world, self.team, 'emotional')
            self.emotions.tick(emotional, receipts,
                               active=bool(emotional and encounter_ready and world.get('control', {}).get(self.team) == self.config.get('control_mode', 'lm') and not world.get('winner') and not world.get('paused') and
                                           self.config.get('soldier_emotions',
                                                           self.config.get('soldier_agents', True))),
                               squad_order_id=squad.get('order_id'))
            self.soldiers.tick(self._members(world), squad, receipts, active=bool(active and not world.get('paused') and self.config.get('soldier_agents', True)))
            self.vehicles.tick(receipts, active=bool(active and not world.get('paused') and self.config.get('soldier_agents', True)))
            from coordination_handover import update as update_handover
            update_handover(self)
            # Paused simulation can complete transport calls, but does not consume/issue decisions.
            if (world.get('paused') and not self._opening_planning()) or not active:
                return
            self._harvest('commander', members)
            self._harvest('executor', members)
            if self.stopped.is_set() or self.budget_exhausted:
                return
            regions, issue = self._eligible_regions(members)
            if not regions:
                self.feedback = issue or 'waiting_for_fresh_native_navigation'
                return
            if self.plan and self.plan['region_id'] not in regions:
                self._wake('plan_invalid')
                self.feedback = 'approved_region_not_reachable_in_current_topology'
                self.plan = {}
                self.version += 1
            if self._due('commander'):
                self._launch('commander', members, regions)
            # A provider failure or slow commander must not suppress the JEV
            # lane. Real JEV first selects its own goal when no plan exists.
            if not self.pending_commands and self._due('executor'):
                self._adopt_commander_plan(members)
                if self.plan or self.model != 'mock':
                    self._launch('executor', members, regions)

