"""A verified squad wipe is a loss; generic Godot exits remain errors."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'deskfront'))
from session_result import controlled_team_elimination, engine_exit_outcome


class SessionResultChecks(unittest.TestCase):
    def setUp(self):
        self.state=dict(time=40.2,winner='',demo=dict(phase='battle',participants=['green','red']),
                        units=[
                            dict(id='green-1',faction='green',deployment_phase='active',hp=0),
                            dict(id='green-2',faction='green',deployment_phase='active',hp=0),
                            dict(id='green-3',faction='green',deployment_phase='active',hp=0),
                            dict(id='red-1',faction='red',deployment_phase='active',hp=33.7),
                            dict(id='red-2',faction='red',deployment_phase='active',hp=19.1)])
        self.ids={'green-1','green-2','green-3'}

    def outcome(self,code=0,ready=True):
        return engine_exit_outcome(self.state,'green',code,duel_ready=ready,
                                   expected_unit_ids=self.ids)

    def test_last_live_snapshot_proves_model_team_wipe_without_native_winner(self):
        before=copy.deepcopy(self.state)
        result=controlled_team_elimination(self.state,'green',self.ids)
        self.assertEqual(result['outcome'],'lost')
        self.assertEqual(result['inferred_winner'],'red')
        self.assertEqual(result['native_winner'],'')
        self.assertEqual(result['eliminated_units'],sorted(self.ids))
        self.assertEqual(self.state,before)
        self.assertEqual(self.outcome()['outcome'],'lost')

    def test_live_controlled_unit_means_exit_zero_is_still_error(self):
        self.state['units'][2]['hp']=1.5
        self.assertIsNone(controlled_team_elimination(self.state,'green',self.ids))
        self.assertEqual(self.outcome(),dict(outcome='error',reason='engine_exited',returncode=0))

    def test_missing_unit_or_health_is_not_evidence_of_death(self):
        self.state['units'].pop(1)
        self.assertEqual(self.outcome()['outcome'],'error')
        self.state['units'].insert(1,dict(id='green-2',faction='green',
                                           deployment_phase='active',hp=None))
        self.assertEqual(self.outcome()['outcome'],'error')

    def test_prebattle_or_native_winner_does_not_infer_elimination(self):
        self.state['demo']['phase']='deploying'
        self.assertEqual(self.outcome()['outcome'],'error')
        self.state['demo']['phase']='battle';self.state['winner']='red'
        self.assertIsNone(controlled_team_elimination(self.state,'green',self.ids))
        self.assertEqual(self.outcome()['outcome'],'error')

    def test_no_surviving_opponent_or_not_ready_remains_error(self):
        self.state['units'][3]['hp']=0;self.state['units'][4]['hp']=0
        self.assertEqual(self.outcome()['outcome'],'error')
        self.state['units'][3]['hp']=5
        self.assertEqual(self.outcome(ready=False)['outcome'],'error')

    def test_unknown_snapshot_cannot_convert_process_error_to_result(self):
        self.assertEqual(engine_exit_outcome({},'green',2,duel_ready=True)['outcome'],'error')
        self.assertEqual(self.outcome(code=2)['outcome'],'error')


if __name__=='__main__':unittest.main()
