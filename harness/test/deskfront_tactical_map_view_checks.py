import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from tactical_map_view import build


class TacticalMapViewChecks(unittest.TestCase):
    def test_world_axes_and_overlays_are_readable_without_inventing_walkability(self):
        state=dict(bounds=[0,0,4,3],strategic_topology=dict(step=1,cells={
            'a':[.5,.5],'b':[1.5,.5],'c':[2.5,.5],'d':[3.5,.5]}),
            covers=[dict(position=[1.5,.5],alive=True)],
            objective=dict(position=[2.5,1.5]),
            units=[dict(id='green-1',faction='green',hp=50,position=[.5,2.5]),
                   dict(id='green-2',faction='green',hp=50,position=[3.5,2.5]),
                   dict(id='red-1',faction='red',hp=50,position=[3.5,.5]),
                   dict(id='red-2',faction='red',hp=0,position=[.5,.5])])
        before=copy.deepcopy(state)
        result=build(state,max_cols=4,max_rows=3)
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['rows'],['.#.A','??F?','1??2'])
        self.assertEqual(result['cell_size_world'],1)
        self.assertIn('+x',result['axis'])
        self.assertIn('+z',result['axis'])
        self.assertEqual(result['legend']['1'],'green-1')
        self.assertEqual(result['legend']['A'],'red-1')
        self.assertNotIn('red-2',result['legend'].values())
        self.assertIn('无法从此图推断精确路线、射界、射程或安全',result['limitation'])
        self.assertEqual(state,before)

    def test_dynamic_topology_outside_stale_bounds_is_still_visible(self):
        state=dict(bounds=[0,0,1,1],strategic_topology=dict(step=.1,cells={
            'near':[.1,.1],'far':[5,2]}),covers=[],units=[],objective=dict(position=[5,2]))
        result=build(state)
        self.assertTrue(result['bounds_expanded'])
        self.assertEqual(result['bounds'],[0,0,5,2])
        self.assertLessEqual(result['cols'],40)
        self.assertLessEqual(result['row_count'],32)
        self.assertEqual(result['rows'][-1][-1],'F')
        self.assertEqual(len(result['rows']),result['row_count'])
        self.assertTrue(all(len(row)==result['cols'] for row in result['rows']))
        self.assertLess(len(json.dumps(result,ensure_ascii=False)),2600)

    def test_overlapping_units_and_flag_are_reported(self):
        state=dict(bounds=[0,0,1,1],strategic_topology=dict(step=.25,cells={'a':[.2,.2]}),
                   objective=dict(position=[.2,.2]),covers=[],
                   units=[dict(id='green-1',faction='green',hp=50,position=[.2,.2]),
                          dict(id='red-1',faction='red',hp=50,position=[.2,.2])])
        result=build(state)
        self.assertTrue(result['flag_under_unit'])
        self.assertEqual(result['stacked_units'][0]['unit_ids'],['green-1','red-1'])
        self.assertIn('*',''.join(result['rows']))

    def test_no_native_samples_yields_partial_map_not_fake_obstacle_claim(self):
        state=dict(bounds=[0,0,2,1],covers=[],objective=dict(position=[1,.5]),
                   units=[dict(id='green-1',faction='green',hp=50,position=[.2,.2])])
        result=build(state,max_cols=8,max_rows=4)
        self.assertEqual(result['status'],'partial_no_navigation_samples')
        self.assertIn('?', ''.join(result['rows']))
        self.assertIn('1', ''.join(result['rows']))
        self.assertIn('F', ''.join(result['rows']))
        self.assertEqual(build({})['status'],'no_geometry')

    def test_requested_dimensions_are_always_capped(self):
        state=dict(bounds=[0,0,100,100],strategic_topology=dict(step=.1,cells={'a':[.1,.1]}),
                   covers=[],units=[],objective={})
        result=build(state,max_cols=1000,max_rows=1000)
        self.assertEqual(result['cols'],32)
        self.assertEqual(result['row_count'],32)

    def test_more_units_than_one_character_palette_are_not_silently_dropped(self):
        units=[dict(id=f'green-{i}',faction='green',hp=50,position=[i/11,.5]) for i in range(1,11)]
        state=dict(bounds=[0,0,1,1],strategic_topology=dict(step=.1,cells={'a':[.1,.5]}),
                   units=units,covers=[],objective={})
        result=build(state)
        self.assertIn('green-10',result['other_units'])
        self.assertIn('@',result['legend'])


if __name__=='__main__':unittest.main()
