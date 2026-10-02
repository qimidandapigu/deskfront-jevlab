"""Lifecycle regressions: use deterministic model answers, no provider or engine."""
import copy
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
sys.path.insert(0, str(DESKFRONT_TOOLS))
from world.director import WorldDirector, MacroBridge, eligible
from world.region_builder import encode_placement,is_placement


OPTION = 'gate_north_books_cross_tight'
CURRENT_PLACEMENT = encode_placement('code_laptop_island',270)


class Game:
    # This suite exercises generic recipe invalidation.  Keep its fixture
    # explicit so the product's current endless default (tank rule on) does
    # not silently change a lifecycle contract test.
    config = {'runtime': {'maxRequests': 40}, 'gameOptions': {'secondStageTankRule': False}}

    def __init__(self):
        self.records = []
        self.calls = []
        self.questions = []
        self.contexts = []
        self.block_commander = False
        self.block_executor = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def record(self, row):
        self.records.append(copy.deepcopy(row))

    def ask(self, context, questions, role=None):
        self.calls.append(role)
        self.questions.append(copy.deepcopy(questions))
        self.contexts.append(copy.deepcopy(context))
        if (role == 'experience_analyst' and self.block_commander) or (role is None and self.block_executor):
            self.entered.set()
            if not self.release.wait(2):
                raise RuntimeError('test release timed out')
        answers={}
        for key,question in questions.items():
            menu=question['criteria']
            if key.startswith('template_'):
                if CURRENT_PLACEMENT not in menu:
                    raise AssertionError(f'current curated placement missing from {key}')
                choice=CURRENT_PLACEMENT
            else:
                choice=next(iter(menu))
            answers[key]=dict(type='choice',choice=choice,confidence=1,
                probabilities={option:int(option==choice) for option in menu})
        return dict(requestId=str(len(self.calls)),answers=answers)


