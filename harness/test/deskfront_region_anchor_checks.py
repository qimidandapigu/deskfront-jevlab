import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/deskfront'))
from strategic_regions import contains,memberships,navigation_anchor
from region_routing import next_region_step,validate_region_path,local_move_allowed


class RegionAnchorChecks(unittest.TestCase):
    def setUp(self):
        self.regions={'A':dict(cells=[[0,0],[.075,0]],sample_step=.075,neighbors=['B']),
                      'B':dict(cells=[[.15,0],[.225,0]],sample_step=.075,neighbors=['A'])}
        self.topology=dict(step=.075,cells={'0,0':[0,0],'1,0':[.075,0],'2,0':[.15,0],'3,0':[.225,0]},
                           edges=[['0,0','1,0'],['1,0','2,0'],['2,0','3,0']])

    def test_gap_anchor_does_not_change_actual_membership_or_arrival(self):
        position=[.075,.06]
        anchor=navigation_anchor(position,self.regions,self.topology)
        self.assertEqual(memberships(position,self.regions),[])
        self.assertEqual(anchor['observed_regions'],[])
        self.assertEqual(anchor['anchor_regions'],['A'])
        task=dict(region_id='A',region_path=['A'])
        step=next_region_step(position,task,self.topology,self.regions)
        self.assertEqual(step['status'],'ready')
        self.assertEqual(step['reason'],'origin_anchor_bridge')
        self.assertEqual(step['position'],[.075,0])
        self.assertEqual(task['_region_progress']['entered'],[])
        self.assertEqual(step['current_regions'],[])
        self.assertTrue(step['requires_native_validation'])
        arrived=next_region_step(step['position'],task,self.topology,self.regions)
        self.assertEqual(arrived['status'],'arrived')

    def test_plan_entry_uses_anchor_without_inventing_long_distance_route(self):
        self.assertEqual(validate_region_path(['A','B'],'B',self.regions,[.075,.06],self.topology),['A','B'])
        self.assertEqual(navigation_anchor([.075,.12],self.regions,self.topology)['anchor_regions'],['A'])
        self.assertEqual(navigation_anchor([.075,.1201],self.regions,self.topology)['anchor_regions'],[])
        with self.assertRaises(ValueError):validate_region_path(['A'],'A',self.regions,[.075,.1201],self.topology)

    def test_no_anchor_from_unverified_authored_center(self):
        regions={'A':dict(center=[0,0],radius=.01,neighbors=[])}
        self.assertEqual(navigation_anchor([.05,0],regions)['anchor_regions'],[])

    def test_origin_bridge_cannot_hide_a_wall_gap_later_in_path(self):
        anchor=navigation_anchor([.075,.06],self.regions,self.topology)
        self.assertTrue(local_move_allowed([.075,.06],[.075,0],['A'],self.regions,origin_bridge=anchor))
        self.assertFalse(local_move_allowed([.075,.06],[.225,0],['A','B'],self.regions,origin_bridge=anchor))
        # Being in one actual region is never treated as an unknown origin.
        self.assertFalse(local_move_allowed([0,0],[.225,0],['A'],self.regions,origin_bridge=anchor))

    def test_reserved_anchor_blocks_without_claiming_region_entry(self):
        task=dict(region_id='B',region_path=['A','B'])
        step=next_region_step([.075,.06],task,self.topology,self.regions,[[.075,0]])
        self.assertEqual(step['reason'],'origin_anchor_reserved')
        self.assertEqual(task['_region_progress']['entered'],[])


if __name__=='__main__':unittest.main()
