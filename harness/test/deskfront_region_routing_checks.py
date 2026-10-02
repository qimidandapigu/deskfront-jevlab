import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from region_routing import local_move_allowed, next_region_step, validate_region_path


def fixture():
    # Two routes from A to D: the commander selects the longer A-B-C-D rim;
    # the center X is shorter but must never be silently substituted.
    positions = {'a':[0,0], 'b':[0,.1], 'b2':[0,.2], 'c':[.1,.2],
                 'c2':[.2,.2], 'd':[.2,.1], 'x':[.1,0], 'x2':[.2,0]}
    edges = [['a','b'], ['b','b2'], ['b2','c'], ['c','c2'], ['c2','d'],
             ['a','x'], ['x','x2'], ['x2','d']]
    groups = {'A':['a'], 'B':['b','b2'], 'C':['c','c2'], 'D':['d'], 'X':['x','x2']}
    regions = {r:dict(id=r,cells=[positions[k] for k in keys],sample_step=.1,neighbors=[]) for r,keys in groups.items()}
    owners = {k:r for r,keys in groups.items() for k in keys}
    for a,b in edges:
        if owners[a] != owners[b]:
            for x,y in ((owners[a],owners[b]), (owners[b],owners[a])):
                if y not in regions[x]['neighbors']:regions[x]['neighbors'].append(y)
    return dict(cells=positions,edges=edges,step=.1), regions, dict(region_id='D',region_path=['A','B','C','D'])


