"""Evidence boundaries for the per-unit local route selector."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from local_maneuver import build_local_maneuvers


def fixture():
    cells = {str(i): [i * .1, 0] for i in range(13)}
    topology = dict(cells=cells, edges=[[str(i), str(i+1)] for i in range(12)], step=.1)
    regions = {
        'A': dict(cells=[cells[str(i)] for i in range(4)], neighbors=['B'], sample_step=.1),
        'B': dict(cells=[cells[str(i)] for i in range(4, 9)], neighbors=['A', 'C'], sample_step=.1),
        'C': dict(cells=[cells[str(i)] for i in range(9, 13)], neighbors=['B'], sample_step=.1),
    }
    risk = dict(status='sampled', travel_s=1.2, exposed_s=.25, peak_attackers=1)
    spatial = dict(origin=[0, 0], navigation_steps=[
        dict(cell_id=str(i), position=cells[str(i)], risk=risk) for i in (1, 2, 3)
    ], firing_positions=[])
    unit = dict(id='green-1', position=[0, 0], hp=50, weapon_range=.5)
    task = dict(command='support', target_id='red-1', region_id='A', region_path=['A'])
    enemies = [dict(id='red-1', position=[1.2, 0], hp=50, combat_ready=True)]
    return unit, task, spatial, regions, topology, enemies


def choices(*, unit=None, task=None, spatial=None, regions=None, topology=None,
            enemies=None, reservations=(), current_destination=None):
    defaults = fixture()
    values = [unit, task, spatial, regions, topology, enemies]
    values = [default if value is None else value for value, default in zip(values, defaults)]
    return build_local_maneuvers(*values[:5], reservations, enemies=values[5],
                                 current_destination=current_destination)


class LocalManeuverChecks(unittest.TestCase):
    def test_far_target_gets_only_native_short_step_with_unknown_fire_lane(self):
        options, report = choices()
        self.assertEqual(report['reason'], 'connected_approach_fire_lane_unknown')
        self.assertLessEqual(len(options), 4)
        self.assertTrue(options)
        for value in options.values():
            self.assertFalse(value['fire_lane_evidence'])
            self.assertEqual(value['native_step_risk']['status'], 'sampled')
            self.assertIn(value['command']['position'], ([.1, 0], [.2, 0], [.3, 0]))
            self.assertGreater(value['destination'][0], value['command']['position'][0])
            self.assertIn('射界未知', value['description'])
            self.assertIn('预测不保证安全', value['description'])

    def test_native_firing_point_is_target_specific_evidence(self):
        unit, task, spatial, regions, topology, enemies = fixture()
        spatial['firing_positions'] = [
            dict(position=[.2, 0], targets=['red-2'], risk=dict(status='sampled')),
            dict(position=[.3, 0], targets=['red-1'], risk=dict(status='sampled', travel_s=1, exposed_s=0)),
        ]
        options, report = choices(unit=unit, task=task, spatial=spatial,
                                  regions=regions, topology=topology, enemies=enemies)
        self.assertEqual(report['native_firing_points'], 1)
        fire = next(value for value in options.values() if value['fire_lane_evidence'])
        self.assertEqual(fire['destination'], [.3, 0])
        self.assertEqual(fire['command']['position'], [.2, 0])
        self.assertIn('原生站姿射线', fire['description'])
        self.assertNotIn([.2, 0], [value['destination'] for value in options.values()
                                   if value['fire_lane_evidence']])

    def test_disconnected_goal_does_not_invent_a_path(self):
        unit, task, spatial, regions, topology, enemies = fixture()
        topology['edges'] = []
        options, report = choices(unit=unit, task=task, spatial=spatial,
                                  regions=regions, topology=topology, enemies=enemies)
        self.assertFalse(options)
        self.assertIn(report['reason'], ('no_reachable_native_short_step',
                                         'no_connected_approach_or_fire_lane'))

    def test_unreachable_native_step_is_not_offered(self):
        unit, task, spatial, regions, topology, enemies = fixture()
        for step in spatial['navigation_steps']:
            step['risk'] = dict(status='unreachable')
        options, report = choices(unit=unit, task=task, spatial=spatial,
                                  regions=regions, topology=topology, enemies=enemies)
        self.assertFalse(options)
        self.assertEqual(report['reason'], 'no_reachable_native_short_step')

    def test_reserved_short_steps_are_excluded(self):
        options, report = choices(reservations=[[.1, 0], [.2, 0], [.3, 0]])
        self.assertFalse(options)
        self.assertEqual(report['reason'], 'no_reachable_native_short_step')

    def test_current_destination_is_offered_as_commitment(self):
        unit, task, spatial, regions, topology, enemies = fixture()
        spatial['firing_positions'] = [dict(position=[.2, 0], targets=['red-1'],
                                            risk=dict(status='sampled', travel_s=.5, exposed_s=.1))]
        options, _ = choices(unit=unit, task=task, spatial=spatial,
                             regions=regions, topology=topology, enemies=enemies,
                             current_destination=[.2, 0])
        self.assertIn('local_continue', options)
        self.assertTrue(options['local_continue']['fire_lane_evidence'])
        self.assertEqual(options['local_continue']['score'], 104)
        self.assertNotIn('local_fire_0', options)  # identical goal is not repeated

    def test_dead_assigned_target_does_not_chase_a_different_enemy(self):
        unit, task, spatial, regions, topology, enemies = fixture()
        enemies[0]['hp'] = 0
        enemies.append(dict(id='red-2', position=[.5, 0], hp=50))
        options, report = choices(unit=unit, task=task, spatial=spatial,
                                  regions=regions, topology=topology, enemies=enemies)
        self.assertFalse(options)
        self.assertEqual(report['reason'], 'assigned_target_not_live')

    def test_region_hint_uses_sampled_cell_and_never_claims_fire_lane(self):
        unit, task, spatial, regions, topology, _enemies = fixture()
        task = dict(command='occupy', region_id='C')
        options, report = choices(unit=unit, task=task, spatial=spatial,
                                  regions=regions, topology=topology, enemies=[])
        self.assertEqual(report['reason'], 'connected_region_approach_fire_lane_unknown')
        self.assertTrue(options)
        for value in options.values():
            self.assertFalse(value['fire_lane_evidence'])
            self.assertIn(value['destination'], regions['C']['cells'])
            self.assertIn(value['command']['position'], ([.1, 0], [.2, 0], [.3, 0]))

    def test_missing_spatial_query_is_explicit(self):
        options, report = choices(spatial={})
        self.assertFalse(options)
        self.assertEqual(report['reason'], 'spatial_query_unavailable')

    def test_unknown_weapon_range_does_not_invent_an_approach_goal(self):
        unit, task, spatial, regions, topology, enemies = fixture()
        unit.pop('weapon_range')
        options, report = choices(unit=unit, task=task, spatial=spatial,
                                  regions=regions, topology=topology, enemies=enemies)
        self.assertFalse(options)
        self.assertEqual(report['reason'], 'weapon_range_unknown')

    def test_rifle_does_not_approach_a_tank_as_an_attack_goal(self):
        unit, task, spatial, regions, topology, enemies = fixture()
        unit['weapon'] = 'rifle'
        enemies[0]['kind'] = 'tank'
        options, report = choices(unit=unit, task=task, spatial=spatial,
                                  regions=regions, topology=topology, enemies=enemies)
        self.assertFalse(options)
        self.assertEqual(report['reason'], 'weapon_cannot_damage_target')


if __name__ == '__main__':
    unittest.main()
