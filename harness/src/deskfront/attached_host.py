"""Existing Harness over a released binary. No native source/staging imports."""
import json
import os
from pathlib import Path
import time

from deskfront_bridge import DeskfrontClient
from attached_state import AttachedState
from human_squad import HumanSquadController, SharedRequestBudget
from story_prompt import with_story_prompts
from level_provider import load_factory
from director_display import DirectorDisplay
from command_presentation import CommandPresentation
from attached_display import AttachedDisplayCache
from lease_keepalive import LeaseKeepalive
from battle_map_recording import BattleMapRecorder


def run(game):
    game = with_story_prompts(game)
    options, runtime = game.config.get('gameOptions', {}), game.config.get('runtime', {})
    connection = options.get('connectionFile') or str(Path(os.environ['LOCALAPPDATA']) / 'Deskfront/connection.json')
    output = Path(os.environ['QUICKPLAY_OUTPUT_DIR'])
    client = None
    states, controllers, leases, keepalives = {}, {}, {}, {}
    provider = None
    world_state = None
    outcome, error = 'finished', None
    try:
        deadline = time.monotonic() + 10
        while True:
            try:client = DeskfrontClient(connection);break
            except (OSError, ValueError) as exc:
                if time.monotonic() >= deadline or str(exc) not in ('connection_not_running',) and not isinstance(exc, OSError):raise
                if game.stopped.wait(.1):return
        generate = bool(options.get('attachedWorldGeneration', False))
        factory = load_factory(options.get('levelGeneratorModule')) if generate else None
        budget = SharedRequestBudget(options.get('teamRequestLimit', runtime.get('maxRequests', 100)))
        for team in ('green', 'red'):
            if options.get(team + 'Controller', 'harness') != 'harness':continue
            row = client.observe(team)
            leases[team] = client.acquire(row['context'], team, game.session_id, world=generate and team == 'green')
            keepalives[team] = LeaseKeepalive(client, team, leases[team], record=game.record)
            state = AttachedState(client, team, leases[team])
            state.update(client.observe(team))
            states[team] = state
            config = dict(provider='quickplay', key='quickplay-local', model=game.config['backend'],
                base_url='https://api.typesafe.ai/v1', interval=3, concurrency=10,
                squad_interval=8., soldier_interval=8., commander_timeout=20.,
                timeout=runtime.get('requestTimeoutMs', 30000) / 1000,
                max_requests=budget.limit, shared_request_budget=budget, opening_gate=False,
                control_mode='agent', candidate_query=state.candidates,
                spatial_path=None, log_path=str(output / (team + '-calls.sqlite3')))
            controllers[team] = HumanSquadController(state, config, game, team)
            controllers[team].start()
        if generate:
            if 'green' not in leases:raise ValueError('world_generation_requires_green_lease')
            world_state = AttachedState(client, 'green', leases['green'])
            provider = factory(world_state, game)
            if not all(callable(getattr(provider, method, None)) for method in ('tick', 'close')):
                raise ValueError('level_generator_invalid_provider')
        game.record(dict(type='release-harness-attached', protocol='deskfront-harness/v1',
            buildVersion=client.info['buildVersion'], engineInstance=client.instance_id,
            enginePid=client.pid, controllers=list(controllers), worldGeneration=bool(provider),
            levelSource='private-ai' if provider else 'game-local',
            sourceRuntime=False))
        seen = {}
        displayed = {}
        command_presentation = CommandPresentation()
        display_cache = AttachedDisplayCache()
        director_display = DirectorDisplay()
        battle_map_recorder = BattleMapRecorder(game.record)
        ds = None
        while not game.stopped.wait(.25):
            for team, state in states.items():
                row = client.observe(team)
                if row['context']['runId'] != leases[team]['context']['runId']:
                    # F5 creates a new battle in the player's process. The old
                    # native lease expires with that run; acquire a new one,
                    # keeping this external session and shared request budget.
                    leases[team] = client.acquire(row['context'], team, game.session_id,
                                                  world=generate and team == 'green')
                    keepalives[team].replace(leases[team])
                    state.lease = leases[team]
                    display_cache.clear(team)
                    row = client.observe(team)
                    game.record(dict(type='release-harness-reattached', team=team,
                        runId=row['context']['runId'], epoch=leases[team]['epoch']))
                state.update(row)
                keepalives[team].tick(row['context'], row['state'])
                leases[team] = keepalives[team].lease
                state.lease = leases[team]
            public = client.observe(spectator=True)
            current = public['state']
            if leases and any(public['context']['runId'] != lease['context']['runId'] for lease in leases.values()):
                continue  # A restart between the two team reads; reconcile next poll.
            battle_map_recorder.sample(current)
            if world_state:world_state.lease = leases['green']
            # A defeated encounter is terminal until the player restarts. Keep
            # the leases/UI alive, but do not prepare more levels while frozen.
            awaiting_restart = current.get('world_growth', {}).get('mission', {}).get('status') == 'failed'
            if not awaiting_restart:
                ds = provider.tick(public) if provider else None
            if provider and 'green' in states:
                director_display.tick(ds, current, states['green'], game)
            while not game.inputs.empty():
                message = game.inputs.get_nowait()['body']
                if message.get('action') == 'pause' and states:
                    next(iter(states.values())).submit(dict(message, run_id=current['run_id']))
            awaiting_restart = current.get('world_growth', {}).get('mission', {}).get('status') == 'failed'
            displays = {team: display_cache.sample(team, controller, current, command_presentation)
                        for team, controller in controllers.items()}
            game.publish(current, dict(engineLive=True, enginePid=client.pid, hostPid=os.getpid(),
                engineRoot=None, attached=True, engineInstance=client.instance_id,
                awaitingRestart=awaiting_restart,
                sdkUrl=client.url, worldDirector=ds, levelSource='private-ai' if provider else 'game-local', model=game.config['backend'],
                greenController='harness' if 'green' in controllers else 'local',
                redController='harness' if 'red' in controllers else 'local',
                controllerDisplaySamples={team: row['sample'] for team, row in displays.items()},
                lm=displays.get('green', {}).get('snapshot'),
                redLm=displays.get('red', {}).get('snapshot')))
            for team, controller in controllers.items():
                sidebar = displays[team]['sidebar']
                signature = json.dumps(sidebar, sort_keys=True, ensure_ascii=False) if sidebar else None
                if sidebar and (sidebar['commander'] or team in displayed) and displayed.get(team) != signature:
                    code, _ = states[team].submit(dict(action='sidebar', faction=team,
                        run_id=current['run_id'], **sidebar))
                    if code == 202:displayed[team] = signature
                for detail in controller.call_log.since(seen.get(team, 0))['items']:
                    detail['controller'] = team + '-harness'
                    game.record(detail);seen[team] = detail['id']
            # The player's game owns its result screen and F5 restart. Remain
            # attached with no new thinking while paused, rather than silently
            # handing the next run to local AI and hiding model expressions.
            if controllers and all(c.budget_exhausted for c in controllers.values()):
                outcome = 'request-budget';break
            if current.get('winner'):break
    except Exception as exc:
        outcome, error = 'error', str(exc)
        if client:
            try:
                discovery = json.loads(Path(connection).read_text(encoding='utf-8-sig'))
                if discovery.get('instanceId') == client.instance_id and discovery.get('status') == 'closed':
                    outcome, error = 'game-closed', None
            except (OSError, ValueError):pass
    finally:
        for keepalive in keepalives.values():keepalive.close()
        for controller in controllers.values():controller.close()
        # The game belongs to the player. Release controls; never terminate EXE.
        for team, lease in leases.items():
            try:
                row = client.observe(team)
                released = client.lease_change('release', row['context'], team, lease)
                game.record(dict(type='release-harness-detached', team=team, status=released['status']))
            except Exception as exc:game.record(dict(type='release-harness-release-error', team=team, error=str(exc)[:100]))
        if provider and callable(getattr(provider, 'close', None)):provider.close()
        for state in list(states.values()) + ([world_state] if world_state else []):state.close()
        if not game.stopped.is_set():game.finish(outcome, error)
