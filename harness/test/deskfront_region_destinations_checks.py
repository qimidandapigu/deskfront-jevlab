import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from region_destinations import build


class RegionDestinationsChecks(unittest.TestCase):
    def setUp(self):
        cells = {'a':[0,0], 'b':[.6,0], 'c':[1.2,0], 'd':[1.8,0], 'e':[2.4,0],
                 'b2':[.6,.15], 'c2':[1.2,.15]}
        self.regions = {key:dict(id=key, center=[n*.6,.2], cells=[cells[key.lower()]], sample_step=.075)
                        for n,key in enumerate('ABCDE')}
        self.regions['B']['sample_step'] = .15
        self.regions['C']['sample_step'] = .15
        self.regions['B']['cells'].append(cells['b2'])
        self.regions['C']['cells'].append(cells['c2'])
        self.unit = dict(id='g1', faction='green', hp=50, position=[0,0])
        self.allies = [self.unit]
        self.state = dict(time=10, navigation_revision=2,
                          strategic_topology=dict(cells=cells, edges=[], step=.075),
                          objective=dict(position=[2.4,0], radius=.17), units=[self.unit])
        self.spatial = dict(sampled_at=10, origin=[0,0], navigation_revision=2,
                            remote_firing_positions=[dict(cell_id='c', position=[1.2,0], targets=['r1'],
                                                          observed_at=10, reachable=True,
                                                          risk=dict(status='sampled', travel_s=2.4,
                                                                    exposed_s=1.2, peak_attackers=1))])
        self.routes = dict(query_status={'g1':'fresh'}, route_options={'g1':[
            dict(goal_region='D', region_path=['A','B','C','D'], first_step=dict(position=[.6,0]))]})

    def test_exact_remote_fire_and_native_path_are_facts_not_route_commands(self):
        result = build(self.unit, self.state, self.regions, self.routes, self.spatial,
                       {'target_id':'r1', 'region_hint':'B'}, self.allies)
        options = result['options']
        self.assertEqual([row['region_id'] for row in options], ['C','B','E','D'])
        self.assertEqual(options[0]['position'], [1.2,0])
        self.assertEqual(options[0]['source'], 'remote_firing')
        self.assertEqual(options[0]['fire_evidence'], 'sampled_standing_ray')
        self.assertEqual(options[0]['path_evidence']['status'], 'sampled')
        self.assertEqual(options[0]['path_evidence']['exposed_s'], 1.2)
        self.assertEqual(options[1]['path_evidence']['status'], 'unknown')
        self.assertEqual(options[1]['fire_evidence'], 'unknown')
        for row in options:
            self.assertNotIn('region_path', row)
            self.assertNotIn('first_step', row)
            self.assertNotIn('score', row)

    def test_region_center_is_not_assumed_walkable_and_reservations_exclude_points(self):
        # B's center is deliberately in an unsampled gap; native cells are at y=0/.15.
        self.allies.append(dict(id='g2', position=[.6,0], reserved_position=[1.2,0]))
        result = build(self.unit, self.state, self.regions, self.routes, self.spatial,
                       {'region_hint':'B'}, self.allies)
        options = result['options']
        self.assertNotIn('C', [row['region_id'] for row in options])
        self.assertEqual(next(row for row in options if row['region_id']=='B')['position'], [.6,.15])
        self.assertNotIn([.6,.2], [row['position'] for row in options])
        self.assertNotIn([1.2,0], [row['position'] for row in options])

    def test_stale_or_changed_query_does_not_claim_fire_or_path(self):
        for patch,status in [({'sampled_at':7},'stale'), ({'origin':[.4,0]},'origin_changed'),
                             ({'navigation_revision':3},'navigation_changed')]:
            spatial=copy.deepcopy(self.spatial);spatial.update(patch)
            result=build(self.unit,self.state,self.regions,self.routes,spatial,
                         {'region_hint':'B'},self.allies)
            self.assertEqual(result['query_status'],status)
            self.assertTrue(all(row['fire_evidence']=='unknown' and row['path_evidence']['status']=='unknown'
                                for row in result['options']))

    def test_known_unreachable_exact_sample_is_not_offered(self):
        self.spatial['navigation_steps']=[dict(position=[.6,0],risk=dict(status='unreachable'))]
        result=build(self.unit,self.state,self.regions,self.routes,self.spatial,
                     {'region_hint':'B'},self.allies)
        self.assertEqual(next(row for row in result['options'] if row['region_id']=='B')['position'],[.6,.15])

    def test_explicit_future_reservation_and_four_option_cap(self):
        self.state['position_reservations']={'g2':dict(unit_id='g2',position=[.6,0])}
        result=build(self.unit,self.state,self.regions,self.routes,self.spatial,
                     {'region_hint':'B'},self.allies)
        self.assertLessEqual(len(result['options']),4)
        self.assertEqual(next(row for row in result['options'] if row['region_id']=='B')['position'],[.6,.15])
        self.assertEqual(len({row['region_id'] for row in result['options']}),len(result['options']))

    def test_no_native_topology_means_no_fabricated_destination(self):
        self.state['strategic_topology']['cells']={}
        result=build(self.unit,self.state,self.regions,self.routes,self.spatial,{'region_hint':'B'},self.allies)
        self.assertEqual(result['options'],[])
        self.assertEqual(result['reason'],'no_native_topology_or_unit_position')

    def test_flag_between_cells_uses_nearby_sample_inside_capture_radius(self):
        self.state['objective']['position']=[2.43,.04]
        result=build(self.unit,self.state,self.regions,self.routes,self.spatial,{},self.allies)
        flag=next(row for row in result['options'] if 'objective' in row['tags'])
        self.assertEqual(flag['position'],[2.4,0])
        self.assertEqual(flag['source'],'objective')
        self.assertEqual(flag['path_evidence']['status'],'unknown')

    def test_read_only(self):
        before=copy.deepcopy((self.unit,self.state,self.regions,self.routes,self.spatial,self.allies))
        build(self.unit,self.state,self.regions,self.routes,self.spatial,{'region_hint':'B'},self.allies)
        self.assertEqual((self.unit,self.state,self.regions,self.routes,self.spatial,self.allies),before)


if __name__ == '__main__':
    unittest.main()
