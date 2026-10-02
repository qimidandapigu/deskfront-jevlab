import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from commander_plan import progress, validate
from strategic_regions import catalog


class CommanderRouteChecks(unittest.TestCase):
    def setUp(self):
        self.unit=dict(id='green-1',faction='green',hp=50,position=[0,0])
        self.state=dict(time=0,bounds=[-.5,-.5,2,1],units=[self.unit],objective=dict(position=[1.2,0],score_to_win=60),
            strategic_topology=dict(cells={'0,0':[0,0],'8,0':[.6,0],'16,0':[1.2,0]},
                                    edges=[['0,0','8,0'],['8,0','16,0']],step=.075))
        self.regions=catalog({},self.state)
        self.path=['N0,0','N8,0','N16,0']
        self.task=dict(region_id=self.path[-1],region_path=list(self.path),command='flank',
            target_id='',partner='',start_when='immediate',wait_timeout_s=5,on_failure='reassess',
            assignment='经指定相邻区域到达当前准备区',complete_when=dict(type='position_reached'),replan_when='通路受阻或火力威胁上升')
        self.plan=dict(objective='控制目标',stage=dict(id='prepare',goal='先到准备区',next_intent='依据火力决定下一阶段'),
                       intent='按区域顺序接近',tasks={'green-1':self.task})

    def validate(self):return validate(self.plan,[self.unit],self.state,{})

    def test_hold_contract_changes_with_mode_and_progress_invalidates_old_task(self):
        from task_modes import instructions
        from commander_plan import INSTRUCTIONS
        enemy=dict(id='red-1',faction='red',hp=50,position=[1,0])
        self.state['units'].append(enemy)
        self.task.update(command='hold',target_id='red-1',complete_when={'type':'target_dead'})
        with self.assertRaises(ValueError):self.validate()
        self.state['world_growth']={'enabled':True}
        task=self.validate()['tasks']['green-1']
        self.assertEqual(task['task_mode'],'clear_exit')
        self.assertFalse(progress(task,self.unit,self.state)['achieved'])
        enemy['hp']=0
        self.assertTrue(progress(task,self.unit,self.state)['achieved'])
        self.state.pop('world_growth')
        self.assertTrue(progress(task,self.unit,self.state)['invalidated'])
        self.state['task_mode']='clear_exit'
        self.assertNotIn('flag_held',instructions(INSTRUCTIONS,self.state))
        self.task['complete_when']={'type':'flag_held','value':10}
        self.task['target_id']=''
        with self.assertRaises(ValueError):self.validate()
        self.state['task_mode']='unknown'
        with self.assertRaisesRegex(ValueError,'unknown task mode'):self.validate()

    def test_support_requires_named_beneficiary_or_enemy_when_enemy_known(self):
        self.state['units'].append(dict(id='red-1',faction='red',hp=50,position=[1,0]))
        self.task['command']='support'
        with self.assertRaisesRegex(ValueError,'support requires a named'):self.validate()
        self.task['target_id']='red-1'
        result=self.validate()['tasks']['green-1']
        self.assertEqual(result['actor_id'],'green-1')
        self.assertEqual(result['target_id'],'red-1')
        self.task['actor_id']='green-2'
        with self.assertRaisesRegex(ValueError,'actor_id must match'):self.validate()

    def test_explicit_region_sequence_survives_validation_without_named_route(self):
        result=self.validate()['tasks']['green-1']
        self.assertEqual(result['region_path'],self.path)
        self.assertEqual(result['route'],'adaptive')
        self.assertEqual(result['region_id'],self.path[-1])
        self.assertNotIn('position',self.task['complete_when'])  # No input mutation.

    def test_explicit_destination_requires_explicit_path(self):
        del self.task['region_path']
        with self.assertRaisesRegex(ValueError,'green-1: region_id and region_path must be supplied together'):self.validate()

    def test_strategic_task_can_leave_region_and_route_to_jev(self):
        del self.task['region_id'];del self.task['region_path']
        self.task.update(command='support',target_id='',assignment='为前排建立真实火力支援')
        result=self.validate()['tasks']['green-1']
        self.assertNotIn('region_id',result)
        self.assertNotIn('region_path',result)
        self.assertNotIn('destination_area',result)
        self.assertEqual(result['complete_when'],{'type':'position_reached'})
        self.assertFalse(progress(result,self.unit,self.state)['achieved'])

    def test_strategic_region_hint_does_not_become_destination(self):
        del self.task['region_id'];del self.task['region_path']
        self.task['region_hint']=self.path[-1]
        result=self.validate()['tasks']['green-1']
        self.assertEqual(result['region_hint'],self.path[-1])
        self.assertNotIn('region_id',result)
        self.assertNotIn('destination_area',result)

    def test_made_up_region_hint_is_rejected(self):
        del self.task['region_id'];del self.task['region_path']
        self.task['region_hint']='made_up'
        with self.assertRaisesRegex(ValueError,'green-1: unknown region_hint'):self.validate()

    def test_path_without_destination_is_rejected(self):
        del self.task['region_id']
        with self.assertRaisesRegex(ValueError,'green-1: region_id and region_path must be supplied together'):self.validate()

    def test_strategic_position_cannot_invent_coordinate(self):
        del self.task['region_id'];del self.task['region_path']
        self.task['complete_when']['position']=[1.2,0]
        with self.assertRaisesRegex(ValueError,'JEV selects the position'):self.validate()

    def test_strategic_position_cannot_hide_hard_region_as_completion(self):
        del self.task['region_id'];del self.task['region_path']
        self.task['complete_when']['position']=self.path[-1]
        with self.assertRaisesRegex(ValueError,'JEV selects the position'):self.validate()

    def test_adjacent_entry_does_not_require_repeating_current_region(self):
        self.task['region_path']=self.path[1:]
        self.assertEqual(self.validate()['tasks']['green-1']['region_path'],self.path[1:])

    def test_stay_in_current_region_uses_single_entry(self):
        self.task.update(region_id=self.path[0],region_path=self.path[:1],command='hold',complete_when=dict(type='flag_held',value=10))
        self.assertEqual(self.validate()['tasks']['green-1']['region_path'],self.path[:1])

    def test_cannot_skip_disconnected_intermediate_region(self):
        self.task['region_path']=[self.path[0],self.path[-1]]
        with self.assertRaisesRegex(ValueError,'disconnected leg'):self.validate()

    def test_path_must_end_at_assigned_region(self):
        self.task['region_path']=self.path[:2]
        with self.assertRaisesRegex(ValueError,'must end at region_id'):self.validate()

    def test_remote_start_is_rejected_instead_of_implicit_shortest_path(self):
        self.task['region_path']=self.path[-1:]
        with self.assertRaisesRegex(ValueError,'current or an adjacent region'):self.validate()

    def test_unknown_area_reports_unit_and_bad_route(self):
        self.task['region_path']=[self.path[0],'made_up',self.path[-1]]
        with self.assertRaisesRegex(ValueError,'green-1: region_path contains an unknown region'):self.validate()

    def test_each_member_is_validated_from_its_own_position(self):
        other=dict(self.unit,id='green-2',position=[1.2,0])
        self.state['units'].append(other)
        self.plan['tasks']['green-2']=dict(copy.deepcopy(self.task),region_id=self.path[0],region_path=list(reversed(self.path)))
        result=validate(self.plan,[self.unit,other],self.state,{})
        self.assertEqual(result['tasks']['green-2']['region_path'],list(reversed(self.path)))
        self.plan['tasks']['green-2']['region_path']=self.path[:1]
        with self.assertRaisesRegex(ValueError,'green-2: region_path must begin'):validate(self.plan,[self.unit,other],self.state,{})

    def test_extra_confirmed_dead_member_is_dropped_without_changing_living_task(self):
        dead=dict(self.unit,id='green-2',hp=0,position=[1.2,0])
        self.state['units'].append(dead)
        self.plan['tasks']['green-2']=dict(copy.deepcopy(self.task),actor_id='green-2',
            target_id='made_up_target',partner='green-1')
        original=copy.deepcopy(self.plan)
        result=self.validate()
        self.assertEqual(set(result['tasks']),{'green-1'})
        self.assertEqual(result['tasks']['green-1']['region_path'],self.path)
        self.assertEqual(self.plan,original)

    def test_dead_extra_does_not_mask_missing_living_task(self):
        dead=dict(self.unit,id='green-2',hp=0)
        self.state['units'].append(dead)
        self.plan['tasks']={'green-2':copy.deepcopy(self.task)}
        with self.assertRaisesRegex(ValueError,'cover living squad exactly'):self.validate()

    def test_unknown_or_other_living_extra_is_not_dropped(self):
        for extra in (dict(self.unit,id='green-2',hp=50),dict(self.unit,id='red-2',faction='red',hp=0)):
            with self.subTest(extra=extra['id']):
                self.state['units'].append(extra)
                self.plan['tasks'][extra['id']]=copy.deepcopy(self.task)
                with self.assertRaisesRegex(ValueError,'cover living squad exactly'):self.validate()
                self.state['units'].pop()
                self.plan['tasks'].pop(extra['id'])

    def test_legacy_without_topology_keeps_existing_coordinate_contract(self):
        del self.state['strategic_topology']
        del self.task['region_id'];del self.task['region_path']
        self.task['complete_when']['position']=[1.2,0]
        result=self.validate()['tasks']['green-1']
        self.assertNotIn('region_path',result)
        self.assertEqual(result['complete_when']['position'],[1.2,0])

    def test_malformed_path_cannot_be_interpreted_as_named_tactic(self):
        for bad in ('left',[True],[],[{'id':self.path[0]}]):
            self.task['region_path']=bad
            with self.assertRaisesRegex(ValueError,'region_path'):self.validate()


if __name__ == '__main__':unittest.main()
