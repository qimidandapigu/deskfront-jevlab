import copy
import sys
import unittest
from pathlib import Path
from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/deskfront'))
sys.path.insert(0,str(DESKFRONT_TOOLS))
from world.assembly import tools_for, compile_operations, validate
from world.catalog import CATALOG
from world.region_builder import build

OPTION='gate_north_books_cross_tight'

def operations():
    return [dict(slot=k,module='original',op=v['original']['op']) for k,v in tools_for(OPTION).items()]

class AssemblyChecks(unittest.TestCase):
    def test_choices_change_actual_geometry_without_mutating_catalog(self):
        before=copy.deepcopy(CATALOG[OPTION]);ops=operations()
        next(r for r in ops if r['slot']=='floor_0')['module']='wide'
        next(r for r in ops if r['slot']=='cover_2')['module']='replace'
        spec=compile_operations(OPTION,ops)
        self.assertNotEqual(spec['floors'],before['floors'])
        self.assertNotEqual(spec['covers'],before['covers'])
        self.assertTrue(validate(spec)['ok'])
        self.assertEqual(CATALOG[OPTION],before)

    def test_cannot_inject_coordinates_duplicate_or_missing_operations(self):
        for mutation in ('missing','duplicate','module','operation'):
            ops=operations()
            if mutation=='missing':ops.pop()
            if mutation=='duplicate':ops[-1]=ops[0]
            if mutation=='module':ops[0]['module']='invented'
            if mutation=='operation':ops[0]['op']='execute_code'
            with self.assertRaises(ValueError):compile_operations(OPTION,ops)

    def test_validator_reports_real_overlap(self):
        spec=compile_operations(OPTION,operations());spec['covers'][1]=spec['covers'][0]
        result=validate(spec)
        self.assertFalse(result['ok']);self.assertEqual(result['reason'],'overlapping_components')

    def test_exact_deployment_spacing_ignores_only_arithmetic_noise(self):
        spec=dict(floors=[[0,-1.1,1.8,1.1]],covers=[],entry=[.1,0],exit=[1.7,0],
                  flank=[],support=[],defender_slots=[[1.675,-.425],[1.675,-.275]])
        self.assertTrue(validate(spec)['ok'])
        spec['defender_slots'][1][1]=-.276
        self.assertEqual(validate(spec)['reason'],'overlapping_deployments')

    def test_all_authored_bases_retain_connectivity(self):
        for option in CATALOG:
            ops=[dict(slot=k,module='original',op=v['original']['op']) for k,v in tools_for(option).items()]
            self.assertTrue(validate(compile_operations(option,ops))['ok'],option)

    def test_builder_legal_choices_produce_connected_tactical_regions(self):
        from types import SimpleNamespace
        contexts=[];records=[];reserved=[]
        def ask(context,questions):
            contexts.append(copy.deepcopy(context))
            return dict(requestId=str(len(contexts)),answers={k:dict(type='choice',choice=next(iter(q['criteria'])),confidence=1,probabilities={v:int(v==next(iter(q['criteria']))) for v in q['criteria']}) for k,q in questions.items()})
        game=SimpleNamespace(ask=ask,record=records.append)
        ops,calls,receipt=build(game,dict(option=OPTION,intent='advance'),lambda:reserved.append(True))
        self.assertEqual(len(calls),2);self.assertTrue(receipt['ok'])
        self.assertEqual(receipt['design_observations']['template_count'],26)
        self.assertEqual(len([o for o in ops if o['op']=='place_region']),9)
        self.assertEqual(reserved,[True])

if __name__=='__main__':unittest.main()
