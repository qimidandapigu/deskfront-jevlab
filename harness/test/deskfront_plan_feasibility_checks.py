"""Commander feasibility view reports evidence without choosing orders."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'deskfront'))
from plan_feasibility import build


class PlanFeasibilityChecks(unittest.TestCase):
    def setUp(self):
        self.g1=dict(id='green-1',faction='green',hp=50,position=[0,0],
                     weapon='rocket',weapon_range=.7,last_shot_at=-10,last_shot_target='')
        self.g2=dict(id='green-2',faction='green',hp=50,position=[0,.2],
                     weapon='rifle',weapon_range=.6,last_shot_at=-10,last_shot_target='')
        self.r1=dict(id='red-1',faction='red',hp=50,position=[1.4,0])
        self.r2=dict(id='red-2',faction='red',hp=50,position=[1.5,.2])
        self.state=dict(time=20,units=[self.g1,self.g2,self.r1,self.r2])
        self.regions={
            'rear':dict(center=[0,0],bounds=[-.2,-.2,.3,.3]),
            'forward':dict(center=[1,0],bounds=[.8,-.2,1.2,.3])}
        self.opportunities=dict(query_status={'green-1':'fresh','green-2':'stale'},
                                regions={
                                    'rear':dict(opportunities={}),
                                    'forward':dict(opportunities={'green-1':[
                                        dict(kind='firing',samples=2,targets=['red-1']),
                                        dict(kind='cover_firing',samples=1,available_samples=1,
                                             targets=['red-2'],available_targets=['red-2'])]})})

    def view(self,plan=None,feedback=None,members=None):
        return build(self.state,plan or {},self.regions,self.opportunities,
                     feedback or {},members=members)

    def test_first_plan_has_range_and_sampled_fire_facts_for_each_member(self):
        result=self.view(members=[self.g1,self.g2])
        self.assertEqual(set(result['units']),{'green-1','green-2'})
        one=result['units']['green-1']
        self.assertNotIn('assignment',one)
        self.assertEqual(one['enemy_range_gaps']['red-1'],.7)
        self.assertEqual(one['sampled_fire_regions'][0]['region'],'forward')
        self.assertEqual(one['sampled_fire_regions'][0]['firing_targets'],['red-1'])
        self.assertEqual(one['sampled_fire_regions'][0]['peek_targets'],['red-2'])
        self.assertNotIn('execution',one)
        two=result['units']['green-2']
        self.assertEqual(two['query_status'],'stale')
        self.assertEqual(two['sampled_fire_regions'],[])
        self.assertIn('unknown',result['basis'])

    def test_assigned_rear_area_shows_gap_and_unknown_sample_not_impossibility(self):
        plan=dict(tasks={'green-1':dict(command='support',target_id='red-1',region_hint='rear')})
        one=self.view(plan,members=[self.g1])['units']['green-1']
        self.assertEqual(one['assignment']['current_target_gap'],.7)
        self.assertEqual(one['assignment']['hint_center_gap'],.7)
        self.assertEqual(one['assignment']['hint_sample_status'],
                         'unknown_no_target_sample')
        self.assertEqual(one['sampled_fire_regions'][0]['region'],'forward')

    def test_assignment_overlap_and_actual_fire_are_separate_facts(self):
        plan=dict(tasks={
            'green-1':dict(command='support',target_id='red-1',region_hint='rear'),
            'green-2':dict(command='flank',target_id='red-1',region_hint='rear')})
        self.g1.update(last_shot_at=19,last_shot_target='red-1')
        feedback={'green-2':dict(no_shot_seconds=15,task_execution=dict(phase='waiting'))}
        result=self.view(plan,feedback,members=[self.g1,self.g2])['units']
        self.assertTrue(result['green-1']['execution']['recent_assigned_target_shot'])
        self.assertFalse(result['green-2']['execution']['recent_assigned_target_shot'])
        self.assertEqual(result['green-2']['execution']['no_observed_shot_s'],15)
        self.assertEqual(result['green-2']['execution']['task_phase'],'waiting')
        self.assertEqual(result['green-1']['overlaps']['same_target'],['green-2'])
        self.assertEqual(result['green-1']['overlaps']['same_hint_region'],['green-2'])

    def test_stale_samples_cannot_be_claimed_for_hint_area(self):
        self.opportunities['query_status']['green-1']='stale'
        plan=dict(tasks={'green-1':dict(command='support',target_id='red-1',region_hint='forward')})
        one=self.view(plan,members=[self.g1])['units']['green-1']
        self.assertEqual(one['assignment']['hint_sample_status'],'unknown_query_stale')
        self.assertNotIn('hint_firing_targets',one['assignment'])
        self.assertEqual(one['sampled_fire_regions'],[])

    def test_remote_firing_is_separate_coarse_sample_not_confirmed_local_lane(self):
        self.opportunities['regions']['rear']['opportunities']={
            'green-1':[dict(kind='remote_firing',samples=3,targets=['red-1'])]}
        plan=dict(tasks={'green-1':dict(command='support',target_id='red-1',region_hint='rear')})
        result=self.view(plan,members=[self.g1])
        one=result['units']['green-1']
        self.assertEqual(one['assignment']['hint_sample_status'],
                         'sampled_remote_target_candidate')
        self.assertEqual(one['assignment']['hint_remote_targets'],['red-1'])
        self.assertNotIn('hint_firing_targets',one['assignment'])
        self.assertEqual(one['sampled_fire_regions'][0]['remote_targets'],['red-1'])
        self.assertIn('远端粗采样',result['basis'])

    def test_query_ids_identify_members_before_first_plan_and_inputs_stay_unchanged(self):
        before=copy.deepcopy((self.state,self.regions,self.opportunities))
        result=self.view()
        self.assertEqual(set(result['units']),{'green-1','green-2'})
        self.assertEqual((self.state,self.regions,self.opportunities),before)

    def test_dead_assigned_target_is_reported_without_inventing_range(self):
        self.r1['hp']=0
        plan=dict(tasks={'green-1':dict(command='support',target_id='red-1',region_hint='rear')})
        one=self.view(plan,members=[self.g1])['units']['green-1']
        self.assertEqual(one['assignment']['target_status'],'not_live_in_snapshot')
        self.assertNotIn('current_target_gap',one['assignment'])


if __name__=='__main__':
    unittest.main()
