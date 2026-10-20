"""Adapt public engine facts and receipts to existing controllers, without policy."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import copy
import threading
import time
import uuid

from deskfront_bridge import BridgeError, BridgeDeadlineError, BridgeTransportError
from soldier_candidate_query import proposals
from soldier_agents import native_grenade_opportunities
from background_query import optional_kwargs, receipt_unknown
from urllib.parse import urlencode, quote


class GrenadePreflightError(ValueError):
    """A local rejection before any mutating bridge request is sent."""


class AttachedState:
    def __init__(self, client, team, lease):
        self.client, self.team, self.lease = client, team, lease
        self.instance_id = client.instance_id
        self.lock = threading.RLock()
        self.query_lock = threading.Lock()
        self.state, self.context, self.pending = {}, {}, {}
        self.results = OrderedDict()
        self.updated = 0
        # update() publishes a detached value and never mutates it in place.
        # Controllers may retain their own isolated copy until this changes.
        self.observation_version = 0
        self.topology = None
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='sdk-' + team)
        self.display_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='sdk-display-' + team)
        self.receipt_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='sdk-receipt-' + team)
        self.unknown = OrderedDict()
        self._receipt_running = False
        self._receipt_stop = threading.Event()
        self._display_latest = None
        self._display_running = False
        self.closed = False

    def update(self, row):
        context, state = row['context'], copy.deepcopy(row['state'])
        key = (context['runId'], context['revision'])
        if self.topology is None or (self.topology['run_id'], self.topology['revision']) != key:
            actor = next((u['id'] for u in state.get('units', []) if u.get('faction') == self.team and u.get('hp', 0) > 0), None)
            if actor:
                try:
                    self.topology = self.client.topology(context, self.team, actor)
                except BridgeError as error:
                    # Construction may commit between observe and query. The
                    # legacy file reader waits for the matching topology too;
                    # a normal revision race must not terminate both teams.
                    if error.code != 'stale_map':raise
        if self.topology and (self.topology['run_id'], self.topology['revision']) == key:
            state['strategic_topology'] = self.topology
        with self.lock:
            self.context, self.state, self.updated = context, state, time.monotonic()
            self.observation_version += 1
        self._schedule_reconciliation()

    def submit(self, command, **_):
        ident = uuid.uuid4().hex
        with self.lock:
            if len(self.pending)+len(self.unknown) >= 64:return 429, {'error': 'queue_full'}
            if command.get('faction', self.team) != self.team:return 403, {'error': 'controller_faction_mismatch'}
            if command.get('run_id') != self.context.get('runId'):return 409, {'error': 'stale_run'}
            context = dict(self.context)
            context['tick'] = command.get('seen_tick', context['tick'])
            native = copy.deepcopy(command)
            self.pending[ident] = native
        queued_at=time.monotonic()
        if command.get('action') == 'sidebar':
            # One currently sending packet and one newest packet; old display
            # work cannot queue in front of tactical commands or grow a FIFO.
            with self.lock:
                old=self._display_latest
                if old:
                    self.pending.pop(old[0],None)
                    self.results[old[0]]=dict(id=old[0],accepted=None,status='superseded',message='presentation_superseded')
                self._display_latest=(ident,context,native,queued_at)
                if not self._display_running:
                    self._display_running=True
                    self.display_pool.submit(self._drain_display)
        else:
            # Single mutation lane preserves tactical order. A separate lane
            # only carries coalesced display packets, never soldier actions.
            self.pool.submit(self._send, ident, context, native, queued_at)
        return 202, {'id': ident, 'status': 'queued'}

    def _drain_display(self):
        while True:
            with self.lock:
                item=self._display_latest
                self._display_latest=None
                if not item:
                    self._display_running=False
                    return
            self._send(*item)

    def _schedule_reconciliation(self):
        with self.lock:
            if self.closed or not self.unknown or self._receipt_running:return
            self._receipt_running=True
            self.receipt_pool.submit(self._drain_receipts)

    def _drain_receipts(self):
        # One real worker, independently of observation polling. Fair polling
        # and absolute expiry keep an unavailable observer/HTTP job from
        # leaving an unknown mutation pending forever or growing a task FIFO.
        try:
            while not self._receipt_stop.is_set():
                now=time.monotonic()
                with self.lock:
                    if self.closed or not self.unknown:return
                    ready=[(ident,row) for ident,row in self.unknown.items()
                        if not row.get('busy') and (now>=row['until'] or now>=row.get('next_at',0))]
                    if ready:
                        ident,row=min(ready,key=lambda item:(item[1]['until']>now,item[1].get('last_polled',0)))
                        row['busy']=True;row['last_polled']=now
                    else:ident=None
                if ident is not None:self._reconcile(ident)
                if self._receipt_stop.wait(.02 if ident is not None else .05):return
        finally:
            with self.lock:
                self._receipt_running=False
                restart=bool(self.unknown) and not self.closed
            if restart:self._schedule_reconciliation()

    def _state_proof(self, context, command):
        """Only a unique observed complete order proves application; no review inference."""
        if command.get('action')!='squad_order' or command.get('task_review'):return None
        if self.context.get('runId')!=context.get('runId') or self.context.get('instanceId')!=context.get('instanceId'):return None
        squad=self.state.get('squad_behavior',{}).get('squads',{}).get(command.get('squad_id'),{})
        order=command.get('order_id')
        if not order or squad.get('order_id')!=order or squad.get('faction',self.team)!=self.team:return None
        plan=squad.get('cooperation_plan',{})
        if command.get('cooperation_plan') and plan.get('plan_id')!=order:return None
        if set(squad.get('unit_ids',[]))!=set(command.get('unit_ids',[])):return None
        if self.state.get('control_epochs',{}).get(self.team)!=command.get('control_epoch'):return None
        return dict(accepted=True,message='applied_observed',receipt_source='authoritative_state',
            tick=self.state.get('tick'),proof=dict(run_id=self.context.get('runId'),order_id=order,
                plan_id=plan.get('plan_id'),control_epoch=command.get('control_epoch')))

    def _reconcile(self, ident):
        with self.lock:
            row=self.unknown.get(ident)
            if not row:return
            context,command=dict(row['context']),row['command']
            deadline=min(row['until'],time.monotonic()+.4)
        result=None
        try:
            args=urlencode(dict(team=self.team,runId=context.get('runId',''),instanceId=context.get('instanceId',self.instance_id)))
            path='/v1/deskfront/receipts/'+quote(ident,safe='')+'?'+args
            response=self.client.request(path,**optional_kwargs(self.client.request,dict(deadline=deadline)))
            if response.get('id')==ident and response.get('status')=='completed':
                candidate=response.get('receipt')
                if isinstance(candidate,dict) and isinstance(candidate.get('accepted'),bool) and not receipt_unknown(candidate):
                    result=dict(candidate,receipt_source='readonly_native_reconciliation')
        except (BridgeError,OSError,TimeoutError,ValueError,TypeError,AttributeError):
            pass
        with self.lock:
            row=self.unknown.get(ident)
            if not row:return
            result=result or self._state_proof(context,command)
            if result:
                self.results[ident]=dict(result,id=ident)
                self.unknown.pop(ident,None)
            elif time.monotonic()>=row['until'] or self.closed:
                self.results[ident]=dict(id=ident,accepted=None,status='unresolved',message='ack_unresolved',
                    receipt_source='bounded_readonly_reconciliation',reconcile_attempts=row.get('attempts',0)+1)
                self.unknown.pop(ident,None)
            else:
                row['busy']=False;row['attempts']=row.get('attempts',0)+1;row['next_at']=time.monotonic()+.2

    def _grenade_preflight(self, context, command, lease, observed):
        fresh, world = observed['context'], observed['state']
        if fresh.get('instanceId') != self.instance_id or fresh.get('instanceId') != context.get('instanceId'):
            raise GrenadePreflightError('grenade_preflight_instance_changed')
        if (fresh.get('runId') != context.get('runId') or world.get('run_id') != fresh.get('runId')
                or command.get('run_id') != fresh.get('runId')):
            raise GrenadePreflightError('grenade_preflight_run_changed')
        if (fresh.get('revision') != context.get('revision')
                or world.get('navigation_revision') != fresh.get('revision')):
            raise GrenadePreflightError('grenade_preflight_map_changed')
        if type(fresh.get('tick')) is not int or world.get('tick') != fresh['tick']:
            raise GrenadePreflightError('grenade_preflight_observation_invalid')
        if (command.get('faction') != self.team or world.get('control', {}).get(self.team) != 'agent'
                or command.get('control_epoch') != lease.get('epoch')
                or world.get('control_epochs', {}).get(self.team) != lease.get('epoch')):
            raise GrenadePreflightError('grenade_preflight_control_changed')
        if world.get('paused') or world.get('winner'):
            raise GrenadePreflightError('grenade_preflight_battle_inactive')
        ids = command.get('unit_ids', [])
        if len(ids) != 1 or not isinstance(command.get('target_id'), str) or not command['target_id']:
            raise GrenadePreflightError('grenade_preflight_invalid_target_action')
        uid = ids[0]
        squad = world.get('squad_behavior', {}).get('squads', {}).get(command.get('squad_id'), {})
        if (not squad or squad.get('faction', self.team) != self.team
                or squad.get('order_id') != command.get('order_id')):
            raise GrenadePreflightError('grenade_preflight_order_changed')
        if uid not in squad.get('assignments', {}):
            raise GrenadePreflightError('grenade_preflight_assignment_changed')
        tokens = squad.get('assignment_tokens', {})
        if ('assignment_token' in command or uid in tokens) and (
                'assignment_token' not in command or uid not in tokens or command['assignment_token'] != tokens[uid]):
            raise GrenadePreflightError('grenade_preflight_assignment_changed')
        unit = next((u for u in world.get('units', []) if u.get('id') == uid
                     and u.get('faction') == self.team and u.get('hp', 0) > 0
                     and u.get('deployment_phase', 'active') == 'active'), None)
        if unit is None:
            raise GrenadePreflightError('grenade_preflight_actor_unavailable')
        target = next((u for u in world.get('units', []) if u.get('id') == command['target_id']
                       and u.get('faction') not in (self.team, None) and u.get('hp', 0) > 0), None)
        if target is None:
            raise GrenadePreflightError('grenade_preflight_target_unavailable')
        contacts = world.get('squad_behavior', {}).get('perception', {}).get(self.team, {}).get('contacts', [])
        if isinstance(contacts, dict): contacts = list(contacts.values())
        if command['target_id'] not in {row['target_id'] for row in
                native_grenade_opportunities(world, self.team, unit, contacts)}:
            raise GrenadePreflightError('grenade_opportunity_expired')
        # This tick belongs to a real, freshly revalidated observation. Do not
        # estimate time, refresh other command kinds or resend a mutation.
        return copy.deepcopy(fresh), dict(command, seen_tick=fresh['tick'])

    def _send(self, ident, context, command, queued_at):
        grenade = command.get('action') == 'soldier_order' and command.get('intent') == 'grenade'
        transport = dict(validation='dispatch_native_observation' if grenade else 'original_context_preserved', selected_tick=context.get('tick'),
                         queued_ms=round(max(0, time.monotonic()-queued_at)*1000), validated_tick=None)
        receipt_source = 'local_preflight' if grenade else None
        dispatched=False
        try:
            with self.lock: lease = copy.deepcopy(self.lease)
            if grenade:
                observed = self.client.observe(self.team)
                transport['validated_tick'] = observed.get('context', {}).get('tick')
                context, command = self._grenade_preflight(context, command, lease, observed)
                receipt_source = 'bridge_rejection'
            with self.lock:
                fresh=dict(self.context)
            if (context.get('runId')!=fresh.get('runId') or context.get('revision')!=fresh.get('revision')):
                raise BridgeError('stale_map_before_dispatch')
            if (type(context.get('tick')) is int and type(fresh.get('tick')) is int
                    and abs(fresh['tick']-context['tick'])>300):
                raise BridgeError('stale_observation_before_dispatch')
            deadline=queued_at+5.
            if time.monotonic()>=deadline:raise BridgeDeadlineError('command_queue_budget_exceeded')
            dispatched=True
            result = self.client.command(context, self.team, lease, command, ident,
                **optional_kwargs(self.client.command,dict(deadline=deadline)))
            if grenade: receipt_source = 'native'
        except Exception as error:
            unknown=dispatched and (isinstance(error,(OSError,TimeoutError)) or isinstance(error,BridgeError) and error.code in ('ack_timeout','command_timeout'))
            result = dict(id=ident, accepted=None if unknown else False,
                status='unknown' if unknown else 'rejected',message=str(error)[:160],receipt_source='transport' if unknown else 'explicit_preflight_or_bridge_rejection')
            if grenade and receipt_source != 'local_preflight' and not isinstance(error, BridgeError):
                receipt_source = 'transport_error'
        if receipt_unknown(result):
            result=dict(result,accepted=None,status='unknown')
        result = dict(result,transport=transport)
        if grenade and result.get('accepted') is not None:result['receipt_source']=receipt_source
        with self.lock:
            self.pending.pop(ident, None)
            self.results[ident] = result
            if receipt_unknown(result) and command.get('action')!='sidebar':
                self.unknown[ident]=dict(context=context,command=command,until=time.monotonic()+8.,next_at=0,busy=False)
            while len(self.results) > 256:self.results.popitem(last=False)
        self._schedule_reconciliation()

    def candidates(self, _path, state, unit, assignment, regions, topology, team, visible_tanks=(), equipment=(), *, deadline=None, timing=None):
        deadline=time.monotonic()+2. if deadline is None else deadline
        timing=timing if timing is not None else {}
        timing['proposal_started_wall']=time.monotonic()
        items = proposals(unit, assignment, regions, topology, visible_tanks=visible_tanks, equipment=equipment)
        timing['proposal_completed_wall']=time.monotonic();timing['proposal_count']=len(items)
        if time.monotonic()>=deadline:return dict(status='candidate_deadline_exceeded',options=[],transport_timing=timing)
        if not items:return dict(status='no_proposals', options=[],transport_timing=timing)
        remaining=max(0.,deadline-time.monotonic())
        if not self.query_lock.acquire(timeout=remaining):return dict(status='candidate_query_lock_deadline',options=[],transport_timing=timing)
        try:
            timing['query_lock_acquired_wall']=time.monotonic()
            with self.lock:context = dict(self.context)
            token = uuid.uuid4().hex
            timing['native_query_id']=token
            try:
                remaining_ms=int(max(0.,deadline-time.monotonic())*1000)
                if remaining_ms<1:raise BridgeDeadlineError('candidate_deadline_before_dispatch')
                timing['post_started_wall']=time.monotonic()
                self.client.request('/v1/query', dict(id=token, context=context, teamId=team,budgetMs=remaining_ms,
                    kind='soldier_candidates', actorIds=[unit['id']], parameters=dict(proposals=items,budgetMs=max(1,remaining_ms-150))),
                    **optional_kwargs(self.client.request,dict(deadline=deadline)))
                timing['post_completed_wall']=time.monotonic();timing['poll_count']=0
                while time.monotonic() < deadline:
                    try:
                        timing['poll_count']+=1;timing.setdefault('poll_started_wall',time.monotonic())
                        result = self.client.request('/v1/deskfront/queries/' + token + '?team=' + team,
                            **optional_kwargs(self.client.request,dict(deadline=deadline)))
                        timing['poll_completed_wall']=time.monotonic()
                        if time.monotonic()>=deadline:return dict(status='candidate_deadline_exceeded',options=[],native_result_status=result.get('status'),transport_timing=timing)
                        if result.get('run_id') == state['run_id'] and result.get('navigation_revision') == state.get('navigation_revision'):
                            return dict(result,transport_timing=timing)
                        return dict(status='stale_map', options=[],transport_timing=timing)
                    except BridgeError as error:
                        if error.code != 'query_not_ready':raise
                    time.sleep(min(.05,max(0.,deadline-time.monotonic())))
            except (BridgeError, OSError) as error:
                return dict(status='candidate_deadline_exceeded' if isinstance(error,BridgeDeadlineError) else str(error),options=[],transport_error=type(error).__name__,transport_timing=timing)
        finally:
            self.query_lock.release()
        return dict(status='candidate_deadline_exceeded', options=[],transport_timing=timing)

    def close(self):
        with self.lock:self.closed=True
        self._receipt_stop.set()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.display_pool.shutdown(wait=True,cancel_futures=True)
        self.receipt_pool.shutdown(wait=True,cancel_futures=True)
