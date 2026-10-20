"""Per-soldier emotion requests, independent of movement and squad orders."""
import copy
import threading
from concurrent.futures import Future

from affect_appraisal import advance as advance_affect, emotion_support, public_state as public_affect
from soldier_emotions import EMOTIONS, EMOTION_CRITERIA, EMOTION_INSTRUCTIONS


PERIOD_SECONDS = 20.0
EVENT_COOLDOWN_SECONDS = 6.0
EVENT_WINDOW_SECONDS = 8.0
HISTORY_SECONDS = 20.0
STRONG_AFFECT_THRESHOLD = .55
MATERIAL_CHANGE_THRESHOLD = .38
MAX_RESPONSE_GAME_AGE = 5.0
APPRAISAL_FIELDS = ('danger', 'pain', 'loss', 'coping', 'relief')
TRIGGER_EVENTS = {'received_damage', 'suppression_started', 'incoming_threat',
                  'teammate_died', 'emergency_ended'}
HIGH_PRIORITY_EVENTS = {'received_damage', 'teammate_died'}


class SoldierEmotionScheduler:
    def __init__(self, owner):
        self.owner = owner
        self.agents = {}
        self.pending = None
        self.receipts = {}
        self.next_wall_at = 0.
        self.last_high_event_at = -100.
        self.last_low_event_at = -100.
        self.pending_low_since = None
        self.calls = 0
        self.periodic_calls = 0
        self.event_calls = 0
        self.low_priority_event_calls = 0
        self.held_events = 0
        self.accepted = 0
        self.discarded = 0
        self._living_ids = set()

    def reset(self):
        self.agents.clear()
        self.receipts.clear()
        self._living_ids.clear()
        self.next_wall_at = 0.
        self.last_high_event_at = -100.
        self.last_low_event_at = -100.
        self.pending_low_since = None
        # Preserve the in-flight transport slot; its run token rejects a late reply.

    def _token(self):
        o = self.owner
        return (o.identity, o.world.get('run_id'),
                o.world.get('control_epochs', {}).get(o.team, 0))

    @staticmethod
    def _appraisal_change(agent):
        previous = agent.get('last_requested_affect')
        if previous is None:
            return 0.
        current = agent['affect_state']
        return max(abs(current[key] - previous[key]) for key in APPRAISAL_FIELDS)

    @staticmethod
    def _strong_at_last_request(agent):
        state = agent.get('last_requested_affect') or {}
        return max((state.get('arousal', 0), state.get('pain', 0),
                    state.get('loss', 0), state.get('relief', 0),
                    .75 * state.get('danger', 0))) >= STRONG_AFFECT_THRESHOLD

    def _holds_stable_affect(self, agent, now):
        last = agent.get('last_requested_at')
        return (last is not None and 0 <= now - last < PERIOD_SECONDS
                and self._strong_at_last_request(agent)
                and self._appraisal_change(agent) < MATERIAL_CHANGE_THRESHOLD)

    @staticmethod
    def _failure_reason(error):
        message = str(error)
        for status in ('429', '502', '503', '504', '529'):
            if 'HTTP ' + status in message:
                return 'upstream_http_' + status
        return message[:160] if isinstance(error, (ValueError, KeyError, TypeError)) else type(error).__name__

    def _retry_after_failure(self, unit_ids, now, reason):
        transient = reason.startswith('upstream_http_')
        for uid in unit_ids:
            agent = self.agents.get(uid)
            if agent is None:
                continue
            failures = agent.get('transient_failures', 0) + 1 if transient else 0
            agent['transient_failures'] = failures
            if transient:
                delay = min(8., 2. * 2 ** (failures - 1))
            else:
                delay = 1. if reason == 'stale_context' else 5.
            agent['next_retry_at'] = now + delay

    @staticmethod
    def _event(agent, kind, at, source, **details):
        serial = agent.get('event_serial', 0) + 1
        agent['event_serial'] = serial
        row = dict(serial=serial, delivered=False, kind=kind, at=at,
                   source=source, **details)
        agent['events'] = (agent.get('events', []) + [row])[-8:]
        return row

    def observe(self, members):
        o = self.owner
        now = o.world.get('time', 0.)
        living = {u['id'] for u in members}
        dead = {u.get('id') for u in o.world.get('units', [])
                if u.get('faction') == o.team and u.get('hp', 0) <= 0}
        fallen = sorted((self._living_ids - living) & dead)
        self._living_ids = living
        self.agents = {uid: a for uid, a in self.agents.items() if uid in living}
        for unit in members:
            uid = unit['id']
            a = self.agents.setdefault(uid, dict(id=uid, last_review=-100., events=[]))
            old = a.get('observed')
            hp = unit.get('hp', 0)
            suppression = unit.get('suppression', 0)
            survival = unit.get('survival_reason') or ''
            damage_at = unit.get('last_damage_at', -100)
            incoming = {item for item in (unit.get('combat') or {}).get('incoming_threats', [])
                        if isinstance(item, str)}
            new_events = []
            if old is not None:
                native_damage = (isinstance(damage_at, (int, float)) and damage_at >= 0
                                 and damage_at > old.get('last_damage_at', -100) + .001)
                hp_lost = round(max(0, old['hp'] - hp), 1)
                if native_damage or hp_lost > 0:
                    details = dict(hp_now=hp)
                    if hp_lost > 0:
                        details['hp_lost_since_last_observation'] = hp_lost
                    new_events.append(self._event(
                        a, 'received_damage', damage_at if native_damage else now,
                        'native_damage_time' if native_damage else 'observed_hp_drop', **details))
                if old['suppression'] < .35 <= suppression:
                    new_events.append(self._event(a, 'suppression_started', now, 'own_suppression'))
                if incoming and not old['incoming_threats']:
                    new_events.append(self._event(a, 'incoming_threat', now,
                                                  'own_engine_warning', threat_count=len(incoming)))
                if old['survival_reason'] and not survival:
                    new_events.append(self._event(
                        a, 'emergency_ended', now, 'own_engine_survival_state',
                        previous_reason=old['survival_reason']))
            for teammate_id in fallen:
                new_events.append(self._event(
                    a, 'teammate_died', now, 'team_status_not_personal_sight',
                    teammate_id=teammate_id))
            a['affect_state'] = advance_affect(a.get('affect_state'), unit, now, new_events)
            if new_events and self._holds_stable_affect(a, now):
                self.held_events += len(new_events)
            if suppression >= .35 and a.get('suppression_since') is None:
                a['suppression_since'] = now
            elif suppression <= .20:
                a['suppression_since'] = None
            if survival and a.get('emergency_since') is None:
                a['emergency_since'] = now
            elif not survival:
                a['emergency_since'] = None
            a['observed'] = dict(hp=hp, suppression=suppression, survival_reason=survival,
                                 last_damage_at=damage_at, incoming_threats=sorted(incoming))
            a['events'] = [event for event in a['events']
                           if not event['delivered'] or 0 <= now - event['at'] <= HISTORY_SECONDS][-8:]

    def _context(self, unit):
        o = self.owner
        a = self.agents[unit['id']]
        now = o.world.get('time', 0.)
        fields = ('id', 'weapon', 'hp', 'max_hp', 'suppression', 'survival_reason',
                  'in_cover', 'ammo', 'ammo_infinite', 'reload_remaining', 'emotion', 'path_failure',
                  'last_hit_at', 'last_damage_at', 'order_mode', 'tactical_role',
                  'deployment_phase', 'combat_ready', 'gun_id')
        events = [dict({key: value for key, value in event.items()
                        if key not in ('serial', 'at', 'delivered')},
                       seconds_ago=round(max(0, now - event['at']), 1))
                  for event in a['events']]
        appraisal = public_affect(a['affect_state'])
        appraisal['danger_change'] = round(
            a['affect_state']['danger'] - a.get('last_requested_danger',
                                               a['affect_state']['danger']), 2)
        return dict(time=now, self={key: unit[key] for key in fields if key in unit},
                    emotion_evidence=dict(
                        recent_events=events,
                        seconds_since_last_damage=round(now - unit['last_damage_at'], 1)
                            if isinstance(unit.get('last_damage_at'), (int, float))
                            and unit['last_damage_at'] >= 0 else None,
                        observed_suppression_seconds=round(now - a['suppression_since'], 1)
                            if a.get('suppression_since') is not None else None,
                        observed_emergency_seconds=round(now - a['emergency_since'], 1)
                            if a.get('emergency_since') is not None else None,
                        evidence_note='队友阵亡是队伍状态，不代表亲眼目睹；来袭威胁由本人引擎预警'),
                    affect_appraisal=appraisal,
                    emotion_support=emotion_support(a['affect_state'], unit))

    def tick(self, members, receipts, *, active, squad_order_id=None):
        o = self.owner
        self.observe(members)
        now = o.world.get('time', 0.)
        for rid, item in list(self.receipts.items()):
            result = receipts.get(rid)
            if result is None and o.clock() - item['submitted'] <= 5:
                continue
            self.receipts.pop(rid)
            if item['token'] != self._token():
                o._record('emotion-receipt-discarded', unit_id=item['uid'], reason='authority_changed')
                continue
            accepted = bool(result and result.get('accepted'))
            self.accepted += int(accepted)
            o._record('emotion-command-receipt', unit_id=item['uid'],
                      result=copy.deepcopy(result or dict(accepted=False, message='receipt_timeout')))

        request = self.pending
        if request is not None:
            if not request['future'].done():
                if (o.clock() - request['started'] > o.config.get('timeout', 10.) + 1
                        and not request.get('timeout_logged')):
                    request['timeout_logged'] = True
                    o._record('emotion-model-timeout', unit_ids=request['unit_ids'])
            elif active or request['token'] != self._token():
                self.pending = None
                try:
                    response = request['future'].result()
                    if (request['token'] != self._token()
                            or o.clock() - request['started'] > o.config.get('timeout', 10.) + 1):
                        self.discarded += 1
                        o._record('emotion-response-discarded',
                                  unit_ids=request['unit_ids'],
                                  reason='authority_or_deadline_changed')
                    elif now - request['game_time'] > MAX_RESPONSE_GAME_AGE:
                        self.discarded += 1
                        o._record('emotion-response-discarded',
                                  unit_ids=request['unit_ids'], reason='game_context_expired',
                                  game_age=round(now - request['game_time'], 1))
                        self._retry_after_failure(request['unit_ids'], now, 'stale_context')
                    else:
                        answers = response['answers']
                        for uid in request['unit_ids']:
                            agent = self.agents.get(uid)
                            if agent is None:
                                continue
                            # A new injury or death changes the question itself. Do not
                            # display an answer chosen before that event was observed.
                            newer_critical = any(
                                event['serial'] > max(request['event_serials'][uid], default=0)
                                and event['kind'] in HIGH_PRIORITY_EVENTS
                                for event in agent['events'])
                            if newer_critical or any(
                                    abs(agent['affect_state'][key] - request['affect'][uid][key])
                                    >= MATERIAL_CHANGE_THRESHOLD for key in APPRAISAL_FIELDS):
                                self.discarded += 1
                                o._record('emotion-response-discarded', unit_id=uid,
                                          reason='game_context_changed')
                                self._retry_after_failure([uid], now, 'stale_context')
                                continue
                            emotion = answers.get('emotion_' + uid, {}).get('choice')
                            if emotion not in EMOTIONS:
                                o._record('emotion-decision-failed', unit_id=uid,
                                          reason='invalid_soldier_emotion')
                                agent['next_retry_at'] = now + 5.
                                continue
                            command = dict(action='unit_emotion', faction=o.team,
                                           unit_ids=[uid], emotion=emotion,
                                           run_id=o.world['run_id'],
                                           seen_tick=int(o.world['tick']),
                                           control_epoch=o.world.get(
                                               'control_epochs', {}).get(o.team, 0))
                            if getattr(o.game, 'session_id', None):
                                command['instance_id'] = o.game.session_id
                            status, receipt = o.state.submit(command, source='lm')
                            if status != 202:
                                o._record('emotion-decision-failed', unit_id=uid,
                                          reason='emotion_queue_rejected:' +
                                          str(receipt.get('error', status)))
                                agent['next_retry_at'] = now + 5.
                                continue
                            self.receipts[receipt['id']] = dict(
                                uid=uid, submitted=o.clock(), token=self._token())
                            for event in agent['events']:
                                if event['serial'] in request['event_serials'][uid]:
                                    event['delivered'] = True
                            agent['last_emotion'] = emotion
                            agent['last_review'] = now
                            agent['transient_failures'] = 0
                            o._record('emotion-decision', unit_id=uid,
                                      trigger=request['trigger'], emotion=emotion,
                                      response={'answers': {'emotion': {'choice': emotion}}})
                except Exception as error:
                    reason = self._failure_reason(error)
                    o._record('emotion-decision-failed',
                              unit_ids=request['unit_ids'], reason=reason)
                    self._retry_after_failure(request['unit_ids'], now, reason)

        if (not active or not members or o.stopped.is_set()
                or o.budget_exhausted or self.pending is not None):
            return

        event_limit = min(8, max(2, int(o.config.get('max_requests', 100) // 8)))
        low_priority_limit = max(1, event_limit - 2)
        fresh_by_unit = {}
        changed_ids = set()
        for unit in members:
            agent = self.agents[unit['id']]
            stable_hold = self._holds_stable_affect(agent, now)
            fresh = [event for event in agent['events']
                     if event['kind'] in TRIGGER_EVENTS and not event['delivered']
                     and event['serial'] > agent.get('last_requested_serial', 0)
                     and 0 <= now - event['at'] <= EVENT_WINDOW_SECONDS
                     and not stable_hold]
            if fresh:
                fresh_by_unit[unit['id']] = fresh
            # Material shifts can occur without a named event, for example
            # exposure ending after moving into cover. Avoid a second model
            # call merely because the appraisal naturally decays one tick.
            if (agent.get('last_requested_at') is not None
                    and now - agent['last_requested_at'] >= 2.
                    and not stable_hold
                    and self._appraisal_change(agent) >= MATERIAL_CHANGE_THRESHOLD):
                changed_ids.add(unit['id'])
        high_priority = any(event['kind'] in HIGH_PRIORITY_EVENTS
                            for events in fresh_by_unit.values() for event in events)
        event_due = False
        if (fresh_by_unit or changed_ids) and self.event_calls < event_limit:
            if high_priority:
                event_due = now - self.last_high_event_at >= 2.
            else:
                event_due = (now - self.last_low_event_at >= EVENT_COOLDOWN_SECONDS
                             and self.low_priority_event_calls < low_priority_limit)
        periodic_ids = {unit['id'] for unit in members
                         if self.agents[unit['id']].get('last_requested_at') is None
                         or now - self.agents[unit['id']]['last_requested_at'] >= PERIOD_SECONDS}
        periodic_due = bool(periodic_ids)
        retry_ids = {uid for uid, agent in self.agents.items()
                     if now >= agent.get('next_retry_at', float('inf'))}
        retry_due = bool(retry_ids)
        if not (event_due or periodic_due or retry_due):
            self.pending_low_since = None
            return
        if event_due and not high_priority and not periodic_due:
            if self.pending_low_since is None:
                self.pending_low_since = now
                return
            if now - self.pending_low_since < .5:
                return
        if o.clock() < self.next_wall_at:
            return
        if o.request_count >= o.config.get('max_requests', 100):
            return
        shared = o.config.get('shared_request_budget')
        if shared is not None and not shared.claim():
            o.budget_exhausted = True
            return

        # Combine every due reason into one batch. A recent strong-but-stable
        # soldier is not silently pulled into another member's periodic batch.
        trigger = 'periodic' if periodic_due else 'event' if event_due else 'retry'
        selected_ids = periodic_ids | retry_ids
        if event_due or periodic_due or retry_due:
            selected_ids |= set(fresh_by_unit) | changed_ids
        selected = [u for u in members if u['id'] in selected_ids]
        context = dict(time=now, soldiers={u['id']: self._context(u) for u in selected},
                       trigger=trigger)
        questions = {}
        for unit in selected:
            uid = unit['id']
            support = context['soldiers'][uid]['emotion_support']
            questions['emotion_' + uid] = dict(
                type='choice',
                criteria={name: f'{description}；该兵情境匹配度 {support[name]:.2f}'
                          for name, description in EMOTION_CRITERIA.items()},
                instructions=(f'只为士兵 {uid} 选择；只把 soldiers.{uid} 的受伤、来袭、压制'
                              '当作本人经历，不借用其他成员的感受。' + EMOTION_INSTRUCTIONS))
        unit_ids = [u['id'] for u in selected]
        event_serials = {uid: [event['serial'] for event in self.agents[uid]['events']]
                         for uid in unit_ids}
        request = dict(token=self._token(), started=o.clock(), game_time=now,
                       affect={uid: {key: self.agents[uid]['affect_state'][key]
                                     for key in APPRAISAL_FIELDS} for uid in unit_ids},
                       future=Future(),
                       unit_ids=unit_ids, event_serials=event_serials,
                       trigger=trigger)
        self.pending = request
        self.next_wall_at = o.clock() + o.config.get('emotion_cooldown_s', .5)
        self.pending_low_since = None
        for uid in unit_ids:
            agent = self.agents[uid]
            agent['last_requested_serial'] = max(
                event_serials[uid], default=agent.get('last_requested_serial', 0))
            agent['last_requested_danger'] = agent['affect_state']['danger']
            agent['last_requested_at'] = now
            agent['last_requested_affect'] = {
                key: agent['affect_state'][key]
                for key in APPRAISAL_FIELDS + ('arousal',)}
            agent.pop('next_retry_at', None)
        if trigger == 'event':
            if high_priority:
                self.last_high_event_at = now
            else:
                self.last_low_event_at = now
                self.low_priority_event_calls += 1
            self.event_calls += 1
        elif trigger == 'periodic':
            self.periodic_calls += 1
        self.calls += 1
        o.request_count += 1
        o._record('emotion-model-request', unit_ids=unit_ids, trigger=trigger,
                  priority='high' if trigger == 'event' and high_priority else 'normal',
                  context=context)

        def ask():
            try:
                response = (dict(answers={'emotion_' + uid: dict(choice='calm')
                                          for uid in unit_ids}) if o.model == 'mock' else
                            o.game.ask(context, questions))
                request['future'].set_result(response)
            except Exception as error:
                request['future'].set_exception(error)
        threading.Thread(target=ask, name='soldier-emotions', daemon=True).start()

    def snapshot(self):
        return dict(agents=copy.deepcopy(self.agents), calls=self.calls,
                    periodic_calls=self.periodic_calls, event_calls=self.event_calls,
                    low_priority_event_calls=self.low_priority_event_calls,
                    held_events=self.held_events,
                    accepted=self.accepted, discarded=self.discarded,
                    pending_units=self.pending['unit_ids'] if self.pending else [])
