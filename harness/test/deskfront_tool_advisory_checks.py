"""The executor receives tool evidence without treating it as an order."""
from pathlib import Path
import sys
import unittest

from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path.insert(0,str(DESKFRONT_TOOLS))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/deskfront'))
from team_executor import compact_state


class AdvisoryToolChecks(unittest.TestCase):
    def test_jev_receives_cover_and_failure_evidence_without_forced_choice(self):
        unit=dict(id='green-1',faction='green',kind='infantry',weapon='rifle',hp=50,
                  position=[0,0],goal=[0,0],cover_id='hard',cover_slot='hard:0',
                  cqb_stance='hide',in_cover=True,ammo=8,reload_remaining=0,
                  last_shot_at=9,last_shot_target='red-1',combat=dict(path_active=True))
        cover=dict(slot_key='hard:0',position=[0,0],peek_position=[.05,0],hard=True,
                   available=True,native_peek_gate=True,targets_from_peek=['red-1'],
                   anchor_threats=[],peek_threats=['red-1'],risk=dict(status='sampled',travel_s=.3,exposed_s=.1,peak_attackers=1))
        failure=dict(phase='engaging',reason='native_cover_hide',severity='info',
                     evidence=dict(cover_cycle=True,local_query='not_run',native_fire_lane='not_in_candidates'))
        state=dict(run_id='r',tick=1,time=10,bounds=[-2,-2,2,2],
                   objective=dict(position=[1,1],radius=.17),units=[unit],covers=[],shared={},
                   executors={'green-1':dict(self=unit,execution_feedback=dict(local_failure=failure,
                       local_maneuver_report=dict(reason='spatial_query_unavailable',options=0)),
                       spatial_tools=dict(sampled_at=10,cover_firing_positions=[cover]))})
        compact=compact_state(state)
        self.assertEqual(compact['units'][0]['cover_phase'],'hiding')
        row=compact['executors']['green-1']
        self.assertEqual(row['feedback']['local_failure']['reason'],'native_cover_hide')
        self.assertEqual(row['feedback']['local_maneuver']['reason'],'spatial_query_unavailable')
        self.assertEqual(row['spatial']['cover_firing_positions'][0]['targets'],['red-1'])
        self.assertIn('reference_only',row['spatial']['cover_selection'])
        self.assertNotIn('action',row['feedback']['local_failure'])

    def test_missing_query_is_unknown_not_safe_or_no_route(self):
        from threat_context import summary
        self.assertEqual(summary({}),{'status':'unknown_no_recent_query'})


if __name__=='__main__':unittest.main()
