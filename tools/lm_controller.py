"""Per-unit LM decisions. Only Godot executes gameplay; secrets never leave the provider client."""
import concurrent.futures
import copy
import math
from pathlib import Path
import threading
import time
import urllib

from lm_call_log import CallLog
from lm_provider import ArkClient, NoRedirect, ProviderError, SYSTEM, build_payload, load_config

ACTIONS = {'move', 'capture', 'cover', 'flank', 'retreat', 'hold', 'attack', 'grenade', 'posture', 'wait', 'man_at_gun', 'leave_gun', 'garrison', 'leave_building'}
INTENTS = {'survive', 'support', 'advance', 'flank', 'engage', 'withdraw', 'capture', 'observe'}

def observation(state, unit, memory):
    fields = ['id', 'faction', 'kind', 'weapon', 'hp', 'max_hp', 'position', 'goal', 'posture', 'suppression', 'ammo', 'reload_remaining', 'order_mode', 'locomotion', 'weapon_state', 'weapon_range', 'turret_yaw', 'reversing', 'in_cover', 'cover_id', 'cqb_stance', 'available_actions', 'last_shot_at', 'last_shot_target', 'survival_reason', 'path_failure', 'gun_id', 'building_floor', 'building_phase', 'elevation', 'combat', 'tactical_role', 'deployment_phase', 'combat_ready']
    small = lambda u: {k: u[k] for k in fields if k in u}
    obs = {'run_id': state['run_id'], 'tick': state['tick'], 'time': state['time'], 'bounds': state['bounds'], 'self': small(unit), 'allies': [small(u) for u in state['units'] if u['hp'] > 0 and u['faction'] == unit['faction'] and u['id'] != unit['id']], 'enemies': [small(u) for u in state['units'] if u['hp'] > 0 and u['faction'] != unit['faction']], 'covers': [{k: c[k] for k in ['id', 'position', 'size', 'height', 'hp', 'alive'] if k in c} for c in state.get('covers', [])], 'objective': {k:v for k,v in state['objective'].items() if k!='screen_position'}, 'weapon_rules': state.get('weapons', {}).get(unit.get('weapon'), {}), 'at_guns': state.get('at_guns',[]), 'building': state.get('building',{}), 'previous': memory[-2:]}

    members=[u for u in state['units'] if u['faction']==unit['faction'] and u['hp']>0]
    movers=[u for u in members if u['kind']!='tank' and u['hp']/max(1,u['max_hp'])>.45 and u.get('suppression',0)<.6 and not u.get('gun_id') and not u.get('building_phase')]
    movers.sort(key=lambda u:(u.get('tactical_role')!='assault',math.dist(u['position'],state['objective']['position']),u['id']))
    distance=math.dist(unit['position'],state['objective']['position'])
    obs['mission']={'advance_unit_id':movers[0]['id'] if movers else '', 'objective_distance':round(distance,3),'in_capture_zone':distance<=state['objective']['radius'],'goal':'安全接敌、建立实际火力、争夺目标；不能全队永久观察'}
    obs['flag_warning']=flag_warning(state, unit)
    if obs['flag_warning'].get('active'):
        obs['mission'].update(priority='critical',goal=obs['flag_warning']['message'],accept_casualties=True)
    obs['scores']=state.get('scores',{})
    obs['covers']=[c for c in obs['covers'] if c.get('alive',True)]
    return obs


def flag_warning(state, unit):
    """Only expose the authoritative engine warning for this unit's faction."""
    if state.get('winner'):return {'active':False}
    return copy.deepcopy(state.get('objective',{}).get('flag',{}).get('alerts',{}).get(unit['faction'],{'active':False}))


def flag_epoch(state):
    return state.get('objective',{}).get('flag',{}).get('capture_epoch',0)


