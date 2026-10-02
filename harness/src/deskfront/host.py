"""Deskfront 的 Quickplay SDK 适配器；模型密钥由 Harness 管理。"""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'sdk/python'))
from quickplay import Game

parser = argparse.ArgumentParser()
parser.add_argument('--root', required=True)
parser.add_argument('--godot', required=True)
args = parser.parse_args()
game = Game()
if game.config.get('variant', '').startswith('infinite'):
    from world.host import run
    run(args, game)
    raise SystemExit(0)
sys.path.insert(0, str(Path(args.root) / 'tools'))
import server
from lm_controller import LMController, ProviderError, load_config
from jev_client import JevClient, checked_choice
from session_result import controlled_team_elimination, engine_exit_outcome

output = Path(os.environ['QUICKPLAY_OUTPUT_DIR'])
runtime = game.config.get('runtime', {})
model = game.config.get('backend', 'model')
config = dict(provider='quickplay', key='quickplay-local', model=model,
              base_url='https://api.typesafe.ai/v1', interval=3,
              timeout=runtime.get('requestTimeoutMs', 10000) / 1000,
              commander_timeout=20.,
              # Personal JEV lanes own these timers independently; the
              # soldier agent adds a stable per-unit phase to avoid a squad
              # wide start/stop pulse.
              soldier_interval=5., soldier_cooldown_s=1., soldier_concurrency=4,
              max_requests=runtime.get('maxRequests', 100), concurrency=10,
              log_path=str(output / 'calls.sqlite3'))


class SharedClient:
    def __init__(self):
        self.builder = JevClient(config)

    def build_payload(self, obs):
        return self.builder.build_payload(obs)

    def __call__(self, obs, trace=None):
        payload = self.build_payload(obs)
        try:
            data = game.ask(payload['state'], payload['questions'])
            answers = data['answers']
            selected = checked_choice(answers['tactic'], payload['state']['command_candidates'])
            decision = copy.deepcopy(payload['state']['command_candidates'][selected])
            if 'posture' in payload['questions']:
                posture = checked_choice(answers['posture'], payload['questions']['posture']['criteria'])
                if decision['action'] != 'wait':
                    decision['posture'] = posture
            decision['reason'] = 'Quickplay ' + model + ': ' + selected
            usage = data.get('usage') or {}
            result_usage = {target: usage[key] for key, target in [('promptTokens', 'prompt_tokens'),
                            ('completionTokens', 'completion_tokens'), ('totalTokens', 'total_tokens')] if key in usage}
            result_usage['usage_complete'] = data.get('usageComplete', False)
            if trace:
                trace(provider_response=data, quickplay_request_id=data['requestId'], resolved_model=data.get('resolvedModel'))
            return decision, result_usage
        except Exception as error:
            raise ProviderError('quickplay_request_failed') from error


