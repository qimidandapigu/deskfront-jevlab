"""Planner coordination contracts, independent of real-model aesthetic quality."""
import copy
import sys
import unittest
from pathlib import Path

from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'src/deskfront'),
    str(DESKFRONT_TOOLS)]

from world.desk_programmes import candidates, menu, desk_fingerprint
from world.generation_agents import plan
from world.region_graph import CELLS
from world.template_cards import cards
from world.catalog import DESCRIPTIONS


class ChoosingGame:
    def __init__(self, programme):
        self.config = {}
        self.programme = programme
        self.calls = []
        self.records = []

    def record(self, row):
        self.records.append(copy.deepcopy(row))

    def ask(self, context, questions):
        self.calls.append((copy.deepcopy(context), copy.deepcopy(questions)))
        answers = {}
        for key, question in questions.items():
            options = question['criteria']
            selected = self.programme if key == 'desk_programme' else next(iter(options))
            answers[key] = dict(type='choice', choice=selected, confidence=1,
                probabilities={option: int(option == selected) for option in options})
        return dict(requestId='planner-test', answers=answers)


class DeskProgrammeChecks(unittest.TestCase):
    def test_rescue_can_start_first_encounter_and_keeps_spacing(self):
        context = dict(hormones={}, phase='explore')
        option = 'gate_north_books_cross_tight'
        active = [dict(id=f'g{i}', faction='green', hp=30, max_hp=30) for i in range(4)]
        def offered(revision, completed=(), units=active):
            game = ChoosingGame('archive_to_research')
            plan(game, context, {option: DESCRIPTIONS[option]},
                 dict(units=units, world_growth=dict(revision=revision,
                                                    completed=list(completed))))
            return set(game.calls[0][1]['mission_kind']['criteria'])
        self.assertEqual(offered(0), {'assault', 'rescue'})
        previous = [dict(index=0, design=dict(design_card=dict(mission_kind='rescue')))]
        self.assertEqual(offered(1, previous), {'assault'})
        self.assertEqual(offered(2, previous), {'assault'})
        self.assertEqual(offered(3, previous), {'assault', 'rescue'})
        full = [dict(id=f'g{i}', faction='green', hp=30, max_hp=30) for i in range(6)]
        self.assertEqual(offered(3, previous, full), {'assault'})

    def test_whole_programmes_use_real_heroes_and_do_not_choose_cards(self):
        available = cards()
        pools = {}
        for key, card in available.items():
            if key in ('empty', 'fortress_base'):
                continue
            actual = {item['asset'] for item in card['items']}
            pools.setdefault(card['purpose'], set()).update(set(card['hero_assets']) & actual)
        programmes = candidates({})
        self.assertTrue(8 <= len(programmes) <= 12)
        for programme in programmes.values():
            self.assertEqual(set(programme['desks']), set(CELLS))
            purposes = {row['purpose'] for row in programme['desks'].values()}
            self.assertTrue(3 <= len(purposes) <= 6)
            for cell, row in programme['desks'].items():
                self.assertTrue(row['hero_assets'])
                self.assertLessEqual(set(row['hero_assets']), pools[row['purpose']])
                self.assertTrue(any(card['purpose'] == row['purpose']
                    and set(row['hero_assets']) <= {item['asset'] for item in card['items']}
                    for key, card in available.items() if key not in ('empty', 'fortress_base')))
                self.assertTrue(row['role'])
                self.assertTrue(row['neighbor_relation'])
                self.assertNotIn('template', row)
                self.assertNotIn('allowed_cards', row)

    def test_programmes_are_not_rotations_of_one_desk_matrix(self):
        def canonical(programme):
            matrix = [[programme['desks'][f'c{x}r{z}']['purpose'] for x in range(3)] for z in range(3)]
            signatures = []
            for _ in range(4):
                signatures.append(tuple(purpose for row in matrix for purpose in row))
                signatures.append(tuple(purpose for row in matrix for purpose in row[::-1]))
                matrix = [list(row) for row in zip(*matrix[::-1])]
            return min(signatures)
        programmes = candidates({})
        self.assertEqual(len({canonical(programme) for programme in programmes.values()}), len(programmes))

    def test_history_uses_actual_built_objects_and_keeps_repeat_selectable(self):
        base = candidates({})['archive_to_research']
        brief = dict(programme_id='archive_to_research', visual_motif=base['visual_motif'],
            desks=copy.deepcopy(base['desks']))
        context = dict(recent_layout_briefs=[brief], recent_designs=[dict(materials={'laptop': 7, 'printer': 4})])
        before = copy.deepcopy(context)
        programmes = candidates(context)
        self.assertIn('archive_to_research', programmes)
        self.assertIn('continue_recent', programmes)
        self.assertEqual(programmes['continue_recent']['desks'], brief['desks'])
        evidence = programmes['archive_to_research']['evidence']
        self.assertEqual(evidence['selected_recently'], 1)
        self.assertTrue(evidence['absent_from_latest_built'])
        self.assertNotIn('laptop', evidence['absent_from_latest_built'])
        self.assertNotIn('printer', evidence['absent_from_latest_built'])
        self.assertEqual(context, before)

    def test_no_history_is_not_claimed_as_proven_novelty(self):
        programmes = candidates({})
        self.assertTrue(all(row['evidence']['absent_from_latest_built'] is None for row in programmes.values()))
        self.assertTrue(all('尚无成图可比较' in label for label in menu(programmes).values()))

    def test_missing_hero_data_does_not_fabricate_a_programme(self):
        with self.assertRaisesRegex(ValueError, 'no_catalogue_supported_desk_programme'):
            candidates({}, catalog={})

    def test_one_planner_answer_becomes_shared_complete_brief(self):
        game = ChoosingGame('archive_to_research')
        context = dict(hormones={}, phase='explore')
        state = dict(units=[dict(id=f'g{i}', faction='green', hp=30, max_hp=30) for i in range(3)],
            world_growth=dict(revision=1, completed=[]))
        option = 'gate_north_books_cross_tight'
        task = plan(game, context, {option: DESCRIPTIONS[option]}, state)
        self.assertEqual(len(game.calls), 1)
        sent, questions = game.calls[0]
        self.assertIn('desk_programme', questions)
        self.assertNotIn('visual_motif', questions)
        self.assertIn('scene_shape', questions)
        self.assertEqual(task['layout_brief']['programme_id'], 'archive_to_research')
        expected = candidates(context)['archive_to_research']
        self.assertEqual(task['layout_brief']['desks'], expected['desks'])
        self.assertEqual(task['layout_brief']['visual_motif'], expected['visual_motif'])
        self.assertEqual(set(task['layout_brief']['desks']), set(CELLS))
        self.assertEqual(len(sent['desk_programmes']['archive_to_research']['desks']), 9)
        self.assertEqual(sent['desk_programmes']['archive_to_research']['columns'],
            ['cell','purpose','hero_assets'])
        self.assertEqual(len(sent['desk_role_by_purpose']),8)
        self.assertIn('相邻格',sent['desk_relation_rule'])
        self.assertIn('完整九桌用途', task['build_directive'])
        self.assertEqual(game.records[0]['plan']['layout_brief'], task['layout_brief'])
        self.assertNotIn('desks', context)

    def test_three_continuations_keep_canonical_source_after_window_rolls(self):
        context = dict(hormones={}, phase='explore', recent_layout_briefs=[])
        state = dict(units=[dict(id=f'g{i}', faction='green', hp=30, max_hp=30) for i in range(3)],
            world_growth=dict(revision=1, completed=[]))
        option = 'gate_north_books_cross_tight'
        history = []
        for selection in ('archive_to_research', 'continue_recent', 'continue_recent', 'continue_recent'):
            context['recent_layout_briefs'] = copy.deepcopy(history[-3:])
            task = plan(ChoosingGame(selection), context, {option: DESCRIPTIONS[option]}, state)
            brief = task['layout_brief']
            self.assertEqual(brief['source_programme_id'], 'archive_to_research')
            if history:
                self.assertEqual(brief['desk_fingerprint'], history[0]['desk_fingerprint'])
            history.append(brief)
        offered = candidates(dict(recent_layout_briefs=history[-3:]))
        for key in ('archive_to_research', 'continue_recent'):
            evidence = offered[key]['evidence']
            self.assertEqual(evidence['selected_recently'], 3)
            self.assertEqual(evidence['same_desks_recently'], 3)
            self.assertEqual(evidence['same_desks_consecutive_in_window'], 3)
            self.assertEqual(evidence['continuations_recently'], 3)
        self.assertIn('continue_recent', menu(offered))
        self.assertIn('续用选择3次', menu(offered)['continue_recent'])
        self.assertEqual(candidates(dict(recent_layout_briefs=history))['archive_to_research']['evidence']['selected_recently'], 4)

    def test_legacy_lost_source_recovers_only_by_matching_desk_semantics(self):
        base = candidates({})['archive_to_research']
        old = dict(programme_id='continue_recent', desks=copy.deepcopy(base['desks']))
        # IDs, harmless prose and hero order do not turn this into a fresh grid.
        for desk in old['desks'].values():
            desk['hero_assets'].reverse()
            desk['role'] = 'same physical intention, rewritten prose'
        self.assertEqual(desk_fingerprint(old['desks']), base['desk_fingerprint'])
        offered = candidates(dict(recent_layout_briefs=[old]))
        self.assertEqual(offered['continue_recent']['source_programme_id'], 'archive_to_research')
        self.assertEqual(offered['archive_to_research']['evidence']['selected_recently'], 1)
        self.assertEqual(offered['archive_to_research']['evidence']['same_desks_recently'], 1)

    def test_unknown_legacy_source_is_not_invented(self):
        base = candidates({})['archive_to_research']
        old = dict(programme_id='continue_recent', desks=copy.deepcopy(base['desks']))
        old['desks']['c0r0'], old['desks']['c1r1'] = old['desks']['c1r1'], old['desks']['c0r0']
        offered = candidates(dict(recent_layout_briefs=[old]))
        continuation = offered['continue_recent']
        self.assertIsNone(continuation['source_programme_id'])
        self.assertIsNone(continuation['evidence']['selected_recently'])
        self.assertEqual(continuation['evidence']['same_desks_recently'], 1)
        self.assertIn('根方案选用未知次', menu(offered)['continue_recent'])


if __name__ == '__main__':
    unittest.main()
