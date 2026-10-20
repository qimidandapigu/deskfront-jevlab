import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from battlefield_equipment import equipment_brief, equipment_opportunities, personal_equipment_opportunities


class EquipmentOpportunityChecks(unittest.TestCase):
    def setUp(self):
        self.gun = dict(id='mortar', kind='mortar', faction='neutral', position=[1., 0.],
                        hp=85, capturable=True, seen_by=['green'], capture_radius=.24,
                        capture_seconds=3., capture_progress=.25, capture_team='green',
                        ammunition_policy='unlimited_reserve',
                        minimum_range=.4, range=3.2,
                        capabilities=dict(damage=72., armor_multiplier=7 / 12, accuracy=.448,
                                          splash=.25, single_setup_seconds=3.5,
                                          setup_seconds=2.5, single_crew_cooldown=10., cooldown=8.),
                        capture_candidates=[dict(unit_id='g1', eligible=True, eligibility_without_distance=True,
                                                 reason='', blocking_conditions=[]),
                                            dict(unit_id='g2', eligible=False, eligibility_without_distance=False,
                                                 reason='suppression', blocking_conditions=['suppression']),
                                            dict(unit_id='hidden-enemy', eligible=True, reason='')])
        self.members = [dict(id='g1', faction='green', position=[.8, 0.], hp=40, max_hp=50,
                             weapon='rifle', suppression=.1, survival_reason=''),
                        dict(id='g2', faction='green', position=[.3, 0.], hp=45, max_hp=50,
                             weapon='rocket', suppression=.6, survival_reason='incoming_shell')]
        self.contacts = [dict(id='visible-tank', kind='tank', position=[2., 0.], visible=True),
                         dict(id='unseen-tank', kind='tank', position=[1.1, 0.], visible=False)]
        self.weapons = dict(rifle=dict(damage=10., armor_multiplier=.08, range=.7),
                            rocket=dict(damage=80., armor_multiplier=1.0, range=1.2))

    def opportunity(self):
        return equipment_opportunities([self.gun], self.members, self.contacts, self.weapons)[0]

    def test_candidate_facts_use_native_admission_and_distinguish_straight_line_from_navigation(self):
        before = copy.deepcopy((self.gun, self.members, self.contacts, self.weapons))
        row = self.opportunity()
        first, second = row['candidates']
        self.assertEqual(first['id'], 'g1')
        self.assertEqual(first['distance'], .2)
        self.assertTrue(first['native_capture_eligible'])
        self.assertTrue(first['in_capture_radius'])
        self.assertEqual(first['distance_basis'], 'euclidean_not_navigation_cost')
        self.assertIsNone(first['path_cost'])
        self.assertEqual(first['path_status'], 'unknown_not_queried')
        self.assertEqual(second['native_admission_reason'], 'suppression')
        self.assertEqual(second['emergency_status'], 'active')
        self.assertFalse(second['eligibility_without_distance'])
        self.assertNotIn('selected_actor', row)
        self.assertEqual((self.gun, self.members, self.contacts, self.weapons), before)

    def test_missing_engine_rules_stay_unknown_even_when_nearby_member_is_healthy(self):
        for key in ('capture_candidates', 'capture_radius', 'capabilities', 'capture_seconds', 'ammunition_policy'):
            self.gun.pop(key)
        self.members[0].pop('survival_reason')
        row = self.opportunity()
        self.assertIsNone(row['candidates'][0]['native_capture_eligible'])
        self.assertIsNone(row['candidates'][0]['eligibility_without_distance'])
        self.assertIsNone(row['candidates'][0]['in_capture_radius'])
        self.assertEqual(row['candidates'][0]['emergency_status'], 'unknown')
        self.assertIsNone(row['capability']['damage'])
        self.assertIsNone(row['capability']['single_setup_seconds'])
        self.assertIsNone(row['capability']['ammunition_policy'])
        self.assertIsNone(row['remaining_capture_seconds'])

    def test_payload_and_own_weapons_are_comparable_without_pretending_actual_hit_damage(self):
        row = self.opportunity()
        self.assertEqual(row['capability']['single_setup_seconds'], 3.5)
        self.assertEqual(row['capability']['ammunition_policy'], 'unlimited_reserve')
        self.assertEqual(row['capability']['direct_damage_before_target_armor'], 42.)
        armor = row['visible_armor'][0]
        self.assertEqual(armor['id'], 'visible-tank')
        self.assertTrue(armor['in_equipment_range'])
        weapons = {w['unit_id']: w for w in armor['own_weapon_comparison']}
        self.assertEqual(weapons['g1']['direct_damage_before_target_armor'], .8)
        self.assertEqual(weapons['g2']['direct_damage_before_target_armor'], 80.)
        self.assertIsNone(weapons['g1']['actual_hit_damage'])
        self.assertEqual(weapons['g1']['firing_line'], 'unknown_not_queried')
        self.assertEqual(armor['friendly_blast_clearance'], 'unknown_not_queried')

    def test_native_top_attack_payload_bypasses_direct_fire_armor_multiplier(self):
        self.gun['capabilities']['top_attack'] = True
        capability = self.opportunity()['capability']
        self.assertEqual(capability['direct_damage_before_target_armor'], 72.)
        self.assertEqual(capability['tank_effect_basis'], 'top_attack_payload_times_tank_multiplier_before_blast_and_shield')
        self.assertTrue(capability['top_attack'])
        self.assertIsNone(capability['actual_hit_damage'])
        self.gun['capabilities'].pop('armor_multiplier')
        self.assertEqual(self.opportunity()['capability']['direct_damage_before_target_armor'], 72.)

    def test_tank_only_modifier_preserves_base_payload_and_directional_armor_semantics(self):
        self.gun['capabilities'].update(top_attack=False, tank_damage_multiplier=3.)
        world = dict(at_guns=[self.gun], units=self.members)
        brief = equipment_brief(world, 'green', [])
        self.assertEqual(brief[0]['capabilities']['tank_damage_multiplier'], 3.)
        row = equipment_opportunities(brief, self.members, self.contacts, self.weapons)[0]
        self.assertEqual(row['capability']['damage'], 72.)
        self.assertEqual(row['capability']['armor_multiplier'], 7 / 12)
        self.assertFalse(row['capability']['top_attack'])
        self.assertEqual(row['capability']['direct_damage_before_target_armor'], 126.)
        self.assertIsNone(row['capability']['actual_hit_damage'])
        self.assertEqual(row['visible_armor'][0]['own_weapon_comparison'][0]['direct_damage_before_target_armor'], .8)

    def test_top_attack_and_tank_modifier_are_independent_native_metadata(self):
        self.gun['capabilities'].update(top_attack=True, tank_damage_multiplier=3.)
        self.assertEqual(self.opportunity()['capability']['direct_damage_before_target_armor'], 216.)

    def test_equipment_discovery_does_not_reveal_dispersion_distance_to_hidden_known_point(self):
        self.gun['capabilities'].update(dispersion_model='artillery_disk_v2',
                                        dispersion_radius_for_known_point=.056)
        world = dict(at_guns=[self.gun], units=self.members)
        brief = equipment_brief(world, 'green', [])
        self.assertEqual(brief[0]['capabilities']['dispersion_model'], 'artillery_disk_v2')
        self.assertNotIn('dispersion_radius_for_known_point', brief[0]['capabilities'])

    def test_hidden_or_unconfirmed_tank_position_never_used(self):
        self.contacts.append(dict(id='unconfirmed-tank', kind='tank', position=[3., 0.]))
        rows = self.opportunity()['visible_armor']
        self.assertEqual([row['id'] for row in rows], ['visible-tank'])
        self.contacts[0]['visible'] = False
        self.assertEqual(self.opportunity()['visible_armor'], [])

    def test_enemy_admission_candidates_do_not_leak_through_equipment_discovery(self):
        world = dict(at_guns=[self.gun], units=self.members +
                     [dict(id='hidden-enemy', faction='red', hp=50, position=[1., 0.])])
        equipment = equipment_brief(world, 'green', [])
        self.assertEqual([row['unit_id'] for row in equipment[0]['capture_candidates']], ['g1', 'g2'])
        opportunities = equipment_opportunities(equipment, self.members, [])
        self.assertNotIn('hidden-enemy', str(opportunities))
        self.gun['seen_by'] = ['red']
        self.assertEqual(equipment_opportunities(equipment_brief(world, 'green', []), self.members, []), [])

    def test_missing_weapon_configuration_never_invents_rifle_strength(self):
        row = equipment_opportunities([self.gun], self.members, self.contacts)[0]
        weapon = row['visible_armor'][0]['own_weapon_comparison'][0]
        self.assertIsNone(weapon['damage'])
        self.assertIsNone(weapon['armor_multiplier'])
        self.assertIsNone(weapon['direct_damage_before_target_armor'])
        self.assertIsNone(weapon['weapon_range'])

    def test_native_timer_progress_is_preserved_without_inventing_a_stall(self):
        row = self.opportunity()
        self.assertEqual(row['remaining_capture_seconds'], 2.25)
        self.assertEqual(row['capture_team'], 'green')
        self.assertEqual(row['capture_progress'], .25)
        self.assertNotIn('capture_failed', row)
        self.assertNotIn('capture_stall_seconds', row)

    def test_dead_member_and_owned_gun_are_not_capture_opportunities(self):
        self.members[1]['hp'] = 0
        self.assertEqual([row['id'] for row in self.opportunity()['candidates']], ['g1'])
        self.gun.update(faction='green', capturable=False)
        self.assertEqual(equipment_opportunities([self.gun], self.members, self.contacts), [])

    def test_personal_view_only_preserves_own_admission_and_weapon_comparison(self):
        opportunities = [self.opportunity()]
        before = copy.deepcopy(opportunities)
        row = personal_equipment_opportunities(opportunities, 'g1')[0]
        self.assertEqual([candidate['id'] for candidate in row['candidates']], ['g1'])
        self.assertEqual([weapon['unit_id'] for weapon in row['visible_armor'][0]['own_weapon_comparison']], ['g1'])
        self.assertEqual(row['capability'], opportunities[0]['capability'])
        self.assertEqual(opportunities, before)
        self.assertEqual(personal_equipment_opportunities(opportunities, 'not-a-member'), [])

    def test_current_native_contested_gate_is_preserved_without_contestant_identity(self):
        self.gun['capture_candidates'][0].update(eligible=False, contested=True,
            block_reasons=['contested'], contestant_ids=['unseen-enemy'])
        self.gun['capture_candidates'][0].pop('reason')
        self.gun['capture_candidates'][0].pop('blocking_conditions')
        world = dict(at_guns=[self.gun], units=self.members)
        opportunities = equipment_opportunities(equipment_brief(world, 'green', []), self.members, [])
        candidate = opportunities[0]['candidates'][0]
        self.assertFalse(candidate['native_capture_eligible'])
        self.assertTrue(candidate['contested'])
        self.assertEqual(candidate['native_admission_reason'], 'contested')
        self.assertNotIn('unseen-enemy', str(opportunities))


if __name__ == '__main__':
    unittest.main()