class OwnedState(server.State):
    def record(self, kind, data):
        with (output / 'engine.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(kind=kind, data=data), ensure_ascii=False) + '\n')


class SharedController(LMController):
    def snapshot(self):
        return dict(super().snapshot(), provider='quickplay', display_name=model)


server.STATE = OwnedState()
is_duel = game.config.get('variant', '').startswith('duel')
coordinated = game.config.get('variant', '').startswith('duel-tactics')
options = game.config.get('gameOptions', {})
human_squad = game.config.get('variant') in ('duel', 'duel-headless') and options.get('behavior', 'human_squad') == 'human_squad'
opponent = options.get('opponent', 'harness' if human_squad else 'game_ai')
if opponent == 'harness' and not human_squad:opponent = 'game_ai'
dual_harness = human_squad and opponent == 'harness'
native_rival = opponent == 'native_jev'
model_team = options.get('modelFaction', 'green')
if native_rival and not is_duel:
    raise ValueError('native_jev opponent requires a duel variant')
from faction_state import FactionState
if human_squad:
    if model not in ('jev', 'mock'):raise ValueError('Human squad requires Jev with DeepSeek commander, or explicit mock rehearsal')
    config['spatial_path'] = str(output / 'spatial.json')
    config['opening_release_path'] = str(output / 'opening-release.json')
    config['opening_gate'] = True
    from human_squad import HumanSquadController, SharedRequestBudget
    if dual_harness:config['shared_request_budget'] = SharedRequestBudget(config['max_requests'])
    server.LM = HumanSquadController(FactionState(server.STATE, model_team), config, game, model_team)
elif coordinated:
    config['spatial_path'] = str(output / 'spatial.json')
    config['validation'] = options.get('tacticalValidation') == 'fixed'
    if config['validation'] and model != 'mock':raise ValueError('Fixed validation requires mock backend; never label scripted control as model play')
    config['tactical_map'] = game.config.get('variant') in ('duel-tactics-routes', 'duel-tactics-routes-headless')
    if model not in ('jev', 'mock'):raise ValueError('Coordinated tactics requires Jev (with DeepSeek commander) or mock rehearsal')
    from tactics import CoordinatedController
    server.LM = CoordinatedController(FactionState(server.STATE, model_team), config, game, model_team)
else:
    server.LM = SharedController(FactionState(server.STATE, model_team) if native_rival else server.STATE, config, client=SharedClient())
    server.LM.origin = 'quickplay'
opponent_lm = HumanSquadController(FactionState(server.STATE, 'red' if model_team == 'green' else 'green'), config, game, 'red' if model_team == 'green' else 'green') if dual_harness else None

def harness_sides():
    return {c.team: c.snapshot() for c in ([server.LM, opponent_lm] if opponent_lm else [server.LM])} if human_squad else {}

native_lm = None
if native_rival:
    native_config = load_config(Path(args.root) / '.env')
    if native_config.get('provider') != 'typesafe_jev' or not native_config.get('key'):
        raise ValueError('Native JEV is not configured')
    native_config.update(interval=config['interval'], timeout=config['timeout'], concurrency=config['concurrency'],
                         max_requests=config['max_requests'], log_path=str(output / 'native-calls.sqlite3'))
    native_lm = LMController(FactionState(server.STATE, 'red' if model_team == 'green' else 'green'), native_config)
server.STUDIO = None
http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
threading.Thread(target=http.serve_forever, kwargs={'poll_interval': .1}, daemon=True).start()
url = 'http://127.0.0.1:' + str(http.server_port)
server.LM.start()
if opponent_lm:opponent_lm.start()
if native_lm:native_lm.start()
engine = None
outcome, failure = 'finished', None
engine_log = (output / 'godot.log').open('w', encoding='utf-8')
if is_duel:
    from duel import DuelSetup
    route_map = game.config.get('variant') in ('duel-tactics-routes', 'duel-tactics-routes-headless')
    if route_map and model_team != 'green':raise ValueError('Route showcase currently uses green attackers')
    duel_setup = DuelSetup(server.STATE, game.session_id, model_team, opponent, game.config.get('variant') in ('duel-tactics-3v5', 'duel-tactics-routes', 'duel-tactics-routes-headless'), route_map, dense_cover=human_squad)


def record_elimination(state, result, engine_live):
    """End this Harness session without inventing a native game winner."""
    game.publish(state, dict(engineLive=engine_live, enginePid=engine.pid if engine else None,
                             hostPid=os.getpid(), dashboardUrl=url + '/?native=1', model=model,
                             battleResult=result, lm=server.LM.snapshot(),
                             nativeLM=native_lm.snapshot() if native_lm else None, harnessSides=harness_sides()))
    game.record(dict(type='battle-result', **result))
    (output / 'battle-result.json').write_text(json.dumps(dict(
        state=state, harness=server.LM.snapshot(),
        native=native_lm.snapshot() if native_lm else None, harnessSides=harness_sides(),
        modelFaction=model_team, inferredResult=result), ensure_ascii=False, indent=2),
        encoding='utf-8')


observed_controlled_ids = set()
try:
    env = dict(os.environ, DESKFRONT_URL=url, DESKFRONT_INSTANCE_ID=game.session_id, DESKFRONT_HEADLESS_BRIDGE='1')
    command = [args.godot] + (['--headless'] if game.config.get('variant', '').endswith('headless') else []) + ['--path', args.root, '--script', str(Path(__file__).with_name('commentary_launch.gd')), '--', '--paused']
    if human_squad:
        env['HARNESS_HUMAN_SQUAD'] = '1'
        env['HARNESS_SPATIAL_OUTPUT'] = str(output / 'spatial.json')
        env['HARNESS_OPENING_GATE'] = str(output / 'opening-release.json')
        command = [args.godot] + (['--headless'] if game.config.get('variant', '').endswith('headless') else []) + ['--path', args.root, '--script', str(Path(__file__).with_name('human_duel.gd')), '--', '--paused']
    if game.config.get('variant') in ('duel-tactics-3v5', 'duel-tactics-routes', 'duel-tactics-routes-headless'):
        env['HARNESS_EXTRA_TEAM'] = 'red' if model_team == 'green' else 'green'
        if route_map:
            from tactical_level import ROUTES
            env['HARNESS_TACTICAL_MAP'] = '1'
            env['HARNESS_ROUTES_JSON'] = json.dumps(ROUTES)
            env['HARNESS_SPATIAL_OUTPUT'] = str(output / 'spatial.json')
            if model!='mock' and game.config.get('mode')!='human':env['HARNESS_OPENING_GATE']=str(output/'opening-release.json')
        command = [args.godot] + (['--headless'] if game.config.get('variant', '').endswith('headless') else []) + ['--path', args.root, '--script', str(Path(__file__).with_name('three_vs_five.gd')), '--', '--paused']
    command[1:1] = ['--log-file', str(output / 'godot-engine.log')]
    engine = subprocess.Popen(command, cwd=args.root, env=env, stdout=engine_log, stderr=engine_log,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    initialized, began, seen = False, time.monotonic(), {}
    opening_last_count=None
    opening_ready_at=None;opening_finished='HARNESS_OPENING_GATE' not in env
    opening_started=time.monotonic()
    while not game.stopped.wait(.25):
        if engine.poll() is not None:
            with server.STATE.lock:
                last_state=copy.deepcopy(server.STATE.state)
                last_instance=server.STATE.instance_id
            exit_result=engine_exit_outcome(last_state,model_team,engine.returncode,
                duel_ready=is_duel and initialized and opening_finished and last_instance==game.session_id,
                expected_unit_ids=observed_controlled_ids or None)
            if exit_result['outcome']=='lost':
                outcome='lost'
                record_elimination(last_state,exit_result,False)
                break
            raise RuntimeError('Godot exited: ' + str(engine.returncode))
        with server.STATE.lock:
            state = copy.deepcopy(server.STATE.state)
            live = bool(server.STATE.updated) and time.monotonic() - server.STATE.updated < 3
            instance = server.STATE.instance_id
        if not live:
            if (initialized and (not dual_harness or time.monotonic() - server.STATE.updated > 10)) or time.monotonic() - began > 60 and not initialized:
                raise RuntimeError('No live Godot state')
            continue
        if instance != game.session_id:
            raise RuntimeError('Godot ownership changed')
        if is_duel and opening_finished and (state.get('demo') or {}).get('phase')=='battle':
            observed_controlled_ids.update(u['id'] for u in state.get('units',[])
                if u.get('faction')==model_team and u.get('deployment_phase')=='active'
                and isinstance(u.get('id'),str))
        if not initialized:
            if is_duel:
                game.publish(state, dict(engineLive=live, enginePid=engine.pid, hostPid=os.getpid(), dashboardUrl=url + '/?native=1', setup='1v1', model=model))
                if not duel_setup.tick(state):
                    continue
            initialized = True
            if is_duel:
                # DuelSetup has just validated the full active deployment.
                observed_controlled_ids.update(u['id'] for u in state.get('units',[])
                    if u.get('faction')==model_team and u.get('deployment_phase')=='active'
                    and isinstance(u.get('id'),str))
            if game.config.get('mode') == 'human' and not is_duel:
                server.STATE.submit(dict(action='control', mode='player', faction='green', instance_id=game.session_id))
            if not is_duel:
                server.STATE.submit(dict(action='pause', value=False, instance_id=game.session_id))
        if not opening_finished and human_squad:
            control = server.LM.snapshot()
            if all(c.get('run_accepted_orders', 0) > 0 for c in harness_sides().values()) and opening_ready_at is None:
                opening_ready_at = time.monotonic()
            remaining = max(0, 3-int(time.monotonic()-opening_ready_at)) if opening_ready_at is not None else None
            phase = 'countdown' if remaining is not None else 'planning'
            reason = '各模型小队的首个意图已获引擎接受' if remaining is not None else '双方暂停，等待 DeepSeek 目标区域与 JEV 小队意图'
            game.publish(state, dict(engineLive=live,enginePid=engine.pid,hostPid=os.getpid(),dashboardUrl=url+'/?native=1',model=model,
                                    opening=dict(phase=phase,reason=reason,remaining=remaining),lm=control,harnessSides=harness_sides()))
            if time.monotonic()-opening_started > 120:
                raise RuntimeError('拟人小队开场超过120秒：'+str(control.get('error') or reason))
            if server.LM.budget_exhausted or (opponent_lm and opponent_lm.budget_exhausted):outcome='request-budget';break
            if server.LM.fatal_error or (opponent_lm and opponent_lm.fatal_error):raise RuntimeError(server.LM.fatal_error or opponent_lm.fatal_error)
            if remaining == 0:
                temporary=output/'opening-release.tmp'
                temporary.write_text(json.dumps(dict(run_id=state['run_id'])),encoding='utf-8')
                temporary.replace(output/'opening-release.json')
                opening_finished=True
                game.record(dict(type='opening-released',run_id=state['run_id'],game_time=state['time'],countdown_seconds=3))
            continue
        if not opening_finished:
            # Actual engine stays paused for both teams; only the planner receives a planning view.
            server.LM.coordination.update(dict(state,paused=False,spatial_clock_paused=True),{})
            plan=server.LM.coordination.snapshot()
            if plan['plan'] and opening_ready_at is None:opening_ready_at=time.monotonic()
            remaining=max(0,3-int(time.monotonic()-opening_ready_at)) if opening_ready_at is not None else None
            phase='countdown' if remaining is not None else 'planning' if plan['pending'] else 'retry' if plan['error'] else 'spatial'
            elapsed=int(time.monotonic()-opening_started)
            reason={'countdown':'开战倒计时','planning':'等待指挥计划','retry':'指挥请求或计划校验失败，等待重试','spatial':'等待有效空间查询'}[phase]
            if phase in ('planning','retry','spatial'):reason+=f'（{elapsed}/90秒）'
            status_key=(phase,remaining,elapsed if phase in ('planning','retry','spatial') else None)
            if status_key!=opening_last_count:
                opening_last_count=status_key
                status_tmp=output/'opening-status.tmp'
                status_tmp.write_text(json.dumps(dict(run_id=state['run_id'],remaining=remaining if remaining is not None else -1,reason=reason)),encoding='utf-8')
                status_tmp.replace(output/'opening-release.json.status')
                game.record(dict(type='opening-status',phase=phase,reason=reason))
            game.publish(state,dict(engineLive=live,enginePid=engine.pid,hostPid=os.getpid(),dashboardUrl=url+'/?native=1',model=model,setup='opening',opening=dict(phase=phase,reason=reason,remaining=remaining),lm=server.LM.snapshot()))
            if server.LM.coordination.budget_exhausted:outcome='request-budget';break
            if time.monotonic()-opening_started>90:raise RuntimeError('开场准备超过90秒：'+reason+'；双方保持暂停，结束本局')
            if remaining==0:
                temporary=output/'opening-release.tmp'
                temporary.write_text(json.dumps(dict(run_id=state['run_id'])),encoding='utf-8')
                temporary.replace(output/'opening-release.json')
                opening_finished=True
                game.record(dict(type='opening-released',run_id=state['run_id'],game_time=state['time'],countdown_seconds=3))
            continue
        while not game.inputs.empty():
            message = game.inputs.get_nowait()
            body = dict(message['body'], instance_id=game.session_id, run_id=state['run_id'])
            status, result = server.STATE.submit(body)
            game.record(dict(type='command-submitted', http_status=status, result=result))
        side_snapshots = harness_sides()
        primary_snapshot = side_snapshots[server.LM.team] if human_squad else server.LM.snapshot()
        game.publish(state, dict(engineLive=live, enginePid=engine.pid, hostPid=os.getpid(), dashboardUrl=url + '/?native=1', model=model,
                                 lm=primary_snapshot, nativeLM=native_lm.snapshot() if native_lm else None, harnessSides=side_snapshots))
        if is_duel and state.get('winner')=='':
            elimination=controlled_team_elimination(state,model_team,observed_controlled_ids or None)
            if elimination:
                outcome='lost'
                record_elimination(state,elimination,live)
                break
        if dual_harness and state.get('winner')=='':
            rival_team = opponent_lm.team
            rival_ids = {u['id'] for u in state.get('units', []) if u.get('faction')==rival_team and u.get('deployment_phase')=='active'}
            eliminated = controlled_team_elimination(state, rival_team, rival_ids or None)
            if eliminated:
                outcome='won'
                eliminated.update(outcome='won', reason='opponent_squad_eliminated', model_faction=model_team)
                record_elimination(state, eliminated, live)
                break
        if coordinated and server.LM.coordination.budget_exhausted:
            outcome = 'request-budget'
            break
        if coordinated and server.LM.team_executor.fatal_error:
            outcome,failure='error',server.LM.team_executor.fatal_error
            break
        if human_squad and (server.LM.budget_exhausted or (opponent_lm and opponent_lm.budget_exhausted)):
            outcome = 'request-budget'
            break
        if human_squad and (server.LM.fatal_error or (opponent_lm and opponent_lm.fatal_error)):
            outcome, failure = 'error', server.LM.fatal_error or opponent_lm.fatal_error
            break
        for side, controller in [('harness', server.LM)] + ([('native', native_lm)] if native_lm else []):
          if human_squad and side == 'harness':continue
          for item in controller.call_log.list()['items']:
            if seen.get((side, item['id'])) == item['updated_at']:
                continue
            detail = controller.call_log.get(item['id'])
            detail['controller'] = side
            receipt = detail.get('receipt', {})
            raw = detail.get('provider_response', {}).get('answers', {})
            accepted = receipt.get('accepted')
            resolution=getattr(controller,'execution_records',{}).get((detail.get('unit_id'),detail.get('tick')))
            detail['execution'] = dict(schema='quickplay-execution-v1', id=detail.get('quickplay_request_id'),
                                       status='applied' if accepted is True else 'rejected' if accepted is False else resolution['status'] if resolution else 'pending',
                                       rawAnswers=raw, executedAnswers=raw if accepted is True else None,
                                       action=resolution['actual'] if resolution else detail.get('decision') if accepted is True else None,
                                       resolution=resolution,receipt=receipt or None)
            if detail.get('unit_id')=='squad':
                detail['execution']=dict(schema='quickplay-team-execution-v1',id=detail.get('quickplay_request_id'),status=detail['phase'],units=detail.get('unit_executions',{}),rawAnswers=raw)
            game.record(detail)
            seen[(side, item['id'])] = item['updated_at']
        if state.get('winner'):
            (output / 'battle-result.json').write_text(json.dumps(dict(state=state, harness=server.LM.snapshot(),
                native=native_lm.snapshot() if native_lm else None, harnessSides=harness_sides(), modelFaction=model_team), ensure_ascii=False, indent=2), encoding='utf-8')
            break
except Exception as error:
    outcome, failure = 'error', str(error)
finally:
    if engine and engine.poll() is None:
        engine.terminate()
        try:
            engine.wait(timeout=3)
        except subprocess.TimeoutExpired:
            engine.kill()
            engine.wait()
    # Stopping the SDK releases model waiters before controller shutdown.
    if not game.stopped.is_set():
        game.finish(outcome, failure)
    server.LM.close()
    if opponent_lm:opponent_lm.close()
    if native_lm:native_lm.close()
    http.shutdown()
    http.server_close()
    engine_log.close()
