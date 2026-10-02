import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'deskfront'))
from executor_view import build


class ExecutorViewChecks(unittest.TestCase):
    def test_reduction_preserves_identity_risk_and_does_not_mutate_execution(self):
        state=dict(controlled_unit_ids=['g'],self_id='g',units=[],executors={'g':dict(
            identity={'unit_id':'g'},assignment_binding={'actor_id':'g','support_for':'ally'},
            task={'actor_id':'g','command':'support','target_id':'r','complete_when':{'type':'target_dead'}},
            spatial={'status':'fresh','sampled_at':5,'current_threats':['r'],
                     'remote_firing_positions':[{'position':[1,2],'targets':['r']}]},
            micro_combat={'fire_blockers':['wall'],'reload_s':2},
            region_choices={'query_status':'fresh','options':[{'region_id':'b','position':[1,2],
                'source':'remote_firing','path_evidence':{'status':'sampled'}}],
                'basis':'sampled endpoint, native engine path'},
            feedback={'last_execution_rejection':'blocked','task_execution':{'phase':'waiting','reason':'partner_not_firing'}})})
        questions={'g':{'criteria':{'fire_0':'targets r; risk unknown; route a b'}}}
        original=copy.deepcopy(state);original_q=copy.deepcopy(questions)
        result=build(state,questions);row=result['executors']['g']
        self.assertEqual(state,original);self.assertEqual(questions,original_q)
        self.assertEqual(result['self_id'],'g')
        self.assertEqual(row['assignment_binding']['support_for'],'ally')
        self.assertEqual(row['micro_combat']['fire_blockers'],['wall'])
        self.assertEqual(row['spatial']['current_threats'],['r'])
        self.assertEqual(row['region_choices']['query_status'],'fresh')
        self.assertIn('native engine path',row['region_choices']['basis'])
        self.assertNotIn('region_path',row['region_choices'])
        self.assertEqual(row['feedback']['last_execution_rejection'],'blocked')
        self.assertNotIn('remote_firing_positions',row['spatial'])
        # Without action evidence, do not silently discard spatial candidates.
        self.assertIn('remote_firing_positions',build(state,{})['executors']['g']['spatial'])
