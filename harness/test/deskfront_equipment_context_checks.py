import copy
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from human_squad import HumanSquadController
from human_squad_contract import CLEAR_PLAN_INSTRUCTIONS, EXECUTOR_INSTRUCTIONS
from soldier_agents import INSTRUCTIONS


class EquipmentContextChecks(unittest.TestCase):
    def setUp(self):
        self.commands, self.records = [], []
        state = SimpleNamespace(lock=threading.RLock(), state={}, results={})
        game = SimpleNamespace(record=lambda row: self.records.append(copy.deepcopy(row)))
        self.controller = HumanSquadController(state, {'model': 'mock', 'soldier_agents': False}, game, 'green')
        self.members = [dict(id='g1', faction='green', position=[.3, 0.], hp=50, max_hp=50,
                             weapon='rifle', suppression=0, survival_reason=''),
                        dict(id='g2', faction='green', position=[.4, 0.], hp=10, max_hp=50,
                             weapon='rifle', suppression=.6, survival_reason='incoming_shell')]
        self.gun = dict(id='mortar', kind='mortar', faction='neutral', position=[1., 0.], capturable=True,
                        seen_by=['green'], phase='abandoned', capture_radius=.24, capture_seconds=3.,
                        capture_progress=0, capture_team='',
                        ammunition_policy='unlimited_reserve',
                        # Finite fixture coefficient isolates context parity from
                        # the model projection's intentional float rounding.
                        capabilities=dict(damage=72., armor_multiplier=.58, single_setup_seconds=3.5),
                        capture_candidates=[dict(unit_id='g1', eligible=False, eligibility_without_distance=True,
                                                 within_radius=False, reason='outside_radius'),
                                            dict(unit_id='g2', eligible=False, eligibility_without_distance=False,
                                                 within_radius=False, reason='suppression')])
        self.controller.world = dict(run_id='capture-test', time=100., units=self.members, at_guns=[self.gun],
            weapons={'rifle': dict(damage=10., armor_multiplier=.08, range=.7)},
            squad_behavior={'perception': {'green': {'contacts': []}}, 'squads': {}, 'events': []})

    def test_commander_and_squad_keep_comparable_capture_facts(self):
        context = self.controller._context(self.members)
        opportunities = context['equipment_opportunities']
        candidates = {row['id']: row for row in opportunities[0]['candidates']}
        self.assertEqual(candidates['g1']['native_admission_reason'], 'outside_radius')
        self.assertTrue(candidates['g1']['eligibility_without_distance'])
        for projection in (self.controller._commander_context, self.controller._executor_context):
            view = projection(context)
            self.assertEqual(view['equipment_opportunities'], opportunities)
            self.assertFalse(next(row for row in view['equipment_opportunities'][0]['candidates']
                                  if row['id'] == 'g2')['eligibility_without_distance'])

    def test_personal_context_excludes_other_member_admission(self):
        agents = self.controller.soldiers
        agents.agents['g1'] = dict(assignment={}, memory=[], engine_execution={})
        context = agents._context(self.members[0], {})
        self.assertEqual([row['id'] for row in context['equipment_opportunities'][0]['candidates']], ['g1'])
        self.assertEqual([row['unit_id'] for row in context['battlefield_equipment'][0]['capture_candidates']], ['g1'])

    def test_circle_crossing_and_capture_start_wake_both_roles_without_progress_chatter(self):
        c = self.controller
        c._observe(self.members)
        initial = copy.deepcopy(c.revision)
        self.assertEqual(initial, dict(commander=1, executor=1))
        c.world['time'] = 104.
        self.members[0]['position'] = [.85, 0.]
        self.gun['capture_candidates'][0].update(within_radius=True, eligible=True, reason='')
        c._observe(self.members)
        self.assertEqual(c.revision, dict(commander=2, executor=2))
        c.world['time'] = 108.
        self.gun.update(phase='capturing', capture_team='green', capture_progress=.1)
        c._observe(self.members)
        self.assertEqual(c.revision, dict(commander=3, executor=3))
        for index in range(1, 40):
            c.world['time'] = 108. + index * .02
            self.gun['capture_progress'] = index / 50.
            c._observe(self.members)
        self.assertEqual(c.revision, dict(commander=3, executor=3))
        c.world['time'] = 112.
        self.gun.update(faction='green', capturable=False, phase='setting_up')
        c._observe(self.members)
        self.assertEqual(c.revision, dict(commander=4, executor=4))

    def test_boundary_jitter_is_coalesced_and_undiscovered_gun_never_wakes(self):
        c = self.controller
        self.gun['seen_by'] = ['red']
        c._observe(self.members)
        self.assertEqual(c.revision, dict(commander=0, executor=0))
        self.gun['seen_by'] = ['green']
        c._observe(self.members)
        for index in range(20):
            c.world['time'] = 100. + index * .05
            self.gun['capture_candidates'][0]['within_radius'] = index % 2 == 0
            c._observe(self.members)
        self.assertEqual(c.revision, dict(commander=1, executor=1))

    def test_prompts_explain_optional_defer_and_native_gate_without_choosing_actor(self):
        for prompt in (CLEAR_PLAN_INSTRUCTIONS, EXECUTOR_INSTRUCTIONS):
            self.assertIn('equipment_opportunities', prompt)
            self.assertIn('不强制夺炮', prompt)
            self.assertIn('defer合法', prompt)
            self.assertIn('native_admission_reason', prompt)
        self.assertIn('只含本人的', INSTRUCTIONS)
        self.assertIn('路径代价', INSTRUCTIONS)


if __name__ == '__main__':
    unittest.main()