class PipelineChecks(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        self.state = SimpleNamespace(lock=threading.Lock(), instance_id='engine',
            updated=time.monotonic(), results={})
        self.state.state = dict(run_id='run', time=30, tick=1800, paused=False,
            control={'green': 'lm'}, units=[dict(id='green-1', faction='green', hp=50,
                max_hp=50, position=[0, 0])], world_growth=dict(enabled=True,
                revision=1, phase='ready', options=[OPTION], planning_options=[OPTION], completed=[]))
        self.commands = []
        self.state.submit = lambda command: (self.commands.append(copy.deepcopy(command))
            or (202, dict(id='cmd-'+str(len(self.commands)))))
        self.director = WorldDirector(MacroBridge(self.state, self.game), self.game)
        self.director.observe(self.state.state)

    def prepare(self):
        return self.director.step(dict(run_id='run', instance_id='engine', prepare=True))

    def ready(self):
        self.state.state['world_growth'].update(phase='ready', options=[OPTION])

    def test_analysis_does_not_block_clear_generation(self):
        self.state.state['world_growth']['phase']='encounter'
        self.game.block_commander=True
        worker=threading.Thread(target=self.director.analyze);worker.start()
        try:
            self.assertTrue(self.game.entered.wait(1))
            self.ready();self.prepare()
            self.assertTrue(self.director.commit_prepared())
            self.assertTrue(worker.is_alive())
        finally:
            self.game.release.set();worker.join(2)
        self.assertEqual(len(self.commands),1)
        self.assertEqual(self.director.snapshot()['status'],'submitted')


    def test_pending_command_blocks_another_same_revision_request(self):
        self.prepare()
        self.ready()
        self.assertTrue(self.director.commit_prepared())
        self.director.last_attempt -= 20
        with self.assertRaisesRegex(ValueError, 'world_submission_pending'):
            self.prepare()
        self.assertEqual(len(self.game.calls), 3)
        self.assertEqual(len(self.commands), 1)

    def test_prepared_recipe_prevents_duplicate_planning(self):
        self.prepare();self.director.last_attempt-=20
        with self.assertRaisesRegex(ValueError,'world_submission_pending'):self.prepare()
        self.assertEqual(len(self.game.calls),3)


    def test_analysis_cannot_replace_prepared_recipe(self):
        self.prepare();before=copy.deepcopy(self.director.prepared)
        self.state.state['world_growth']['phase']='encounter'
        self.director.analyze()
        self.assertEqual(self.director.prepared,before)


    def test_run_reset_while_provider_waits_cannot_publish_old_recipe(self):
        self.game.block_executor = True
        errors = []

        def prepare():
            try:
                self.prepare()
            except ValueError as exc:
                errors.append(str(exc))

        worker = threading.Thread(target=prepare)
        worker.start()
        try:
            self.assertTrue(self.game.entered.wait(1))
            self.state.state['run_id'] = 'next-run'
            self.director.observe(self.state.state)
        finally:
            self.game.release.set()
            worker.join(2)
        self.assertEqual(errors, ['world_preparation_superseded'])
        self.assertIsNone(self.director.prepared)
        self.assertFalse(self.commands)
        self.assertEqual(self.director.snapshot()['status'], 'observing')
        self.assertEqual(self.game.calls, [None])

    def test_new_run_clears_cached_recipe_and_rate_limit(self):
        self.prepare()
        self.state.state['run_id'] = 'next-run'
        self.director.observe(self.state.state)
        self.assertIsNone(self.director.prepared)
        self.assertEqual(self.director.snapshot()['prepare_retry_in'], 0)
        self.assertEqual(self.director.snapshot()['requests_used'], 0)
        self.assertFalse(self.director.commit_prepared())

    def test_changed_team_invalidates_recipe_instead_of_rewriting_model_choice(self):
        self.prepare()
        self.state.state['units'] *= 5
        self.ready()
        self.assertFalse(self.director.commit_prepared())
        self.assertIsNone(self.director.prepared)
        self.assertFalse(self.commands)
        self.assertEqual(self.game.records[-1]['reason'], 'force_context_changed')

    def test_temporarily_full_queue_retries_same_operation_with_backoff(self):
        self.prepare()
        self.ready()
        operation = self.director.prepared['command']['operation_id']
        attempts = []

        def submit(command):
            attempts.append(copy.deepcopy(command))
            return (429, dict(error='queue_full')) if len(attempts) == 1 else (202, dict(id='cmd'))

        self.state.submit = submit
        now = time.monotonic()
        with patch('world.director.time.monotonic', return_value=now):
            self.assertFalse(self.director.commit_prepared())
            self.assertFalse(self.director.commit_prepared())
        self.assertEqual(len(attempts), 1)
        self.state.updated = now+1.1
        with patch('world.director.time.monotonic', return_value=now+1.1):
            self.assertTrue(self.director.commit_prepared())
        self.assertEqual([a['operation_id'] for a in attempts], [operation, operation])

    def test_permanent_submit_rejection_is_not_retried_forever(self):
        self.prepare()
        self.ready()
        self.state.submit = lambda command: (400, dict(error='invalid_growth_option'))
        self.assertFalse(self.director.commit_prepared())
        self.assertIsNone(self.director.prepared)
        self.assertFalse(self.director.snapshot()['submission_pending'])
        self.assertEqual(self.director.snapshot()['error'], 'invalid_growth_option')

    def test_engine_rejection_reopens_preparation_without_claiming_completion(self):
        self.prepare()
        self.ready()
        self.assertTrue(self.director.commit_prepared())
        self.state.results['cmd-1'] = dict(accepted=False, message='site_occupied')
        self.director.observe(self.state.state)
        status = self.director.snapshot()
        self.assertFalse(status['submission_pending'])
        self.assertEqual(status['history'][-1]['status'], 'rejected')
        self.assertEqual(status['error'], 'site_occupied')

    def test_pause_preserves_recipe_without_committing(self):
        self.prepare()
        self.ready()
        self.state.state['paused'] = True
        self.assertFalse(self.director.commit_prepared())
        self.assertIsNotNone(self.director.prepared)
        self.assertFalse(self.commands)

    def test_generator_has_distinct_planner_and_builder_calls(self):
        prepared=self.prepare()
        self.assertEqual(set(self.game.questions[0]),{'blueprint','mission_kind','force_package','defender_mix','support_type',
            'tactical_approach','scene_shape','desk_programme'})
        self.assertEqual(prepared['command']['mission_kind'],'rescue')
        self.assertEqual(prepared['command']['defender_mix'],'balanced')
        self.assertIn('entry_cell',self.game.questions[1])
        self.assertIn('fortress_cell',self.game.questions[1])
        self.assertEqual(len([key for key in self.game.questions[1] if key.startswith('template_')]),9)
        self.assertEqual(len([key for key in self.game.questions[1] if key.startswith('rotation_')]),0)
        self.assertEqual(len([key for key in self.game.questions[1] if key.startswith('other_c2_')]),0)
        self.assertIn('mock_revision',self.game.questions[2])
        self.assertTrue(prepared['command']['build_operations'])
        self.assertEqual(len([o for o in prepared['command']['build_operations'] if o['op']=='place_region']),9)
        self.assertEqual(len([o for o in prepared['command']['build_operations']
            if o.get('op')=='place_region' and o.get('module')=='fortress_base']),1)
        self.assertEqual([r['type'] for r in self.game.records if r['type'] in ('world-planner','world-builder')],['world-planner','world-builder','world-builder'])

    def test_last_three_world_requests_keep_full_card_revision_without_unfunded_prop_edit(self):
        self.game.config={'backend':'jev','runtime':{'maxRequests':3}}
        self.director.limit=3
        self.prepare()
        self.assertEqual(self.director.calls,3)
        edits=[q for key,q in self.game.questions[2].items() if key.endswith('_action')]
        self.assertEqual(len(edits),9)
        self.assertTrue(all(not any(action=='add' or action.startswith(('remove_','move_','replace_'))
            for action in q['criteria']) for q in edits))
        self.assertEqual(sum(any(is_placement(key) for key in q['criteria']) for q in edits),8)

    def test_completed_layout_and_outcome_reach_planner_and_builder(self):
        from world.region_graph import CELLS, LIBRARY
        previous=[dict(op='set_ports',entry='c0r1',exit='c2r1')]
        previous += [dict(op='place_region',cell=cell,module='books' if cell=='c0r0' else 'open')
            for cell in CELLS]
        previous += [dict(op='connect_regions',edge=edge) for edge in LIBRARY['edges']]
        previous.append(dict(op='deploy',module='rear'))
        self.director.history.append(dict(status='completed',operation_id='previous',
            option=OPTION,build_operations=previous,tool_validation={}))
        self.state.state['world_growth']['mission_results']=[dict(operation_id='previous',
            status='completed',duration_seconds=12,enemies_remaining=0)]
        self.director.experience=dict(world_revision=1,observed_at=30,
            next_goal=dict(experience='形成侧路',tactical_problem='从侧面进攻',
                avoid='不要重复书堆',route_preference='flank'))
        prepared=self.prepare()
        planner=self.game.contexts[0]['recent_designs']
        builder=self.game.contexts[1]['recent_designs']
        self.assertEqual(planner,builder)
        self.assertEqual(planner[0]['cells']['c0r0']['card'],'books')
        self.assertIn('bookstack',planner[0]['materials'])
        self.assertEqual(planner[0]['mission']['duration_seconds'],12)
        self.assertIn('recent_layout_briefs',self.game.contexts[0])
        from world.region_builder import menu_for_cell
        from world.template_cards import menu as template_menu
        real_menu=menu_for_cell('c0r0',template_menu(),recent=planner)
        self.assertNotIn('books',real_menu)  # Historical evidence stays readable; the active catalogue is curated.
        self.assertEqual(len(real_menu),26)
        self.assertEqual(len(self.game.contexts[2]['draft_design_feedback']['recent_design_similarity']),1)
        self.assertEqual(len(prepared['tool_validation']['design_observations']['recent_design_similarity']),1)

    def test_fast_clear_gets_current_encounter_analysis_before_next_plan(self):
        self.state.state['world_growth']['mission_results']=[dict(index=1,status='completed',
            option=OPTION,duration_seconds=7.2,enemies_remaining=0)]
        prepared=self.prepare()
        self.assertEqual(self.game.calls[0],'experience_analyst')
        self.assertEqual(self.director.experience['source'],'completed_encounter')
        self.assertIsNotNone(prepared['macro_call'])
        plan=next(r['plan'] for r in self.game.records if r['type']=='world-planner')
        self.assertIsNotNone(plan['next_goal'])


    def test_evicted_ack_does_not_erase_observed_acceptance(self):
        self.prepare()
        self.ready()
        self.assertTrue(self.director.commit_prepared())
        self.state.state['world_growth']['phase'] = 'building'
        self.state.results['cmd-1'] = dict(accepted=True)
        self.director.observe(self.state.state)
        self.assertEqual(self.director.history[-1]['status'], 'building')
        self.state.results.clear()
        self.director.observe(self.state.state)
        self.assertEqual(self.director.history[-1]['status'], 'building')
        self.assertTrue(self.director.history[-1]['receipt']['accepted'])

    def test_missing_confirmation_is_visible_and_never_reissued_on_timeout(self):
        self.prepare()
        self.ready()
        self.assertTrue(self.director.commit_prepared())
        self.state.pending = {}
        self.director.history[-1]['submitted_at'] -= 16
        self.director.observe(self.state.state)
        snapshot = self.director.snapshot()
        self.assertEqual(snapshot['status'], 'confirmation_unknown')
        self.assertTrue(snapshot['submission_pending'])
        self.assertFalse(self.director.commit_prepared())
        self.director.last_attempt -= 20
        with self.assertRaisesRegex(ValueError, 'world_submission_pending'):
            self.prepare()
        self.assertEqual(len(self.commands), 1)

    def test_transport_timeout_is_ambiguous_until_native_construction_evidence(self):
        self.prepare()
        self.ready()
        self.assertTrue(self.director.commit_prepared())
        row = self.director.history[-1]
        self.state.results['cmd-1'] = dict(accepted=False, message='command_timeout')
        self.director.observe(self.state.state)
        self.assertEqual(row['status'], 'confirmation_unknown')
        self.state.state['world_growth'].update(revision=1,
            mission=dict(operation_id=row['operation_id'], index=1, option=OPTION, status='active'))
        self.director.observe(self.state.state)
        self.assertEqual(row['status'], 'completed')
        self.assertEqual(row['construction']['evidence'], 'native_mission')
        self.assertFalse(self.director.snapshot()['submission_pending'])

    def test_new_revision_unblocks_only_as_unconfirmed_superseded(self):
        self.prepare()
        self.ready()
        self.assertTrue(self.director.commit_prepared())
        self.state.state['world_growth']['revision'] = 2
        self.director.observe(self.state.state)
        snapshot = self.director.snapshot()
        self.assertEqual(snapshot['history'][-1]['status'], 'superseded_unconfirmed')
        self.assertFalse(snapshot['submission_pending'])
        self.assertIsNone(snapshot['history'][-1]['construction'])
        self.assertEqual(len(self.commands), 1)

    def test_native_mission_history_confirms_construction_after_completed_list_retired(self):
        self.prepare()
        self.ready()
        self.assertTrue(self.director.commit_prepared())
        row = self.director.history[-1]
        self.state.state['world_growth'].update(revision=4,
            mission_results=[dict(operation_id=row['operation_id'], index=1, option=OPTION, status='failed')])
        self.director.observe(self.state.state)
        self.assertEqual(row['status'], 'completed', 'combat failure does not erase actual construction')
        self.assertFalse(self.director.snapshot()['submission_pending'])


if __name__ == '__main__':
    unittest.main()
