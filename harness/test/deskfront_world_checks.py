"""Tests the Harness boundary without provider calls or a fabricated engine."""
import copy
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
sys.path.insert(0, str(DESKFRONT_TOOLS))
from world.director import AXES, WorldDirector, MacroBridge, eligible_choices, CATALOG
from world.region_builder import encode_placement


CURRENT_PLACEMENT = encode_placement('code_laptop_island',270)


class Game:
    config = {'runtime': {'maxRequests': 5}}
    def __init__(self): self.calls = []; self.records = []; self.after_ask = None
    def ask(self, state, questions, role=None):
        self.calls.append((role, copy.deepcopy(state)))
        if self.after_ask: self.after_ask()
        answers={}
        for key,question in questions.items():
            menu=question['criteria']
            if key.startswith('template_'):
                if CURRENT_PLACEMENT not in menu:
                    raise AssertionError(f'current curated placement missing from {key}')
                choice=CURRENT_PLACEMENT
            else:
                choice=next(iter(menu))
            answers[key]={'type':'choice','choice':choice,'confidence':1,
                'probabilities':{option:int(option==choice) for option in menu}}
        return {'requestId':str(len(self.calls)),'answers':answers}
    def record(self, row): self.records.append(row)


class Checks(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        self.state = SimpleNamespace(lock=threading.Lock(), updated=time.monotonic(), instance_id='i', results={})
        self.state.state = dict(run_id='r', tick=100, time=10, paused=False, control={'green': 'game_ai'}, units=[
            dict(id='g', faction='green', hp=100, position=[0, 0])],
            world_growth=dict(enabled=True, revision=0, phase='ready', options=['gate_north_books_cross_tight'], completed=[]))
        self.submitted = []
        self.state.submit = lambda c: (self.submitted.append(c) or (202, {'id': 'cmd'}))
        self.director = WorldDirector(MacroBridge(self.state, self.game), self.game)
        self.director.observe(self.state.state)

    def step(self): return self.director.step(dict(run_id='r', instance_id='i'))

    def test_shared_roles_and_smoothing(self):
        self.state.state['world_growth']['phase']='encounter'
        self.director.analyze()
        self.assertAlmostEqual(self.director.hormones['expansion'],.4)
        self.state.state['world_growth']['phase']='ready'
        row=self.step()
        self.assertEqual([r[0] for r in self.game.calls],['experience_analyst',None,None,None])
        self.assertEqual(row['status'],'queued_not_completed')
        self.assertEqual(self.game.calls[1][1]['experience_report']['report_id'],'1')


    def test_battle_only_analyzes_and_clear_triggers_generation(self):
        w=self.state.state['world_growth'];w['phase']='encounter'
        with self.assertRaisesRegex(ValueError,'world_not_ready'):self.step()
        self.assertTrue(self.director.analyze())
        self.assertIsNone(self.director.prepared)
        self.assertFalse(self.submitted)
        w['phase']='ready'
        self.step()
        self.assertEqual(len(self.submitted),1)


    def test_prepared_revision_cannot_cross_worlds(self):
        w = self.state.state['world_growth']
        w.update(phase='ready', planning_options=w['options'])
        self.director.step(dict(run_id='r', instance_id='i', prepare=True))
        w.update(phase='ready', revision=1)
        self.assertFalse(self.director.commit_prepared())
        self.assertFalse(self.submitted)

    def test_observer_not_player(self):
        self.assertEqual(self.director.samples[0]['human_evidence'], [])

    def test_stale_revision_after_model_call(self):
        self.game.after_ask = lambda: self.state.state['world_growth'].update(revision=9)
        with self.assertRaisesRegex(ValueError, 'world_context_changed'): self.step()
        self.assertFalse(self.submitted)

    def test_pause_and_budget_prevent_requests(self):
        self.state.state['paused'] = True
        with self.assertRaisesRegex(ValueError, 'world_not_ready'): self.step()
        self.state.state['paused'] = False
        self.director.calls = 3
        with self.assertRaisesRegex(ValueError, 'budget'): self.step()
        self.assertFalse(self.game.calls)

    def test_receipt_is_not_completion(self):
        row = self.step()
        self.state.results['cmd'] = {'accepted': True}
        self.director.observe(self.state.state)
        self.assertEqual(row['status'], 'building')
        self.state.state['world_growth']['completed'] = [{'operation_id': row['operation_id'], 'spawned': []}]
        self.director.observe(self.state.state)
        self.assertEqual(row['status'], 'completed')

    def test_rejection_preserved(self):
        row = self.step()
        self.state.results['cmd'] = {'accepted': False, 'message': 'growth_revision_changed'}
        self.director.observe(self.state.state)
        self.assertEqual(row['status'], 'rejected')

    def test_late_construction_cancellation_is_not_completion(self):
        row = self.step()
        self.state.results['cmd'] = {'accepted': True}
        self.state.state['world_growth']['construction_failures'] = [
            {'operation_id': row['operation_id'], 'reason': 'site_occupied_before_commit'}]
        self.director.observe(self.state.state)
        self.assertEqual(row['status'], 'rejected')
        self.assertEqual(row['construction_failure']['reason'], 'site_occupied_before_commit')

    def test_repetition_and_layout_selection(self):
        world = dict(options=list(CATALOG), completed=[dict(option='gate_north_books_cross_tight', spawned=['red-100'])])
        self.assertEqual(len(eligible_choices(world)),48)
        self.assertTrue(all(not k.startswith('gate_') for k in eligible_choices(world)))

    def test_component_choices_and_hormones_change_actual_layout(self):
        from world.catalog import CATALOG as specs, eligible
        self.assertEqual(len(specs),64)
        base=specs['gate_north_books_cross_tight']
        self.assertNotEqual(base['covers'],specs['gate_north_books_cross_wide']['covers'])
        self.assertNotEqual(base['covers'],specs['court_north_books_cross_tight']['covers'])
        self.assertNotEqual(base['defenders'],specs['gate_north_books_depth_tight']['defenders'])
        selected=eligible(dict(options=list(specs)),dict(recovery=.8,pressure=.8,teaching=.8))
        self.assertTrue(selected)
        self.assertTrue(all(specs[k]['selection']['defense']=='depth' and specs[k]['selection']['position']=='wide' for k in selected))

    def test_generation_keeps_geometry_in_engine(self):
        self.state.state.update(bounds=[0,0,1,1], covers=[{'id':'cover-a'}], obstacles=[{'id':'wall-a'}])
        before = copy.deepcopy(self.state.state)
        self.step()
        self.assertEqual(before, self.state.state)
        for _, context in self.game.calls:
            self.assertNotIn('local_space', context)
            self.assertNotIn('component_choices', context)
        self.assertEqual(self.game.calls[0][1]['teams']['green']['alive'], 1)
        self.assertEqual(self.game.calls[-1][1]['agent'],'spatial_builder')
        self.assertTrue(self.submitted[0]['build_operations'])
        self.assertNotIn('recent_observations', self.game.calls[-1][1])
        self.assertEqual(self.submitted[0]['option'], 'gate_north_books_cross_tight')

    def test_history_keeps_progress_and_failures_without_specs(self):
        from world.context import macro_context, context_chars
        from world.catalog import CATALOG as specs
        s = copy.deepcopy(self.state.state)
        w = s['world_growth']
        w['mission'] = dict(name='test', status='completed', spec=specs[next(iter(specs))],
            started=1.123456789, arrived=2, required=2, enemies_remaining=0)
        w['completed'] = [dict(option=key, design=spec, spawned=['a','b','c'])
                          for key, spec in list(specs.items())[:6]]
        w['construction_failures'] = [dict(option='x', reason='site_occupied_before_commit', tick=90)]
        s['covers'] = [dict(id='part', collision_geometry='x'*1000)]*58
        context = macro_context(s, [], self.director.hormones, 'explore')
        self.assertEqual(context['mission']['elapsed_seconds'], 8.877)
        self.assertEqual(context['mission']['enemies_remaining'], 0)
        self.assertEqual(context['recent_construction'][0]['selection']['structure'], 'gate')
        self.assertEqual(context['recent_construction_failures'][0]['reason'], 'site_occupied_before_commit')
        self.assertNotIn('spec', context['mission'])
        self.assertLess(context_chars(context), 4000)
        self.assertEqual(s['world_growth']['mission']['started'], 1.123456789)

    def test_missing_pressure_is_unknown_not_safe(self):
        self.state.state['world_growth']['phase']='encounter'
        self.director.analyze()
        self.assertIsNone(self.game.calls[0][1]['teams']['green']['mean_pressure'])
        self.assertEqual(self.game.calls[0][1]['human_sample_count'], 0)
        macro_record = next(r for r in self.game.records if r['type']=='world-macro')
        self.assertNotIn('hormones', macro_record['context'])


if __name__ == '__main__': unittest.main()
