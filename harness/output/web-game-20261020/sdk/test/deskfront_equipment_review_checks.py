import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from battlefield_equipment import equipment_brief, equipment_opportunities, validate_equipment_goal, personal_equipment_opportunities
from equipment_review import EquipmentReview, capture_sample, annotate_approaches


class EquipmentReviewChecks(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parent / 'fixtures/deskfront-mortar-defer-63e6336c.json'
        self.record = json.loads(fixture.read_text(encoding='utf-8'))
        self.world = self.record['world']
        self.contacts = self.record['contacts']
        self.members = [u for u in self.world['units'] if u['hp'] > 0]
        self.gun = self.world['at_guns'][0]
        self.rifle = next(u for u in self.members if u['weapon'] == 'rifle')
        self.uid = self.rifle['id']
        self.squad = dict(order_id='accepted-order', assignment_tokens={self.uid: 'native-assignment'})
        self.review = EquipmentReview()

    def opportunities(self):
        return equipment_opportunities(equipment_brief(self.world, 'green', self.contacts),
                                       self.members, self.contacts, self.world['weapons'])

    def apply(self, plan=None, samples=None):
        return self.review.apply(self.opportunities(), self.world, self.members, self.contacts,
                                 plan or {}, {}, self.squad, samples or {})

    def sample(self, **overrides):
        # Query-envelope fixture uses real native lengths; positions below are
        # synthetic to isolate freshness validation from the historic match.
        p = self.gun['position']
        result = dict(status='fresh', run_id=self.world['run_id'], unit_id=self.uid,
                      navigation_revision=self.world['navigation_revision'],
                      assignment_token='native-assignment', sampled_at=self.world['time'],
                      unit_position=copy.deepcopy(self.rifle['position']),
                      options=[dict(id='C1', equipment_id=self.gun['id'], kind='equipment_approach',
                                    purpose='capture', position=[p[0]+.104, p[1]], path_length=.281)])
        result.update(overrides)
        return capture_sample(self.world, self.rifle, self.squad, result, [self.gun])

    def candidate(self, rows):
        return next(c for c in rows[0]['candidates'] if c['id'] == self.uid)

    def test_historical_snapshot_keeps_capture_possible_outside_radius(self):
        before = copy.deepcopy(self.world)
        row = self.apply()[0]
        self.assertEqual([c['id'] for c in row['candidates']], ['green-3', 'green-900'])
        self.assertTrue(self.candidate([row])['eligibility_without_distance'])
        self.assertFalse(self.candidate([row])['native_capture_eligible'])
        plan = validate_equipment_goal(dict(equipment_id=self.gun['id'], phase='capture',
            reason='approach then operate'), [self.gun], self.members)
        self.assertNotIn('actor_id', plan)
        direct = {w['unit_id']: w for w in row['visible_armor'][0]['own_weapon_comparison']}
        self.assertEqual(direct['green-3']['seconds_since_actual_fire'], 83.)
        self.assertEqual(direct['green-900']['seconds_since_actual_fire'], 114.9)
        self.assertFalse(direct['green-900']['target_engageable'])
        self.assertEqual(self.world, before)
        self.assertNotIn('selected_actor', row)

    def test_recorded_accepted_plan_history_counts_once_and_exposes_repeated_no_fire(self):
        # Only decision timing is replayed. All other facts remain the saved
        # final snapshot; this is not a reconstructed historical battlefield.
        for recorded in self.record['accepted_defer_plans']:
            self.world['time'] = recorded['time']
            first = self.apply(recorded['plan'])[0]['defer_review']
            self.assertEqual(first, self.apply(recorded['plan'])[0]['defer_review'])
        self.assertEqual(first['accepted_defer_plans'], 9)
        self.assertEqual(first['observed_for_s'], 69.4)
        self.assertTrue(first['repeated_without_observed_fire'])
        self.assertFalse(first['actual_fire_at_these_targets_since_defer'])
        self.assertEqual(first['objective'], 'eliminate_visible_armor')

    def test_fire_at_the_current_target_is_evidence_not_a_compulsory_capture_rule(self):
        plan = copy.deepcopy(self.record['accepted_defer_plans'][0]['plan'])
        self.apply(plan)
        self.world['time'] += 12
        self.rifle.update(last_shot_at=self.world['time'], last_shot_target=self.contacts[0]['id'])
        plan['request_id'] = 'accepted-new-plan'
        review = self.apply(plan)[0]['defer_review']
        self.assertTrue(review['actual_fire_at_these_targets_since_defer'])
        self.assertFalse(review['repeated_without_observed_fire'])
        goal = {k: v for k, v in plan['equipment_goal'].items() if k not in ('actor_id', 'support_ids')}
        self.assertEqual(validate_equipment_goal(goal, [self.gun], self.members)['phase'], 'defer')

    def test_new_run_new_stage_time_rewind_and_target_change_clear_defer_episode(self):
        plan = self.record['accepted_defer_plans'][0]['plan']
        for change in ('run', 'stage', 'rewind', 'target'):
            with self.subTest(change=change):
                self.setUp();plan = self.record['accepted_defer_plans'][0]['plan']
                self.apply(plan);self.world['time'] += 20
                second = dict(plan, request_id='second')
                self.assertEqual(self.apply(second)[0]['defer_review']['accepted_defer_plans'], 2)
                if change == 'run':self.world['run_id'] = 'new-run'
                if change == 'stage':self.world['world_growth']['mission']['operation_id'] = 'new-stage'
                if change == 'rewind':self.world['time'] -= 21
                if change == 'target':self.contacts[0]['id'] = 'different-visible-tank'
                self.assertEqual(self.apply(second)[0]['defer_review']['accepted_defer_plans'], 1)

    def test_capture_or_owned_gun_ends_defer_episode(self):
        plan = self.record['accepted_defer_plans'][0]['plan']
        self.apply(plan)
        capture = copy.deepcopy(plan);capture['equipment_goal'].update(phase='capture', actor_id=self.uid)
        self.assertNotIn('defer_review', self.apply(capture)[0])
        self.assertEqual(self.review.episodes, {})
        self.gun.update(faction='green', capturable=False)
        self.assertEqual(self.apply(plan), [])

    def test_recent_native_path_comparison_contains_no_replayable_site_or_command(self):
        sample = self.sample()
        candidate = self.candidate(self.apply(samples={self.uid: sample}))
        facts = candidate['approach_sample']
        self.assertEqual(facts['status'], 'recent_native_paths')
        self.assertEqual(facts['paths'][0], dict(path_length=.281, end_distance=.104, inside_capture_radius=True))
        self.assertNotIn('position', str(facts))
        self.assertNotIn('site_id', str(facts))
        self.assertIsNone(candidate['path_cost'])  # live navigation stays unknown

    def test_cached_sample_is_not_used_across_run_navigation_assignment_motion_time_or_weapon_changes(self):
        for change in ('run', 'navigation', 'assignment', 'motion', 'old', 'future', 'gun_move'):
            with self.subTest(change=change):
                self.setUp();sample = self.sample()
                if change == 'run':self.world['run_id'] = 'other-run'
                if change == 'navigation':self.world['navigation_revision'] += 1
                if change == 'assignment':self.squad['assignment_tokens'][self.uid] = 'new-assignment'
                if change == 'motion':self.rifle['position'][0] += .05
                if change == 'old':self.world['time'] += 3.1
                if change == 'future':self.world['time'] -= .1
                if change == 'gun_move':self.gun['position'][0] += .1
                facts = self.candidate(self.apply(samples={self.uid: sample}))['approach_sample']
                self.assertNotEqual(facts['status'], 'recent_native_paths')
                self.assertNotIn('paths', facts)

    def test_stale_response_cannot_be_relabeled_current_by_cache(self):
        for result in (dict(run_id='old-run'), dict(navigation_revision=-1),
                       dict(unit_id='other-unit'), dict(assignment_token='old-task'),
                       dict(status='native_query_timeout'), dict(sampled_at=None), dict(unit_position=None)):
            with self.subTest(result=result):
                facts = self.candidate(self.apply(samples={self.uid: self.sample(**result)}))['approach_sample']
                self.assertNotEqual(facts['status'], 'recent_native_paths')
                self.assertNotIn('paths', facts)

    def test_no_validated_option_is_unknown_not_unreachable_and_dead_operator_is_excluded(self):
        facts = self.candidate(self.apply(samples={self.uid: self.sample(options=[])}))['approach_sample']
        self.assertEqual(facts['status'], 'no_local_sample_not_unreachable')
        self.rifle['hp'] = 0
        rows = self.apply(samples={self.uid: self.sample()})
        self.assertNotIn(self.uid, [c['id'] for c in rows[0]['candidates']])

    def test_hidden_targets_are_not_added_to_comparison(self):
        self.contacts[0]['visible'] = False
        self.assertEqual(self.apply()[0]['visible_armor'], [])
        self.assertNotIn('defer_review', self.apply(self.record['accepted_defer_plans'][0]['plan'])[0])

    def test_personal_projection_still_excludes_other_soldiers(self):
        rows = self.apply(samples={self.uid: self.sample()})
        personal = personal_equipment_opportunities(rows, self.uid)[0]
        self.assertEqual([c['id'] for c in personal['candidates']], [self.uid])
        self.assertEqual([w['unit_id'] for w in personal['visible_armor'][0]['own_weapon_comparison']], [self.uid])


if __name__ == '__main__':
    unittest.main()
