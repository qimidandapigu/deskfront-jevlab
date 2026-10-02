"""Harness-only 1v1 setup using Deskfront's existing scenario/demo commands."""
import copy
import time


class DuelSetup:
    def __init__(self, state, instance, model_team='green', opponent='game_ai', extra_opponents=False, tactical_map=False, dense_cover=False):
        self.tactical_map = tactical_map
        self.dense_cover = dense_cover
        self.extra_opponents = extra_opponents
        if model_team not in ('green', 'red'):
            raise ValueError('Invalid duel model faction')
        self.state, self.instance, self.model_team = state, instance, model_team
        if opponent not in ('game_ai', 'native_jev', 'harness'):
            raise ValueError('Invalid duel opponent')
        self.opponent = opponent
        self.pending = None
        self.loaded = False
        self.started = time.monotonic()
        self.source_run = None
        self.sent_steps = set()

    def submit(self, snapshot, **command):
        status, result = self.state.submit(dict(command, instance_id=self.instance, run_id=snapshot['run_id']))
        if status != 202:
            raise RuntimeError('Duel setup rejected: ' + str(result))
        self.pending = result['id']

    def tick(self, snapshot):
        if time.monotonic() - self.started > 90:
            raise RuntimeError('Duel deployment timed out')
        if self.pending:
            with self.state.lock:
                receipt = copy.deepcopy(self.state.results.get(self.pending))
            if receipt is None:
                return False
            if not receipt.get('accepted'):
                raise RuntimeError('Duel engine rejected: ' + str(receipt))
            self.pending = None
        if not self.loaded:
            # Compile data with the game's public scenario contract; Godot validates it.
            from scenario_authoring import example, compile_scenario
            spec = example()
            spec.update(name='Harness 1v1: model vs ' + self.opponent,
                        briefing='Green and red: three infantry each. Blue stays in reserve. Swap model faction for repeated trials.',
                        objective=[.54, 2.17], spawns=[[.54, 2.89], [-.18, .85], [.54, 1.45]])
            spec['covers'] = [dict(kind='sandbag', position=[x, z], size=[.24, .06, .043], yaw=yaw)
                              for x, z, yaw in [(.20, 1.72, 0), (.88, 1.72, 0), (.20, 2.62, 0),
                                               (.88, 2.62, 0), (.05, 2.17, 90), (1.03, 2.17, 90)]]
            if self.dense_cover:
                spec['name'] = '1v1 · 街区掩体交战'
                spec['covers'] += [
                    dict(kind='building', position=[.06,1.96], size=[.24,.23,.24], yaw=0),
                    dict(kind='building', position=[1.02,2.38], size=[.24,.23,.24], yaw=0),
                    *[dict(kind='sandbag', position=[x,z], size=[.18,.06,.043], yaw=yaw)
                      for x,z,yaw in [(.48,1.82,0),(.60,2.52,0),(.16,2.90,0),(.92,1.44,0)]],
                    dict(kind='crate',position=[.78,2.02],size=[.12,.09,.12],yaw=0),
                    dict(kind='crate',position=[.30,2.32],size=[.12,.09,.12],yaw=0)]
            if self.tactical_map:
                from tactical_level import specification
                spec = specification()
            self.source_run = snapshot['run_id']
            modes = {t: 'lm' if t == self.model_team else 'game_ai' for t in ('green', 'blue', 'red')}
            if self.opponent in ('native_jev', 'harness'):
                modes['red' if self.model_team == 'green' else 'green'] = 'lm'
            self.submit(snapshot, action='scenario', level=compile_scenario(spec, 'harness-duel'),
                        modes=modes, demo=True, demo_driver='harness')
            self.loaded = True
            return False
        if snapshot['run_id'] == self.source_run:
            return False
        demo = snapshot.get('demo', {})
        if not demo.get('enabled') or demo.get('participants') != ['green', 'red']:
            raise RuntimeError('Engine did not load the two-team demo')
        if demo.get('phase') == 'battle':
            active = [u for u in snapshot['units'] if u.get('deployment_phase', 'active') == 'active']
            if self.extra_opponents and len(active) == 6:return False
            if len(active) != (8 if self.extra_opponents else 6) or any(u['faction'] == 'blue' or u.get('kind') == 'tank' for u in active):
                raise RuntimeError('Invalid 1v1 deployment')
            return True
        steps = [step for step in demo.get('steps', []) if step['id'] not in self.sent_steps]
        if steps:
            self.submit(snapshot, action='demo_step', step_id=steps[0]['id'])
            self.sent_steps.add(steps[0]['id'])
        return False
