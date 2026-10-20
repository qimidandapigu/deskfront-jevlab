import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from battlefield_equipment import equipment_brief, equipment_route_fact, equipment_task, live_plan_brief, validate_equipment_goal
from soldier_candidate_query import proposals


class EquipmentIntelligenceChecks(unittest.TestCase):
    def setUp(self):
        self.gun = dict(id='mortar', kind='mortar', faction='red', position=[1., 0.], hp=85,
                        crew_ids=['gunner', 'guard'], gunner_id='gunner', guard_id='guard',
                        crew_alive=2, capturable=False, seen_by=['red', 'green'])
        self.world = dict(at_guns=[self.gun], units=[dict(id='guard', faction='red', hp=50, position=[1., .2])])

    def test_discovered_equipment_preserves_role_identity_but_not_hidden_coordinates(self):
        result = equipment_brief(self.world, 'green', [])[0]
        self.assertEqual(result['gunner_id'], 'gunner')
        self.assertEqual(result['guard_id'], 'guard')
        self.assertEqual([c['role'] for c in result['crew']], ['gunner', 'guard'])
        for crew in result['crew']:
            self.assertNotIn('position', crew)
            self.assertNotIn('hp', crew)
            self.assertFalse(crew['visible'])
            self.assertEqual(crew['targeting'], 'reacquire_visual_contact')

    def test_known_target_and_equipment_have_bidirectional_role_association(self):
        contacts = [dict(id='gunner', visible=True, position=[.9, 0.], last_seen=10)]
        before = copy.deepcopy(self.world)
        result = equipment_brief(self.world, 'green', contacts)[0]
        self.assertEqual(contacts[0]['equipment_role'], 'gunner')
        self.assertEqual(contacts[0]['equipment_id'], 'mortar')
        self.assertEqual(result['crew'][0]['position'], [.9, 0.])
        self.assertNotIn('position', result['crew'][1])
        self.assertEqual(self.world, before)

    def test_undiscovered_equipment_does_not_reveal_crew_ids(self):
        self.gun['seen_by'] = ['red']
        self.assertEqual(equipment_brief(self.world, 'green', []), [])

    def test_nondamageable_equipment_is_not_presented_as_a_health_target(self):
        self.gun.update(damageable=False, target_policy='crew_only')
        row = equipment_brief(self.world, 'green', [])[0]
        self.assertFalse(row['damageable'])
        self.assertEqual(row['target_policy'], 'crew_only')
        self.assertNotIn('hp', row)

    def test_own_operator_is_friendly_known_support_not_a_hidden_enemy(self):
        self.gun.update(faction='green', crew_ids=['operator'], gunner_id='operator', guard_id='',
                        crew_alive=1, minimum_range=.4, range=3.2, last_block_reason='no_visible_target')
        self.world['units'].append(dict(id='operator', faction='green', hp=50, position=[1., .1],
                                        weapon='rifle', gun_id='mortar', order_mode='operate_mortar'))
        before = copy.deepcopy(self.world)
        row = equipment_brief(self.world, 'green', [])[0]
        self.assertEqual(row['control_status'], 'friendly_operated')
        self.assertEqual(row['crew'][0]['targeting'], 'friendly_do_not_attack')
        self.assertEqual(row['crew'][0]['position'], [1., .1])
        self.assertTrue(row['crew'][0]['visible'])
        self.assertEqual(row['last_block_reason'], 'no_visible_target')
        self.assertEqual(self.world, before)
        goal = dict(equipment_id='mortar', phase='support_fire', reason='侦察报点')
        self.assertEqual(validate_equipment_goal(goal, [row], [dict(id='scout', weapon='rifle')])['phase'], 'support_fire')
        with self.assertRaises(ValueError):
            validate_equipment_goal(dict(goal, phase='reconnoitre'), [row], [dict(id='scout', weapon='rifle')])

    def test_capture_plan_is_invalidated_when_equipment_changes_owner(self):
        self.gun.update(faction='neutral', capturable=True, crew_alive=0, crew_ids=[], gunner_id='', guard_id='')
        members = [dict(id='g', weapon='rifle')]
        goal = validate_equipment_goal(dict(equipment_id='mortar', phase='capture', reason='接管'), equipment_brief(self.world, 'green', []), members)
        plan = dict(objective='去夺敌炮', risk='炮组未知', wait_for='清除炮组', equipment_goal=goal)
        self.gun.update(faction='green', capturable=False, crew_alive=1, gunner_id='operator', crew_ids=['operator'])
        brief = live_plan_brief(plan, self.world, 'green', members)
        self.assertEqual(brief['invalid_reason'], 'equipment_control_changed')
        self.assertEqual(brief['objective'], '')
        self.assertNotIn('equipment_goal', brief)

    def test_occupied_enemy_mortar_offers_reconnaissance_steps_without_claiming_capture(self):
        unit = dict(id='g', faction='green', position=[0., 0.], weapon='rifle')
        regions = {'a': dict(center=[0., 0.], cells=[[.15, 0.], [.3, 0.], [.8, 0.]])}
        rows = proposals(unit, dict(region_path=['a']), regions, dict(cells={'x': [0., 0.]}), equipment=[self.gun])
        steps = [r for r in rows if r['kind'] == 'equipment_approach']
        self.assertTrue(steps)
        self.assertTrue(all(r['purpose'] == 'reconnoitre_enemy_crew' and r['position'][0] <= .42 for r in steps))
        self.gun.update(capturable=True, faction='neutral')
        rows = proposals(unit, dict(region_path=['a']), regions, dict(cells={'x': [0., 0.]}), equipment=[self.gun])
        self.assertTrue(all(r['purpose'] == 'capture' for r in rows if r['kind'] == 'equipment_approach'))

    def test_dead_member_dependencies_are_removed_without_replacing_executable_destination(self):
        self.world['units'].append(dict(id='green-3', faction='green', hp=0))
        plan = dict(region_id='a', stage='approach', position=[0., 0.],
                    objective='green-3装填后打坦克', wait_for='green-3装填完成', risk='前方未知')
        result = live_plan_brief(plan, self.world, 'green', [dict(id='green-1')])
        self.assertTrue(result['requires_replan'])
        self.assertEqual(result['invalid_dependencies'], ['green-3'])
        self.assertEqual(result['wait_for'], '')
        self.assertEqual(result['region_id'], plan['region_id'])
        self.assertNotEqual(plan['objective'], '')

    def test_commander_equipment_intent_requires_known_asset_real_gate_and_no_personnel(self):
        equipment = equipment_brief(self.world, 'green', [])
        members = [dict(id='g', weapon='rifle'), dict(id='cover', weapon='rifle')]
        goal = dict(equipment_id='mortar', phase='reconnoitre', reason='先观察炮组')
        result = validate_equipment_goal(goal, equipment, members)
        self.assertNotIn('actor_id', result)
        self.assertEqual(result['source'], 'commander_intent_not_personnel_assignment')
        for field, bad in [('actor_id', 'dead'), ('equipment_id', 'hidden'), ('phase', 'capture'), ('phase', 'attack_crew')]:
            with self.assertRaises(ValueError):
                validate_equipment_goal(dict(goal, **{field: bad}), equipment, members)
        self.gun.update(capturable=True, faction='neutral')
        equipment = equipment_brief(self.world, 'green', [])
        self.assertEqual(validate_equipment_goal(dict(goal, phase='capture'), equipment, members)['phase'], 'capture')
        # The commander decides the task; JEV selects the eligible operator.
        self.assertNotIn('actor_id', validate_equipment_goal(dict(goal, phase='capture'), equipment,
            [dict(id='g', weapon='rocket'), members[1]]))

    def test_commander_equipment_goal_has_no_personnel_dependency(self):
        self.world['units'].append(dict(id='green-3', faction='green', hp=0))
        plan = dict(region_id='a', objective='观察炮位', wait_for='',
                    equipment_goal=dict(equipment_id='mortar', phase='reconnoitre'))
        result = live_plan_brief(plan, self.world, 'green', [dict(id='green-1')])
        self.assertFalse(result.get('requires_replan'))
        self.assertEqual(result['equipment_goal'], plan['equipment_goal'])

    def test_assigned_living_crew_is_not_reported_as_a_ready_operator(self):
        self.gun.update(operator_ready=False, gunner_at_station=False, crew_at_weapon=[],
                        phase='returning', operation_radius=.07, gunner_station=[1., -.035])
        row = equipment_brief(self.world, 'green', [])[0]
        self.assertEqual(row['crew_alive'], 2)
        self.assertFalse(row['operator_ready'])
        self.assertEqual(row['operation_status'], 'not_ready')
        self.assertEqual(row['phase'], 'returning')
        self.assertFalse(row['capturable'])
        self.assertEqual(row['crew_at_weapon'], [])
        self.assertNotIn('position', row['crew'][0])

    def test_attack_crew_route_compares_the_assigned_crew_instead_of_nearest_tank(self):
        gun = equipment_brief(self.world, 'green', [dict(id='gunner', visible=True, position=[1., 0.])])[0]
        goal = dict(equipment_id='mortar', phase='attack_crew', actor_id='g', support_ids=[])
        unit = dict(id='g', position=[0., 0.], weapon_range=.7)
        toward = equipment_route_fact(unit, [.5, 0.], goal, [gun])
        away = equipment_route_fact(unit, [-.2, 0.], goal, [gun])
        self.assertEqual(toward['target_id'], 'gunner')
        self.assertEqual(toward['distance_gain'], .5)
        self.assertTrue(toward['in_weapon_range'])
        self.assertEqual(toward['firing_line'], 'unverified')
        self.assertLess(away['distance_gain'], 0)
        self.assertIsNone(equipment_route_fact(dict(unit, id='other'), [.5, 0.], goal, [gun]))

    def test_hidden_crew_coordinates_are_not_used_to_compute_attack_routes(self):
        gun = equipment_brief(self.world, 'green', [])[0]
        goal = dict(equipment_id='mortar', phase='attack_crew', actor_id='g', support_ids=[])
        fact = equipment_route_fact(dict(id='g', position=[0., 0.]), [.5, 0.], goal, [gun])
        self.assertEqual(fact['basis'], 'crew_visual_contact_lost')
        self.assertNotIn('destination_distance', fact)
        self.assertNotIn('target_id', fact)

    def test_task_engageable_targets_require_personal_fire_evidence_not_team_visibility(self):
        gun = equipment_brief(self.world, 'green', [dict(id='gunner', visible=True, position=[1., 0.])])[0]
        goal = dict(equipment_id='mortar', phase='attack_crew', actor_id='g', support_ids=[])
        unit = dict(id='g', position=[.5, 0.], combat=dict(engageable_targets=['tank', 'guard']))
        task = equipment_task(goal, [gun], [unit])
        self.assertEqual(task['visible_crew_ids'], ['gunner'])
        self.assertEqual(task['actor_engageable_crew_ids'], [])
        unit['combat']['engageable_targets'].append('gunner')
        self.assertEqual(equipment_task(goal, [gun], [unit])['actor_engageable_crew_ids'], ['gunner'])

    def test_capture_route_reports_radius_without_claiming_capture_completion(self):
        self.gun.update(faction='neutral', capturable=True, capture_radius=.24, capture_progress=0)
        gun = equipment_brief(self.world, 'green', [])[0]
        goal = dict(equipment_id='mortar', phase='capture', actor_id='g', support_ids=[])
        fact = equipment_route_fact(dict(id='g', position=[.5, 0.]), [.85, 0.], goal, [gun])
        self.assertTrue(fact['inside_capture_radius'])
        self.assertNotIn('completed', fact)


if __name__ == '__main__':
    unittest.main()
