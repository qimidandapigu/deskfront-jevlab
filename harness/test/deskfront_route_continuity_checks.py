import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from route_continuity import assess,remember


def option(path,goal=None,step='ready',risk=None):
    return dict(goal_region=goal or path[-1],region_path=list(path),
                first_step=dict(status=step,**({'risk':risk} if risk else {})))


class RouteContinuityChecks(unittest.TestCase):
    def test_shortened_suffix_is_forward_progress_and_does_not_select_for_model(self):
        previous=remember(option(['A','B','C']),1.0,7)
        options=[option(['A','B','C']),option(['B','C']),option(['B','D','C'])]
        before=copy.deepcopy((previous,options))
        row=assess(previous,options,2.0)
        self.assertEqual(row['status'],'forward_available')
        self.assertEqual([v['continuation'] for v in row['options']],
                         ['same','forward','different_route'])
        self.assertEqual(row['matching_indices'],[0,1])
        self.assertEqual(row['available_continuation_indices'],[0,1])
        self.assertEqual(row['task_revision'],7)
        self.assertEqual((previous,options),before)

    def test_longer_path_after_advanced_choice_is_observed_backtrack(self):
        previous=remember(option(['B','C']),3.0,7)
        row=assess(previous,[option(['A','B','C'])],4.0)
        self.assertEqual(row['status'],'backtrack_detected')
        self.assertEqual(row['backtrack_indices'],[0])
        self.assertEqual(row['options'][0]['continuation'],'backtrack')

    def test_same_goal_other_branch_and_changed_goal_are_distinct(self):
        previous=remember(option(['A','B','C']),1.0,7)
        reroute=assess(previous,[option(['A','D','C'])],2.0)
        self.assertEqual(reroute['status'],'route_missing')
        self.assertEqual(reroute['options'][0]['continuation'],'different_route')
        changed=assess(previous,[option(['A','D'],goal='D')],2.0)
        self.assertEqual(changed['status'],'goal_missing')
        self.assertEqual(changed['options'][0]['continuation'],'goal_changed')

    def test_matching_route_with_unusable_first_step_is_reported_blocked(self):
        previous=remember(option(['A','B','C']),1.0,7)
        row=assess(previous,[option(['B','C'],step='too_close')],2.0)
        self.assertEqual(row['status'],'continuation_blocked')
        self.assertEqual(row['matching_indices'],[0])
        self.assertEqual(row['available_continuation_indices'],[])
        self.assertTrue(row['options'][0]['first_step_blocked'])
        unreachable=assess(previous,[option(['B','C'],risk={'status':'unreachable'})],2.0)
        self.assertEqual(unreachable['status'],'continuation_blocked')

    def test_invalid_samples_do_not_become_route_continuation(self):
        previous=remember(option(['A','B','C']),1.0,7)
        bad=[dict(goal_region='C',region_path=['A','A','C']),
             dict(goal_region='C',region_path=['A','B']),None]
        row=assess(previous,bad,2.0)
        self.assertEqual(row['status'],'candidates_invalid')
        self.assertEqual([v['continuation'] for v in row['options']],['invalid']*3)
        self.assertEqual(assess(previous,[option(['B','C'])],.5)['status'],'clock_reset')
        self.assertEqual(assess({},[option(['B','C'])],2)['status'],'invalid_previous')
        self.assertEqual(assess(None,[option(['B','C'])],2)['status'],'unselected')
        with self.assertRaises(ValueError):remember(bad[0],2,7)


if __name__=='__main__':unittest.main()
