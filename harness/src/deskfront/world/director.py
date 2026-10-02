"""Adaptive world harness. DeepSeek regulates pacing; JEV chooses construction.

No world state is synthesized here. Model output must receive a Godot receipt,
then a later completed-region entry before it is considered constructed.
"""
import copy
import math
import threading
import time
import uuid
from collections import deque

from jev_client import checked_choice

# Compatibility exports: the stable macro contract lives in director_contract.
from .director_contract import AXES, PHASES, ROUTE_PREFERENCES, eligible_choices, validate_macro
from .catalog import CATALOG as COMPONENTS, DESCRIPTIONS as CATALOG, CHOICES, eligible
from .context import macro_context, generator_context, context_chars, observation_sample
from .forces import validate_forces
from .macro_bridge import MacroBridge

class WorldDirector:
    def __init__(self, studio, game):
        self.studio = studio
        self.game = game
        self.lock = threading.RLock()
        self.busy = False
        self.analysis_busy = False
        self.analysis_error = ''
        self.experience = None
        self.samples = deque(maxlen=60)
        self.run_id = ''
        self.last_sample = -1.0
        self.calls = 0
        self.limit = game.config.get('runtime', {}).get('maxRequests', 100)
        self.last_attempt = -math.inf
        self.hormones = dict(pressure=.3, recovery=.4, expansion=.6, teaching=.3, novelty=.5)
        self.phase = 'explore'
        self.phase_since = 0.0
        self.history = deque(maxlen=32)
        self.status = 'idle'
        self.error = ''
        self.prepared = None
        self.preparation_epoch = 0
        self.next_commit_at = 0.0
        self.commit_failures = 0

    def _submission_pending(self):
        return any(row['status'] in ('queued_not_completed', 'building', 'confirmation_unknown') for row in self.history)

    def _discard_prepared(self, reason):
        if self.prepared:
            c = self.prepared['command']
            self.game.record(dict(type='world-prepared-discarded', reason=reason,
                option=c['option'], operation_id=c['operation_id'], revision=c['growth_revision']))
        self.prepared = None
        self.next_commit_at = 0.0
        self.commit_failures = 0
        self.error = reason
        self.status = 'awaiting_preparation'

    def observe(self, s):
        if not s.get('world_growth', {}).get('enabled'):
            return
        # State.sync mutates and evicts the bounded receipt map under this lock.
        # Snapshot it before taking the director lock; never hold a state lock
        # across model calls or game.record.
        with self.studio.state.lock:
            receipts = copy.deepcopy(self.studio.state.results)
            queued = set(getattr(self.studio.state, 'pending', {}))
            queue_known = hasattr(self.studio.state, 'pending')
        with self.lock:
            if s.get('run_id') != self.run_id:
                self.run_id = s['run_id']; self.samples.clear(); self.history.clear()
                self.calls = 0; self.last_sample = -1.; self.phase_since = 0.
                self.hormones = dict(pressure=.3, recovery=.4, expansion=.6, teaching=.3, novelty=.5)
                self.phase = 'explore'; self.error = ''; self.status = 'observing'
                self.prepared = None; self.last_attempt = -math.inf
                self.experience = None; self.analysis_error = ''
                self.preparation_epoch += 1
                self.next_commit_at = 0.0; self.commit_failures = 0
            world = s['world_growth']
            completed = {c['operation_id']: c for c in world.get('completed', [])}
            # Rolling terrain may retire the completed list before a delayed
            # observer catches up. An exact native mission operation also proves
            # construction; winning that mission is a separate fact.
            for mission in [world.get('mission', {})] + world.get('mission_results', []):
                operation = mission.get('operation_id')
                if operation and operation not in completed:
                    completed[operation] = {k: mission[k] for k in ('operation_id', 'index', 'option') if k in mission}
                    completed[operation]['evidence'] = 'native_mission'
            failed = {c['operation_id']: c for c in world.get('construction_failures', [])}
            for row in self.history:
                if row['status'] == 'completed': continue
                receipt = receipts.get(row['command_id']) or row.get('receipt')
                if row['operation_id'] in completed:
                    row.update(status='completed', receipt=receipt, construction=completed[row['operation_id']])
                    self.game.record(dict(type='world-receipt', **copy.deepcopy(row)))
                    if self.status == 'confirmation_unknown':self.status = 'completed'; self.error = ''
                    continue
                if row['status'] in ('rejected', 'superseded_unconfirmed'): continue
                if row['operation_id'] in failed:
                    row.update(status='rejected', construction_failure=failed[row['operation_id']])
                    self.status = 'awaiting_preparation'
                    self.error = failed[row['operation_id']].get('reason', 'world_construction_failed')
                    self.game.record(dict(type='world-receipt', **copy.deepcopy(row)))
                    continue
                timed_out = receipt and receipt.get('message') == 'command_timeout'
                if receipt and not receipt.get('accepted') and not timed_out:
                    status = 'rejected'
                elif world.get('revision', 0) > row.get('growth_revision', math.inf):
                    # An old-revision command cannot mutate the current world.
                    # Do not invent a successful or failed construction when its
                    # exact native evidence has already been lost.
                    status = 'superseded_unconfirmed'
                elif timed_out or (queue_known and row['command_id'] not in queued
                        and (not receipt or world.get('phase') != 'building')
                        and time.monotonic()-row.get('submitted_at', time.monotonic()) >= 15):
                    status = 'confirmation_unknown'
                else:
                    status = 'building' if receipt and receipt.get('accepted') else 'queued_not_completed'
                if row['status'] != status:
                    row.update(status=status, receipt=receipt, construction=completed.get(row['operation_id']))
                    if status == 'rejected':
                        self.status = 'awaiting_preparation'
                        self.error = receipt.get('message', 'world_command_rejected')
                    elif status == 'confirmation_unknown':
                        self.status = 'confirmation_unknown'; self.error = 'world_confirmation_missing'
                    elif status == 'superseded_unconfirmed':
                        self.status = 'awaiting_preparation'; self.error = 'world_revision_advanced_without_receipt'
                    self.game.record(dict(type='world-receipt', **copy.deepcopy(row)))
            if s['time'] - self.last_sample < 1:
                return
            self.last_sample = s['time']
            self.samples.append(observation_sample(s))

    def snapshot(self):
        with self.lock:
            return copy.deepcopy({'status': self.status, 'error': self.error, 'run_id': self.run_id,
                'phase': self.phase, 'hormones': self.hormones, 'requests_used': self.calls,
                'experience': self.experience, 'analysis_busy': self.analysis_busy, 'analysis_error': self.analysis_error,
                'generation_policy': 'clear_triggered_planner_then_spatial_builder',
                'request_limit': self.limit, 'observations': len(self.samples), 'history': list(self.history),
                'submission_pending': self._submission_pending(),
                'prepare_retry_in': max(0.0, self.last_attempt + 5 - time.monotonic()),
                'prepared': None if not self.prepared else dict(
                    option=self.prepared['command']['option'],
                    mission_kind=self.prepared['command'].get('mission_kind','assault'),
                    defender_mix=self.prepared['command'].get('defender_mix','balanced'),
                    support_type=self.prepared['command'].get('support_type','infantry'),
                    revision=self.prepared['command']['growth_revision'],
                    seen_tick=self.prepared['seen_tick'],
                    friendly_count=self.prepared['command']['friendly_count'],
                    enemy_count=self.prepared['command']['enemy_count']),
                'player_profile_status': 'provisional_observation_only',
                'note': '观战不推断玩家；当前仅收集玩家控制阵营的行为样本，尚无长期技能评估。'})

    def analyze(self, final=False):
        """Analyze the current encounter, including a short finished encounter."""
        with self.studio.state.lock:
            state=copy.deepcopy(self.studio.state.state)
            instance=self.studio.state.instance_id
            age=time.monotonic()-self.studio.state.updated
        world=state.get('world_growth',{})
        if (age>3 or state.get('paused') or
                (world.get('phase')!='encounter' and not (final and world.get('phase')=='ready' and world.get('mission_results')))):
            return False
        with self.lock:
            reserve=3
            if self.analysis_busy or self.calls+reserve+1>self.limit:return False
            self.analysis_busy=True;self.calls+=1
            previous=dict(self.hormones);phase=self.phase
            samples=copy.deepcopy(list(self.samples))
            old=copy.deepcopy(self.experience)
        try:
            context=macro_context(state,samples,previous,phase)
            context.update(agent='experience_analyst',previous_understanding=old,
                analysis_rules='仅分析体验与节奏，不选择地图或组件。偏好与能力无操作机会证据时标记未知。')
            macro,request=self.studio.regulate(context);macro=validate_macro(macro)
            with self.studio.state.lock:
                valid=(self.studio.state.instance_id==instance and self.studio.state.state.get('run_id')==state['run_id'])
            with self.lock:
                if not valid or self.run_id!=state['run_id']:return False
                self.hormones={k:round(max(previous[k]-.2,min(previous[k]+.2,macro['hormones'][k])),3) for k in AXES}
                if state['time']-self.phase_since>=8 and macro['phase']!=self.phase:
                    self.phase=macro['phase'];self.phase_since=state['time']
                self.experience=dict(report_id=request,observed_at=state['time'],observed_tick=state['tick'],
                    world_revision=world.get('revision'),
                    source='completed_encounter' if final else 'player_observation' if context['human_sample_count'] else 'bot_battle_observation',
                    assessment=macro['player_assessment'],reason=macro['reason'],
                    current_analysis=macro['current_analysis'],next_goal=macro['next_goal'],
                    hormones=dict(self.hormones),phase=self.phase)
                self.analysis_error=''
            self.game.record(dict(type='world-experience-updated',report=copy.deepcopy(self.experience)))
            return True
        except Exception as exc:
            with self.lock:self.analysis_error=str(exc) if isinstance(exc,ValueError) else 'experience_analysis_failed'
            raise
        finally:
            with self.lock:self.analysis_busy=False

    def step(self, payload):
        """Clear-triggered planner -> spatial builder. No DeepSeek call here."""
        from .generation_agents import plan
        from .region_builder import build
        st=self.studio
        with st.state.lock:
            state=copy.deepcopy(st.state.state);instance=st.state.instance_id
            age=time.monotonic()-st.state.updated
        if age>3 or not state:raise ValueError('engine_offline')
        if payload.get('run_id')!=state.get('run_id') or payload.get('instance_id')!=instance:raise ValueError('stale_world_session')
        world=state.get('world_growth',{})
        if (not world.get('enabled') or world.get('phase')!='ready' or not world.get('options')
                or state.get('paused') or state.get('winner')):raise ValueError('world_not_ready')
        # A short encounter can clear before the periodic analyst fires. Give
        # DeepSeek one final look at that *current* encounter before JEV plans.
        with self.lock:latest_report=copy.deepcopy(self.experience)
        if (world.get('mission_results') and (not latest_report or
                latest_report.get('world_revision')!=world.get('revision'))):
            try:self.analyze(final=True)
            except Exception as exc:self.game.record(dict(type='world-analysis-error',
                error=str(exc) if isinstance(exc,ValueError) else 'final_experience_analysis_failed'))
        with self.lock:
            if self.busy:raise ValueError('world_director_busy')
            if self.prepared or self._submission_pending():raise ValueError('world_submission_pending')
            required=3
            if self.calls+required>self.limit:raise ValueError('world_request_budget_reached')
            if time.monotonic()-self.last_attempt<5:raise ValueError('world_rate_limited')
            self.busy=True;self.calls+=2;self.last_attempt=time.monotonic()
            self.status='jev_planning';self.error=''
            epoch=self.preparation_epoch;report=copy.deepcopy(self.experience)
            hormones=dict(self.hormones);phase=self.phase
            samples=copy.deepcopy(list(self.samples))
        started=time.monotonic()
        def reserve_request():
            with self.lock:
                if self.calls>=self.limit:raise ValueError('world_request_budget_reached')
                if epoch!=self.preparation_epoch:raise ValueError('world_preparation_superseded')
                self.calls+=1
        try:
            context=generator_context(macro_context(state,samples,hormones,phase))
            context.update(hormones=hormones,phase=phase,experience_report=report,
                trigger='empty_start' if world.get('revision')==0 else 'encounter_cleared',
                report_age_seconds=max(0,state['time']-report['observed_at']) if report else None,
                freshness_rule='teams和mission是最新清场事实，旧体验报告不能覆盖当前伤亡。无报告按当前战果选常规关。')
            from .design_memory import describe
            with self.lock:
                previous=[copy.deepcopy(row) for row in self.history if row.get('status')=='completed'][-3:]
            outcomes={result.get('operation_id'):result for result in world.get('mission_results',[])}
            recent_designs=[]
            for row in previous:
                outcome=outcomes.get(row.get('operation_id'),{})
                mission={key:outcome[key] for key in ('status','duration_seconds','reason',
                    'enemies_remaining','friendly_added') if key in outcome}
                preview=row.get('tool_validation',{}).get('tactical_estimate')
                summary=describe(row.get('build_operations',[]),option=row.get('option'),
                    mission=mission or None,tactical=preview,
                    actual_spec=(row.get('construction') or {}).get('design'))
                if summary:recent_designs.append(summary)
            context['recent_designs']=recent_designs
            context['recent_layout_briefs']=[row['layout_brief'] for row in previous if row.get('layout_brief')]
            choices=eligible(world,hormones) or eligible(world)  # Never erase the engine's whole legal menu.
            task=plan(self.game,context,choices,state)
            with self.lock:
                if epoch!=self.preparation_epoch:raise ValueError('world_preparation_superseded')
                self.status='jev_building'
                # One call is still guaranteed for the whole-board revision.
                # Single-prop details use a fourth call only when JEV selects
                # such an edit and there is room in this director's budget.
                task['allow_prop_edits']=self.calls+2<=self.limit
            task['recent_builds']=[row.get('build_operations',[]) for row in previous]
            task['recent_designs']=recent_designs
            task['generation_index']=world['revision']
            operations,build_calls,validation=build(self.game,task,reserve_request)
            with st.state.lock:
                current=copy.deepcopy(st.state.state)
                valid=(st.state.instance_id==instance and current.get('run_id')==state['run_id']
                    and current.get('world_growth',{}).get('revision')==world['revision']
                    and current.get('world_growth',{}).get('phase')=='ready'
                    and task['option'] in current.get('world_growth',{}).get('options',[])
                    and not current.get('paused') and not current.get('winner')
                    and time.monotonic()-st.state.updated<=3)
            if not valid:raise ValueError('world_context_changed')
            tank_rule=bool(self.game.config.get('gameOptions',{}).get('secondStageTankRule',True)) and world['revision']==1
            if not validate_forces(current,task['forces'],hormones,phase,ensure_rocket=tank_rule,support_type=task['support_type']):raise ValueError('force_context_changed')
            command=dict(action='grow_world',option=task['option'],hormones=hormones,
                mission_kind=task['mission_kind'],defender_mix=task['defender_mix'],support_type=task['support_type'],
                visual_pattern=validation.get('design_observations',{}).get('layout_pattern','open_field'),
                growth_revision=world['revision'],operation_id=str(uuid.uuid4()),
                run_id=state['run_id'],instance_id=instance,assembly_kind='region_graph_v1',build_operations=operations,**task['forces'])
            with self.lock:
                if epoch!=self.preparation_epoch or self._submission_pending():raise ValueError('world_preparation_superseded')
                self.prepared=dict(command=command,macro_call=report.get('report_id') if report else None,
                    jev_call=task['request_id'],builder_calls=build_calls,phase=phase,
                    layout_brief=task.get('layout_brief'),
                    reason=task['intent'],player_assessment=report.get('assessment','证据不足') if report else '证据不足',
                    source='clear_triggered_two_agents',seen_tick=state['tick'],tool_validation=validation,
                    build_operations=operations,generation_ms=round((time.monotonic()-started)*1000))
                self.status='prepared';self.next_commit_at=0;self.commit_failures=0
                prepared=copy.deepcopy(self.prepared)
            self.game.record(dict(type='world-prepared',option=task['option'],revision=world['revision'],
                generation_ms=prepared['generation_ms'],builder_calls=build_calls))
            if not payload.get('prepare') and self.commit_prepared():return self.history[-1]
            return prepared
        except Exception as exc:
            error=str(exc) if isinstance(exc,ValueError) else 'world_generation_failed'
            with self.lock:
                if epoch==self.preparation_epoch:self.status='error';self.error=error
            raise ValueError(error) from None
        finally:
            with self.lock:self.busy=False

    def commit_prepared(self):
        with self.lock:
            if not self.prepared or self._submission_pending():return False
            if time.monotonic() < self.next_commit_at:return False
            p = copy.deepcopy(self.prepared)
            c = p['command']
            with self.studio.state.lock:
                s = self.studio.state.state
                w = s.get('world_growth', {})
                if c['run_id'] != s.get('run_id') or c['instance_id'] != self.studio.state.instance_id or c['growth_revision'] != w.get('revision'):
                    self._discard_prepared('world_context_changed')
                    return False
                if time.monotonic()-self.studio.state.updated>3 or s.get('paused') or s.get('winner') or w.get('phase')!='ready':return False
                if c['option'] not in w.get('options', []):
                    self._discard_prepared('world_option_unavailable')
                    return False
                tank_rule=bool(self.game.config.get('gameOptions',{}).get('secondStageTankRule',True)) and w.get('revision')==1
                if not validate_forces(s, c, c['hormones'], p['phase'],ensure_rocket=tank_rule):
                    self._discard_prepared('force_context_changed')
                    return False
            code, receipt = self.studio.state.submit(c)
            if code != 202:
                reason = receipt.get('error', 'world_submit_failed')
                self.game.record(dict(type='world-submit-rejected', operation_id=c['operation_id'],
                    revision=c['growth_revision'], status=code, reason=reason))
                if code == 429 or code >= 500 or reason == 'engine_offline':
                    self.commit_failures += 1
                    self.next_commit_at = time.monotonic() + min(8, 2 ** min(3, self.commit_failures - 1))
                    self.status = 'commit_retry'; self.error = reason
                else:
                    self._discard_prepared(reason)
                return False
            row = dict(p, run_id=c['run_id'], option=c['option'], hormones=c['hormones'],
                selection=COMPONENTS[c['option']]['selection'], command_id=receipt['id'],
                operation_id=c['operation_id'], status='queued_not_completed')
            row.pop('command')
            row['growth_revision'] = c['growth_revision']
            row.update(friendly_count=c['friendly_count'],enemy_count=c['enemy_count'],mission_kind=c.get('mission_kind','assault'),defender_mix=c.get('defender_mix','balanced'),support_type=c.get('support_type','infantry'),
                clear_to_submit_game_seconds=max(0,s.get('time',0)-w['mission']['completed_at'])
                    if w.get('mission',{}).get('completed_at') is not None else None)
            row['submitted_at'] = time.monotonic()
            self.history.append(row); self.prepared=None; self.status='submitted'; self.error=''
            self.preparation_epoch += 1
            self.next_commit_at = 0.0; self.commit_failures = 0
            self.game.record(dict(type='world-submitted', **row))
            return True


