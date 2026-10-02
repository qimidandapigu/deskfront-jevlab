import copy, sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from server import validate_command
from lm_controller import validate_decision
from test_lm import state

class HumanSquads(unittest.TestCase):
    def setUp(self):
        self.s=state()
        self.s.state['squad_behavior']={'enabled':True,'perception':{'green':{'contacts':[]}}}
        self.c={'action':'squad_order','faction':'green','unit_ids':['green-1','green-2'],'squad_id':'green-squad','order_id':'order-1','intent':'advance','position':[.2,.2],'radius':.15,'run_id':'r','seen_tick':10,'control_epoch':1}

    def test_squad_command_retains_authority_and_single_unit_contract(self):
        self.assertEqual(self.s.submit(self.c,source='lm')[0],202)
        bad={**self.c,'unit_ids':['green-1','red-1']}
        self.assertEqual(self.s.submit(bad,source='lm')[1]['error'],'invalid_unit_authority')
        self.assertEqual(self.s.submit({**self.c,'control_epoch':0},source='lm')[1]['error'],'lm_authority_changed')
        self.assertEqual(self.s.submit({**self.c,'action':'hold'},source='lm')[1]['error'],'lm_single_unit_required')

    def test_emotion_command_preserves_single_owner(self):
        c={**self.c,'action':'unit_emotion','unit_ids':['green-1'],'emotion':'afraid'}
        self.assertEqual(self.s.submit(c,source='lm')[0],202)
        self.assertEqual(self.s.submit({**c,'unit_ids':['red-1']},source='lm')[1]['error'],'invalid_unit_authority')
        for patch in [{'emotion':'invincible'},{'unit_ids':['green-1','green-2']},{'unit_ids':[]}]:
            self.assertIsNotNone(validate_command({**c,**patch}))

    def test_identity_membership_region_validation(self):
        for patch in [{'unit_ids':[]},{'unit_ids':['green-1','green-1']},{'radius':float('nan')},{'radius':0},{'position':[float('inf'),0]},{'squad_id':''},{'intent':'teleport'}]:
            self.assertIsNotNone(validate_command({**self.c,**patch}),patch)
        self.s.state['squad_behavior']['enabled']=False
        self.assertEqual(self.s.submit(self.c,source='lm')[1]['error'],'human_squad_disabled')

    def test_model_cannot_assign_hostile_or_unseen_targets(self):
        value={k:v for k,v in self.c.items() if k not in ['faction','run_id','seen_tick','control_epoch']}
        unit=self.s.state['units'][0]
        self.assertEqual(validate_decision(value,self.s.state,unit)['action'],'squad_order')
        for patch in [{'unit_ids':['red-1']},{'target_id':'red-1'},{'position':[999,0]}]:
            with self.assertRaises(ValueError):validate_decision({**value,**patch},self.s.state,unit)

if __name__=='__main__':unittest.main()