class RegionRoutingChecks(unittest.TestCase):
    def setUp(self):self.topology,self.regions,self.task=fixture()

    def test_explicit_route_accepts_current_or_adjacent_start(self):
        self.assertEqual(validate_region_path(['B','C','D'],'D',self.regions,[0,0]), ['B','C','D'])
        self.assertEqual(validate_region_path(self.task['region_path'],'D',self.regions,[0,0]),self.task['region_path'])

    def test_rejects_unknown_disconnected_wrong_end_and_remote_entry(self):
        for path,end,pos in [(['Z'],'Z',None), (['A','D'],'D',None), (['A','B'],'D',None), (['C','D'],'D',[0,0])]:
            with self.assertRaises(ValueError):validate_region_path(path,end,self.regions,pos)

    def test_longer_rim_is_not_replaced_by_shorter_center(self):
        row=next_region_step([0,0],self.task,self.topology,self.regions)
        self.assertEqual(row['status'],'ready')
        self.assertEqual(row['position'],[0,.1])
        self.assertNotIn('x',row['path_cells'])
        self.assertEqual(row['path_regions'],['A','B'])
        self.assertEqual(row['risk_status'],'unknown')

    def test_progress_requires_actual_entry_and_tracks_each_region(self):
        next_region_step([0,0],self.task,self.topology,self.regions)
        self.assertEqual(self.task['_region_progress']['index'],1)
        next_region_step([0,0],self.task,self.topology,self.regions)
        self.assertEqual(self.task['_region_progress']['index'],1)
        row=next_region_step([0,.1],self.task,self.topology,self.regions)
        self.assertEqual(row['next_region'],'C')
        self.assertEqual(row['position'],[0,.2])  # Stop before turn, never cut it.
        self.assertEqual(self.task['_region_progress']['entered'],['A','B'])
        next_region_step([.1,.2],self.task,self.topology,self.regions)
        row=next_region_step([.2,.1],self.task,self.topology,self.regions)
        self.assertEqual(row['status'],'arrived')
        self.assertEqual(row['entered'],['A','B','C','D'])

    def test_jump_to_future_region_does_not_complete_intermediate_regions(self):
        next_region_step([0,0],self.task,self.topology,self.regions)
        row=next_region_step([.2,.1],self.task,self.topology,self.regions)
        self.assertEqual(row['status'],'blocked')
        self.assertEqual(row['index'],1)
        self.assertEqual(row['entered'],['A'])

    def test_reservation_blocks_narrow_corridor_without_center_fallback(self):
        row=next_region_step([0,0],self.task,self.topology,self.regions,[[0,.1]])
        self.assertEqual(row['status'],'blocked')
        self.assertEqual(row['reason'],'corridor_reserved_or_disconnected')

    def test_reservation_can_use_another_lane_inside_same_corridor(self):
        t=self.topology;r=self.regions
        t['cells'].update(a2=[-.1,0],b3=[-.1,.1]);t['edges'] += [['a','a2'],['a2','b3'],['b3','b']]
        r['A']['cells'].append([-.1,0]);r['B']['cells'].append([-.1,.1])
        row=next_region_step([0,0],self.task,t,r,[[0,.1]])
        self.assertEqual(row['status'],'ready')
        self.assertEqual(row['position'],[-.1,0])
        self.assertNotIn('x',row['path_cells'])

    def test_retreat_retraces_visited_regions_instead_of_skipping(self):
        for p in ([0,0],[0,.1],[.1,.2]):next_region_step(p,self.task,self.topology,self.regions)
        row=next_region_step([0,0],self.task,self.topology,self.regions)
        self.assertEqual(row['index'],3)
        self.assertEqual(row['next_region'],'B')
        self.assertEqual(row['position'],[0,.1])

    def test_changed_path_resets_progress(self):
        for p in ([0,0],[0,.1]):next_region_step(p,self.task,self.topology,self.regions)
        self.task['region_path']=['A','X','D']
        row=next_region_step([0,0],self.task,self.topology,self.regions)
        self.assertEqual(row['next_region'],'X')
        self.assertEqual(row['entered'],['A'])

    def test_unknown_region_after_topology_update_is_explicit_blocker(self):
        del self.regions['B']
        row=next_region_step([0,0],self.task,self.topology,self.regions)
        self.assertEqual(row['reason'],'invalid_region_path')

    def test_missing_native_edge_cannot_be_replaced_by_region_adjacency_claim(self):
        self.topology['edges'].remove(['a','b'])
        row=next_region_step([0,0],self.task,self.topology,self.regions)
        self.assertEqual(row['reason'],'corridor_disconnected')

    def test_native_arrival_offset_does_not_resubmit_nearby_grid_center(self):
        # The native engine can finish .024 from the center. It must still get
        # a forward point, rather than a .024 move that keep_move turns to wait.
        position=[0,.024]
        row=next_region_step(position,self.task,self.topology,self.regions)
        self.assertEqual(row['status'],'ready')
        self.assertEqual(row['position'],[0,.1])
        self.assertGreater(math.dist(position,row['position']),.055)
        self.assertFalse(row['requires_precise_arrival'])

    def test_off_axis_sample_offset_can_advance_in_verified_corridor(self):
        position=[-.035,0]
        row=next_region_step(position,self.task,self.topology,self.regions)
        self.assertEqual(row['status'],'ready')
        self.assertEqual(row['position'],[0,.1])
        self.assertTrue(local_move_allowed(position,row['position'],row['path_regions'],self.regions))

    def test_arrived_short_of_sample_continues_after_region_entry(self):
        next_region_step([0,0],self.task,self.topology,self.regions)
        row=next_region_step([0,.076],self.task,self.topology,self.regions)
        self.assertEqual(row['status'],'ready')
        self.assertEqual(row['next_region'],'C')
        self.assertEqual(row['position'],[0,.2])

    def test_necessary_move_inside_harness_radius_is_explicitly_precise(self):
        topology=dict(cells={'a':[0,0],'b':[.075,0]},edges=[['a','b']],step=.075)
        regions={key:dict(cells=[p],sample_step=.075,neighbors=['B' if key=='A' else 'A'])
                 for key,p in [('A',[0,0]),('B',[.075,0])]}
        task=dict(region_id='B',region_path=['A','B'])
        row=next_region_step([.03,0],task,topology,regions)
        self.assertEqual(row['status'],'ready')
        self.assertEqual(row['position'],[.075,0])
        self.assertTrue(row['requires_precise_arrival'])
        self.assertLessEqual(row['arrival_radius'],.015)

    def test_shortcuts_across_unsampled_corner_are_rejected(self):
        regions={'A':dict(cells=[[0,0],[0,.075],[.075,.075]],sample_step=.075)}
        self.assertFalse(local_move_allowed([.035,-.035],[.075,.075],['A'],regions))


if __name__ == '__main__':unittest.main()
