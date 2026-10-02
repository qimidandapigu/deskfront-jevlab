import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/deskfront'))
from objective_timing import build


class ObjectiveTimingChecks(unittest.TestCase):
    def test_reports_deadline_and_net_flag_progress_without_selecting_action(self):
        unit=dict(id='green-2',faction='green',hp=50,position=[0,2])
        state=dict(time=20,objective=dict(position=[0,0],radius=.2,
                     flag=dict(owner='red',contested=False,remaining_seconds=8)))
        feedback={'green-2':dict(recent_positions=[dict(time=10,position=[0,1.5])],no_shot_seconds=30)}
        spatial={'green-2':dict(objective_path_risk=dict(status='sampled',travel_s=10,exposed_s=4))}
        row=build(state,[unit],feedback,spatial)['units']['green-2']
        self.assertEqual(row['distance_to_flag_circle'],1.8)
        self.assertEqual(row['net_flag_progress'],-.5)
        self.assertEqual(row['center_eta_minus_remaining_s'],2)
        self.assertEqual(row['no_shot_s'],30)
        self.assertNotIn('action',row)

    def test_missing_path_and_history_remain_unknown(self):
        state=dict(time=20,objective=dict(position=[0,0],radius=.2,flag=dict(owner='red',remaining_seconds=8)))
        row=build(state,[dict(id='green-1',faction='green',hp=50,position=[0,1])],{}, {})['units']['green-1']
        self.assertEqual(row['path_to_flag_center']['status'],'unknown')
        self.assertIsNone(row['center_eta_minus_remaining_s'])
        self.assertIsNone(row['net_flag_progress'])


if __name__=='__main__':unittest.main()
