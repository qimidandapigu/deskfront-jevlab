"""World generation uses the existing SDK and configured Harness decision roles."""
import concurrent.futures
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


def run(args, game):
    if game.config.get('backend') not in ('jev', 'mock'):
        game.finish('error', 'Infinite mode requires JEV with the configured DeepSeek role, or mock')
        return
    sys.path.insert(0, str(Path(args.root) / 'tools'))
    import server
    from .stage import stage
    from .director import WorldDirector, MacroBridge, AXES, CATALOG
    output = Path(os.environ['QUICKPLAY_OUTPUT_DIR'])
    tank_showcase = bool(game.config.get('gameOptions', {}).get('secondStageTankShowcase'))
    # The current endless product contract always includes the second-stage
    # tank encounter.  A caller may still pass false for a regression fixture,
    # but an omitted option must resolve to the product default.
    tank_rule = bool(game.config.get('gameOptions', {}).get('secondStageTankRule', True))
    original_validate = server.validate_command
    from combat_command_validation import validate as validate_combat_command

    def validate(c, agent=False):
        if isinstance(c, dict) and c.get('action') == 'showcase_clear_opening' and not agent:
            if not tank_showcase:return 'showcase_not_enabled'
            if not isinstance(c.get('run_id'), str):return 'run_id_required'
            return None
        if isinstance(c, dict) and c.get('action') == 'grow_world' and not agent:
            h = c.get('hormones')
            if c.get('mission_kind','assault') not in ('assault','rescue'):return 'invalid_mission_kind'
            if c.get('defender_mix','balanced') not in ('balanced','rifle_screen','close_patrol'):return 'invalid_defender_mix'
            if c.get('support_type','infantry') not in ('infantry','rocket_team','tank'):return 'invalid_support_type'
            if c.get('option') not in CATALOG: return 'invalid_growth_option'
            if type(c.get('growth_revision')) is not int or c['growth_revision'] < 0: return 'invalid_growth_revision'
            if not isinstance(c.get('operation_id'), str) or not 1 <= len(c['operation_id']) <= 100: return 'invalid_operation_id'
            if not isinstance(h, dict) or set(h) != set(AXES) or any(type(v) not in (int,float) or not math.isfinite(v) or not 0 <= v <= 1 for v in h.values()): return 'invalid_hormones'
            if not isinstance(c.get('run_id'), str): return 'run_id_required'
            if 'build_operations' in c:
                from .assembly import compile_operations, validate as validate_assembly
                try:
                    if c.get('assembly_kind')=='region_graph_v1':
                        from .region_graph import validate_graph,compile_graph
                        result=validate_graph(c['build_operations'])
                        if result['ok'] and c.get('mission_kind')=='rescue':
                            from .fortress import apply as fortify
                            count=int(c.get('enemy_count',3))
                            result=validate_assembly(fortify(compile_graph(c['build_operations']),count))
                    else:result=validate_assembly(compile_operations(c['option'],c['build_operations']))
                    if not result['ok']:return 'invalid_assembly:'+result['reason']
                except (ValueError,TypeError,KeyError):return 'invalid_build_operations'
            return None
        return validate_combat_command(c, agent, original_validate)

    class OwnedState(server.State):
        def record(self, kind, data):
            with (output / 'engine.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(kind=kind, data=data), ensure_ascii=False) + '\n')

    server.validate_command = validate
    server.STATE = OwnedState()
    server.LM = None
    server.STUDIO = None
    harness_green = game.config.get('gameOptions', {}).get('greenController', 'harness') == 'harness'
    harness_red = game.config.get("gameOptions", {}).get("redController", "harness") == "harness"
    controllers = {}
    if harness_green or harness_red:
        from faction_state import FactionState
        from human_squad import HumanSquadController, SharedRequestBudget
        runtime = game.config.get('runtime', {})
        config = dict(provider='quickplay', key='quickplay-local', model=game.config['backend'],
                  base_url='https://api.typesafe.ai/v1', interval=3, concurrency=10,
                  # Keep valid squad orders longer. Meaningful plan, route,
                  # contact and failure events still wake the executor; this
                  # only removes periodic re-asks during the same task.
                  squad_interval=8.,
                  timeout=runtime.get('requestTimeoutMs',30000)/1000,
                  # Personal JEV reviews keep a valid action until a meaningful
                  # event wakes them; the engine still handles instant survival.
                  soldier_interval=8.,
                  commander_timeout=20.,
                  max_requests=game.config.get('gameOptions',{}).get('teamRequestLimit',runtime.get('maxRequests',100)),
                      spatial_path=str(output/'spatial.json'), log_path=str(output/'calls.sqlite3'))
        # Endless mode has two Harness controllers plus emotion requests. Use
        # one atomic allowance so both teams cannot spend the same global
        # runtime budget and discover the limit only after an overrun.
        shared_budget = SharedRequestBudget(config['max_requests'])
        config['opening_gate']=False
        for team,enabled in [('green',harness_green),('red',harness_red)]:
            if not enabled:continue
            team_config=dict(config, shared_request_budget=shared_budget,
                             log_path=str(output/('calls.sqlite3' if team=='green' else 'red-calls.sqlite3')))
            controllers[team]=HumanSquadController(FactionState(server.STATE,team),team_config,game,team)
            controllers[team].start()
        server.LM=controllers.get('green')
    director = WorldDirector(MacroBridge(server.STATE, game), game)
    http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
    threading.Thread(target=http.serve_forever, kwargs={'poll_interval': .1}, daemon=True).start()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    engine = None
    outcome, error = 'finished', None
    log = (output / 'godot.log').open('w', encoding='utf-8')
    try:
        root = stage(args.root, output / 'engine')
        env = dict(os.environ, DESKFRONT_URL='http://127.0.0.1:' + str(http.server_port),
                   DESKFRONT_INSTANCE_ID=game.session_id, DESKFRONT_HEADLESS_BRIDGE='1',
                   HARNESS_RECORDING_COUNTDOWN='1', HARNESS_HUMAN_SQUAD='1' if controllers else '0', HARNESS_GREEN_CONTROL='lm' if harness_green else 'game_ai', HARNESS_RED_CONTROL='lm' if harness_red else 'game_ai', HARNESS_SPATIAL_OUTPUT=str(output/'spatial.json'), HARNESS_SECOND_STAGE_TANK_SHOWCASE='1' if tank_showcase else '0', HARNESS_SECOND_STAGE_TANK_RULE='1' if tank_rule else '0')
        command = [args.godot] + (['--headless'] if game.config.get('variant', '').endswith('headless') else [])
        command += ['--path', str(root), '--', '--paused', '--infinite-world', '--map=0', '--battle']
        engine = subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=log,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        initialized, began, future, next_at = False, time.monotonic(), None, 0
        showcase_cleared = showcase_paused = False
        showcase_clear_id = showcase_pause_id = None
        analysis_revision = None
        analysis_future = None
        seen = {}
        outcome = 'running'
        while not game.stopped.wait(.25):
            if engine.poll() is not None:
                # Godot exits cleanly after the finite/infinite mission has
                # published its terminal snapshot.  Preserve that result;
                # only a non-zero exit or an incomplete mission is an error.
                with server.STATE.lock:
                    exited_state = copy.deepcopy(server.STATE.state)
                exited_world = exited_state.get('world_growth', {})
                exited_mission = exited_world.get('mission', {}) if isinstance(exited_world, dict) else {}
                completed = (exited_mission.get('status') == 'completed'
                             or bool(exited_state.get('winner')))
                failed = exited_mission.get('status') == 'failed'
                if engine.returncode == 0 and completed:
                    outcome = 'finished'
                    break
                if engine.returncode == 0 and failed:
                    outcome = 'expedition-failed'
                    break
                raise RuntimeError('Godot exited: ' + str(engine.returncode))
            with server.STATE.lock:
                state = copy.deepcopy(server.STATE.state)
                # A visible Godot window can briefly stop publishing snapshots
                # during a slow render or navigation step. Do not end an otherwise
                # live battle after one missed three-second heartbeat.
                live = bool(server.STATE.updated) and time.monotonic() - server.STATE.updated < 12
                instance = server.STATE.instance_id
            if not live:
                if initialized or time.monotonic() - began > 60: raise RuntimeError('No live Godot state')
                continue
            if instance != game.session_id: raise RuntimeError('Godot ownership changed')
            if not initialized:
                for faction in ('green', 'red', 'blue'):
                    mode = 'lm' if faction in controllers else 'game_ai'
                    server.STATE.submit(dict(action='control', faction=faction, mode=mode, instance_id=instance))
                server.STATE.submit(dict(action='pause', value=False, instance_id=instance))
                initialized = True
                next_at = time.monotonic() + 20
            director.observe(state)
            world = state.get('world_growth', {})
            if showcase_clear_id and showcase_clear_id in server.STATE.results:
                result = server.STATE.results[showcase_clear_id]
                showcase_cleared = bool(result.get('accepted'))
                if not showcase_cleared:game.record(dict(type='showcase-opening-skip-failed', receipt=result))
                showcase_clear_id = None
            if (tank_showcase and not showcase_cleared and not showcase_clear_id and world.get('revision') == 1
                    and world.get('phase') == 'encounter' and not state.get('paused')):
                code, receipt = server.STATE.submit(dict(action='showcase_clear_opening',
                    run_id=state['run_id'], instance_id=instance))
                if code == 202:
                    showcase_clear_id = receipt['id']
                    game.record(dict(type='showcase-opening-skip-submitted', receipt=receipt))
            if state.get('paused') and world.get('revision') == 2:showcase_paused = True
            if (tank_showcase and showcase_cleared and not showcase_paused and not showcase_pause_id
                    and world.get('revision') == 2 and world.get('phase') == 'encounter'
                    and not state.get('paused')):
                code, receipt = server.STATE.submit(dict(action='pause', value=True,
                    run_id=state['run_id'], instance_id=instance))
                if code == 202:
                    showcase_pause_id = receipt['id']
                    game.record(dict(type='showcase-second-stage-pause',
                        support_status=world.get('mission', {}).get('support_status'), receipt=receipt))
            if showcase_pause_id and showcase_pause_id in server.STATE.results:
                if server.STATE.results[showcase_pause_id].get('accepted'):
                    showcase_paused = True
                else:
                    game.record(dict(type='showcase-second-stage-pause-failed', receipt=server.STATE.results[showcase_pause_id]))
                showcase_pause_id = None
            while not game.inputs.empty():
                message = game.inputs.get_nowait()
                body = message['body']
                # Growth authority belongs to the two-role controller, not arbitrary UI commands.
                if body.get('action') not in ('pause',):
                    game.record(dict(type='input-rejected', reason='unsupported-infinite-action'))
                    continue
                code, receipt = server.STATE.submit(dict(body, instance_id=instance, run_id=state['run_id']))
                game.record(dict(type='input-submitted', status=code, receipt=receipt))
            if future and future.done():
                try: future.result()
                except Exception as exc: game.record(dict(type='world-error', error=str(exc)))
                future = None
            if analysis_future and analysis_future.done():
                try: analysis_future.result()
                except Exception as exc: game.record(dict(type='world-analysis-error', error=str(exc)))
                analysis_future = None

            director.commit_prepared()
            ds = director.snapshot()
            # Read-only spectator data, separate from game commands and observations.
            sidebar = dict(run_id=state.get('run_id'), teams={})
            for team, controller in controllers.items():
                with controller.lock:
                    if controller.world.get('run_id') == state.get('run_id'):
                        plan = controller.plan or {}
                        sidebar['teams'][team] = dict(commander=str(plan.get('objective', '')),
                                                     goal=copy.deepcopy(plan.get('position') or []),
                                                     region_id=str(plan.get('region_id', '')))
            sidebar_tmp = root / 'battle-sidebar.tmp'
            sidebar_tmp.write_text(json.dumps(sidebar, ensure_ascii=False), encoding='utf-8')
            try:
                sidebar_tmp.replace(root / 'battle-sidebar.json')
            except PermissionError:
                pass  # The renderer may briefly hold the file; retry next tick.
            ready = state.get('world_growth', {}).get('enabled') and state.get('world_growth', {}).get('phase') in ('ready', 'encounter') and state.get('world_growth', {}).get('mission', {}).get('status') != 'failed' and not state.get('paused') and not state.get('winner')
            if ready and state['world_growth']['phase']=='encounter' and analysis_revision!=state['world_growth'].get('revision'):
                analysis_revision=state['world_growth'].get('revision')
                next_at=time.monotonic()+5
            if ready and state['world_growth']['phase']=='encounter' and not analysis_future and time.monotonic()>=next_at:
                next_at = time.monotonic() + 20
                analysis_future = pool.submit(director.analyze)
            if (not future and ready and state['world_growth']['phase']=='ready'
                    and not ds.get('prepared') and not ds.get('submission_pending')
                    and ds['prepare_retry_in']<=0 and ds['requests_used']+3<=ds['request_limit']):
                future = pool.submit(director.step, dict(run_id=state['run_id'], instance_id=instance, prepare=True))
            game.publish(state, dict(engineLive=live, enginePid=engine.pid, hostPid=os.getpid(), worldDirector=ds,
                                    model=game.config.get('backend'), engineRoot=str(root),
                                    greenController='harness' if harness_green else 'local',
                                    redController='harness' if harness_red else 'local',
                                    redLm=controllers['red'].snapshot() if 'red' in controllers else None,
                                    lm=server.LM.snapshot() if server.LM else None))
            for team,controller in controllers.items():
                for item in controller.call_log.list()['items']:
                    key=(team,item['id'])
                    stamp=item.get('updated_at',item['id'])
                    if seen.get(key) == stamp:continue
                    detail=controller.call_log.get(item['id'])
                    detail['controller']=team+'-harness'
                    game.record(detail)
                    seen[key]=stamp
            if controllers and all(c.budget_exhausted for c in controllers.values()):
                outcome='request-budget';break
            if state.get('world_growth', {}).get('mission', {}).get('status') == 'failed':
                outcome = 'expedition-failed'
                game.record(dict(type='expedition-failed', mission=state['world_growth']['mission']))
                break
            if state.get('winner'):
                outcome = 'finished'
                break
    except Exception as exc:
        outcome, error = 'error', str(exc)
    finally:
        if engine and engine.poll() is None:
            engine.terminate()
            try: engine.wait(timeout=3)
            except subprocess.TimeoutExpired: engine.kill(); engine.wait()
        if not game.stopped.is_set(): game.finish(outcome, error)
        for controller in controllers.values():controller.close()
        pool.shutdown(wait=True, cancel_futures=True)
        http.shutdown(); http.server_close(); log.close()
