import copy
import sys
import unittest
import tempfile
import json
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path.insert(0, str(DESKFRONT_TOOLS))
sys.path.insert(0, str(ROOT / 'src/deskfront'))
from tactics import Coordination, support_ready, DecisionSchedule
from lm_controller import observation


class Game:
    def record(self, row):pass


def unit(uid, weapon='rifle'):
    return dict(id=uid, faction='green', kind='infantry', hp=100, max_hp=100, weapon=weapon,
                position=[0, 0], goal=[0, 0], in_cover=True, suppression=0, ammo=8,
                last_shot_at=9, reload_remaining=0, cqb_stance='peek', combat_ready=True,
                available_actions=['move', 'cover', 'flank', 'hold', 'attack', 'grenade', 'retreat'],
                combat=dict(engageable_targets=['red-1'], incoming_threats=[], path_active=False,
                            flag_hint=dict(pending=False, advance_options=[dict(position=[.3, .2], exposure=.2)])))


class Checks(unittest.TestCase):
    def test_real_single_unit_round_preserves_spatial_revision_and_identity(self):
        from team_executor import build_round,compact_state
        u=self.s['units'][1]
        self.s['navigation_revision']=7
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'spatial.json'
            path.write_text(json.dumps(dict(run_id=self.s['run_id'],time=self.s['time'],navigation_revision=7,
                units={u['id']:dict(origin=u['position'],firing_positions=[],navigation_steps=[])})),encoding='utf-8')
            self.c.spatial_path=str(path)
            payload=build_round(self.c,self.s,[u],{})
            self.assertEqual(payload['state']['executors'][u['id']]['spatial_tools']['sampled_at'],self.s['time'])
            view=compact_state(payload['state'])
            self.assertEqual(view['self_id'],u['id'])
            self.assertEqual(view['executors'][u['id']]['identity']['unit_id'],u['id'])
            self.assertIn('你就是 '+u['id'],payload['questions'][u['id']]['instructions'])
            self.s['navigation_revision']=8
            stale=build_round(self.c,self.s,[u],{})
            self.assertEqual(stale['state']['executors'][u['id']]['spatial_tools'],{})

    def test_enemy_approach_does_not_count_as_soldier_progress(self):
        for u in self.s['units']:u['last_shot_at']=-100
        enemy=unit('red-1');enemy.update(faction='red',position=[1.5,0])
        self.s['units'].append(enemy)
        self.c.update(self.s,{})
        start=self.c.units['green-2']['last_productive_time']
        self.s['time']+=4
        enemy['position']=[.5,0]
        self.c.update(self.s,{})
        row=self.c.units['green-2']
        self.assertEqual(row['last_productive_time'],start)
        self.assertGreaterEqual(row['unproductive_seconds'],4)

    def test_immediate_task_start_time_is_not_reset_each_frame(self):
        from task_execution import evaluate
        task=dict(command='support',start_when='immediate')
        u=self.s['units'][1]
        row=evaluate(task,u,self.s,{}, {},lambda a,t:False)
        initial=row['granted_at']
        self.s['time']+=5
        later=evaluate(task,u,self.s,{},row,lambda a,t:False)
        self.assertEqual(later['granted_at'],initial)
        self.assertEqual(later['phase'],'executing')

    def test_provider_credit_failure_is_visible_without_leaking_response(self):
        from team_executor import provider_failure_summary
        message=provider_failure_summary(RuntimeError('402 Your organization has no available TypeSafe API credits'))
        self.assertIn('HTTP 402',message)
        self.assertIn('额度不足',message)
        self.assertNotIn('Your organization',message)

    def test_route_destination_is_after_required_nodes(self):
        from task_tools import route_step
        routes={'left':dict(points=[[0,1],[0,2],[0,3]])}
        task=dict(route='left',waypoint=0,complete_when=dict(position=[.1,2]))
        self.assertEqual(route_step(task,routes),[0,1])
        task['waypoint']=1
        self.assertEqual(route_step(task,routes),[0,2])
        task['waypoint']=2
        self.assertIsNone(route_step(task,routes))

    def test_support_board_requires_actual_fire(self):
        from task_tools import board
        u=self.s['units'][0];u['last_shot_at']=-10
        tasks={u['id']:dict(command='support',route='adaptive')}
        self.assertFalse(board(self.s,tasks,{})[u['id']]['support_ready'])
        u['last_shot_at']=self.s['time']
        self.assertTrue(board(self.s,tasks,{})[u['id']]['support_ready'])
        u['combat']['fire_check']=dict(status='blocked',time=self.s['time'],reason='cover_blocks_muzzle')
        self.assertFalse(board(self.s,tasks,{})[u['id']]['support_ready'])

    def test_preparation_does_not_spend_fire_wait_timeout(self):
        from task_execution import evaluate
        task=dict(command='occupy',partner='green-1',start_when='partner_firing',wait_timeout_s=3)
        ally=self.s['units'][0];ally['combat']['path_active']=True
        status=evaluate(task,self.s['units'][1],self.s,{}, {},lambda a,t:False)
        self.s['time']+=5
        status=evaluate(task,self.s['units'][1],self.s,{},status,lambda a,t:False)
        self.assertEqual(status['phase'],'preparing')
        ally['combat']['path_active']=False
        status=evaluate(task,self.s['units'][1],self.s,{},status,lambda a,t:False)
        self.assertEqual(status['phase'],'waiting')

    def test_granted_occupier_without_real_progress_requests_reassessment(self):
        from task_execution import evaluate
        task=dict(command='occupy',partner='green-1',start_when='partner_firing',wait_timeout_s=6,on_failure='reassess')
        u=self.s['units'][1]
        status=evaluate(task,u,self.s,{}, {},lambda a,t:True)
        self.assertEqual(status['phase'],'executing')
        self.s['time']+=3.1
        stalled=evaluate(task,u,self.s,{},status,lambda a,t:True)
        self.assertEqual(stalled['reason'],'granted_without_progress')
        self.s['time']=10
        moving=evaluate(task,u,self.s,{}, {},lambda a,t:True)
        u['position']=[.1,.2]
        self.s['time']+=3.1
        moving=evaluate(task,u,self.s,{},moving,lambda a,t:True)
        self.assertEqual(moving['phase'],'executing')

    def test_outer_controller_does_not_block_on_missing_plan(self):
        import threading,time
        from types import SimpleNamespace
        from unittest.mock import Mock
        from tactics import CoordinatedController
        ctrl=CoordinatedController.__new__(CoordinatedController)
        ctrl.state=SimpleNamespace(lock=threading.RLock(),state=self.s,results={},updated=time.monotonic())
        ctrl.coordination=SimpleNamespace(update=Mock(),scenario={'active':True},plan={})
        ctrl.config={'model':'jev'};ctrl.team_executor=Mock()
        ctrl.tick()
        ctrl.team_executor.tick.assert_called_once()

    def test_dependency_requires_observed_fire_and_times_out(self):
        from task_execution import evaluate,constrain
        task=dict(command='flank',partner='green-1',target_id='red-1',start_when='partner_firing',wait_timeout_s=3,on_failure='reassess')
        u=self.s['units'][1];ally=self.s['units'][0];ally['last_shot_at']=-10
        status=evaluate(task,u,self.s,{}, {},support_ready)
        self.assertEqual(status['phase'],'waiting')
        options={k:dict(description=k) for k in ('task_waypoint','firing_0','shelter_0','continue_task')}
        constrain(options,status)
        self.assertNotIn('task_waypoint',options)
        self.assertIn('firing_0',options)
        self.s['time']=14
        status=evaluate(task,u,self.s,{},status,support_ready)
        self.assertEqual(status['reason'],'dependency_timeout')
        ally['last_shot_at']=14;ally['last_shot_target']='red-1'
        status=evaluate(task,u,self.s,{},status,support_ready)
        self.assertEqual(status['phase'],'reassess')
        # A timed-out task requires a fresh assessment, not late automatic revival.
        status=evaluate(task,u,self.s,{}, {},support_ready)
        self.assertEqual(status['phase'],'executing')
        ally['hp']=0
        status=evaluate(task,u,self.s,{},status,support_ready)
        self.assertEqual(status['phase'],'blocked')

    def test_move_retention_rejects_stall_and_new_destination(self):
        from action_continuity import keep_move
        u=unit('green-1');u['combat']['path_active']=True;u['goal']=[.5,.5]
        move=dict(action='move',position=[.5,.5])
        self.assertTrue(keep_move(u,move,{}))
        self.assertFalse(keep_move(u,move,dict(no_movement_seconds=4)))
        self.assertFalse(keep_move(u,dict(action='move',position=[1,1]),{}))
        u['combat']['path_active']=False;u['position']=[.5,.5]
        self.assertTrue(keep_move(u,move,{}))

    def test_support_reload_preserves_stage_but_damage_revokes_it(self):
        from task_execution import evaluate
        task=dict(command='flank',partner='green-1',start_when='partner_firing',waypoint=0)
        u=self.s['units'][1]
        status=evaluate(task,u,self.s,{}, {},lambda a,t:True)
        self.s['time']+=2
        status=evaluate(task,u,self.s,{},status,lambda a,t:False)
        self.assertEqual(status['phase'],'executing')
        self.assertEqual(status['reason'],'stage_permission_retained')
        u['hp']=70
        status=evaluate(task,u,self.s,{},status,lambda a,t:False)
        self.assertEqual(status['phase'],'reassess')

    def test_recovery_contract_does_not_offer_attack_route_waypoint(self):
        self.c.routes={'center':dict(name='center',points=[[.7,.7]])}
        self.c.plan['tasks']={'green-2':dict(route='center',waypoint=0,complete_when=dict(type='recovered',value=70))}
        self.assertNotIn('task_waypoint',self.c.options(self.obs()))

    def test_independent_executor_slow_member_does_not_block_others(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from concurrent.futures import Future
        from team_executor import IndependentExecutor
        futures=[Future() for _ in range(4)]
        ctrl=SimpleNamespace(coordination=self.c,units={},used=0,config=dict(max_requests=300,model='jev'),memory={},metrics={},pool=Mock(),call_log=Mock(),provider='quickplay')
        ctrl.pool.submit.side_effect=futures
        ex=IndependentExecutor(ctrl)
        with patch('team_executor.time.monotonic',return_value=10):ex.tick(self.s,{},0)
        self.assertEqual(ex.in_flight,3)
        self.assertEqual(ctrl.used,3)
        for uid,w in ex.workers.items():self.assertEqual(list(w.pending['payload']['questions']),[uid])
        # Unit two returns while unit one and three are still pending.
        futures[1].set_result(dict(answers={}))
        with patch('team_executor.time.monotonic',return_value=10.3):ex.tick(self.s,{},0)
        self.assertEqual(ex.in_flight,2)
        with patch('team_executor.time.monotonic',return_value=10.49):ex.tick(self.s,{},0)
        self.assertEqual(ctrl.used,3)
        with patch('team_executor.time.monotonic',return_value=10.5):ex.tick(self.s,{},0)
        self.assertEqual(ctrl.used,4)
        self.assertIs(ex.workers['green-1'].pending['future'],futures[0])
        self.assertIs(ex.workers['green-2'].pending['future'],futures[3])

    def test_executor_can_request_before_commander_returns(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from team_executor import TeamExecutor
        self.c.plan={}
        ctrl=SimpleNamespace(coordination=self.c,units={},used=0,config=dict(max_requests=300,model='jev'),memory={},metrics={},pool=Mock(),call_log=Mock(),provider='quickplay')
        executor=TeamExecutor(ctrl)
        executor.tick(self.s,{},0)
        self.assertEqual(ctrl.used,1)
        self.assertIsNotNone(executor.pending)
        self.assertEqual(set(executor.pending['members']),{'green-1','green-2','green-3'})

    def test_death_preserves_surviving_tasks_and_feedback(self):
        self.c.plan['tasks']={'green-2':dict(route='adaptive',waypoint=0,partner='green-1')}
        self.c.units['green-2']['last_productive_time']=3
        self.s['units'][0]['hp']=0
        self.c.update(self.s,{})
        self.assertTrue(self.c.plan)
        self.assertIn('green-2',self.c.plan['tasks'])
        self.assertEqual(self.c.plan['tasks']['green-2']['partner'],'')
        self.assertNotIn('green-1',self.c.units)

    def test_distant_firing_option_becomes_short_step_not_deleted(self):
        from stage_execution import segment_candidates
        topo=dict(cells={str(i):[i*.075,0] for i in range(10)},edges=[[str(i),str(i+1)] for i in range(9)])
        opts={'firing_0':dict(command=dict(action='move',intent='advance',position=[.675,0]),description='射位')}
        self.assertEqual(segment_candidates(opts,[0,0],topo),[])
        self.assertAlmostEqual(opts['firing_0']['command']['position'][0],.225)
        self.assertEqual(opts['firing_0']['destination'],[.675,0])

    def test_fire_block_is_target_specific_and_never_promises_clear_muzzle(self):
        from stage_execution import fire_status
        u=unit('green-1');u['weapon_range']=.7
        a=unit('red-1');a['position']=[.2,0]
        b=unit('red-2');b['position']=[.3,0]
        u['combat']['engageable_targets']=['red-1','red-2']
        u['combat']['fire_check']=dict(target_id='red-1',status='blocked',reason='cover_blocks_muzzle',time=10)
        status=fire_status(u,[a,b],10)
        self.assertEqual(status[0]['status'],'cover_blocks_muzzle')
        self.assertEqual(status[1]['status'],'candidate_requires_muzzle_validation')
        b['position']=[2,0]
        self.assertEqual(fire_status(u,[b],10)[0]['status'],'out_of_range')

    def test_stage_approach_is_short_and_cannot_cross_disconnected_wall(self):
        from stage_execution import approach,status
        cells={str(i):[i*.075,0] for i in range(10)}
        edges=[[str(i),str(i+1)] for i in range(9)]
        area=dict(cells=[[.675,0]],sample_step=.075)
        step=approach([0,0],area,dict(cells=cells,edges=edges))
        self.assertAlmostEqual(step[0],.225)
        self.assertIsNone(approach([0,0],area,dict(cells=cells,edges=edges[1:])))
        self.assertEqual(status({'a':{}},{'a':dict(task_progress=dict(achieved=True))})['phase'],'completed')

    def test_prepare_stage_does_not_offer_flag_capture_or_distant_move(self):
        self.c.plan['stage']=dict(id='prepare',goal='集结',next_intent='以后占旗')
        self.c.plan['tasks']={'green-2':dict(command='flank',route='adaptive',assignment='集结',complete_when=dict(type='position_reached',position=[.9,.9]))}
        opts=self.c.options(self.obs())
        self.assertNotIn('contest_flag',opts)
        self.assertNotIn('assigned_position',opts)
        self.assertIn('continue_task',opts)

    def test_occupy_arrival_stage_does_not_require_flag_completion(self):
        from commander_plan import validate,progress
        task=dict(command='occupy',start_when='immediate',wait_timeout_s=5,on_failure='reassess',assignment='先接近',route='adaptive',target_id='',partner='',complete_when=dict(type='position_reached',position=[0,0]),replan_when='到位')
        value=dict(objective='占旗',stage=dict(id='approach',goal='到位',next_intent='夺旗'),intent='接近阶段',tasks={u['id']:copy.deepcopy(task) for u in self.s['units']})
        plan=validate(value,self.s['units'],self.s,{})
        self.assertEqual(plan['tasks']['green-1']['complete_when']['type'],'position_reached')
        del value['stage']
        with self.assertRaisesRegex(ValueError,'requires flag_held'):validate(value,self.s['units'],self.s,{})

    def test_native_region_contract_allows_jev_route_choice_and_legacy_route(self):
        from commander_plan import validate
        self.s['strategic_topology']=dict(cells={'a':[0,0]},edges=[],step=.075)
        for u in self.s['units']:u['position']=[0,0]
        task=dict(command='occupy',start_when='immediate',wait_timeout_s=5,on_failure='reassess',assignment='占领',target_id='',partner='',complete_when=dict(type='flag_held',value=60),replan_when='受威胁')
        value=dict(objective='占旗',stage=dict(id='prepare',goal='集结',next_intent='确认后推进'),intent='分区行动',tasks={u['id']:copy.deepcopy(task) for u in self.s['units']})
        unbound=validate(value,self.s['units'],self.s,{})
        self.assertTrue(all('region_path' not in t and 'region_id' not in t for t in unbound['tasks'].values()))
        for t in value['tasks'].values():t.update(region_id='Na',region_path=['Na'])
        for t in value['tasks'].values():t.pop('wait_timeout_s')
        plan=validate(value,self.s['units'],self.s,{})
        self.assertTrue(all(t['region_id']=='Na' for t in plan['tasks'].values()))
        value['tasks']['green-2'].update(partner='green-1',start_when='partner_arrived',wait_timeout_s=5)
        with self.assertRaisesRegex(ValueError,'partner has no arrival destination'):validate(value,self.s['units'],self.s,{})
        value['tasks']['green-1']['complete_when']=dict(type='position_reached')
        value['tasks']['green-1'].pop('region_id')
        value['tasks']['green-1'].pop('region_path')
        self.assertEqual(validate(value,self.s['units'],self.s,{})['tasks']['green-2']['start_when'],'partner_arrived')

    def test_large_region_arrival_does_not_require_center(self):
        from commander_plan import progress
        from strategic_regions import contains
        from context_views import rounded
        area=dict(center=[0,0],radius=.1,cells=[[0,0],[.3,0]],sample_step=.075)
        u=unit('green-1');u['position']=[.3,0]
        task=dict(command='flank',destination_area=area,complete_when=dict(type='position_reached',position=[0,0]))
        self.assertTrue(progress(task,u,self.s)['achieved'])
        self.assertFalse(contains([.15,0],area)) # Hole in region is not silently included.
        self.assertNotIn('destination_area',rounded(task))

    def test_region_candidates_allow_choices_instead_of_center(self):
        from strategic_regions import catalog
        topology=dict(cells={'a':[0,0],'b':[.075,0],'c':[.15,0]},edges=[['a','b'],['b','c']],step=.075)
        self.c.world=dict(self.s,strategic_topology=topology)
        region=next(iter(catalog({},self.c.world)))
        self.c.plan['tasks']={'green-2':dict(command='flank',route='adaptive',region_id=region,assignment='区域行动',complete_when=dict(type='position_reached',position=[.075,0]))}
        self.c.spatial=lambda obs:dict(firing_positions=[dict(position=[.15,0],targets=['red-1'],threats=[],distance=.15)])
        opts=self.c.options(self.obs())
        self.assertIn('assigned_firing_0',opts)
        self.assertNotIn('assigned_position',opts)

    def test_commander_timing_records_success_and_failure(self):
        from request_timing import measured_ask,summary
        from unittest.mock import Mock
        game=Mock();game.ask.return_value={'requestId':'one'};samples=[]
        with patch('request_timing.time.monotonic',side_effect=[10,12]):measured_ask(game,{'time':0},{},samples)
        game.ask.side_effect=TimeoutError()
        with patch('request_timing.time.monotonic',side_effect=[20,23]):
            with self.assertRaises(TimeoutError):measured_ask(game,{'time':1},{},samples)
        report=summary(samples)
        self.assertEqual(report['average_ms'],2000)
        self.assertEqual(report['failed'],1)
        self.assertEqual(game.record.call_count,2)

    def test_auto_regions_never_connect_across_missing_native_edge(self):
        from auto_regions import generate
        topo=dict(cells={'a':[.05,.05],'b':[.1,.05],'c':[.15,.05],'d':[.65,.05]},edges=[['a','b'],['c','d']])
        regions,owners=generate(topo)
        self.assertEqual(owners['a'],owners['b'])
        self.assertNotEqual(owners['b'],owners['c'])
        self.assertNotIn(owners['c'],regions[owners['b']]['neighbors'])
        self.assertIn(owners['d'],regions[owners['c']]['neighbors'])

    def test_full_grid_covers_edges_and_keeps_ids_on_expansion(self):
        from strategic_regions import catalog,memberships
        small=catalog({},dict(bounds=[-.17,.83,1.38,3.46]))
        for p in [[-.17,.83],[1.38,3.46],[.45,2.15]]:self.assertTrue(memberships(p,small))
        large=catalog({},dict(bounds=[-.5,.6,2,4]))
        self.assertTrue(set(small)<=set(large))

    def test_dynamic_target_state_tracks_motion_and_death(self):
        from task_tools import board
        u=self.s['units'][0];e=unit('red-1');e['faction']='red';self.s['units'].append(e)
        tasks={u['id']:dict(command='support',route='adaptive',target_id='red-1')}
        self.assertEqual(board(self.s,tasks,{})[u['id']]['target_status'],'engageable')
        e['position']=[1,1];u['combat']['engageable_targets']=[]
        fact=board(self.s,tasks,{})[u['id']]
        self.assertEqual(fact['target_status'],'out_of_fire_lane')
        self.assertEqual(fact['target_position'],[1,1])
        e['hp']=0
        self.assertEqual(board(self.s,tasks,{})[u['id']]['target_status'],'dead')

    def test_region_arrival_is_independent_of_partner_final_goal(self):
        from commander_plan import validate
        from task_execution import evaluate
        task=dict(command='hold',start_when='immediate',wait_timeout_s=5,on_failure='reassess',assignment='守点',route='adaptive',target_id='',partner='',complete_when=dict(type='flag_held',value=10),replan_when='受威胁')
        value=dict(intent='分区协作',tasks={u['id']:copy.deepcopy(task) for u in self.s['units']})
        value['tasks']['green-2'].update(start_when='partner_arrived',partner='green-1',wait_region_id='C1')
        routes={'center':dict(name='中路',points=[[0,0]])}
        plan=validate(value,self.s['units'],self.s,routes)
        status=evaluate(plan['tasks']['green-2'],self.s['units'][1],self.s,plan['tasks'],{},lambda a,t:False)
        self.assertEqual(status['phase'],'executing')
        value['tasks']['green-1'].update(command='support',complete_when=dict(type='position_reached',position='C1'))
        converted=validate(value,self.s['units'],self.s,routes)
        self.assertEqual(converted['tasks']['green-1']['complete_when']['position'],[0,0])
        value['tasks']['green-2']['wait_region_id']='missing'
        with self.assertRaisesRegex(ValueError,'unknown wait_region_id'):validate(value,self.s['units'],self.s,routes)

    def test_generated_plan_validation_and_completion(self):
        from commander_plan import validate,progress
        task=dict(command='hold',start_when='immediate',wait_timeout_s=5,on_failure='reassess',assignment='保持旗点，配合队友',route='adaptive',target_id='',partner='',complete_when=dict(type='flag_held',value=10),replan_when='敌人进入旗点或队友阵亡')
        value=dict(intent='控制目标并交替掩护',tasks={u['id']:copy.deepcopy(task) for u in self.s['units']})
        plan=validate(value,self.s['units'],self.s,{})
        self.c.install('generated',plan,self.s['units'],'deepseek_commander')
        self.assertEqual(self.c.plan['reason'],value['intent'])
        self.s['objective']['flag']=dict(owner='green',held_seconds=10)
        self.assertTrue(progress(task,self.s['units'][0],self.s)['achieved'])
        value['tasks']['green-1']['partner']='ghost'
        with self.assertRaises(ValueError):validate(value,self.s['units'],self.s,{})

    def test_task_preserves_firing_choices_and_forecasts(self):
        self.c.routes={'left':dict(name='left',points=[[.7,.7]])}
        self.c.plan['tasks']={'green-2':dict(route='left',waypoint=0)}
        risk=dict(status='sampled',exposed_s=2,peak_attackers=2)
        spatial=dict(firing_positions=[dict(position=[.4,.3],targets=['red-1'],threats=[],distance=.4,risk=risk)],
            threat_forecast=dict(standing_exposure=[dict(id='red-1',ready_in_s=0)]))
        self.c.spatial=lambda obs:spatial
        choices=self.c.options(self.obs())
        self.assertIn('task_waypoint',choices)
        self.assertIn('firing_0',choices)
        self.assertIn('2.0s暴露',choices['firing_0']['description'])
        self.assertIn('未知',choices['task_waypoint']['description'])
        from team_executor import build_round,compact_state
        compact=compact_state(build_round(self.c,self.s,self.s['units'],{})['state'])
        self.assertEqual(compact['executors']['green-2']['spatial']['threat_forecast'],spatial['threat_forecast'])

    def test_forecasts_do_not_transfer_to_nearby_unqueried_positions(self):
        from threat_context import annotate
        choices={'x':dict(command=dict(action='move',position=[.01,0]),description='move')}
        annotate(choices,dict(route_forecasts=[dict(position=[0,0],risk=dict(exposed_s=0))]))
        self.assertNotIn('exposed_s',choices['x']['description'])
        self.assertIn('未知',choices['x']['description'])

    def test_context_whitelist_groups_buildings_preserves_pose_and_precision(self):
        from context_views import terrain_view,unit_view,rounded,question_view
        covers=[dict(id='house-'+str(i),kind='building',alive=True,position=[i*.01,0],size=[.01,.01],ray_size=[1,2,3]) for i in range(46)]
        terrain=terrain_view(covers,[dict(hp=100,position=[0,0])])
        self.assertEqual(len(terrain),1)
        self.assertEqual(terrain[0]['kind'],'building_summary')
        u=dict(self.s['units'][0],posture='prone',ray_size=[1,2,3],position=[.123456789,0])
        self.assertEqual(unit_view(u)['posture'],'prone')
        self.assertNotIn('ray_size',unit_view(u))
        self.assertEqual(rounded(unit_view(u))['position'][0],.123)
        self.assertEqual(u['position'][0],.123456789)
        q={'u':dict(type='choice',instructions='go',criteria={'p':'position 0.123456789'})}
        self.assertEqual(question_view(q)['u']['criteria']['p'],'position 0.123')
        self.assertEqual(q['u']['criteria']['p'],'position 0.123456789')
    def test_team_payload_shared_state_and_partial_answer_failure(self):
        from team_executor import build_round,decode_round
        p=build_round(self.c,self.s,self.s['units'],{})
        self.assertEqual(set(p['questions']),{'green-1','green-2','green-3'})
        self.assertEqual(len(p['state']['units']),3)
        for local in p['state']['executors'].values():self.assertNotIn('allies',local)
        answers={}
        for uid in ('green-1','green-3'):
            choices=p['state']['executors'][uid]['command_candidates']
            answers[uid]=dict(type='choice',choice='continue_task',confidence=1,probabilities={k:float(k=='continue_task') for k in choices})
        decisions,errors=decode_round(p,dict(answers=answers))
        self.assertEqual(set(decisions),{'green-1','green-3'})
        self.assertEqual(errors,{'green-2':'invalid_unit_answer'})
    def test_move_survives_shortlist_change_but_not_native_rejection(self):
        from tactics import CoordinatedController
        for valid in [True,False]:
            ctrl=CoordinatedController.__new__(CoordinatedController)
            ctrl.coordination=self.c;ctrl.units={};ctrl.next_due={};ctrl.execution_records={}
            self.c.spatial_path='unused';self.c.routes={'left':dict(name='left',points=[])}
            u=self.s['units'][1];decision=dict(action='move',intent='survive',position=[.9,.8])
            def submit(instance,s,u,d,origin,now,seen_tick=None):instance.units[u['id']]={'command_id':'cmd' if d['action']=='move' else None}
            with patch('execution_validation.validate_move',return_value=dict(valid=valid,reason='reachable' if valid else 'no_route')),patch('lm_controller.LMController._submit',new=submit):
                ctrl._submit(self.s,u,decision,'quickplay_jev',1,100)
            r=ctrl.execution_records[(u['id'],100)]
            self.assertEqual(r['actual']['action'],'move' if valid else 'wait')
            self.assertEqual(r['requested']['position'],[.9,.8])
            if not valid:self.assertEqual(r['status'],'not_submitted')
    def test_early_damage_warning_and_shelter_without_fire_lane(self):
        u=self.s['units'][1];self.s['time']=12;u['hp']=84
        self.c.update(self.s,{})
        self.assertTrue(self.c.units[u['id']]['early_retreat_warning'])
        self.c.spatial=lambda obs:dict(current_threats=['red-1'],shelter_positions=[dict(position=[.4,.6],distance=.5,threats=[],route_threat_samples=1)])
        self.assertEqual(self.c.options(self.obs())['shelter_0']['command']['intent'],'survive')
        self.c.reservations['green-1']=[.4,.6]
        self.assertNotIn('shelter_0',self.c.options(self.obs()))
    def test_retreat_continuation_is_advice_not_forced_action(self):
        u=self.s['units'][1];u['combat']['path_active']=True
        choice=dict(command=dict(action='move',intent='survive',position=[.4,.6]),description='escape')
        self.c.commit(self.s,u,choice['command'],choice,'escape')
        opts=self.c.options(self.obs())
        self.assertIn('正在执行撤离',opts['continue_task']['description'])
        self.assertIn('halt',opts)
    def test_execution_block_feedback_preserves_reposition_choices(self):
        u=self.s['units'][1];u['combat']['fire_check']=dict(status='blocked',target_id='red-1',reason='cover_blocks_muzzle',time=10)
        e=unit('red-1');e['faction']='red';self.s['units'].append(e)
        opts=self.c.options(self.obs())
        self.assertNotIn('attack_red-1',opts)
        self.assertIn('advance_0',opts)
        self.assertIn('开火已被执行层拦截',opts['continue_task']['description'])
        self.s['time']=14
        self.assertIn('attack_red-1',self.c.options(self.obs()))
    def test_ally_obstruction_wait_is_bounded(self):
        u=self.s['units'][1]
        u['combat']['fire_check']=dict(status='blocked',target_id='red-1',reason='ally_blocks_muzzle',time=10)
        self.assertIn('1.5',self.c.options(self.obs())['continue_task']['description'])
        self.s['time']=12;u['combat']['fire_check']['time']=12
        self.assertNotIn('1.5',self.c.options(self.obs())['continue_task']['description'])
        self.assertIn('换射位',self.c.options(self.obs())['continue_task']['description'])

    def test_rocket_blocked_shot_and_withdrawal_choices(self):
        u=self.s['units'][1];u['weapon']='rocket'
        e=unit('red-1');e['faction']='red';self.s['units'].append(e)
        self.c.spatial=lambda obs:dict(blocked_shots=['red-1'],withdrawal_positions=[dict(position=[.7,.8],nearest_enemy=.6,targets=[],threats=[])])
        options=self.c.options(self.obs())
        self.assertNotIn('attack_red-1',options)
        self.assertIn('withdraw_0',options)
        u['weapon']='rifle'
        self.assertIn('attack_red-1',self.c.options(self.obs()))
    def test_target_context_records_actual_allied_fire(self):
        e=unit('red-1');e['faction']='red';self.s['units'].append(e)
        self.s['units'][0].update(last_shot_target='red-1',last_shot_at=9)
        context=self.c.payload(self.obs())['state']['target_comparison']
        self.assertEqual(context[0]['allies_engaging'],['green-1'])
    def test_spatial_candidates_expire_and_respect_reservations(self):
        from spatial_queries import read_queries
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'spatial.json';u=self.s['units'][1]
            p.write_text(json.dumps(dict(run_id='r',time=10,units={u['id']:dict(origin=u['position'],firing_positions=[dict(position=[.7,.8],targets=['red-1'],threats=[],distance=1)])})))
            self.c.spatial_path=str(p)
            self.assertIn('firing_0',self.c.options(self.obs()))
            self.c.reservations['green-1']=[.7,.8]
            self.assertNotIn('firing_0',self.c.options(self.obs()))
            self.s['time']=13
            self.assertEqual(read_queries(p,self.s,u),{})
            self.s['time']=10;self.s['run_id']='other'
            self.assertEqual(read_queries(p,self.s,u),{})
    def test_attack_without_path_or_fire_is_not_executing_forever(self):
        u=self.s['units'][1];u['combat']['engageable_targets']=[];u['last_shot_at']=-10
        choice=dict(command=dict(action='attack',intent='engage',target_id='red-1'),description='approach')
        self.c.commit(self.s,u,choice['command'],choice,'attack-cmd')
        self.s['time']=15
        self.c.update(self.s,{'attack-cmd':{'accepted':True}})
        self.assertEqual(self.c.orders[u['id']]['phase'],'blocked')
        self.assertTrue(self.c.blocked(u['id'],'attack',{'target_id':'red-1'},15,u['position']))
        self.assertFalse(self.c.blocked(u['id'],'attack',{'target_id':'red-2'},15,u['position']))
    def test_attack_with_fire_lane_is_not_blocked(self):
        u=self.s['units'][1]
        choice=dict(command=dict(action='attack',intent='engage',target_id='red-1'),description='fire')
        self.c.commit(self.s,u,choice['command'],choice,'attack-cmd')
        self.s['time']=15
        self.c.update(self.s,{'attack-cmd':{'accepted':True}})
        self.assertEqual(self.c.orders[u['id']]['phase'],'executing')
    def test_route_choices_are_optional_and_reservations_apply(self):
        self.c.routes={'left':{'name':'left','points':[[.1,-.2]]}}
        self.assertIn('route_left',self.c.options(self.obs()))
        self.assertIn('continue_task',self.c.options(self.obs()))
        self.c.reservations['green-1']=[.1,-.2]
        self.assertNotIn('route_left',self.c.options(self.obs()))
    def test_flag_and_stale_resets_cannot_bypass_interval(self):
        schedule=DecisionSchedule({}, {'green-1':100})
        schedule['green-1']=0
        self.assertEqual(schedule['green-1'],100.5)
        schedule['green-1']=110
        self.assertEqual(schedule['green-1'],110)
    def setUp(self):
        self.c = Coordination(Game(), 'green', 'mock')
        a,b,c=unit('green-1'),unit('green-2','smg'),unit('green-3','rocket')
        b['position']=[.1, .1];c['position']=[-.2,-.2]
        self.s = dict(run_id='r', tick=100, time=10, control={'green':'lm'}, control_epochs={'green':1},
                      objective=dict(position=[1,1],radius=.17),units=[a,b,c],bounds=[-2,-2,2,2],paused=False,winner='',covers=[])
        self.c.update(self.s,{})
    def tearDown(self):self.c.close()
    def obs(self):return observation(self.s,self.s['units'][1],[])
    def test_role_assignment(self):
        self.assertEqual(self.c.plan['roles'],{'green-1':'executor','green-2':'executor','green-3':'executor'})
    def test_commander_only_chooses_direction(self):
        def ask(state, questions, role=None):
            self.assertEqual(set(questions), {'strategy'})
            self.assertEqual(role, 'commander')
            return {'answers':{'strategy':{'type':'choice','choice':'covered_advance','confidence':1,'probabilities':{k:float(k=='covered_advance') for k in questions['strategy']['criteria']}}},'requestId':'test'}
        self.c.game.ask=ask
        self.assertEqual(self.c.request_plan(self.s,self.s['units'],{},[]),('covered_advance',None))
    def test_stalled_injured_unit_has_alternatives_and_feedback(self):
        u=self.s['units'][1];u['hp']=20;u['combat']['path_active']=True
        self.s['time']=18;self.c.update(self.s,{})
        payload=self.c.payload(self.obs())
        self.assertTrue(payload['state']['execution_feedback']['path_stalled'])
        self.assertIn('halt',payload['state']['command_candidates'])
        self.assertIn('advance_0',payload['state']['command_candidates'])
    def test_waiting_or_reloading_is_not_covering_fire(self):
        self.assertTrue(support_ready(self.s['units'][0],10))
        self.s['units'][0]['reload_remaining']=1
        self.assertFalse(support_ready(self.s['units'][0],10))
        self.s['units'][0]['reload_remaining']=0;self.s['units'][0]['combat']['path_active']=True
        self.assertFalse(support_ready(self.s['units'][0],10))
    def test_recent_actual_cover_fire_survives_brief_hide(self):
        from task_tools import board
        u=self.s['units'][0]
        u.update(cover_id='hard',cover_slot='hard:0',cqb_stance='hide',
                 last_shot_at=9,last_shot_target='red-1')
        u['combat'].update(path_active=True,engageable_targets=[])
        self.assertTrue(support_ready(u,10))
        support=board(self.s,{u['id']:dict(command='support',target_id='red-1')},{})[u['id']]
        self.assertTrue(support['support_ready'])
        self.assertEqual(support['cover_phase'],'hiding')
        self.s['time']=12.4
        self.assertFalse(support_ready(u,self.s['time']))
    def test_native_peek_is_not_described_as_idle_or_new_cover(self):
        u=self.s['units'][1]
        u.update(cover_id='hard',cover_slot='hard:0',cqb_stance='peek',
                 in_cover=False,cover_step=True)
        u['combat'].update(path_active=True,engageable_targets=[])
        options=self.c.options(self.obs())
        self.assertNotIn('seek_cover',options)
        self.assertIn('已占用掩体',options['continue_task']['description'])
        self.assertIn('探头点移动不等于罚站',options['continue_task']['description'])
        enemy=unit('red-1');enemy['faction']='red';enemy['position']=[.3,0]
        self.s['units'].append(enemy)
        u['combat'].update(path_active=False,engageable_targets=['red-1'])
        options=self.c.options(self.obs())
        self.assertIn('attack_red-1',options)
        self.assertIn('可能在缩回无射线时追敌',options['attack_red-1']['description'])
    def test_exposure_is_reported_for_jev_to_judge(self):
        self.assertIn('advance_0',self.c.options(self.obs()))
        for u in self.s['units']:u['last_shot_at']=-100
        self.assertIn('advance_0',self.c.options(self.obs()))
        self.assertIn('[]',self.c.options(self.obs())['advance_0']['description'])
    def test_reservation_and_occupied_flag_remove_extra_advance(self):
        self.c.reservations['green-1']=[.31,.2]
        self.assertNotIn('advance_0',self.c.options(self.obs()))
        self.c.reservations.clear();self.s['units'][0]['position']=[1,1]
        self.assertIn('advance_0',self.c.options(self.obs()))
    def test_acceptance_does_not_mean_arrival(self):
        u=self.s['units'][1];u['combat']['path_active']=True
        choice=dict(command=dict(action='move',intent='advance',position=[.3,.2]),description='推进',requires_support=True)
        self.c.commit(self.s,u,choice['command'],choice,'cmd')
        self.c.update(self.s,{'cmd':{'accepted':True}})
        self.assertEqual(self.c.orders[u['id']]['phase'],'executing')
        self.assertEqual(self.c.handoffs,0)
        u['position']=[.3,.2];u['combat']['path_active']=False
        self.c.update(self.s,{'cmd':{'accepted':True}})
        self.assertEqual(self.c.orders[u['id']]['phase'],'arrived')
        self.assertEqual(self.c.handoffs,0) # No automatic tactical reassignment
        self.assertEqual(self.c.plan['roles']['green-1'],'executor')
    def test_support_interruption_requests_protection(self):
        u=self.s['units'][1];u['combat']['path_active']=True
        choice=dict(command=dict(action='move',intent='advance',position=[.3,.2]),description='推进',requires_support=True)
        self.c.commit(self.s,u,choice['command'],choice,'cmd')
        for v in self.s['units']:v['last_shot_at']=-100
        self.c.update(self.s,{'cmd':{'accepted':True}})
        self.assertIn('掩护中断',self.c.units[u['id']]['interrupt'])
        self.assertIn('protect',self.c.options(self.obs()))
        self.assertIn('halt',self.c.options(self.obs()))
    def test_control_epoch_clears_reservations(self):
        self.c.reservations['green-1']=[.3,.2];self.s['control_epochs']['green']=3
        self.c.update(self.s,{})
        self.assertEqual(self.c.reservations,{})
    def test_wait_preserves_active_reservation(self):
        u=self.s['units'][1];self.c.reservations[u['id']]=[.3,.2]
        choice=self.c.options(self.obs())['continue_task']
        self.c.commit(self.s,u,choice['command'],choice,None)
        self.assertEqual(self.c.reservations[u['id']],[.3,.2])
    def test_regroup_does_not_forbid_jev_advance(self):
        self.c.plan['style']='regroup';self.s['units'][0]['suppression']=.8
        self.assertIn('advance_0',self.c.options(self.obs()))
        self.assertIn('regroup_hold',self.c.options(self.obs()))
    def test_wounded_ally_does_not_deadlock_healthy_mover(self):
        self.c.plan['style']='regroup';self.s['units'][0]['hp']=6.5
        self.assertIn('advance_0',self.c.options(self.obs()))
        self.assertNotIn('regroup_hold',self.c.options(self.obs()))


    def test_wounded_unit_can_contest_enemy_flag(self):
        self.s['units'][1]['hp']=6.5
        self.s['units'][1]['available_actions'].append('capture')
        self.s['objective']['flag']={'owner':'red','remaining_seconds':8}
        self.assertIn('contest_flag',self.c.options(self.obs()))
    def test_failed_cover_aliases_are_all_blocked(self):
        u=self.s['units'][1]
        self.c.mark_failed(u['id'],dict(action='cover',start_position=u['position']),10)
        opts=self.c.options(self.obs())
        self.assertFalse(any(x['command']['action']=='cover' for x in opts.values()))
        self.s['time']=23
        self.assertFalse(self.c.blocked(u['id'],'cover',{},23,u['position']))
    def test_solo_plan_has_no_imaginary_support(self):
        self.s['units']=self.s['units'][1:2]
        self.c.update(self.s,{})
        self.assertEqual(self.c.plan['style'],'solo_contest')
    def test_capture_is_a_choice_not_a_forced_override(self):
        self.s['units'][1]['available_actions'].append('capture')
        self.s['objective']['flag']={'owner':'red','remaining_seconds':25}
        self.assertIn('contest_flag',self.c.options(self.obs()))
    def test_no_fire_lane_allows_explicit_approach(self):
        self.s['units'][1]['combat']['engageable_targets']=[]
        enemy=unit('red-1');enemy['faction']='red';self.s['units'].append(enemy)
        self.assertIn('approach_red-1',self.c.options(self.obs()))
        self.assertNotIn('find_fire_position',self.c.options(self.obs()))

if __name__=='__main__':unittest.main()
