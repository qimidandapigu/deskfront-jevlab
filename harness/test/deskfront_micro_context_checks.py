import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'deskfront'))
from micro_context import build


class MicroContextChecks(unittest.TestCase):
    def setUp(self):
        self.unit = dict(id='green-1', kind='infantry', hp=50, max_hp=50, position=[0, 0],
                         weapon_range=.92, ammo=1, reload_remaining=0, suppression=0,
                         combat=dict(path_active=False, incoming_threats=[], engageable_targets=['red-1']))
        self.enemy = dict(id='red-1', hp=50, position=[.8, 0], weapon_range=.7)

    def test_range_advantage_is_distance_only_and_not_fire_permission(self):
        result = build(self.unit, [self.enemy], {}, 10)
        target = result['targets'][0]
        self.assertEqual(target['distance_relation'], 'self_only')
        self.assertTrue(target['self_range_reaches'])
        self.assertFalse(target['enemy_range_reaches'])
        self.assertEqual(target['fire_lane'], 'native_candidate_requires_muzzle_check')
        self.assertIn('distance_only', result['range_basis'])
        self.assertEqual(result['threats']['query_status'], 'unknown_or_stale')
        self.assertNotIn('action', result)

    def test_missing_range_stays_unknown_instead_of_claiming_safety(self):
        del self.enemy['weapon_range']
        result = build(self.unit, [self.enemy], {}, 10)
        self.assertIsNone(result['targets'][0]['enemy_range_reaches'])
        self.assertEqual(result['targets'][0]['distance_relation'], 'unknown')
        self.assertEqual(result['preferred_distance']['basis'], 'spacing_heuristic_not_safe_range')

    def test_enemy_range_advantage_exposes_approach_cost_before_damage(self):
        self.unit['weapon_range'] = .6
        self.enemy['position'] = [.65, 0]
        result = build(self.unit, [self.enemy], {}, 10)
        self.assertEqual(result['targets'][0]['distance_relation'], 'enemy_only')
        self.assertEqual(result['targets'][0]['gap_to_self_range'], .05)
        self.assertEqual(result['tradeoffs']['approach']['outside_range'], ['red-1'])
        self.assertEqual(result['tradeoffs']['stop_and_fire']['within_range'], [])
        self.assertIn('enemy_distance_reach_not_los', result['threats']['warning_before_damage'])

    def test_movement_and_reload_explain_loss_of_fire_without_forcing_action(self):
        self.unit['combat']['path_active'] = True
        self.unit['reload_remaining'] = 1.2
        result = build(self.unit, [self.enemy], {}, 10)
        self.assertEqual(result['fire_blockers'], ['moving_infantry_cannot_fire', 'reloading'])
        self.assertEqual(result['reload_s'], 1.2)
        self.unit['kind'] = 'tank'
        result = build(self.unit, [self.enemy], {}, 10)
        self.assertNotIn('moving_infantry_cannot_fire', result['fire_blockers'])

    def test_fresh_muzzle_obstruction_overrides_rough_engageable_list(self):
        self.unit['combat']['fire_check'] = dict(target_id='red-1', time=9.8, status='blocked',
                                                 reason='cover_blocks_muzzle', position=[0, 0])
        result = build(self.unit, [self.enemy], {}, 10)
        self.assertEqual(result['targets'][0]['fire_lane'], 'recent_muzzle_block:cover_blocks_muzzle')
        self.unit['position'] = [0, .2]
        result = build(self.unit, [self.enemy], {}, 10)
        self.assertEqual(result['targets'][0]['fire_lane'], 'native_candidate_requires_muzzle_check')

    def test_damage_is_not_required_to_report_observed_and_forecast_threat(self):
        self.enemy['position'] = [.65, 0]
        spatial = dict(sampled_at=9.5, origin=[0, 0], current_threats=['red-1'],
                       threat_forecast=dict(standing_exposure=[dict(id='red-1', ready_in_s=.2, damage_per_hit=25)]))
        result = build(self.unit, [self.enemy], spatial, 10)
        self.assertEqual(self.unit['hp'], self.unit['max_hp'])
        self.assertIn('predicted_standing_exposure', result['threats']['warning_before_damage'])
        self.assertIn('enemy_distance_reach_not_los', result['threats']['warning_before_damage'])
        self.assertEqual(result['threats']['standing_forecast'][0]['damage_per_hit'], 25)

    def test_stale_spatial_data_cannot_claim_a_valid_retreat_or_threat_ray(self):
        spatial = dict(sampled_at=1, origin=[0, 0], current_threats=['red-1'],
                       withdrawal_positions=[dict(position=[-.2, 0])], blocked_shots=['red-1'])
        result = build(self.unit, [self.enemy], spatial, 10)
        self.assertEqual(result['threats']['sampled'], [])
        self.assertEqual(result['tradeoffs']['withdraw']['queried_options'], 0)
        self.assertEqual(result['targets'][0]['fire_lane'], 'native_candidate_requires_muzzle_check')

    def test_one_volley_compares_ready_enemy_weapon_damage_to_current_hp(self):
        spatial = dict(sampled_at=9.5, origin=[0, 0], threat_forecast=dict(standing_exposure=[
            dict(id='red-1', ready_in_s=0, damage_per_hit=25),
            dict(id='red-2', ready_in_s=1, damage_per_hit=30),
            dict(id='red-3', ready_in_s=1.1, damage_per_hit=100)]))
        volley = build(self.unit, [self.enemy], spatial, 10)['threats']['one_volley_potential']
        self.assertEqual(volley['damage'], 55)
        self.assertEqual(volley['hp'], 50)
        self.assertEqual(volley['shooters'], ['red-1', 'red-2'])
        self.assertTrue(volley['damage_meets_current_hp'])
        self.assertEqual(volley['status'], 'complete_sample')
        self.assertIn('不是预计命中伤害', volley['basis'])
        self.assertIn('不是总伤害上界', volley['basis'])

    def test_missing_damage_or_readiness_is_explicitly_partial_not_guessed(self):
        spatial = dict(sampled_at=10, origin=[0, 0], threat_forecast=dict(standing_exposure=[
            dict(id='red-1', ready_in_s=0, damage_per_hit=25),
            dict(id='red-2', ready_in_s=.2),
            dict(id='red-3', damage_per_hit=100)]))
        volley = build(self.unit, [self.enemy], spatial, 10)['threats']['one_volley_potential']
        self.assertEqual(volley['status'], 'partial')
        self.assertEqual(volley['damage'], 25)
        self.assertEqual(volley['shooters'], ['red-1'])
        self.assertEqual(volley['unquantified_shooters'], ['red-2', 'red-3'])
        self.assertFalse(volley['damage_meets_current_hp'])

    def test_unavailable_volley_query_is_unknown_not_zero_damage(self):
        for spatial in [{}, dict(sampled_at=10, origin=[0, 0]),
                        dict(sampled_at=1, origin=[0, 0], threat_forecast=dict(standing_exposure=[]))]:
            with self.subTest(spatial=spatial):
                volley = build(self.unit, [self.enemy], spatial, 10)['threats']['one_volley_potential']
                self.assertEqual(volley['status'], 'unknown')
                self.assertIsNone(volley['damage'])
                self.assertIsNone(volley['damage_meets_current_hp'])

    def test_dead_targets_excluded_and_input_not_mutated(self):
        dead = dict(self.enemy, id='red-2', hp=0)
        before = copy.deepcopy(self.unit)
        result = build(self.unit, [self.enemy, dead], {}, 10)
        self.assertEqual([t['id'] for t in result['targets']], ['red-1'])
        self.assertEqual(self.unit, before)


if __name__ == '__main__':
    unittest.main()
