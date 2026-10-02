"""Observed fire-task failure must not confuse arrival with effective support."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'deskfront'))
from local_failure import assess


class LocalFailureChecks(unittest.TestCase):
    def setUp(self):
        self.unit = dict(id='green-1', hp=50, position=[0, 0], weapon_range=.7,
                         ammo=8, reload_remaining=0, suppression=0,
                         last_shot_at=-100, last_shot_target='',
                         combat=dict(path_active=False, engageable_targets=[]))
        self.enemy = dict(id='red-1', hp=50, position=[1.4, 0])
        self.state = dict(time=10, units=[self.unit, self.enemy])
        self.task = dict(command='support', target_id='red-1', region_id='R1',
                         region_path=['R1'], task_revision=1)
        self.feedback = dict(region_navigation=dict(status='arrived'))

    def evaluate(self, previous=None, candidates=None):
        return assess(self.task, self.unit, self.state, self.feedback,
                      previous, candidates)

    def test_arrival_outside_weapon_range_requests_local_reposition(self):
        row = self.evaluate()
        self.assertTrue(row['arrived'])
        self.assertEqual(row['reason'], 'target_out_of_range_at_destination')
        self.assertEqual(row['action'], 'local_reposition')
        self.assertNotEqual(row['phase'], 'effective')
        self.assertEqual(row['range_gap'], .7)

    def test_actual_shot_of_assigned_target_is_effective(self):
        previous = self.evaluate()
        self.state['time'] = 11
        self.unit['last_shot_at'] = 10.5
        self.unit['last_shot_target'] = 'red-1'
        self.assertEqual(self.evaluate(previous)['phase'], 'effective')
        self.unit['last_shot_target'] = 'red-2'
        self.assertNotEqual(self.evaluate(previous)['phase'], 'effective')

    def test_reload_and_suppression_do_not_trigger_replan(self):
        self.unit['reload_remaining'] = 1.2
        row = self.evaluate()
        self.assertEqual((row['phase'], row['action']), ('recovering', 'continue'))
        self.unit['reload_remaining'] = 0
        self.unit['suppression'] = .98
        self.assertEqual(self.evaluate(row)['reason'], 'heavy_suppression')

    def test_reload_is_not_reported_as_missing_local_route(self):
        self.task.pop('region_id')
        self.task.pop('region_path')
        self.unit['reload_remaining'] = 2.5
        row = self.evaluate()
        self.state['time'] = 14
        self.assertEqual(self.evaluate(row)['reason'], 'reloading')

    def test_native_cover_cycle_is_not_a_stalled_route_or_absent_lane(self):
        self.enemy['position'] = [.55, 0]
        self.unit.update(cover_id='sandbag-1', cover_slot='sandbag-1:0',
                         cqb_stance='hide', in_cover=True)
        row = self.evaluate()
        self.assertEqual((row['phase'], row['reason']), ('engaging', 'native_cover_hide'))
        self.assertTrue(row['evidence']['cover_cycle'])
        self.assertEqual(row['evidence']['native_fire_lane'], 'not_in_candidates')
        self.state['time'] = 13.2
        self.unit.update(cqb_stance='peek', in_cover=False, cover_step=True)
        self.unit['combat']['path_active'] = True
        row = self.evaluate(row)
        self.assertEqual((row['action'], row['reason']), ('continue', 'cover_step_in_progress'))
        self.assertEqual(row['phase'], 'engaging')
        self.state['time'] = 15.9
        self.unit.update(cqb_stance='hide', in_cover=True, cover_step=False)
        self.unit['combat']['path_active'] = False
        self.assertEqual(self.evaluate(row)['reason'], 'native_cover_hide')

    def test_cover_cycle_without_fire_eventually_reports_uncertainty(self):
        self.enemy['position'] = [.55, 0]
        self.unit.update(cover_id='sandbag-1', cover_slot='sandbag-1:0',
                         cqb_stance='hide', in_cover=True)
        row = self.evaluate(candidates=None)
        self.assertEqual(row['evidence']['local_query'], 'not_run')
        self.state['time'] = 16.1
        row = self.evaluate(row, candidates={'nearby': {'id': 'nearby'}})
        self.assertEqual((row['reason'], row['action']),
                         ('fire_not_observed_during_cover_cycle', 'local_reposition'))
        self.assertEqual(row['evidence']['sampled_local_options'], 1)
        self.assertEqual(row['evidence']['local_query'], 'sampled')
        self.assertEqual(row['evidence']['range_gap_at_current_position'], 0)
        self.assertEqual(row['evidence']['range_basis'],
                         'current_position_distance_only_not_peek_muzzle')
        self.unit['last_shot_at'] = 16.2
        self.unit['last_shot_target'] = 'red-1'
        self.state['time'] = 16.3
        self.assertEqual(self.evaluate(row)['phase'], 'effective')

    def test_cover_reloading_or_cooling_down_is_not_fire_failure(self):
        self.enemy['position'] = [.55, 0]
        self.unit.update(cover_id='sandbag-1', cover_slot='sandbag-1:0',
                         cqb_stance='hide', in_cover=True)
        row = self.evaluate()
        self.state['time'] = 17
        self.unit['weapon_state'] = 'cooldown'
        self.assertEqual(self.evaluate(row)['reason'], 'weapon_cooldown')
        self.unit['weapon_state'] = 'reload'
        self.assertEqual(self.evaluate(row)['reason'], 'reloading')

    def test_fresh_muzzle_block_is_distinct_from_normal_cover_hide(self):
        self.enemy['position'] = [.55, 0]
        self.unit.update(cover_id='sandbag-1', cover_slot='sandbag-1:0',
                         cqb_stance='hide', in_cover=True)
        self.unit['combat']['fire_check'] = dict(status='blocked', target_id='red-1',
                                                  time=9.8, position=[0, 0],
                                                  reason='cover_blocks_muzzle')
        row = self.evaluate()
        self.assertEqual((row['reason'], row['action']),
                         ('muzzle_blocked', 'local_reposition'))

    def test_muzzle_block_is_fresh_only_at_same_position(self):
        self.enemy['position'] = [.5, 0]
        self.unit['combat']['engageable_targets'] = ['red-1']
        self.unit['combat']['fire_check'] = dict(status='blocked', target_id='red-1',
                                                  time=9.8, position=[0, 0],
                                                  reason='cover_blocks_muzzle')
        self.assertEqual(self.evaluate()['reason'], 'muzzle_blocked')
        self.unit['position'] = [0, .2]
        self.assertNotEqual(self.evaluate()['reason'], 'muzzle_blocked')

    def test_route_stall_clock_survives_ticks_and_resets_on_real_motion(self):
        self.feedback['region_navigation']['status'] = 'ready'
        self.unit['combat']['path_active'] = True
        row = self.evaluate()
        self.state['time'] = 13
        row = self.evaluate(row)
        self.assertEqual(row['phase'], 'advancing')
        self.state['time'] = 14.1
        row = self.evaluate(row)
        self.assertEqual((row['reason'], row['action']),
                         ('route_stalled', 'local_reposition'))
        self.unit['position'] = [.05, 0]
        self.state['time'] = 14.2
        self.assertEqual(self.evaluate(row)['phase'], 'advancing')

    def test_completed_local_search_escalates_only_when_empty(self):
        self.assertEqual(self.evaluate(candidates=[])['action'], 'commander_reassess')
        self.assertEqual(self.evaluate(candidates=None)['action'], 'local_reposition')
        self.assertEqual(self.evaluate(candidates=[dict(id='nearby')])['action'], 'local_reposition')
        self.enemy['position'] = [.5, 0]
        self.unit['combat']['engageable_targets'] = ['red-1']
        self.assertEqual(self.evaluate(candidates=[])['action'], 'continue')

    def test_nearby_target_without_shot_gets_settling_grace_then_repositions(self):
        self.enemy['position'] = [.5, 0]
        self.unit['combat']['engageable_targets'] = ['red-1']
        row = self.evaluate()
        self.assertEqual(row['reason'], 'settling_at_firing_position')
        self.state['time'] = 11.6
        row = self.evaluate(row)
        self.assertEqual(row['reason'], 'aiming_or_awaiting_fire')
        self.state['time'] = 13.1
        row = self.evaluate(row)
        self.assertEqual(row['reason'], 'fire_not_observed_after_arrival')
        self.assertEqual(row['action'], 'local_reposition')

    def test_task_revision_resets_stall_clock(self):
        self.feedback['region_navigation']['status'] = 'ready'
        self.unit['combat']['path_active'] = True
        row = self.evaluate()
        self.state['time'] = 15
        row = self.evaluate(row)
        self.assertEqual(row['reason'], 'route_stalled')
        self.task['task_revision'] = 2
        self.assertEqual(self.evaluate(row)['reason'], 'moving_toward_task')

    def test_no_commander_region_stationary_out_of_range_needs_local_route(self):
        self.task.pop('region_id')
        self.task.pop('region_path')
        row = self.evaluate()
        self.assertEqual(row['reason'], 'awaiting_local_route_or_fire')
        self.state['time'] = 11.6
        row = self.evaluate(row)
        self.assertEqual((row['reason'], row['action']),
                         ('no_local_route_selected', 'local_reposition'))
        self.assertFalse(row['arrived'])

    def test_no_commander_region_selected_destination_requires_actual_arrival(self):
        self.task.pop('region_id')
        self.task.pop('region_path')
        self.feedback['selected_destination'] = [.5, 0]
        self.assertFalse(self.evaluate()['arrived'])
        self.unit['position'] = [.48, 0]
        self.assertTrue(self.evaluate()['arrived'])
        self.assertNotEqual(self.evaluate()['phase'], 'effective')

    def test_no_commander_region_in_range_still_requires_actual_fire(self):
        self.task.pop('region_id')
        self.task.pop('region_path')
        self.enemy['position'] = [.5, 0]
        self.unit['combat']['engageable_targets'] = ['red-1']
        row = self.evaluate()
        self.state['time'] = 11.6
        row = self.evaluate(row)
        self.assertEqual((row['phase'], row['action']), ('positioned', 'continue'))
        self.state['time'] = 13.1
        row = self.evaluate(row)
        self.assertEqual(row['reason'], 'fire_not_observed_at_stationary_position')

    def test_no_target_id_with_observed_empty_lane_needs_local_route(self):
        self.task.pop('region_id')
        self.task.pop('region_path')
        self.task['target_id'] = ''
        row = self.evaluate()
        self.state['time'] = 11.6
        self.assertEqual(self.evaluate(row)['reason'], 'no_local_route_selected')


if __name__ == '__main__':
    unittest.main()