def validate_squad_decision(value, state, unit):
    allowed={'action','intent','position','radius','squad_id','order_id','unit_ids','target_id','reason'}
    if not isinstance(value,dict) or set(value)-allowed:raise ValueError('invalid_decision_fields')
    from server import validate_command
    error=validate_command({**value,'faction':unit['faction']})
    if error:raise ValueError(error)
    if not state.get('squad_behavior',{}).get('enabled'):raise ValueError('human_squad_disabled')
    alive={u['id'] for u in state['units'] if u['hp']>0 and u['faction']==unit['faction']}
    if any(uid not in alive for uid in value['unit_ids']):raise ValueError('invalid_unit_authority')
    b=state['bounds'];p=value['position']
    if not (b[0]<=p[0]<=b[2] and b[1]<=p[1]<=b[3]):raise ValueError('invalid_position')
    if 'target_id' in value:
        contacts=state['squad_behavior'].get('perception',{}).get(unit['faction'],{}).get('contacts',[])
        if not any(c['id']==value['target_id'] and c.get('visible') for c in contacts):raise ValueError('target_not_observed')
    return {**value,'reason':str(value.get('reason',''))[:80]}


def validate_decision(value, state, unit):
    if isinstance(value,dict) and value.get('action')=='squad_order':return validate_squad_decision(value,state,unit)
    if not isinstance(value, dict) or set(value) - {'action', 'intent', 'posture', 'position', 'target_id', 'reason', 'gun_id', 'floor'}:
        raise ValueError('invalid_decision_fields')
    action = value.get('action')
    if action not in ACTIONS or value.get('intent') not in INTENTS:
        raise ValueError('invalid_decision_action_or_intent')
    if action != 'wait' and action not in unit.get('available_actions', []):
        raise ValueError('action_unavailable')
    clean = {'action': action, 'intent': value['intent'], 'reason': str(value.get('reason', ''))[:80]}
    if action == 'posture' and 'posture' not in value:
        raise ValueError('posture_required')
    if 'posture' in value:
        if unit['kind'] == 'tank' or value['posture'] not in {'auto', 'stand', 'crouch', 'prone'}:
            raise ValueError('invalid_posture')
        clean['posture'] = value['posture']
    if action == 'move':
        p = value.get('position');b = state['bounds']
        if not isinstance(p, list) or len(p) != 2 or not all(type(n) in (int, float) and math.isfinite(n) for n in p) or not (b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]):
            raise ValueError('invalid_position')
        clean['position'] = p
    if 'floor' in value:
        if action != 'garrison' or type(value['floor']) is not int or value['floor'] not in (1,2):raise ValueError('invalid_floor')
        clean['floor']=value['floor']
    if 'gun_id' in value:
        if action != 'man_at_gun' or not any(g['id']==value['gun_id'] and g['faction']==unit['faction'] for g in state.get('at_guns',[])):raise ValueError('invalid_gun')
        clean['gun_id']=value['gun_id']
    if action == 'attack' and not value.get('target_id'):
        raise ValueError('target_required')
    if 'target_id' in value:
        targets = [u for u in state['units'] if u['hp'] > 0 and u['faction'] != unit['faction'] and u['id'] == value['target_id']]
        if not targets:
            raise ValueError('invalid_target')
        if action == 'attack' and targets[0].get('kind')=='tank' and unit.get('weapon') not in ('rocket','cannon'):raise ValueError('anti_armor_required')
        if action == 'grenade' and math.dist(unit['position'], targets[0]['position']) > .65:
            raise ValueError('grenade_out_of_range')
        clean['target_id'] = value['target_id']
    return clean


