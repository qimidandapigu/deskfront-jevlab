"""Spatial facts expire when the native map or unit position changes."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path.insert(0, str(DESKFRONT_TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'deskfront'))
from spatial_queries import read_queries
from tactics import Coordination


class SpatialQueryFreshnessChecks(unittest.TestCase):
    def test_paused_opening_one_tick_skew_preserves_other_guards(self):
        unit={'id':'green-1','position':[0.1,0.2]}
        state={'run_id':'round-1','time':0,'navigation_revision':4,
               'paused':False,'spatial_clock_paused':True}
        report={'run_id':'round-1','time':1/60,'navigation_revision':4,
                'units':{'green-1':{'origin':unit['position']}}}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'spatial.json'
            path.write_text(json.dumps(report),encoding='utf-8')
            self.assertTrue(read_queries(path,state,unit))
            for change in ({'spatial_clock_paused':False},{'run_id':'other'},
                           {'navigation_revision':5},{'time':3}):
                self.assertEqual(read_queries(path,dict(state,**change),unit),{})
            self.assertEqual(read_queries(path,state,dict(unit,position=[1,1])),{})
            report['time']=.04
            path.write_text(json.dumps(report),encoding='utf-8')
            self.assertEqual(read_queries(path,state,unit),{})

    def test_unit_observation_uses_full_snapshot_revision_for_jev_query(self):
        unit={'id':'green-1','position':[0.1,0.2]}
        report={'run_id':'round-1','time':12.0,'navigation_revision':4,
                'units':{'green-1':{'origin':unit['position'],'current_threats':['red-1']}}}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'spatial.json'
            path.write_text(json.dumps(report),encoding='utf-8')
            coordination=Coordination(Mock(),'green','mock')
            self.addCleanup(coordination.close)
            coordination.spatial_path=str(path)
            coordination.world={'navigation_revision':4}
            observation={'run_id':'round-1','time':12.0,'self':unit}
            self.assertEqual(coordination.spatial(observation)['current_threats'],['red-1'])
            coordination.world['navigation_revision']=5
            self.assertEqual(coordination.spatial(observation),{})

    def test_cover_ray_is_advisory_and_invalid_after_map_change(self):
        unit = {'id': 'green-1', 'position': [0.1, 0.2]}
        state = {'run_id': 'round-1', 'time': 12.0, 'navigation_revision': 4}
        evidence = {'origin': unit['position'], 'cover_selection': 'reference_only',
                    'cover_firing_positions': [{'slot_key': 'wall-1', 'position': [0.2, 0.2],
                                                'targets_from_peek': ['red-1'], 'available': True}]}
        report = {'run_id': state['run_id'], 'time': state['time'],
                  'navigation_revision': state['navigation_revision'], 'units': {unit['id']: evidence}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'spatial.json'
            path.write_text(json.dumps(report), encoding='utf-8')
            read = read_queries(path, state, unit)
            self.assertEqual(read['cover_firing_positions'], evidence['cover_firing_positions'])
            self.assertEqual(read['navigation_revision'], 4)
            self.assertNotIn('action', read)
            self.assertEqual(read_queries(path, {**state, 'navigation_revision': 5}, unit), {})
            self.assertEqual(read_queries(path, state, {**unit, 'position': [0.3, 0.2]}), {})
            self.assertEqual(read_queries(path, {**state, 'time': 14.1}, unit), {})


if __name__ == '__main__':
    unittest.main()
