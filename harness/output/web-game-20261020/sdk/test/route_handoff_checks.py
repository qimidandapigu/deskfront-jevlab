"""Real order conversion with fake transport; no provider or game dependency."""
from pathlib import Path
from types import SimpleNamespace
import sys,copy,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/deskfront'))
from human_squad_orders import SquadOrderMixin

def fixture(team='green',weapon='smg'):
    old=dict(role='maneuver',source='jev',region_id='E',region_path=['A','B','C','D','E'],position=[12.,2.],route_positions=[[10.,2.],[10.5,2.],[11.,2.],[11.5,2.],[12.,2.]],endpoint_id='finish-site',endpoint_basis='native_region_cell',approach_region='D',route_id='P1',route_source='jev')
    short=dict(old,region_path=['D','E'],route_positions=[[11.5,2.],[12.,2.]])
    captured=[]
    o=SimpleNamespace(last_order=dict(order_id='old',intent='bound',assignments={'unit':copy.deepcopy(old)}),world=dict(time=30,run_id='probe',tick=20,control_epochs={team:1}),team=team,squad_id='squad',plan=dict(region_id='E',position=[12.,2.],radius=.1),identity='probe',version=1,pending_commands={},order_serial=0,revision={'executor':0},game=SimpleNamespace(session_id=None),clock=lambda:0.,kept_orders=0)
    o._accepted_assignments=lambda:{'unit':dict(old,keep_available=True)}
    o._record=lambda *a,**k:None;o._order_matches_plan=lambda:False;o._submit_task_review=lambda *args:False
    o.state=SimpleNamespace(submit=lambda cmd,**kw:(captured.append(copy.deepcopy(cmd))or(202,{'id':'queued'})))
    response={'answers':{'intent':{'type':'choice','choice':'advance'},'route_unit':{'type':'choice','choice':'P1'},'role_unit':{'type':'choice','choice':'maneuver'}}}
    request={'serial':1,'member_region_choices':{'unit':{'P1':short}},'accepted_assignments':{}}
    return o,[{'id':'unit','weapon':weapon,'position':[11.5,2.]}],response,request,captured,short

class Checks(unittest.TestCase):
    def test_selected_suffix_is_transported_for_both_teams_all_infantry(self):
        for team in ['green','red']:
            for weapon in ['rifle','smg','rocket']:
                for intent in ['bound','advance']:
                    with self.subTest(team=team,weapon=weapon,intent=intent):
                        o,units,response,request,sent,short=fixture(team,weapon)
                        response['answers']['intent']['choice']=intent
                        SquadOrderMixin._submit(o,intent,units,response,request)
                        self.assertEqual(sent[0]['assignments']['unit']['route_positions'],short['route_positions'])
                        self.assertEqual(sent[0]['assignments']['unit']['region_path'],short['region_path'])
                        self.assertEqual(sent[0]['keep_unit_ids'],[])

    def test_canonical_comparison_does_not_repeat_same_work(self):
        o,units,response,request,sent,short=fixture()
        SquadOrderMixin._submit(o,'advance',units,response,request)
        o.pending_commands.clear();o._order_matches_plan=lambda:True
        SquadOrderMixin._submit(o,'advance',units,response,request)
        self.assertEqual(len(sent),1)
        self.assertEqual(o.kept_orders,1)
        self.assertEqual(o.last_order['assignments']['unit']['route_positions'],short['route_positions'])

    def test_new_corridor_is_never_replaced_by_old_corridor(self):
        o,units,response,request,sent,short=fixture()
        row=request['member_region_choices']['unit']['P1']
        row['region_path']=['D','SIDE','E'];row['route_positions']=[[11.5,2.],[11.7,2.2],[12.,2.]]
        SquadOrderMixin._submit(o,'advance',units,response,request)
        self.assertEqual(sent[0]['assignments']['unit']['route_positions'],row['route_positions'])

    def test_explicit_return_route_is_not_forced_forward(self):
        o,units,response,request,sent,short=fixture()
        row=request['member_region_choices']['unit']['P1']
        row.update(region_path=['D','BACK'],route_positions=[[11.5,2.],[10.5,2.]],position=[10.5,2.],region_id='BACK',endpoint_id='back-site')
        SquadOrderMixin._submit(o,'advance',units,response,request)
        self.assertEqual(sent[0]['assignments']['unit']['position'],[10.5,2.])
        self.assertEqual(sent[0]['assignments']['unit']['route_positions'],row['route_positions'])

if __name__=='__main__':unittest.main()
