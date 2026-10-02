"""DeepSeek owns regions, JEV owns squad intentions, Godot owns movement.

Only native navigation topology and the faction perception view enter prompts.
Simulation time drives reviews; wall time drives network deadlines/rate limits.
An HTTP queue response is never presented as an engine acceptance.
"""
import copy
from soldier_agents import SoldierAgents
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
from human_squad_model import SquadModelMixin
from human_squad_orders import SquadOrderMixin
from human_squad_receipts import SquadReceiptMixin
from human_squad_snapshot import SquadSnapshotMixin

class HumanSquadController(SquadContextMixin, SquadModelMixin, SquadOrderMixin, SquadReceiptMixin, SquadSnapshotMixin):
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
        self.identity = None
        self.plan = {}
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
        self.order_serial = 0
        self.request_serial = 0
        self._member_ids = ()
        self._navigation_revision = None
        self._near_threats = set()
        self.unit_history = {}
        self.failed_regions = {}
        self.stage_started = None
        self.region_started = None
        self.stage_review_at = None
        self.stage_review_notified = False
        self.region_renewals = 0
        self.arrived_at = None
        self.participation_notified = False
        self.soldier_escalated = set()
        self.soldiers = SoldierAgents(self)
        self.emotions = SoldierEmotionScheduler(self)

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
        return [u for u in state.get('units', []) if u.get('faction') == self.team
                and u.get('hp', 0) > 0 and u.get('deployment_phase', 'active') == 'active'
                and u.get('kind') != 'tank' and not u.get('gun_id')]

    def _reset(self, identity, members):
        self.soldiers.reset()
        self.emotions.reset()
        self.identity = identity
        self.plan = {}
        self.version += 1
        self.last_order = None
        self.run_accepted_orders = 0
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
        self.unit_history = {}
        self.failed_regions = {}
        self.stage_started = None
        self.region_started = None
        self.stage_review_at = None
        self.stage_review_notified = False
        self.region_renewals = 0
        self.arrived_at = None
        self.participation_notified = False
        self.soldier_escalated.clear()
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
                or event.get('reason') in ('prolonged_pressure_replan_route', 'local_attempt_no_contribution_5s')
        key = (kind, event.get('squad_id'), event.get('unit_id'), event.get('target_id'), event.get('threat_id'))
        quiet_window = 1.
        if kind == 'participation_gap':
            # One stalled squad episode needs one review, not one request per
            # soldier and per symptom. Preserve a separate commander escalation.
            # Per-unit details and reasons remain in engine facts.
            key = (kind, event['squad_id'], strategic,
                   event.get('reason') == 'local_attempt_no_contribution_5s')
            quiet_window = 8.
        elif kind == 'path_blocked' and event.get('reason') == 'no_reachable_protection':
            key = (kind, event['squad_id'], event['reason'])
            quiet_window = 8.
        elif kind in ('cover_destroyed', 'cover_lost') and event.get('cover_id'):
            # One unusable cover can be reported repeatedly while a unit is
            # still nearby. A different cover is a new tactical fact.
            key = (kind, event['squad_id'], event.get('unit_id'), event.get('cover_id'))
            quiet_window = 6.
        elif kind == 'support_lost':
            key = (kind, event['squad_id'])
            quiet_window = 2.
        # Coalesce repeated reports of the same condition, while different dangers remain distinct.
        if now - self.event_keys.get(key, -1000) < quiet_window:
            return
        self.event_keys[key] = now
        if kind in LOCAL_EVENTS or kind in PLAN_EVENTS:
            self.trigger_count += 1
        if kind in LOCAL_EVENTS or kind == 'plan_invalid':
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
        clean = {k: event[k] for k in ('unit_id', 'target_id', 'squad_id', 'seq', 'reason', 'cover_id', 'estimated_position', 'eta', 'expires_at') if k in event}
        self._event(kind, **clean)

    def _observe(self, members):
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
        for u in members:
            distance = math.dist(u['position'], self.plan['position']) if self.plan else None
            danger = bool(u.get('survival_reason') or u.get('suppression', 0) >= .55)
            old = self.unit_history.get(u['id'])
            if old is None:
                self.unit_history[u['id']] = dict(observed_since=now, progress_at=now,
                    position=list(u['position']), stationary_at=now, last_shot=u.get('last_shot_at', -1),
                    last_hit=u.get('last_hit_at', -1),
                    covered=bool(u.get('in_cover')), region_id=self.plan.get('region_id'),
                    best_distance=distance, approach_at=now, range_limited_since=None,
                    pressure_since=now if danger else None, pressure_notified=False)
                continue
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
                old.update(region_id=self.plan.get('region_id'), best_distance=distance, progress_at=now, approach_at=now)
            elif distance is not None and (old['best_distance'] is None or distance < old['best_distance'] - .04):
                old.update(best_distance=distance, progress_at=now, approach_at=now)
            shot = u.get('last_shot_at', -1)
            hit = u.get('last_hit_at', -1)
            if shot > old['last_shot'] or hit > old.get('last_hit', -1) or (u.get('in_cover') and not old['covered']):
                old['progress_at'] = now
            old.update(last_shot=shot, last_hit=hit, covered=bool(u.get('in_cover')))
            agent = self.soldiers.agents.get(u['id'], {})
            episode = (u['id'], agent.get('assignment', {}).get('order_id'))
            action_at = agent.get('last_action_at', -100)
            if (episode[1] and episode not in self.soldier_escalated
                    and agent.get('last_choice') not in (None, 'continue_task')
                    and action_at >= 0 and now - action_at >= 5
                    and old['progress_at'] <= action_at
                    and now - old['stationary_at'] >= 5
                    and not danger):
                self.soldier_escalated.add(episode)
                self._wake('participation_gap', dict(unit_id=u['id'], reason='local_attempt_no_contribution_5s'))
        if self.stage_review_at is not None and now >= self.stage_review_at and not self.stage_review_notified:
            self.stage_review_notified = True
            self._wake('stage_review_due')

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
            world = copy.deepcopy(self.state.state if snapshot is None else snapshot)
            receipts = copy.deepcopy(self.state.results)
        with self.lock:
            if not world:
                return
            self.world = world
            members = self._members(world)
            growth = world.get('world_growth', {})
            stage_revision = growth.get('revision') if growth.get('enabled') else None
            identity = (world.get('run_id'), world.get('control_epochs', {}).get(self.team, 0),
                        world.get('control', {}).get(self.team), stage_revision)
            if identity != self.identity:
                self._reset(identity, members)
            self._receipts(receipts)
            self._observe(members)
            self._update_progress(members)
            evidence = self._context(members)['execution_evidence']['members']
            stalled = [uid for uid, row in evidence.items() if not row['needs_recovery']
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
            active = (encounter_ready and members and world.get('control', {}).get(self.team) == 'lm'
                      and not world.get('winner') and world.get('demo', {}).get('phase', 'battle') == 'battle')
            squad = world.get('squad_behavior', {}).get('squads', {}).get(self.squad_id, {})
            self.emotions.tick(members, receipts,
                               active=bool(active and not world.get('paused') and
                                           self.config.get('soldier_emotions',
                                                           self.config.get('soldier_agents', True))),
                               squad_order_id=squad.get('order_id'))
            self.soldiers.tick(members, squad, receipts, active=bool(active and not world.get('paused') and self.config.get('soldier_agents', True)))
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
            if self.plan and not self.pending_commands and self._due('executor'):
                self._launch('executor', members)

