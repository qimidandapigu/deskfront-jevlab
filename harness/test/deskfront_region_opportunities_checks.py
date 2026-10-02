import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from region_opportunities import build


class RegionOpportunitiesChecks(unittest.TestCase):
    def setUp(self):
        self.regions={'A':dict(bounds=[0,0,1,1]),'B':dict(bounds=[1.1,0,2.1,1]),'C':dict(bounds=[2.2,0,3.2,1])}
        self.members=[dict(id='g1',faction='green',hp=50,position=[.2,.2]),dict(id='g2',faction='green',hp=50,position=[.5,.5])]
        self.state=dict(time=10,units=self.members+[dict(id='r1',faction='red',hp=50,position=[1.5,.5]),dict(id='dead',faction='red',hp=0,position=[.5,.5])],objective=dict(position=[2.5,.5]))
        self.spatial={'g1':dict(sampled_at=9.5,origin=[.2,.2],firing_positions=[
            dict(position=[1.3,.2],targets=['r1'],threats=['r1'],risk=dict(status='sampled',exposed_s=3,travel_s=5)),
            dict(position=[1.7,.7],targets=['r2'],threats=[],risk=dict(status='sampled',exposed_s=1,travel_s=2))])}

    def test_aggregates_targets_and_measured_risk_without_raw_positions(self):
        result=build(self.state,self.members,self.regions,self.spatial)
        opportunity=result['regions']['B']['opportunities']['g1'][0]
        self.assertEqual(opportunity['targets'],['r1','r2'])
        self.assertEqual(opportunity['threats'],['r1'])
        self.assertEqual(opportunity['exposed_s'],[1,3])
        self.assertEqual(opportunity['min_travel_s'],2)
        self.assertEqual(opportunity['samples'],2)
        self.assertEqual(opportunity['sampled_at'],9.5)
        self.assertNotIn('position',opportunity)
        self.assertNotIn('cells',opportunity)

    def test_no_samples_explicitly_means_unknown_not_zero_risk(self):
        result=build(self.state,self.members,self.regions,self.spatial)
        self.assertEqual(result['regions']['A']['unknown_for'],['g1','g2'])
        self.assertEqual(result['regions']['B']['unknown_for'],['g2'])
        self.assertEqual(result['regions']['C']['opportunities'],{})
        self.assertEqual(result['query_status']['g2'],'unknown')

    def test_current_occupancy_and_flag_center_are_separate_from_samples(self):
        result=build(self.state,self.members,self.regions,self.spatial)['regions']
        self.assertEqual(result['A']['allies'],['g1','g2'])
        self.assertEqual(result['A']['enemies'],[])
        self.assertEqual(result['B']['enemies'],['r1'])
        self.assertTrue(result['C']['objective_center'])
        self.assertFalse(result['B']['objective_center'])

    def test_stale_or_displaced_query_does_not_become_current_opportunity(self):
        for changes,status in [(dict(sampled_at=7),'stale'),(dict(sampled_at=11),'stale'),(dict(origin=[.5,.5]),'origin_changed')]:
            spatial=copy.deepcopy(self.spatial);spatial['g1'].update(changes)
            result=build(self.state,self.members,self.regions,spatial)
            self.assertEqual(result['query_status']['g1'],status)
            self.assertEqual(result['regions']['B']['unknown_for'],['g1','g2'])

    def test_three_candidate_types_become_at_most_two_summaries_with_deduplication(self):
        escape=dict(position=[1.4,.4],targets=['r1'],threats=[],risk=dict(status='sampled',exposed_s=0,travel_s=4))
        self.spatial['g1']['withdrawal_positions']=[escape]
        self.spatial['g1']['shelter_positions']=[copy.deepcopy(escape)]
        items=build(self.state,self.members,self.regions,self.spatial)['regions']['B']['opportunities']['g1']
        self.assertEqual(len(items),2)
        disengage=next(item for item in items if item['kind']=='disengage')
        self.assertEqual(disengage['samples'],1)

    def test_missing_risk_remains_unknown_and_is_not_averaged_as_safe(self):
        self.spatial['g1']['firing_positions'][1].pop('risk')
        row=build(self.state,self.members,self.regions,self.spatial)['regions']['B']['opportunities']['g1'][0]
        self.assertEqual(row['risk_status'],'partial')
        self.assertEqual(row['risk_samples'],1)
        self.assertEqual(row['exposed_s'],[3,3])
        self.spatial['g1']['firing_positions'][0]['risk']={'status':'unknown'}
        row=build(self.state,self.members,self.regions,self.spatial)['regions']['B']['opportunities']['g1'][0]
        self.assertEqual(row['risk_status'],'unknown')
        self.assertIsNone(row['exposed_s'])
        self.assertIsNone(row['min_travel_s'])

    def test_build_does_not_mutate_native_evidence(self):
        before=copy.deepcopy((self.state,self.members,self.regions,self.spatial))
        build(self.state,self.members,self.regions,self.spatial)
        self.assertEqual((self.state,self.members,self.regions,self.spatial),before)

    def route_fixture(self):
        cells={'a':[0,0],'b':[.075,0],'c':[.15,0],
               'd':[0,.075],'e':[.075,.075],'f':[.15,.075]}
        edges=[['a','b'],['b','c'],['a','d'],['d','e'],['e','f'],['f','c'],['b','e']]
        neighbors={'A':['B','D'],'B':['A','C','E'],'C':['B','F'],
                   'D':['A','E'],'E':['D','B','F'],'F':['E','C']}
        regions={key:dict(id=key,center=cells[cell],cells=[cells[cell]],sample_step=.075,
                          neighbors=neighbors[key])
                 for key,cell in zip('ABCDEF','abcdef')}
        unit=dict(id='g1',faction='green',hp=50,position=[0,0],weapon_range=.7)
        ally=dict(id='g2',faction='green',hp=50,position=[.075,0],weapon_range=.7)
        enemy=dict(id='r1',faction='red',hp=50,position=[.15,0],weapon_range=.7)
        state=dict(time=10,units=[unit,ally,enemy],objective=dict(position=[.15,0]),
                   strategic_topology=dict(cells=cells,edges=edges,step=.075))
        spatial={'g1':dict(sampled_at=10,origin=[0,0],navigation_steps=[
            dict(position=[.075,0],risk=dict(status='sampled',travel_s=.4,exposed_s=.3,peak_attackers=1)),
            dict(position=[0,.075],risk=dict(status='sampled',travel_s=.5,exposed_s=0,peak_attackers=0))],
            firing_positions=[dict(position=[.15,0],targets=['r1'],threats=['r1'],
                                   risk=dict(status='sampled',travel_s=3,exposed_s=2))])}
        return state,[unit,ally],regions,spatial

    def test_route_options_show_two_connected_paths_and_only_exact_first_step_risk(self):
        state,members,regions,spatial=self.route_fixture()
        result=build(state,members,regions,spatial)
        options=[row for row in result['route_options']['g1'] if row['goal_region']=='C']
        self.assertEqual(len(options),2)
        self.assertEqual(options[0]['region_path'],['A','B','C'])
        self.assertEqual(options[0]['first_step']['status'],'blocked')
        self.assertEqual(options[0]['first_step']['reason'],'corridor_reserved_or_disconnected')
        self.assertNotEqual(options[0]['region_path'],options[1]['region_path'])
        self.assertEqual(options[1]['region_path'][1],'D')
        self.assertEqual(options[1]['first_step']['risk']['exposed_s'],0)
        self.assertEqual(result['regions']['C']['enemies'],['r1'])
        self.assertEqual(result['regions']['B']['allies'],['g2'])
        self.assertEqual(result['regions']['C']['opportunities']['g1'][0]['targets'],['r1'])
        self.assertNotIn('score',options[0])
        self.assertNotIn('command',options[0])
        self.assertIn('整条区域路线暴露未知',result['route_basis'])
        members[1]['position']=[.15,.075]
        direct=next(row for row in build(state,members,regions,spatial)['route_options']['g1']
                    if row['region_path']==['A','B','C'])
        self.assertEqual(direct['first_step']['risk']['exposed_s'],.3)

    def test_support_shortlist_prioritizes_its_target_fire_site_over_flag(self):
        state,members,regions,spatial=self.route_fixture()
        spatial['g1']['firing_positions'][0]['position']=[0,.075]
        support=build(state,members,regions,spatial,tasks={'g1':dict(command='support',target_id='r1')})
        self.assertEqual(support['route_options']['g1'][0]['goal_region'],'D')
        self.assertIn('assigned_fire_sample',support['route_options']['g1'][0]['goal_tags'])
        occupy=build(state,members,regions,spatial,tasks={'g1':dict(command='occupy')})
        self.assertEqual(occupy['route_options']['g1'][0]['goal_region'],'C')

    def test_unmatched_or_stale_native_first_step_has_unknown_risk(self):
        state,members,regions,spatial=self.route_fixture()
        members[1]['position']=[.15,.075]
        spatial['g1']['navigation_steps']=[]
        row=build(state,members,regions,spatial)['route_options']['g1'][0]
        self.assertEqual(row['first_step']['risk'],{'status':'unknown'})
        spatial['g1']['sampled_at']=7
        result=build(state,members,regions,spatial)
        row=result['route_options']['g1'][0]
        self.assertEqual(row['first_step']['risk'],{'status':'unknown'})
        self.assertEqual(result['regions']['C']['unknown_for'],['g1','g2'])

    def test_cover_peek_reports_available_fire_separately_from_occupied_slot(self):
        state,members,regions,spatial=self.route_fixture()
        spatial['g1']['cover_firing_positions']=[
            dict(slot_key='available',position=[.15,0],targets_from_peek=['r1'],peek_threats=[],
                 available=True,reachable=True,risk=dict(status='sampled',travel_s=2,exposed_s=.5)),
            dict(slot_key='occupied',position=[.15,0],targets_from_peek=['r2'],peek_threats=[],
                 available=False,reachable=True,risk=dict(status='sampled',travel_s=2,exposed_s=.5))]
        result=build(state,members,regions,spatial)
        cover=next(row for row in result['regions']['C']['opportunities']['g1'] if row['kind']=='cover_firing')
        self.assertEqual(cover['samples'],2)
        self.assertEqual(cover['available_samples'],1)
        self.assertEqual(cover['available_targets'],['r1'])
        option=next(row for row in result['route_options']['g1'] if row['goal_region']=='C')
        self.assertIn('sampled_peek',option['goal_tags'])

    def test_route_options_are_bounded_for_repeated_goals(self):
        state,members,regions,spatial=self.route_fixture()
        state['units'].append(dict(id='r2',faction='red',hp=50,position=[0,.075]))
        state['units'].append(dict(id='r3',faction='red',hp=50,position=[.075,.075]))
        state['units'].append(dict(id='r4',faction='red',hp=50,position=[.15,.075]))
        result=build(state,members,regions,spatial)
        self.assertLessEqual(len(result['route_options']['g1']),6)
        self.assertGreater(result['omitted_route_goals']['g1'],0)
        self.assertTrue(all(len(row['region_path'])<=len(regions) for row in result['route_options']['g1']))

    def test_disconnected_goal_is_reported_and_does_not_consume_display_slot(self):
        state,members,regions,spatial=self.route_fixture()
        regions['B']['neighbors'].remove('C')
        regions['F']['neighbors'].remove('C')
        regions['C']['neighbors']=[]
        result=build(state,members,regions,spatial)
        self.assertIn('C',result['unreachable_route_goals']['g1'])
        self.assertTrue(all(row['goal_region']!='C' for row in result['route_options']['g1']))

    def test_too_close_first_step_uses_farther_queried_cell_in_same_region(self):
        cells={'a':[0,0],'b':[.04,0],'c':[.08,0]}
        regions={'A':dict(cells=[[0,0]],sample_step=.04,neighbors=['B']),
                 'B':dict(cells=[[.04,0],[.08,0]],sample_step=.04,neighbors=['A'])}
        unit=dict(id='g1',faction='green',hp=50,position=[0,0])
        state=dict(time=10,units=[unit],objective=dict(position=[.08,0]),
                   strategic_topology=dict(cells=cells,edges=[['a','b'],['b','c']],step=.04))
        spatial={'g1':dict(sampled_at=10,origin=[0,0],navigation_steps=[
            dict(position=[.04,0],risk=dict(status='sampled',travel_s=.4,exposed_s=0)),
            dict(position=[.08,0],risk=dict(status='sampled',travel_s=.8,exposed_s=.2))])}
        result=build(state,[unit],regions,spatial)
        row=result['route_options']['g1'][0]
        self.assertEqual(row['region_path'],['A','B'])
        self.assertEqual(row['first_step']['status'],'ready')
        self.assertEqual(row['first_step']['position'],[.08,0])
        self.assertEqual(row['first_step']['risk']['exposed_s'],.2)
        spatial['g1']['navigation_steps'].pop()
        row=build(state,[unit],regions,spatial)['route_options']['g1'][0]
        self.assertEqual(row['first_step']['status'],'too_close')
        self.assertNotIn('position',row['first_step'])


if __name__ == '__main__':unittest.main()
