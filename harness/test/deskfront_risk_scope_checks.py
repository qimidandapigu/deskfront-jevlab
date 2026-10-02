"""A route forecast belongs to its exact destination and sampled origin."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/deskfront'))
from stage_execution import segment_candidates
from threat_context import annotate


class RiskScopeChecks(unittest.TestCase):
    def setUp(self):
        self.risk=dict(status='sampled',travel_s=5,exposed_s=3,peak_attackers=2,endpoint_attackers=1)
        self.spatial=dict(origin=[0,0],sampled_at=4,
                          firing_positions=[dict(position=[.6,0],risk=self.risk)])
        self.topology=dict(cells={str(i):[i*.1,0] for i in range(7)},
                           edges=[[str(i),str(i+1)] for i in range(6)])

    def test_segment_keeps_final_risk_but_does_not_transfer_it_to_short_step(self):
        options={'fire':dict(command=dict(action='move',intent='advance',position=[.6,0]),description='fire')}
        self.assertEqual(segment_candidates(options,[0,0],self.topology),[])
        annotate(options,self.spatial)
        item=options['fire']
        self.assertEqual(item['path_risk']['forecast']['status'],'unknown')
        self.assertEqual(item['final_destination_risk']['scope'],'final_destination_scope')
        self.assertEqual(item['final_destination_risk']['forecast'],self.risk)
        self.assertIn('非本次短步',item['description'])
        self.assertIn('未知',item['description'])

    def test_short_step_uses_independently_queried_navigation_forecast(self):
        options={'fire':dict(command=dict(action='move',intent='advance',position=[.6,0]),description='fire')}
        segment_candidates(options,[0,0],self.topology)
        step=options['fire']['command']['position']
        self.spatial['navigation_steps']=[dict(position=step,risk=dict(self.risk,exposed_s=.2,origin=[.01,0],observed_at=4.1))]
        annotate(options,self.spatial)
        self.assertEqual(options['fire']['path_risk']['forecast']['exposed_s'],.2)
        self.assertEqual(options['fire']['path_risk']['origin'],[.01,0])
        self.assertEqual(options['fire']['path_risk']['observed_at'],4.1)
        self.assertEqual(options['fire']['final_destination_risk']['forecast']['exposed_s'],3)

    def test_nearby_sample_does_not_claim_current_step_was_queried(self):
        options={'move':dict(command=dict(action='move',position=[.6,.004]),description='move')}
        annotate(options,self.spatial)
        self.assertEqual(options['move']['path_risk']['forecast']['status'],'unknown')

    def test_annotate_then_segment_moves_forecast_into_final_scope(self):
        options={'fire':dict(command=dict(action='move',intent='advance',position=[.6,0]),description='fire')}
        annotate(options,self.spatial)
        segment_candidates(options,[0,0],self.topology)
        self.assertNotIn('path_risk',options['fire'])
        self.assertEqual(options['fire']['final_destination_risk']['scope'],'final_destination_scope')
        self.assertEqual(options['fire']['final_destination_risk']['position'],[.6,0])


if __name__=='__main__':unittest.main()