class LMController:
    def __init__(self, state, config, client=None):
        self.state = state;self.config = config
        if config.get('provider')=='typesafe_jev':
            from jev_client import JevClient
            self.client=client if client is not None else JevClient(config)
        else:self.client = client if client is not None else ArkClient(config)
        self.provider=config.get('provider','volcengine_ark')
        self.origin='typesafe_jev' if self.provider=='typesafe_jev' else 'deepseek_lm'
        self.ready = bool(config['key'] and config['model'])
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=config['concurrency'], thread_name_prefix='deskfront-lm')
        self.lock = threading.Lock();self.stop_event = threading.Event()
        self.run_id = '';self.pending = {};self.units = {};self.next_due = {};self.memory = {};self.fallback_due = {}
        self.used = 0;self.metrics = {};self.history = [];self.backoff_until = 0
        self.status='idle';self.progress={};self.warning_keys={};self.flag_alerts={}
        self.call_log=CallLog(config.get('log_path', ':memory:' if client is not None else str(Path(__file__).resolve().parents[1]/'output/lm-calls.sqlite3')), config['key'],extra_secrets=[config.get('text_config',{}).get('key','')])
        self.call_receipts={}
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True);self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=2)
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _loop(self):
        while not self.stop_event.wait(.15):
            try:self.tick()
            except Exception:
                # Internal failures do not take down the real-time simulation or leak secrets.
                with self.lock:self.metrics['controller_errors'] = self.metrics.get('controller_errors', 0) + 1

    def snapshot(self):
        with self.lock:
            return copy.deepcopy({'status':self.status,'flag_alerts':self.flag_alerts,'configured': self.ready, 'provider': self.provider, 'display_name':'TypeSafe JEV' if self.provider=='typesafe_jev' else 'DeepSeek LLM', 'model': self.config['model'], 'interval_seconds': self.config['interval'], 'max_requests': self.config['max_requests'], 'used_requests': self.used, 'budget_remaining': max(0, self.config['max_requests'] - self.used), 'run_id': self.run_id, 'in_flight': len(self.pending), 'metrics': self.metrics, 'units': self.units, 'recent': self.history[-18:]})

    def _invoke(self, obs, call_id):
        started=time.monotonic()
        try:
            if isinstance(self.client, ArkClient) or hasattr(self.client,'build_payload'):
                result=self.client(obs, trace=lambda **data:self.call_log.update(call_id, **data))
            else:result=self.client(obs)
            value,usage=result
            self.call_log.update(call_id, phase='returned', parsed_response=value, usage=usage, latency_ms=round((time.monotonic()-started)*1000))
            return result
        except Exception as error:
            code=str(error) if isinstance(error,ProviderError) else 'provider_client_error'
            self.call_log.update(call_id, phase='error', error=code, latency_ms=round((time.monotonic()-started)*1000))
            raise

    def _record(self, entry):
        self.history.append(entry)
        self.history = self.history[-120:]
        self.state.record('lm_decision', entry)

    def _submit(self, s, u, decision, origin, now, seen_tick=None):
        entry = {'unit_id': u['id'], 'run_id': s['run_id'], 'tick': s['tick'], 'phase': 'waiting' if decision['action'] == 'wait' else 'submitted', 'origin': origin, 'flag_warning':flag_warning(s,u), **decision}
        if decision['action'] != 'wait':
            c = {k: v for k, v in decision.items() if k not in {'intent', 'reason'}}
            c.update(faction=u['faction'], unit_ids=[u['id']], run_id=s['run_id'], seen_tick=s['tick'] if seen_tick is None else seen_tick, control_epoch=s.get('control_epochs', {}).get(u['faction'], 0), flag_epoch=flag_epoch(s), intent=decision['intent'], reason=decision['reason'], decision_origin=origin)
            code, ack = self.state.submit(c, source='lm')
            if code == 202:entry['command_id'] = ack['id']
            else:entry.update(phase='rejected', error=ack.get('error', 'queue_rejected'))
        self.units[u['id']] = entry
        if origin==self.origin:
            counts=self.metrics.setdefault('unit_decisions', {});counts[u['id']]=counts.get(u['id'], 0)+1
            actions=self.metrics.setdefault('model_actions',{});actions[decision['action']]=actions.get(decision['action'],0)+1
        self.memory.setdefault(u['id'], []).append({k: entry[k] for k in ['action', 'intent', 'reason']})
        self.memory[u['id']] = self.memory[u['id']][-2:]
        self._record(entry)
        self.next_due[u['id']] = now + (min(1.0,self.config['interval']) if flag_warning(s,u).get('active') else self.config['interval'])

    def _fallback(self, s, u, reason, now):
        if now < self.fallback_due.get(u['id'], 0):return
        self.fallback_due[u['id']] = now + 6
        action = 'wait' if u.get('gun_id') or u.get('building_phase') or u.get('in_cover') or u.get('survival_reason') or u.get('order_mode') == 'self_preserve' else 'cover'
        warning=flag_warning(s,u)
        if warning.get('active'):
            action='leave_building' if u.get('building_phase') else 'leave_gun' if u.get('gun_id') else 'capture'
            if action not in u.get('available_actions',[]):action='wait'
            reason+='；夺旗告急，本地尝试反攻（不是模型决策）'
        self._submit(s, u, {'action': action, 'intent': 'capture' if warning.get('active') else 'survive', 'reason': reason}, 'local_fallback', now)
        self.units[u['id']]['phase'] = 'fallback'
        self.metrics['fallbacks'] = self.metrics.get('fallbacks', 0) + 1

    def tick(self):
        now = time.monotonic()
        # Lock order: state snapshot first; never hold State.lock while taking LM.lock.
        with self.state.lock:
            s = copy.deepcopy(self.state.state);age = now - self.state.updated;acks = copy.deepcopy(self.state.results)
        with self.lock:
            if not s or 'run_id' not in s:return
            if self.run_id != s['run_id']:
                self.run_id = s['run_id'];self.units = {};self.memory = {};self.next_due = {};self.fallback_due = {};self.used = 0;self.metrics = {};self.history = [];self.backoff_until = 0;self.progress={};self.warning_keys={}
            for command_id,call_id in list(self.call_receipts.items()):
                if command_id in acks:
                    ack=acks[command_id];self.call_log.update(call_id, receipt=ack, phase='executed' if ack['accepted'] else 'rejected');del self.call_receipts[command_id]
            live = {u['id']: u for u in s['units'] if u['hp'] > 0}
            active = {k: u for k, u in live.items() if s.get('control', {}).get(u['faction']) == 'lm' and u.get('combat_ready',True)}
            self.status=('unconfigured' if not self.ready else 'offline' if age>3 else 'finished' if s.get('winner') else 'idle' if not active else 'paused' if s.get('paused') else 'budget_exhausted' if self.used>=self.config['max_requests'] else 'backoff' if now<self.backoff_until else 'running')
            self.flag_alerts={} if s.get('winner') else copy.deepcopy(s.get('objective',{}).get('flag',{}).get('alerts',{}))
            if age<=3 and not s.get('paused') and not s.get('winner'):
                for uid,u in active.items():
                    warning=flag_warning(s,u)
                    seconds=warning.get('remaining_seconds',30)
                    band=5 if seconds<=5 else 10 if seconds<=10 else 15 if seconds<=15 else 30
                    key=(flag_epoch(s),warning.get('active',False),warning.get('contested',False),band)
                    if self.warning_keys.get(uid)!=key:
                        self.warning_keys[uid]=key
                        if warning.get('active'):
                            self.next_due[uid]=0;self.fallback_due[uid]=0
                            self.units.setdefault(uid,{'unit_id':uid}).update(flag_warning=warning,warning_received_tick=s['tick'])
                            self.metrics['flag_warnings']=self.metrics.get('flag_warnings',0)+1
            for uid, row in self.units.items():
                if uid not in live:row['phase'] = 'dead'
                elif uid not in active:row['phase'] = 'inactive'
                elif row.get('command_id') in acks and row.get('phase') == 'submitted':
                    ack = acks[row['command_id']];row['receipt'] = ack;row['phase'] = 'executing' if ack['accepted'] else 'rejected'
                    metric = 'accepted' if ack['accepted'] else 'rejected';self.metrics[metric] = self.metrics.get(metric, 0) + 1
            for uid, task in list(self.pending.items()):
                if not task['future'].done():continue
                del self.pending[uid]
                u = active.get(uid)
                if task.get('flag_epoch',0)!=flag_epoch(s) or task['run_id'] != s['run_id'] or u is None or age > 3 or s.get('paused') or s.get('winner') or task['epoch'] != s.get('control_epochs', {}).get(u['faction'], 0) or s['tick'] - task['tick'] > 300:
                    self.call_log.update(task['call_id'], phase='discarded', discard_reason='旗点归属、控制权、局次、单位存活或观察时效已变化，未执行返回')
                    self.metrics['discarded'] = self.metrics.get('discarded', 0) + 1
                    if u:
                        self.units[uid] = {'unit_id': uid, 'phase': 'stale', 'reason': '旗点归属、控制权、局次或观察已变化，丢弃旧回复'}
                        self.next_due[uid]=0
                    continue
                try:
                    value, usage = task['future'].result()
                    self.metrics.pop('last_error', None)  # A successful response clears a recovered provider warning.
                    self.metrics['responses'] = self.metrics.get('responses', 0) + 1
                    self.metrics['tokens'] = self.metrics.get('tokens', 0) + usage.get('total_tokens', 0)
                    latency = round((now - task['started']) * 1000)
                    self.metrics['latency_ms_total'] = self.metrics.get('latency_ms_total', 0) + latency
                    decision = validate_decision(value, s, u)
                    self._submit(s, u, decision, self.origin, now, task['tick'])
                    if usage.get('jev_evaluation'):self.units[uid]['jev_evaluation']=usage['jev_evaluation']
                    self.units[uid]['latency_ms'] = latency;self.units[uid]['usage'] = usage
                    entry=self.units[uid];entry['call_id']=task['call_id']
                    self.call_log.update(task['call_id'], phase='waiting' if decision['action']=='wait' else entry['phase'], decision=decision, command_id=entry.get('command_id'), error=entry.get('error'))
                    if entry.get('command_id'):self.call_receipts[entry['command_id']]=task['call_id']
                except (ProviderError, ValueError, TypeError, KeyError) as error:
                    code=str(error) if isinstance(error, ProviderError) else (str(error) if isinstance(error,ValueError) and str(error) in {'invalid_decision_fields','invalid_decision_action_or_intent','action_unavailable','invalid_posture','invalid_floor','invalid_gun','invalid_position','target_required','invalid_target','grenade_out_of_range','anti_armor_required','posture_required'} else 'invalid_or_unavailable_action')
                    self.call_log.update(task['call_id'], phase='error' if isinstance(error,ProviderError) else 'rejected', error=code)
                    self.metrics['last_error'] = code
                    counts=self.metrics.setdefault('error_codes',{});counts[code]=counts.get(code,0)+1
                    self.metrics['errors'] = self.metrics.get('errors', 0) + 1
                    if isinstance(error, ProviderError):self.backoff_until = now + min(30, 2 ** min(4, self.metrics['errors']))
                    self._fallback(s, u, '模型请求或动作校验失败，保持自保', now)
            if age > 3 or s.get('paused') or s.get('winner'):return
            for uid in sorted(active, key=lambda k: (not flag_warning(s,active[k]).get('active',False),self.next_due.get(k, 0))):
                u = active[uid]
                if uid in self.pending or now < self.next_due.get(uid, 0):continue
                row=self.units.get(uid, {})
                if row.get('phase')=='submitted' and row.get('command_id') not in acks:continue
                if not self.ready or self.used >= self.config['max_requests'] or now < self.backoff_until:
                    self._fallback(s, u, {'unconfigured':'LLM 未配置，使用本地自保','budget_exhausted':'LLM 本局预算已耗尽，模型已停止请求，使用本地自保','backoff':'LLM 请求暂时失败，退避期间使用本地自保'}.get(self.status,'LLM 暂不可用，使用本地自保'), now);continue
                if len(self.pending) >= self.config['concurrency']:break
                obs = observation(s, u, self.memory.get(uid, []))
                previous=self.progress.get(uid)
                if previous is None or math.dist(u['position'],previous['position'])>.04 or u.get('last_shot_at',-1)!=previous['shot']:
                    previous={'position':list(u['position']),'shot':u.get('last_shot_at',-1),'time':s['time']};self.progress[uid]=previous
                obs['progress']={'idle_seconds':round(max(0,s['time']-previous['time']),1),'last_action':row.get('action',''),'last_receipt':row.get('receipt',{}).get('message','')}

                payload=self.client.build_payload(obs) if hasattr(self.client,'build_payload') else build_payload(self.config,obs)
                call_id=self.call_log.start(unit_id=uid, faction=u['faction'], run_id=s['run_id'], tick=s['tick'], model=self.config['model'], request=payload, provider=self.provider)
                future = self.pool.submit(self._invoke, obs, call_id)
                self.pending[uid] = {'call_id':call_id, 'future': future, 'run_id': s['run_id'], 'tick': s['tick'], 'epoch': s.get('control_epochs', {}).get(u['faction'], 0), 'started': now, 'flag_epoch':flag_epoch(s)}
                self.units[uid] = {**self.units.get(uid, {}), 'unit_id': uid, 'phase': 'thinking', 'started_tick': s['tick']}
                self.next_due[uid] = now + (min(1.0,self.config['interval']) if flag_warning(s,u).get('active') else self.config['interval']);self.used += 1
                counts=self.metrics.setdefault('unit_calls', {});counts[uid]=counts.get(uid, 0)+1
