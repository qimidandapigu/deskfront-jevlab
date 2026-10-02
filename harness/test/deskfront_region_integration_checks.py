"""Region command -> candidate -> shared context integration regressions."""
import copy
import sys
import threading
import unittest
from concurrent.futures import Future
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path.insert(0, str(DESKFRONT_TOOLS))
sys.path.insert(0, str(ROOT / 'src' / 'deskfront'))
from lm_controller import observation
from tactics import Coordination, CoordinatedController
from team_executor import TeamExecutor, build_round, compact_state, decode_round


def soldier(uid, position, faction='green'):
    return dict(id=uid, faction=faction, kind='infantry', weapon='rifle', hp=50, max_hp=50,
                position=position, goal=position, weapon_range=.7, ammo=8, reload_remaining=0,
                suppression=0, in_cover=True, cqb_stance='peek', combat_ready=True,
                last_shot_at=9, last_shot_target='red-1',
                available_actions=['move', 'cover', 'flank', 'hold', 'attack', 'capture', 'retreat'],
                combat=dict(path_active=False, engageable_targets=['red-1'], incoming_threats=[],
                            flag_hint=dict(pending=False, advance_options=[dict(position=[0, .15], exposure=.1)])))


class RegionIntegrationChecks(unittest.TestCase):
    def setUp(self):
        areas = {'A': [[0, 0], [0, -.075]],
                 'L': [[-.075, 0], [-.075, .075], [-.075, .15]],
                 'R': [[.075, 0], [.075, .075], [.075, .15]], 'E': [[0, .15]]}
        neighbors = {'A': ['L', 'R'], 'L': ['A', 'E'], 'R': ['A', 'E'], 'E': ['L', 'R']}
        self.regions = {key: dict(id=key, cells=points, center=points[0], radius=.15,
                                  sample_step=.075, neighbors=neighbors[key], route='adaptive')
                        for key, points in areas.items()}
        cells = {key+str(i): point for key, points in areas.items() for i, point in enumerate(points)}
        edges = [['A0', 'A1'], ['A0', 'L0'], ['L0', 'L1'], ['L1', 'L2'], ['L2', 'E0'],
                 ['A0', 'R0'], ['R0', 'R1'], ['R1', 'R2'], ['R2', 'E0']]
        self.topology = dict(cells=cells, edges=edges, step=.075)
        self.catalog_patch = patch('strategic_regions.catalog', return_value=self.regions)
        self.catalog_patch.start()
        self.addCleanup(self.catalog_patch.stop)
        self.unit = soldier('green-1', [0, 0])
        self.partner = soldier('green-2', [.6, .6])
        self.enemy = soldier('red-1', [.3, 0], 'red')
        self.state = dict(run_id='test', tick=100, time=10, control={'green': 'lm'},
                          control_epochs={'green': 1}, units=[self.unit, self.partner, self.enemy],
                          bounds=[-1, -1, 1, 1], paused=False, winner='', covers=[],
                          strategic_topology=self.topology,
                          objective=dict(position=[0, .7], radius=.17, flag={}))
        self.game = Mock()
        self.c = Coordination(self.game, 'green', 'mock')
        self.addCleanup(self.c.close)
        self.c.update(self.state, {})
        self.c.spatial = lambda obs: dict(sampled_at=10, origin=self.unit['position'],
            firing_positions=[dict(position=[0, -.075], targets=['red-1'], threats=[], distance=.075),
                              dict(position=[-.075, 0], targets=['red-1'], threats=[], distance=.075)],
            withdrawal_positions=[dict(position=[0, -.15], nearest_enemy=.4, targets=[], threats=[])])
        self.install(['A', 'L', 'E'])

    def task(self, path):
        return dict(command='flank', route='adaptive', region_id=path[-1], region_path=path,
                    assignment='从指定区域通路接近', target_id='', partner='', start_when='immediate',
                    wait_timeout_s=3, on_failure='reassess',
                    destination_area=self.regions[path[-1]],
                    complete_when=dict(type='position_reached', position=self.regions[path[-1]]['center']))

    def install(self, path, task=None):
        plan = dict(intent='区域通路测试', objective='控制目标',
                    stage=dict(id='prepare', goal='准备', next_intent='重评'),
                    tasks={'green-1': task or self.task(path)})
        self.c.install('generated', plan, [self.unit], 'deepseek_commander')

    def options(self):
        return self.c.options(observation(self.state, self.unit, []))

    def test_commander_request_shows_exact_living_roster_and_no_stale_task(self):
        dead=soldier('green-3',[.4,.4]);dead['hp']=0
        self.state['units'].append(dead)
        old=copy.deepcopy(self.c.plan)
        old['tasks']['green-3']=self.task(['A','L','E'])
        self.c.units['green-3']=dict(no_movement_seconds=20)
        self.c.plan_validation_feedback=dict(error='old plan invalid',tasks={'green-3':dict(command='flank')})
        captured=[]
        def answer(game,context,questions,timings):
            captured.append(context)
            return dict(requestId='test',answers={'plan':dict(value={'tasks':{}})})
        self.c.model='jev'
        with patch('request_timing.measured_ask',side_effect=answer),\
             patch('commander_plan.validate',return_value=dict(intent='test',tasks={})):
            self.c.request_plan(self.state,[self.unit,self.partner],old,[])
        self.assertEqual(captured[0]['living_controlled_unit_ids'],['green-1','green-2'])
        self.assertEqual(set(captured[0]['previous_plan']['tasks']),{'green-1'})
        self.assertNotIn('green-3',captured[0]['execution'])
        self.assertNotIn('green-3',captured[0]['plan_validation_feedback']['tasks'])
        self.assertIn('green-3',old['tasks'])

    def test_regionless_support_jev_binds_verified_final_firing_position(self):
        task=dict(command='support',route='adaptive',assignment='建立射界',target_id='red-1',
                  partner='',start_when='immediate',wait_timeout_s=5,on_failure='reassess',
                  complete_when=dict(type='position_reached'))
        self.install([],task)
        risk=dict(status='sampled',travel_s=.4,exposed_s=0,peak_attackers=0)
        self.c.spatial=lambda obs:dict(origin=self.unit['position'],sampled_at=self.state['time'],
            navigation_steps=[dict(cell_id='R0',position=[.075,0],risk=risk)],
            firing_positions=[dict(position=[.075,0],targets=['red-1'],threats=[],distance=.075,risk=risk)])
        choices=self.options()
        self.assertIn('local_fire_0',choices)
        selected=choices['local_fire_0']
        self.assertEqual(selected['destination'],[.075,0])
        self.c.commit(self.state,self.unit,selected['command'],selected,'cmd')
        self.assertEqual(self.c.plan['tasks']['green-1']['complete_when']['position'],[.075,0])
        self.assertEqual(self.c.units['green-1']['selected_destination'],[.075,0])
        self.assertTrue(self.c.orders['green-1']['local_autonomy'])
        old_revision=self.c.plan['tasks']['green-1']['task_revision']
        self.install([],task)
        self.assertEqual(self.c.plan['tasks']['green-1']['task_revision'],old_revision)
        self.assertEqual(self.c.plan['tasks']['green-1']['selected_destination'],[.075,0])

    def test_changed_task_clears_local_goal_and_cancels_old_movement(self):
        task=dict(command='support',route='adaptive',assignment='建立射界',target_id='red-1',
                  partner='',start_when='immediate',wait_timeout_s=5,on_failure='reassess',
                  complete_when=dict(type='position_reached'))
        self.install([],task)
        current=dict(command=dict(action='move',intent='advance',position=[.075,0]),
                     destination=[.15,0],fire_lane_evidence=False,requires_native_validation=True,
                     description='本地接敌')
        self.c.commit(self.state,self.unit,current['command'],current,'cmd')
        self.unit['combat']['path_active']=True
        task['target_id']=''
        task['assignment']='守住当前阵线'
        task['command']='hold'
        task['complete_when']=dict(type='flag_held',value=1)
        self.install([],task)
        self.assertNotIn('selected_destination',self.c.units['green-1'])
        self.assertFalse(self.c.move_compatible(self.unit))

    def test_same_destination_different_region_sequences_produce_different_steps(self):
        left = self.options()['stage_approach']['command']['position']
        self.install(['A', 'R', 'E'])
        right = self.options()['stage_approach']['command']['position']
        self.assertEqual(left, [-.075, 0])
        self.assertEqual(right, [.075, 0])

    def test_explicit_route_removes_native_chase_flank_and_capture_bypasses(self):
        self.unit['combat']['engageable_targets'] = []
        choices = self.options()
        self.assertIn('stage_approach', choices)
        self.assertNotIn('contest_flag', choices)
        self.assertNotIn('flank', choices)
        self.assertFalse(any(k.startswith(('advance_', 'approach_', 'route_')) for k in choices))

    def test_dependency_wait_keeps_firing_local_preparation_and_withdrawal(self):
        self.c.units['green-1']['task_execution'] = dict(phase='waiting')
        choices = self.options()
        self.assertNotIn('stage_approach', choices)
        self.assertNotIn('firing_1', choices)  # The adjacent route region requires permission.
        self.assertIn('firing_0', choices)  # Preparation inside the current region remains possible.
        self.assertIn('attack_red-1', choices)
        self.assertIn('withdraw_0', choices)

    def submit_selected(self, candidate, key='stage_approach', native_validation=None):
        ctrl = CoordinatedController.__new__(CoordinatedController)
        ctrl.coordination = self.c
        ctrl.units, ctrl.next_due, ctrl.execution_records = {}, {}, {}
        def submit(instance, state, unit, decision, origin, now, seen_tick=None):
            instance.units[unit['id']] = dict(command_id='move' if decision['action'] == 'move' else None)
        validation_patch = patch('execution_validation.validate_move', return_value=native_validation) if native_validation is not None else nullcontext()
        with patch('lm_controller.LMController._submit', new=submit), validation_patch:
            ctrl._submit(self.state, self.unit, candidate['command'], 'quickplay_jev', 20, 100,
                         selection=dict(key=key, candidate=candidate))
        return ctrl.execution_records[('green-1', 100)]

    def test_old_advance_answer_is_rejected_if_dependency_became_waiting(self):
        selected = copy.deepcopy(self.options()['stage_approach'])
        self.c.units['green-1']['task_execution'] = dict(phase='waiting')
        record = self.submit_selected(selected)
        self.assertEqual(record['requested']['action'], 'move')
        self.assertEqual(record['actual']['action'], 'wait')
        self.assertEqual(record['validation']['reason'], 'task_or_region_corridor_changed')

    def test_near_grid_corner_step_is_not_mistaken_for_already_arrived(self):
        self.unit['position'] = [-.03, 0]
        selected = copy.deepcopy(self.options()['stage_approach'])
        self.assertEqual(selected['command']['position'], [-.075, 0])
        self.assertTrue(selected['requires_precise_arrival'])
        record = self.submit_selected(selected)
        self.assertEqual(record['actual']['action'], 'move')
        self.assertEqual(record['status'], 'submitted')

    def test_new_route_and_waiting_permission_cancel_incompatible_old_move(self):
        for change in ('new_route', 'waiting'):
            with self.subTest(change=change):
                self.install(['A', 'L', 'E'])
                self.unit['combat']['path_active'] = True
                self.unit['goal'] = [-.075, 0]
                self.c.orders['green-1'] = dict(action='move', intent='advance')
                self.c.units['green-1'].pop('task_execution', None)
                old_wait = dict(command=dict(action='wait', intent='observe'), description='保留旧动作')
                if change == 'new_route':
                    self.install(['A', 'R', 'E'])
                else:
                    self.c.units['green-1']['task_execution'] = dict(phase='waiting')
                self.assertEqual(self.options()['continue_task']['command']['action'], 'hold')
                record = self.submit_selected(old_wait, key='continue_task')
                self.assertEqual(record['requested']['action'], 'wait')
                self.assertEqual(record['actual']['action'], 'hold')

    def test_survival_withdrawal_is_not_cancelled_by_new_route_boundary(self):
        self.unit['combat']['path_active'] = True
        self.unit['goal'] = [0, -.15]
        self.c.orders['green-1'] = dict(action='move', intent='survive')
        self.c.units['green-1']['task_execution'] = dict(phase='waiting')
        selected = self.options()['continue_task']
        self.assertEqual(selected['command']['action'], 'wait')
        self.assertEqual(self.submit_selected(selected, key='continue_task')['actual']['action'], 'wait')

    def test_unsampled_origin_bridge_survives_filters_and_requires_short_native_path(self):
        self.unit['position'] = [0, .057]
        self.c.spatial_path = 'unused-native-validation-path'
        self.c.routes = {'legacy': dict(name='legacy', points=[])}
        selected = copy.deepcopy(self.options()['rejoin_region'])
        self.assertEqual(selected['command']['position'], [0, 0])
        self.assertTrue(selected['requires_precise_arrival'])
        self.assertEqual(selected['navigation_anchor']['observed_regions'], [])
        self.assertAlmostEqual(selected['bridge_max_path_length'], .087)
        self.assertEqual(self.c.units['green-1']['region_navigation']['entered'], [])
        for length, expected in [(selected['bridge_max_path_length'], 'move'), (.2, 'wait')]:
            with self.subTest(native_path_length=length):
                self.c.orders.clear()
                record = self.submit_selected(selected, key='rejoin_region',
                    native_validation=dict(valid=True, reason='reachable', path_length=length))
                self.assertEqual(record['actual']['action'], expected)
                if expected == 'wait':
                    self.assertEqual(record['validation']['reason'], 'origin_bridge_requires_short_native_path')

    def test_current_stage_hold_can_finish_on_arrival_without_claiming_flag_capture(self):
        from commander_plan import validate
        task = self.task(['A', 'L'])
        task.update(command='hold', replan_when='敌情变化时重新判断')
        raw = dict(objective='控制目标', intent='先到掩护区守住',
                   stage=dict(id='prepare', goal='到位准备', next_intent='之后重评'),
                   tasks={'green-1': task})
        plan = validate(raw, [self.unit], self.state, {})
        self.assertEqual(plan['tasks']['green-1']['command'], 'hold')
        self.assertEqual(plan['tasks']['green-1']['complete_when']['type'], 'position_reached')
        self.assertEqual(plan['tasks']['green-1']['region_path'], ['A', 'L'])

    def test_completed_task_keeps_region_boundary_until_commander_reassignment(self):
        self.c.update(self.state, {})
        self.unit['position'] = [-.075, 0]
        self.state['time'] += 1
        self.c.update(self.state, {})
        self.unit['position'] = [0, .15]
        self.state['time'] += 1
        self.c.update(self.state, {})
        task = self.c.plan['tasks']['green-1']
        self.assertEqual(task['region_path'], ['A', 'L', 'E'])
        self.assertTrue(self.c.units['green-1']['task_progress']['achieved'])
        choices = self.options()
        self.assertNotIn('contest_flag', choices)
        self.assertFalse(any(k.startswith(('route_', 'approach_', 'advance_')) for k in choices))

    def test_reapproved_plan_resets_dependency_without_resetting_route(self):
        task = self.task(['A', 'L', 'E'])
        task.update(start_when='partner_firing', partner='green-2')
        self.partner['last_shot_at'] = -10
        self.install(task['region_path'], task)
        self.c.update(self.state, {})
        self.state['time'] += 4
        self.c.update(self.state, {})
        self.assertEqual(self.c.units['green-1']['task_execution']['phase'], 'reassess')
        old_revision = self.c.plan['tasks']['green-1']['task_revision']
        self.install(task['region_path'], task)
        self.partner['last_shot_at'] = self.state['time']
        self.c.update(self.state, {})
        self.assertEqual(self.c.plan['tasks']['green-1']['task_revision'], old_revision)
        self.assertEqual(self.c.units['green-1']['task_execution']['phase'], 'executing')
        task['assignment']='队友已恢复火力后重新推进'
        self.install(task['region_path'], task)
        self.c.update(self.state, {})
        self.assertGreater(self.c.plan['tasks']['green-1']['task_revision'], old_revision)
        self.assertEqual(self.c.units['green-1']['task_execution']['phase'], 'executing')

    def test_response_from_old_commander_version_is_discarded_before_submission(self):
        ctrl = SimpleNamespace(coordination=self.c, units={}, metrics={}, call_log=Mock(),
                               used=300, config={'max_requests': 300}, _submit=Mock())
        worker = TeamExecutor(ctrl, 'green-1')
        result = Future()
        result.set_result(dict(answers={}, requestId='old', usage={}))
        worker.pending = dict(id='old-call', future=result, run='test', epoch=1,
                              version=self.c.version-1, started=20, members=['green-1'])
        with patch('team_executor.time.monotonic', return_value=21):
            worker.tick(self.state, {}, 0)
        ctrl._submit.assert_not_called()
        ctrl.call_log.update.assert_called_with('old-call', phase='discarded',
                                               discard_reason='run_control_plan_or_freshness_changed')

    def returned_worker(self):
        ctrl = CoordinatedController.__new__(CoordinatedController)
        ctrl.coordination = self.c
        ctrl.units, ctrl.next_due, ctrl.execution_records, ctrl.metrics = {}, {}, {}, {}
        ctrl.state = SimpleNamespace(lock=threading.RLock(), state=self.state)
        ctrl.origin, ctrl.used, ctrl.config = 'quickplay_jev', 1, {'max_requests': 300}
        ctrl.call_log, ctrl.pool = Mock(), Mock()
        worker = TeamExecutor(ctrl, 'green-1')
        worker.next_at = 100  # Process the prepared response without creating an unrelated call.
        return ctrl, worker

    def queue_response(self, worker, payload, now=21, call_id='returned'):
        options = payload['state']['executors']['green-1']['command_candidates']
        response = dict(requestId=call_id, usage={}, answers={'green-1': dict(type='choice',
            choice='stage_approach', confidence=1,
            probabilities={key: float(key == 'stage_approach') for key in options})})
        future = Future()
        future.set_result(response)
        worker.pending = dict(id=call_id, future=future, payload=payload, run='test', epoch=1,
                              version=self.c.version, tick=100, started=now-1, members=['green-1'])
        return response

    def test_real_response_decode_strips_choice_metadata_before_native_validation_and_submit(self):
        from lm_controller import validate_decision
        ctrl, worker = self.returned_worker()
        payload = build_round(self.c, self.state, [self.unit], {})
        response = self.queue_response(worker, payload)
        decoded, errors = decode_round(payload, response)
        self.assertFalse(errors)
        self.assertEqual(decoded['green-1']['_choice_key'], 'stage_approach')
        # Confirm this is exercising the actual strict native validator.
        with self.assertRaisesRegex(ValueError, '^invalid_decision_fields$'):
            validate_decision(decoded['green-1'], self.state, self.unit)
        def engine_submit(instance, state, unit, decision, origin, now, seen_tick=None):
            instance.units[unit['id']] = dict(command_id='real-chain-command')
        with patch('lm_controller.LMController._submit', new=engine_submit), \
             patch('team_executor.time.monotonic', return_value=21):
            worker.tick(self.state, {}, 0)
        record = ctrl.execution_records[('green-1', 100)]
        self.assertEqual(record['actual']['action'], 'move')
        self.assertEqual(record['status'], 'submitted')
        self.assertNotIn('_choice_key', record['requested'])
        self.assertFalse(worker.fatal_error)
        self.assertEqual(worker.structural_errors, 0)
        events = [call.args[0] for call in self.game.record.call_args_list]
        self.assertTrue(any(row.get('type') == 'execution-resolution' for row in events))
        self.assertEqual(worker.receipts['real-chain-command'], ('returned', 'green-1'))

    def test_three_native_schema_failures_stop_further_calls_before_budget_is_spent(self):
        ctrl, worker = self.returned_worker()
        payload = build_round(self.c, self.state, [self.unit], {})
        payload['state']['executors']['green-1']['command_candidates']['stage_approach']['unexpected_field'] = True
        for attempt in range(1, 4):
            now = 20 + attempt
            ctrl.used = attempt
            self.queue_response(worker, payload, now=now, call_id='invalid-'+str(attempt))
            with patch('team_executor.time.monotonic', return_value=now):
                worker.tick(self.state, {}, 0)
            self.assertEqual(worker.structural_errors, attempt)
        self.assertTrue(worker.fatal_error)
        self.assertLess(ctrl.used, ctrl.config['max_requests'])
        self.assertFalse(ctrl.execution_records)
        resolved = [call.kwargs for call in ctrl.call_log.update.call_args_list if call.kwargs.get('phase') == 'resolved']
        self.assertEqual(len(resolved), 3)
        self.assertTrue(all(row['unit_executions']['green-1']['validation_error'] == 'invalid_decision_fields' for row in resolved))
        with patch('team_executor.time.monotonic', return_value=200):
            worker.tick(self.state, {}, 0)
        self.assertEqual(ctrl.status, 'error')
        ctrl.call_log.start.assert_not_called()
        ctrl.pool.submit.assert_not_called()
        self.assertEqual(ctrl.used, 3)

    def test_compact_request_keeps_current_route_micro_and_shared_teammate_state(self):
        self.c.update(self.state, {})
        compact = compact_state(build_round(self.c, self.state, [self.unit], {})['state'])
        local = compact['executors']['green-1']
        self.assertEqual(local['task']['region_path'], ['A', 'L', 'E'])
        self.assertEqual(compact['tactical_map']['status'],'ready')
        self.assertEqual(compact['tactical_map']['legend']['1'],'green-1')
        self.assertEqual(local['region_navigation']['next_region'], 'L')
        self.assertIn('own_range', local['micro_combat'])
        self.assertIn('distance_to_flag_circle', local['objective_timing'])
        self.assertEqual(local['objective_timing']['flag_owner'], None)
        self.assertIn('未知路径', local['objective_timing']['basis'])
        self.assertEqual(local['micro_combat']['targets'][0]['id'], 'red-1')
        self.assertEqual({u['id'] for u in compact['units']}, {'green-1', 'green-2', 'red-1'})
        self.assertIn('green-1', compact['cooperation_board'])
        self.assertNotIn('command_details', local)
        self.assertNotIn('destination_area', local['task'])

    def test_commander_receives_feasibility_and_flag_clock_before_first_plan(self):
        self.state['objective']['flag']=dict(owner='red',remaining_seconds=9,
                                              contested=False)
        observed={}
        def answer(context,questions,role=None):
            observed.update(context)
            return dict(answers={'strategy':dict(type='choice',choice='covered_advance',
                confidence=1,probabilities={key:float(key=='covered_advance')
                                            for key in questions['strategy']['criteria']})},
                requestId='context-test')
        self.game.ask.side_effect=answer
        self.c.request_plan(self.state,[self.unit,self.partner],{},[])
        self.assertEqual(observed['plan_feasibility']['units']['green-1']
                         ['enemy_range_gaps']['red-1'],0)
        self.assertNotIn('assignment',observed['plan_feasibility']['units']['green-1'])
        self.assertEqual(observed['objective_timing']['units']['green-1']
                         ['enemy_hold_remaining_s'],9)
        self.assertEqual(observed['objective_timing']['units']['green-1']
                         ['path_to_flag_center']['status'],'unknown')

    def test_deepseek_receives_distinct_connected_corridors_with_soft_midpoint_hints(self):
        self.state['objective']['position']=[0,.15]
        self.regions['L']['center']=[-.075,.075]
        self.regions['R']['center']=[.075,.075]
        self.c.model='jev'
        observed={}
        def answer(context,questions,role=None):
            observed.update(context)
            raise RuntimeError('captured_commander_context')
        self.game.ask.side_effect=answer
        with self.assertRaisesRegex(RuntimeError,'captured_commander_context'):
            self.c.request_plan(self.state,[self.unit],{},[])
        corridors=observed['approach_corridors']
        self.assertEqual(corridors['status'],'ready')
        self.assertGreaterEqual(len(corridors['corridors']),2)
        self.assertTrue(all(row['via_region_hint'] in observed['strategic_regions']
                            for row in corridors['corridors']))
        self.assertTrue(all(row['risk_status']=='unknown_full_route'
                            for row in corridors['corridors']))
        tactical_map=observed['tactical_map']
        self.assertEqual(tactical_map['status'],'ready')
        self.assertEqual(tactical_map['legend']['1'],'green-1')
        self.assertIn('F',''.join(tactical_map['rows']))
        self.assertIn('无法从此图推断',tactical_map['limitation'])
        self.assertNotIn('region_opportunities',observed)

    def test_jev_receives_region_destination_and_native_engine_owns_path(self):
        task=dict(command='flank',route='adaptive',assignment='寻找侧路',target_id='red-1',
                  partner='',start_when='immediate',wait_timeout_s=5,on_failure='reassess',
                  complete_when=dict(type='position_reached'))
        self.install([],task)
        risk=dict(status='sampled',travel_s=.4,exposed_s=.1,peak_attackers=1)
        self.c.spatial=lambda obs:dict(origin=self.unit['position'],sampled_at=self.state['time'],
            navigation_steps=[dict(cell_id='L0',position=[-.075,0],risk=risk),
                              dict(cell_id='R0',position=[.075,0],risk=risk)],
            firing_positions=[dict(position=[0,.15],targets=['red-1'],threats=[],
                                   distance=.3,risk=risk)])
        choices=self.options()
        region_choices=[v for k,v in choices.items() if k.startswith('region_goal_')]
        self.assertTrue(region_choices)
        self.assertEqual({v['region_goal'] for v in region_choices},{'E'})
        self.assertEqual(region_choices[0]['command']['position'],[0,.15])
        self.assertTrue(region_choices[0]['requires_native_validation'])
        self.assertNotIn('region_path',region_choices[0])
        self.assertNotIn('first_step',region_choices[0])
        self.assertNotIn('region_path',region_choices[0]['command'])
        compact=compact_state(build_round(self.c,self.state,[self.unit],{})['state'])
        advisory=compact['executors']['green-1']['region_choices']
        self.assertEqual(advisory['query_status'],'fresh')
        self.assertTrue(any(r['region_id']=='E' for r in advisory['options']))
        self.assertNotIn('command',advisory['options'][0])
        self.assertNotIn('region_path',advisory['options'][0])

    def test_remote_fire_sample_becomes_reachable_choice_and_advisory_region_fact(self):
        task=dict(command='support',route='adaptive',assignment='建立可用射位',target_id='red-1',
                  partner='',start_when='immediate',wait_timeout_s=5,on_failure='reassess',
                  complete_when=dict(type='position_reached'))
        self.install([],task)
        risk=dict(status='sampled',travel_s=1.1,exposed_s=.2,peak_attackers=1)
        self.c.spatial=lambda obs:dict(origin=self.unit['position'],sampled_at=self.state['time'],
            navigation_steps=[dict(cell_id='L0',position=[-.075,0],risk=risk),
                              dict(cell_id='R0',position=[.075,0],risk=risk)],
            remote_firing_search=dict(status='sampled',sampled_cells=7,clear_ray_cells=1,path_queries=1,returned=1),
            remote_firing_positions=[dict(cell_id='E0',position=[0,.15],targets=['red-1'],
                focus_target_id='red-1',sector=2,reachable=True,risk=risk)])
        choices=self.options()
        self.assertIn('local_fire_0',choices)
        candidate=choices['local_fire_0']
        self.assertEqual(candidate['destination'],[0,.15])
        self.assertEqual(candidate['fire_lane_scope'],'remote_coarse_sample')
        self.assertGreater(sum(abs(v) for v in candidate['command']['position']),.055)
        self.assertIn('全图粗采样',candidate['description'])
        compact=compact_state(build_round(self.c,self.state,[self.unit],{})['state'])
        local=compact['executors']['green-1']
        self.assertEqual(local['spatial']['remote_firing_positions'][0]['targets'],['red-1'])
        self.assertTrue(any(site['source']=='remote_firing' and site['region_id']=='E' for site in
            local['region_choices']['options']))

    def test_selected_region_goal_is_committed_as_destination_without_route(self):
        task=dict(command='flank',route='adaptive',assignment='探索侧路',target_id='red-1',
                  partner='',start_when='immediate',wait_timeout_s=5,on_failure='reassess',
                  complete_when=dict(type='position_reached'))
        self.install([],task)
        risk=dict(status='sampled',travel_s=.4,exposed_s=.1,peak_attackers=1)
        self.c.spatial=lambda obs:dict(origin=self.unit['position'],sampled_at=self.state['time'],
            navigation_steps=[dict(cell_id='L0',position=[-.075,0],risk=risk),
                              dict(cell_id='R0',position=[.075,0],risk=risk)],
            remote_firing_positions=[dict(cell_id='E0',position=[0,.15],targets=['red-1'],
                focus_target_id='red-1',sector=2,reachable=True,risk=risk)])
        candidate=next(value for key,value in self.options().items()
                       if key.startswith('region_goal_') and value['region_goal']=='E')
        self.c.commit(self.state,self.unit,candidate['command'],candidate,'route-cmd')
        compact=compact_state(build_round(self.c,self.state,[self.unit],{})['state'])
        advisory=compact['executors']['green-1']['region_choices']
        self.assertEqual(candidate['command']['position'],[0,.15])
        self.assertEqual(self.c.orders['green-1']['destination'],[0,.15])
        self.assertEqual(self.c.units['green-1']['selected_destination'],[0,.15])
        self.assertTrue(any(option['region_id']=='E' for option in advisory['options']))
        self.assertNotIn('region_path',candidate['command'])
        self.assertNotIn('first_step',candidate)


if __name__ == '__main__':
    unittest.main()
