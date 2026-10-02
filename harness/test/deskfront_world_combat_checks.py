import sys
import unittest
from pathlib import Path
from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/deskfront'))
sys.path.insert(0,str(DESKFRONT_TOOLS))
from deskfront_tactics_checks import unit
from deskfront_world_checks import Game
from lm_controller import observation
from tactics import Coordination

class Checks(unittest.TestCase):
    def setUp(self):
        self.game=Game();self.c=Coordination(self.game,'green','mock')
        u=unit('green-1');u['available_actions'].append('capture')
        enemy=unit('red-1');enemy['faction']='red';enemy['position']=[1,0]
        self.s=dict(run_id='r',tick=1,time=10,control={'green':'lm','red':'game_ai'},control_epochs={'green':1},
            bounds=[0,-2,3,2],units=[u,enemy],covers=[],objective={'position':[2,0],'radius':.17,'flag':{'owner':'red','remaining_seconds':1}},
            world_growth={'mission':dict(left=0,center_z=0,defenders=['red-1'],target=[2,0],status='active',spec={'support':[[.5,.1]],'flank':[[.3,-1],[1,-1],[1.5,0]]})})
        self.c.update(self.s,{})
    def tearDown(self):self.c.close()
    def test_encounter_has_no_capture_actions_or_flag_emergency(self):
        p=self.c.payload(observation(self.s,self.s['units'][0],[]))
        self.assertNotIn('contest_flag',p['state']['command_candidates'])
        self.assertTrue(all(c['action']!='capture' for c in p['state']['command_candidates'].values()))
        self.assertFalse(p['state']['flag_warning']['active'])
        self.assertIn('task_waypoint',p['state']['command_candidates'])
        self.assertNotIn('secure_exit',p['state']['command_candidates'])
        self.assertEqual(self.s['objective']['flag']['owner'],'red')
    def test_stalled_unit_receives_evidence_without_forced_action(self):
        self.c.units['green-1']['unproductive_seconds']=9
        u=self.s['units'][0]
        u['combat']['engageable_targets']=['red-1']
        u['reload_remaining']=0
        opts=self.c.options(observation(self.s,u,[]))
        self.assertIn('attack_red-1',opts)
        self.assertIn('halt',opts)
        self.assertIn('已有可尝试的交火/换位候选',opts['halt']['description'])
        u['reload_remaining']=2
        opts=self.c.options(observation(self.s,u,[]))
        self.assertIn('halt',opts)

    def test_dead_target_retires_task_and_reservation(self):
        self.c.plan['tasks']['green-1']=dict(command='eliminate',route='adaptive',target_id='red-1',complete_when=dict(type='target_dead'))
        self.c.reservations['green-1']=[1,0]
        self.s['units'][1]['hp']=0
        self.c.update(self.s,{})
        self.assertNotIn('green-1',self.c.plan['tasks'])
        self.assertNotIn('green-1',self.c.reservations)
        self.assertEqual(self.c.units['green-1']['retired_task']['reason'],'target_no_longer_alive')

    def test_arrival_radius_is_not_proof_of_support(self):
        from commander_plan import progress
        u=self.s['units'][0];u['position']=[.1,0]
        task=dict(command='flank',complete_when=dict(type='position_reached',position=[0,0],radius=.15))
        self.assertTrue(progress(task,u,self.s)['achieved'])
        task.update(command='support',target_id='red-1')
        u['last_shot_at']=-100
        self.assertFalse(progress(task,u,self.s)['achieved'])
        u['last_shot_at']=self.s['time'];u['last_shot_target']='red-1';u['combat']['engageable_targets']=['red-1']
        self.assertTrue(progress(task,u,self.s)['achieved'])

    def test_exit_unlock_requires_guard_clear(self):
        self.s['units'][1]['hp']=0
        self.c.update(self.s,{})
        self.assertIn('secure_exit',self.c.options(observation(self.s,self.s['units'][0],[])))
    def test_commander_uses_shared_role_and_actual_encounter(self):
        self.c.request_plan(self.s,self.s['units'][:1],{},[])
        role,context=self.game.calls[-1]
        self.assertEqual(role,'commander')
        self.assertEqual(context['mission']['details']['defenders'],['red-1'])
        self.assertIn('不是占旗',context['mission']['goal'])

    def test_assigned_route_survives_replan_and_advances_only_on_arrival(self):
        self.c.install('flank_pressure',{'green-1':'flank'},self.s['units'][:1],'deepseek_commander')
        task=self.c.plan['tasks']['green-1']
        self.assertEqual(task['waypoint'],0)
        self.c.update(self.s,{})
        self.assertEqual(task['waypoint'],0)
        self.s['units'][0]['position']=[.3,-1]
        self.c.update(self.s,{})
        self.assertEqual(task['waypoint'],1)
        self.c.install('flank_pressure',{'green-1':'flank'},self.s['units'][:1],'deepseek_commander')
        self.assertEqual(self.c.plan['tasks']['green-1']['waypoint'],1)
        opts=self.c.options(observation(self.s,self.s['units'][0],[]))
        self.assertEqual(opts['task_waypoint']['command']['position'],[1,-1])
        # Route progress persists, but does not forbid a local engine movement option.
        self.assertIn('advance_0',opts)
        self.assertEqual(self.c.plan['tasks']['green-1']['waypoint'],1)

    def test_fixed_scenario_uses_identical_persistent_task_logic(self):
        self.s.pop('world_growth')
        self.c.authored_routes={'left':{'name':'左路','points':[[.3,-1],[1,-1]]}}
        self.c.update(self.s,{})
        self.c.install('flank_pressure',{'green-1':'left'},self.s['units'][:1],'deepseek_commander')
        self.s['units'][0]['position']=[.3,-1]
        self.c.update(self.s,{})
        self.assertEqual(self.c.plan['tasks']['green-1']['waypoint'],1)
        self.assertEqual(self.c.scenario['kind'],'capture')

    def test_commander_selects_complete_non_conflicting_formation(self):
        import copy
        members=[copy.deepcopy(self.s['units'][0]) for _ in range(3)]
        for i,u in enumerate(members):u['id']='green-'+str(i+1)
        style,tasks=self.c.request_plan(self.s,members,{},[])
        self.assertEqual(len(tasks),3)
        self.assertEqual(len(set(tasks.values())),3)
        self.assertIn('flank',tasks.values())

if __name__=='__main__':unittest.main()
