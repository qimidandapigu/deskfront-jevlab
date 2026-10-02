"""Shared squad facts distinguish position, fire possibility and observed fire."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'deskfront'))
from task_tools import board


class CooperationBoardChecks(unittest.TestCase):
    def setUp(self):
        self.shooter = dict(
            id='green-1', faction='green', hp=50, position=[0, 0],
            cover_id='hard', cover_slot='hard:0', cqb_stance='peek',
            ammo=8, reload_remaining=0, suppression=0,
            last_shot_at=-10, last_shot_target='',
            combat=dict(path_active=False, engageable_targets=['red-1']))
        self.maneuver = dict(
            id='green-2', faction='green', hp=50, position=[.2, 0],
            ammo=8, reload_remaining=0, suppression=0,
            last_shot_at=-10, last_shot_target='', combat=dict(path_active=False,
                                                                engageable_targets=[]))
        self.enemy = dict(id='red-1', faction='red', hp=50, position=[.5, 0])
        self.state = dict(time=10, units=[self.shooter, self.maneuver, self.enemy])
        self.routes = {'left': dict(name='左路', points=[[0, 0]])}
        self.tasks = {
            'green-1': dict(command='support', region_id='L1', target_id='red-1',
                            partner='green-2'),
            'green-2': dict(command='flank', partner='green-1', target_id='red-1')}

    def shooter_fact(self):
        return board(self.state, self.tasks, self.routes)['green-1']

    def test_arrival_and_native_lane_do_not_claim_actual_support(self):
        fact = self.shooter_fact()
        self.assertEqual(fact['arrival_status'], 'inside_assigned_region')
        self.assertTrue(fact['arrival_observed'])
        self.assertEqual(fact['arrival_basis'],
                         'region_membership_only_not_firing_position')
        self.assertTrue(fact['fire_lane'])
        self.assertEqual(fact['fire_evidence']['native_lane'],
                         'candidate_requires_muzzle_check')
        self.assertFalse(fact['fire_evidence']['recent_assigned_shot'])
        self.assertFalse(fact['support_ready'])
        self.assertEqual(fact['partner'], 'green-2')

    def test_real_shot_remains_visible_during_brief_native_hide(self):
        self.shooter.update(last_shot_at=9.5, last_shot_target='red-1',
                            cqb_stance='hide', in_cover=True)
        self.shooter['combat'].update(path_active=True, engageable_targets=[])
        fact = self.shooter_fact()
        self.assertEqual(fact['phase'], 'supporting')
        self.assertEqual(fact['fire_evidence']['native_lane'], 'temporarily_hidden')
        self.assertTrue(fact['fire_evidence']['recent_assigned_shot'])
        self.assertIsNone(fact['fire_evidence']['interruption'])
        self.assertTrue(fact['support_ready'])
        self.state['time'] = 12.5
        fact = self.shooter_fact()
        self.assertEqual(fact['phase'], 'cover_hiding')
        self.assertFalse(fact['support_ready'])
        self.assertEqual(fact['fire_evidence']['interruption'], 'native_cover_hide')
        self.assertEqual(fact['fire_evidence']['last_assigned_shot_at'], 9.5)
        self.assertEqual(fact['fire_evidence']['assigned_shot_age_s'], 3)

    def test_peek_move_is_not_mislabeled_as_route_advance(self):
        self.shooter.update(cqb_stance='peek', in_cover=False, cover_step=True)
        self.shooter['combat'].update(path_active=True, engageable_targets=[])
        fact = self.shooter_fact()
        self.assertEqual(fact['phase'], 'cover_peeking')
        self.assertEqual(fact['cover_phase'], 'peeking')
        self.assertFalse(fact['support_ready'])

    def test_reload_interrupts_support_without_erasing_observed_shot(self):
        self.shooter.update(last_shot_at=9.5, last_shot_target='red-1',
                            reload_remaining=1.2, cqb_stance='hide')
        fact = self.shooter_fact()
        self.assertTrue(fact['fire_evidence']['recent_assigned_shot'])
        self.assertFalse(fact['support_ready'])
        self.assertEqual(fact['fire_evidence']['interruption'], 'reloading')
        self.assertEqual(fact['phase'], 'reloading')

    def test_recent_muzzle_block_and_wrong_target_are_not_support(self):
        self.shooter.update(last_shot_at=9.5, last_shot_target='red-2')
        self.shooter['combat']['fire_check'] = dict(
            status='blocked', target_id='red-1', time=9.8,
            reason='cover_blocks_muzzle')
        fact = self.shooter_fact()
        self.assertFalse(fact['fire_evidence']['recent_assigned_shot'])
        self.assertFalse(fact['support_ready'])
        self.assertEqual(fact['fire_evidence']['interruption'], 'recent_muzzle_block')
        self.assertEqual(fact['fire_evidence']['native_lane'], 'recent_muzzle_block')


if __name__ == '__main__':
    unittest.main()
