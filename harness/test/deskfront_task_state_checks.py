"""Task dependency regressions independent of the engine and model providers."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'deskfront'))
from task_execution import constrain, evaluate


class TaskDependencyChecks(unittest.TestCase):
    def setUp(self):
        self.unit = dict(id='green-1', hp=50, position=[0, 0], suppression=0,
                         combat=dict(path_active=False))
        self.partner = dict(id='green-2', hp=50, position=[0, 1],
                            combat=dict(path_active=False))
        self.state = dict(time=10, units=[self.unit, self.partner])
        self.task = dict(command='flank', region_id='R3', region_path=['R1', 'R2', 'R3'],
                         region_cursor=0, stage_id='approach', task_revision=1,
                         partner='green-2', start_when='partner_firing',
                         wait_timeout_s=3, on_failure='reassess')

    def check_task(self, previous=None, firing=False):
        return evaluate(self.task, self.unit, self.state, {}, previous or {},
                        lambda partner, now: firing)

    def timed_out(self):
        status = self.check_task()
        self.state['time'] += 3
        status = self.check_task(status)
        self.assertEqual(status['reason'], 'dependency_timeout')
        return status

    def test_immediate_task_is_not_blocked_by_moving_partner(self):
        self.task['start_when'] = 'immediate'
        self.partner['combat']['path_active'] = True
        status = self.check_task()
        self.assertEqual(status['phase'], 'executing')
        self.assertNotIn('preparing_since', status)

    def test_dependency_preparation_has_a_separate_clock(self):
        self.partner['combat']['path_active'] = True
        status = self.check_task()
        self.state['time'] += 5
        status = self.check_task(status)
        self.assertEqual(status['phase'], 'preparing')
        self.partner['combat']['path_active'] = False
        status = self.check_task(status)
        self.assertEqual(status['phase'], 'waiting')
        self.state['time'] += 3
        self.assertEqual(self.check_task(status)['reason'], 'dependency_timeout')

    def test_same_revision_cannot_revive_timeout_even_when_fire_arrives(self):
        status = self.timed_out()
        status = self.check_task(status, firing=True)
        self.assertEqual(status['phase'], 'reassess')
        self.assertEqual(status['reason'], 'dependency_timeout')

    def test_new_approved_revision_can_reassess_unchanged_assignment(self):
        status = self.timed_out()
        self.task['task_revision'] = 2
        status = self.check_task(status, firing=True)
        self.assertEqual(status['phase'], 'executing')
        self.assertEqual(status['reason'], 'start_condition_observed')

    def test_area_route_and_stage_change_invalidate_old_dependency(self):
        baseline = copy.deepcopy(self.task)
        for key, value in [('region_id', 'R4'), ('region_path', ['R1', 'R4', 'R3']),
                           ('stage_id', 'push')]:
            with self.subTest(field=key):
                self.task = copy.deepcopy(baseline)
                status = self.timed_out()
                self.task[key] = value
                self.assertEqual(self.check_task(status, firing=True)['phase'], 'executing')

    def test_region_progress_requires_new_permission_but_reload_does_not(self):
        status = self.check_task(firing=True)
        self.state['time'] += 2
        status = self.check_task(status, firing=False)
        self.assertEqual(status['phase'], 'executing')
        self.assertEqual(status['reason'], 'stage_permission_retained')
        old_signature = status['signature']
        self.task['region_cursor'] = 1
        status = self.check_task(status, firing=False)
        self.assertEqual(status['signature'], old_signature)
        self.assertEqual(status['phase'], 'waiting')
        status = self.check_task(status, firing=True)
        self.assertEqual(status['phase'], 'executing')
        self.assertEqual(status['stage'], 1)

    def test_new_revision_never_overrides_native_survival(self):
        status = self.timed_out()
        self.task['task_revision'] = 2
        self.task['start_when'] = 'immediate'
        self.unit['order_mode'] = 'self_preserve'
        status = self.check_task(status, firing=True)
        self.assertEqual(status['phase'], 'reassess')
        self.assertEqual(status['reason'], 'native_survival_override')
        self.assertEqual(status['on_failure'], 'withdraw')

    def test_waiting_filters_dependent_advance_but_keeps_local_actions(self):
        dependent = ['task_waypoint', 'assigned_position', 'stage_approach', 'contest_flag']
        local = ['firing_0', 'shelter_0', 'withdraw_0', 'protect', 'attack_red-1',
                 'continue_task', 'halt']
        for phase in ['preparing', 'waiting', 'blocked', 'reassess']:
            with self.subTest(phase=phase):
                options = {key: dict(description=key) for key in dependent + local}
                constrain(options, dict(phase=phase))
                self.assertEqual(set(options), set(local))
        options = {key: dict(description=key) for key in dependent + local}
        constrain(options, dict(phase='executing'))
        self.assertEqual(set(options), set(dependent + local))


if __name__ == '__main__':
    unittest.main()
