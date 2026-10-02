import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from approach_corridors import build


def grid_fixture(transform=lambda x,y:[x,y]):
    labels={(x,y):('L' if x==-1 else 'C' if x==0 else 'R')+str(y)
            for x in (-1,0,1) for y in (0,1,2)}
    positions={label:transform(x,y) for (x,y),label in labels.items()}
    neighbors={key:[] for key in positions};edges=[]
    for (x,y),key in labels.items():
        for other in ((x+1,y),(x,y+1)):
            if other in labels:
                neighbor=labels[other]
                neighbors[key].append(neighbor);neighbors[neighbor].append(key)
                edges.append([key,neighbor])
    regions={key:dict(id=key,center=position,cells=[position],sample_step=.4,
                      neighbors=neighbors[key]) for key,position in positions.items()}
    unit=dict(id='g1',faction='green',hp=50,position=positions['C0'])
    state=dict(strategic_topology=dict(cells=positions,edges=edges,step=.1),
               objective=dict(position=positions['C2']),units=[unit])
    return state,[unit],regions


class ApproachCorridorsChecks(unittest.TestCase):
    def test_three_distinct_paths_are_relative_to_team_advance(self):
        state,members,regions=grid_fixture()
        before=copy.deepcopy((state,members,regions))
        result=build(state,members,regions)
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['origin_region'],'C0')
        self.assertEqual(result['objective_region'],'C2')
        self.assertEqual([row['side'] for row in result['corridors']],['center','left','right'])
        self.assertEqual(result['corridors'][0]['region_path'],['C0','C1','C2'])
        self.assertEqual(len({tuple(row['region_path']) for row in result['corridors']}),3)
        self.assertGreater(result['corridors'][1]['signed_lateral_offset'],0)
        self.assertLess(result['corridors'][2]['signed_lateral_offset'],0)
        for row in result['corridors']:
            self.assertEqual(row['region_path'][0],'C0')
            self.assertEqual(row['region_path'][-1],'C2')
            self.assertEqual(row['risk_status'],'unknown_full_route')
            self.assertEqual(row['sampled_far_fire']['status'],'unknown')
            self.assertNotIn('score',row)
            self.assertNotIn('command',row)
        self.assertEqual((state,members,regions),before)
        self.assertLess(len(json.dumps(result,ensure_ascii=False)),1900)

    def test_side_labels_rotate_with_advance_vector(self):
        state,members,regions=grid_fixture(lambda x,y:[y,-x])
        result=build(state,members,regions)
        self.assertEqual([row['side'] for row in result['corridors']],['center','left','right'])
        self.assertGreater(result['corridors'][1]['signed_lateral_offset'],0)
        self.assertLess(result['corridors'][2]['signed_lateral_offset'],0)

    def test_far_fire_only_uses_fresh_sampled_regions(self):
        state,members,regions=grid_fixture()
        evidence=dict(query_status={'g1':'fresh'},regions={
            'L2':dict(opportunities={'g1':[dict(kind='firing',targets=['red-1'])]}),
            'R2':dict(opportunities={'g1':[dict(kind='cover_firing',available_targets=['red-2'])]})})
        result=build(state,members,regions,evidence)
        left=next(row for row in result['corridors'] if row['side']=='left')
        right=next(row for row in result['corridors'] if row['side']=='right')
        self.assertEqual(left['sampled_far_fire']['targets'],['red-1'])
        self.assertEqual(right['sampled_far_fire']['targets'],['red-2'])
        evidence['query_status']['g1']='stale'
        stale=build(state,members,regions,evidence)
        self.assertTrue(all(row['sampled_far_fire']['status']=='unknown' for row in stale['corridors']))

    def test_disconnected_or_missing_topology_does_not_invent_corridor(self):
        state,members,regions=grid_fixture()
        state['strategic_topology'].pop('edges')
        result=build(state,members,regions)
        self.assertEqual(result['corridors'],[])
        self.assertEqual(result['reason'],'native_connected_regions_unavailable')
        state,members,regions=grid_fixture()
        regions['C1']['neighbors']=[]
        regions['L0']['neighbors']=[]
        regions['R0']['neighbors']=[]
        result=build(state,members,regions)
        self.assertEqual(result['corridors'],[])
        self.assertEqual(result['reason'],'objective_disconnected')

    def test_single_connected_lane_is_honestly_one_corridor(self):
        state,members,regions=grid_fixture()
        for key in list(regions):
            if key.startswith(('L','R')):regions.pop(key)
        for region in regions.values():
            region['neighbors']=[key for key in region['neighbors'] if key in regions]
        result=build(state,members,regions)
        self.assertEqual([row['side'] for row in result['corridors']],['center'])


if __name__=='__main__':unittest.main()
