import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from idle_guard import constrain_idle_routes


class IdleGuardChecks(unittest.TestCase):
    def setUp(self):
        self.task = {'command': 'occupy'}
        self.unit = {'hp': 50, 'max_hp': 50, 'order_mode': 'hold',
                     'suppression': 0, 'reload_remaining': 0,
                     'combat': {'path_active': False, 'engageable_targets': []}}
        self.feedback = {'no_movement_seconds': 4, 'unproductive_seconds': 4}
        self.options = {
            'continue_task': {'command': {'action': 'wait'}},
            'halt': {'command': {'action': 'hold'}},
            'local_region_0': {'command': {'action': 'move'},
                               'native_step_risk': {'status': 'sampled',
                                                    'peak_attackers': 0,
                                                    'exposed_s': 0}},
            'local_region_1': {'command': {'action': 'move'},
                               'native_step_risk': {'status': 'sampled',
                                                    'peak_attackers': 0,
                                                    'exposed_s': 0.1}},
        }

    def test_idle_occupier_must_choose_among_safe_steps(self):
        self.assertTrue(constrain_idle_routes(self.options, self.task, self.unit,
                                              self.feedback, 'none'))
        self.assertNotIn('continue_task', self.options)
        self.assertNotIn('halt', self.options)
        self.assertIn('local_region_0', self.options)
        self.assertIn('local_region_1', self.options)

    def test_no_known_safe_step_keeps_wait_available(self):
        self.options['local_region_0']['native_step_risk']['peak_attackers'] = 1
        self.options['local_region_1']['native_step_risk']['status'] = 'unknown'
        self.assertFalse(constrain_idle_routes(self.options, self.task, self.unit,
                                               self.feedback, 'none'))
        self.assertIn('continue_task', self.options)

    def test_sampled_region_goal_is_also_a_valid_jev_choice(self):
        self.options.pop('local_region_0')
        self.options.pop('local_region_1')
        self.options['region_goal_0'] = {
            'command': {'action': 'move'},
            'native_step_risk': {'status': 'sampled', 'peak_attackers': 0,
                                 'exposed_s': 0.1}}
        self.assertTrue(constrain_idle_routes(self.options, self.task, self.unit,
                                              self.feedback, 'none'))
        self.assertIn('region_goal_0', self.options)

    def test_native_cover_cycle_and_active_move_are_not_interrupted(self):
        self.assertFalse(constrain_idle_routes(self.options, self.task, self.unit,
                                               self.feedback, 'peeking'))
        self.unit['combat']['path_active'] = True
        self.assertFalse(constrain_idle_routes(self.options, self.task, self.unit,
                                               self.feedback, 'none'))

    def test_failed_support_position_requires_a_new_safe_route(self):
        self.task['command'] = 'support'
        self.feedback['local_failure'] = {'action': 'local_reposition'}
        self.assertTrue(constrain_idle_routes(self.options, self.task, self.unit,
                                              self.feedback, 'none'))
        self.assertNotIn('continue_task', self.options)

    def test_support_native_cover_cycle_without_failure_keeps_wait(self):
        self.task['command'] = 'support'
        self.assertFalse(constrain_idle_routes(self.options, self.task, self.unit,
                                               self.feedback, 'peeking'))
        self.assertIn('continue_task', self.options)


if __name__ == '__main__':
    unittest.main()
