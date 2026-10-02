import sys
import unittest
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'deskfront'))
sys.path.insert(0,str(DESKFRONT_TOOLS))
from world.director import MacroBridge, AXES

class DirectorJsonChecks(unittest.TestCase):
    def test_one_analysis_json_request_and_validated_axes(self):
        value=dict(phase='build_up',hormones={k:.5 for k in AXES},reason='evidence',player_assessment='unknown')
        game=SimpleNamespace(config={'backend':'jev'},record=Mock(),ask=Mock(return_value={
            'requestId':'one','answers':{'regulation':{'type':'json','value':value}}}))
        bridge=MacroBridge(None,game)
        self.assertEqual(bridge.regulate({})[0],value)
        game.ask.assert_called_once()
        self.assertEqual(game.ask.call_args.kwargs['role'],'experience_analyst')
        self.assertEqual(list(game.ask.call_args.args[1]),['regulation'])
        self.assertEqual(game.ask.call_args.args[1]['regulation']['type'],'json')
        value['hormones']['pressure']=float('nan')
        with self.assertRaisesRegex(ValueError,'invalid_director_hormones'):bridge.regulate({})

    def test_analyst_view_deduplicates_design_labels_and_old_report_metadata(self):
        value=dict(phase='build_up',hormones={k:.5 for k in AXES},
                   reason='evidence',player_assessment='unknown',
                   current_analysis='current',
                   next_goal=dict(experience='x',tactical_problem='y',avoid='z',
                                  layout_change='change',route_preference='varied'))
        game=SimpleNamespace(config={'backend':'jev'},record=Mock(),ask=Mock(return_value={
            'requestId':'one','answers':{'regulation':{'type':'json','value':value}}}))
        bridge=MacroBridge(None,game)
        design={'cells':{'c0r0':{'props_basis':'same','props':['laptop'],
                                 'visual_identity':{'basis':'same','material_counts':{'laptop':1}}}},
                 'materials':{'laptop':1},
                 'material_profile':{'counts':{'laptop':1},'main_route':['laptop']}}
        context={'current_design':design,
                 'previous_understanding':dict(report_id='drop',observed_at=4,
                     phase='explore',hormones={k:.2 for k in AXES},
                     current_analysis='old',next_goal=value['next_goal'],
                     player_assessment='unknown',extra='drop')}
        bridge.regulate(context)
        model=game.ask.call_args.args[0]
        self.assertNotIn('props_basis',str(model['current_design']))
        self.assertNotIn('material_counts',str(model['current_design']))
        self.assertNotIn('report_id',model['previous_understanding'])
        self.assertNotIn('extra',model['previous_understanding'])
        self.assertIn('next_goal',model['previous_understanding'])
