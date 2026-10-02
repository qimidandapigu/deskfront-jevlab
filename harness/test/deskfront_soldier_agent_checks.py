import sys, time, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
from deskfront_human_squad_checks import State, Game, Clock
from human_squad import HumanSquadController, SharedRequestBudget
from soldier_candidate_query import proposals


def native_sites(*_args, **_kwargs):
    return dict(status='fresh', id='native-1', options=[dict(
        id='C1', region_id='Nc', position=[.7, 0.], path_length=.7,
        fire_targets=[], potential_attackers=1, cover_key='', cover_id='')])


class SoldierChecks(unittest.TestCase):
    def test_equipment_approach_stays_on_assigned_short_steps(self):
        unit=dict(id='green-1', weapon='rifle', position=[0.,0.])
        regions={'a':dict(center=[.2,0.], cells=[[0.,0.],[.2,0.],[.4,0.]]),
                 'b':dict(center=[.6,0.], cells=[[.55,0.]])}
        gear=[dict(id='mortar',position=[.6,0.],capturable=True)]
        rows=proposals(unit,dict(region_path=['a']),regions,dict(cells={'a':{}}),equipment=gear)
        approaches=[r for r in rows if r.get('kind')=='equipment_approach']
        self.assertTrue(approaches)
        self.assertTrue(all(r['region_id']=='a' and 0<r['position'][0]<=.42 for r in approaches))
        unit['weapon']='rocket'
        self.assertFalse(any(r.get('kind')=='equipment_approach' for r in
            proposals(unit,dict(region_path=['a']),regions,dict(cells={'a':{}}),equipment=gear)))

    def test_only_discovered_equipment_reaches_model_context(self):
        self.c.world['at_guns']=[
            dict(id='hidden',kind='mortar',faction='red',seen_by=['red']),
            dict(id='discovered',kind='mortar',faction='neutral',seen_by=['green'],
                 capturable=True,position=[.4,0.],capture_seconds=3.,capture_radius=.24,required_crew=1)]
        request=self.launch()
        self.assertEqual([r['id'] for r in request['state']['battlefield_equipment']],['discovered'])
        self.assertEqual(request['state']['battlefield_equipment'][0]['required_crew'],1)

    def setUp(self):
        self.state, self.game, self.clock = State(), Game(), Clock()
        self.c = HumanSquadController(self.state, {'model':'jev','max_requests':100,'timeout':10},
                                      self.game, 'green', wall_clock=self.clock)
        self.c.world = self.state.state
        self.c.identity = ('run-1', 3, 'lm')
        self.squad = dict(order_id='order-1', intent='bound',
            assignments={uid:dict(role='maneuver',region_id='Nc',region_path=['Na','Nc'])
                         for uid in ('green-1','green-2')},
            duties={'green-1':dict(role='blocked',reason='muzzle_cover'),
                    'green-2':dict(role='support',reason='actual_fire')})
        self.state.state['squad_behavior']['squads']['green-squad'] = self.squad
        for unit in self.state.state['units']:
            if unit['faction']=='green':unit['emotion']='calm'
        self.members = self.c._members(self.c.world)
        self.native = patch('soldier_agents.query_candidates', native_sites)
        self.native.start()

    def tearDown(self):
        self.c.stop(); self.native.stop()
        for row in self.game.requests:
            if not row['future'].done(): row['future'].set_exception(RuntimeError('test_end'))

    def tick(self): self.c.soldiers.tick(self.members,self.squad,self.state.results,active=True)

    def launch(self):
        old=len(self.game.requests)
        self.tick()
        for _ in range(100):
            if len(self.game.requests)>old:return self.game.requests[-1]
            time.sleep(.001)
        self.fail('no request')

    def answer(self, action, *, site=None, target=None):
        key=':'.join(x for x in (action, site, target) if x is not None)
        answers={'action':{'choice':key}}
        self.game.requests[-1]['future'].set_result({'answers':answers})
        for _ in range(100):
            if self.c.soldiers.pending['future'].done():break
            time.sleep(.001)
        self.tick()

    def test_private_context_and_native_site_selection(self):
        request=self.launch();ctx=request['state']
        self.assertEqual(ctx['self']['id'],'green-1')
        self.assertEqual(ctx['assignment']['target_region_id'],'Nc')
        self.assertNotIn('red-hidden',str(ctx))
        self.assertEqual(ctx['candidate_sites'][0]['id'],'C1')
        self.assertNotIn('emotion',request['questions'])
        self.answer('move_to_site',site='C1')
        self.assertEqual(self.state.commands[0]['intent'],'move_to_site')
        self.assertEqual(self.state.commands[0]['candidate_query_id'],'native-1')
        self.assertEqual(self.state.commands[0]['site_id'],'C1')
        self.assertEqual(self.c.soldiers.accepted,0)
        self.state.results['command-1']={'accepted':True,'message':'applied'};self.tick()
        self.assertEqual(self.c.soldiers.accepted,1)

    def test_clear_personal_fire_target_is_offered_without_teammate_report(self):
        self.state.state['squad_behavior']['perception']['green']['contacts'] = [
            dict(id='red-hidden', position=[.5, 0.], visible=True, last_seen=0, kind='infantry', weapon='rifle')]
        self.members[0]['combat'] = {'engageable_targets': ['red-hidden'], 'path_active': True}
        request = self.launch()
        self.assertIn('focus_fire:red-hidden', request['questions']['action']['criteria'])
        self.assertEqual(list(request['questions']), ['action'])

    def test_nearby_visible_tank_receives_satchel_choice_and_target(self):
        self.members[0]['satchel_ready_in']=0
        self.members[0]['satchel_range']=.44
        position=self.members[0]['position']
        self.state.state['squad_behavior']['perception']['green']['contacts'] = [
            dict(id='red-tank', position=[position[0]+.3,position[1]], visible=True,
                 last_seen=0, kind='tank', weapon='cannon')]
        request=self.launch()
        self.assertIn('satchel:red-tank',request['questions']['action']['criteria'])
        self.assertNotIn('target', request['questions'])
        self.answer('satchel',target='red-tank')
        self.assertEqual(self.state.commands[0]['intent'],'satchel')
        self.assertEqual(self.state.commands[0]['target_id'],'red-tank')

    def test_satchel_is_not_offered_during_cooldown(self):
        self.members[0]['satchel_ready_in']=4
        self.members[0]['satchel_range']=.44
        position=self.members[0]['position']
        self.state.state['squad_behavior']['perception']['green']['contacts'] = [
            dict(id='red-tank', position=[position[0]+.3,position[1]], visible=True,
                 last_seen=0, kind='tank', weapon='cannon')]
        self.assertFalse(any(k.startswith('satchel:') for k in self.launch()['questions']['action']['criteria']))

    def test_throw_wakes_again_when_explosive_evasion_ends(self):
        soldier=self.members[0]
        soldier.update(satchel_ready_in=0,satchel_range=.60,survival_reason='incoming_explosive')
        position=soldier['position']
        self.state.state['squad_behavior']['perception']['green']['contacts'] = [
            dict(id='red-tank',position=[position[0]+.55,position[1]],visible=True,
                 last_seen=0,kind='tank',weapon='cannon')]
        self.c.soldiers.observe(self.members,self.squad,{})
        agent=self.c.soldiers.agents[soldier['id']]
        self.assertEqual(agent['anti_armor_stage'],'throw')
        self.assertFalse(agent['anti_armor_throw_ready'])
        agent['anti_armor_wake']=False
        agent['next_at']=100
        soldier['survival_reason']=''
        self.c.soldiers.observe(self.members,self.squad,{})
        self.assertTrue(agent['anti_armor_throw_ready'])
        self.assertTrue(agent['anti_armor_wake'])
        self.assertLess(agent['next_at'],100)

    def test_blocked_throw_proposes_short_throw_sites(self):
        soldier=dict(position=[0.,0.],satchel_range=.60,satchel_ready_in=0,
                     combat={'satchel_check':{'target_id':'red-tank','reason':'muzzle_obstructed_or_blast_too_close'}})
        assignment=dict(region_id='near',region_path=['near'])
        regions={'near':dict(center=[0.,0.],cells=[[0.,0.],[0.,.10],[.10,.10],[.30,0.]])}
        choices=proposals(soldier,assignment,regions,{'cells':{'0,0':[0.,0.]}},
                          visible_tanks=[dict(id='red-tank',position=[.5,0.])])
        self.assertTrue(any(c['kind']=='anti_armor_throw_site' and c['target_id']=='red-tank' for c in choices))
        self.assertFalse(any(c['kind']=='anti_armor_approach' for c in choices))

    def test_visible_tank_adds_short_native_checked_approach(self):
        soldier=dict(position=[0.,0.],satchel_range=.60,satchel_ready_in=0)
        assignment=dict(region_id='near',region_path=['near'])
        regions={'near':dict(center=[0.,0.],cells=[[0.,0.],[.15,0.],[.25,0.],[.39,0.]])}
        topology={'cells':{'0,0':[0.,0.]}}
        choices=proposals(soldier,assignment,regions,topology,
                          visible_tanks=[dict(id='red-tank',position=[.7,0.])])
        self.assertEqual(choices[0]['kind'],'anti_armor_approach')
        self.assertEqual(choices[0]['target_id'],'red-tank')
        self.assertLess(choices[0]['target_distance'],.7)
        self.assertEqual(choices[0]['position'],[.15,0.])
        self.assertGreaterEqual(choices[0]['target_distance'],.50)

    def test_tank_approach_exposes_rush_and_prone_with_native_site_evidence(self):
        self.members[0].update(satchel_ready_in=0,satchel_range=.44)
        position=self.members[0]['position']
        self.state.state['squad_behavior']['perception']['green']['contacts'] = [
            dict(id='red-tank',position=[position[0]+.8,position[1]],visible=True,
                 last_seen=0,kind='tank',weapon='cannon')]
        site=dict(id='C1',region_id='Nc',position=[position[0]+.35,position[1]],
                  kind='anti_armor_approach',target_id='red-tank',target_distance=.45,
                  path_length=.35,potential_attackers=1,hard_cover=True,
                  fire_targets=[],cover_key='',cover_id='')
        with patch('soldier_agents.query_candidates',return_value=dict(status='fresh',id='native-2',options=[site])):
            request=self.launch()
        self.assertEqual(request['state']['anti_armor_approach_sites'][0]['id'],'C1')
        self.assertIn('1.4倍速',request['questions']['action']['criteria']['rush_to_site:C1'])
        self.assertIn('匍匐',request['questions']['action']['criteria']['prone_approach:C1'])

    def test_throw_opportunity_interrupts_ongoing_personal_approach(self):
        self.members[0].update(satchel_ready_in=0,satchel_range=.44)
        position=self.members[0]['position']
        self.state.state['squad_behavior']['perception']['green']['contacts'] = [
            dict(id='red-tank',position=[position[0]+.3,position[1]],visible=True,
                 last_seen=0,kind='tank',weapon='cannon')]
        self.squad['personal']={'green-1':dict(intent='rush_to_site',status='active',
                                              order_id='order-1',until=6.)}
        request=self.launch()
        self.assertIn('satchel:red-tank',request['questions']['action']['criteria'])
        self.answer('satchel',target='red-tank')
        self.assertEqual(self.state.commands[0]['intent'],'satchel')

    def test_recent_backward_site_is_advisory_and_still_selectable(self):
        unit=self.members[0]
        unit.update(position=[4.12,2.04],in_cover=True)
        self.squad['assignments']['green-1']['position']=[3.9,2.1]
        self.squad['goal']=[9.,9.]
        self.c.soldiers.observe(self.members,self.squad,{})
        agent=self.c.soldiers.agents['green-1']
        agent['movement_history']=[dict(time=-2.,position=[4.2,2.025])]
        row=dict(id='C1',region_id='Nc',position=[4.2,2.025],path_length=.08,
                 fire_targets=[],potential_attackers=0,cover_key='',cover_id='')
        with patch('soldier_agents.query_candidates',return_value=dict(status='fresh',id='native-2',options=[row])):
            request=self.launch()
        context=request['state']
        self.assertEqual(context['assignment']['goal'],[3.9,2.1])
        self.assertTrue(context['candidate_sites'][0]['recently_visited'])
        self.assertLess(context['candidate_sites'][0]['goal_distance_gain'],0)
        self.assertIn('move_to_site:C1',request['questions']['action']['criteria'])
        self.answer('move_to_site',site='C1')
        self.assertEqual(self.state.commands[0]['site_id'],'C1')

    def test_atomic_peek_only_pairs_cover_with_its_verified_target(self):
        sites=[dict(id='C1',region_id='Nc',position=[.7,0.],path_length=.7,
                    fire_targets=['red-1'],potential_attackers=1,cover_key='cover:1',cover_id='cover'),
               dict(id='C2',region_id='Nc',position=[.8,0.],path_length=.8,
                    fire_targets=['red-2'],potential_attackers=0,cover_key='',cover_id='')]
        with patch('soldier_agents.query_candidates',return_value=dict(status='fresh',id='native-2',options=sites)):
            request=self.launch()
        options=request['questions']['action']['criteria']
        self.assertEqual(list(request['questions']),['action'])
        self.assertIn('peek_fire:C1:red-1',options)
        self.assertNotIn('peek_fire:C1:red-2',options)
        self.assertNotIn('peek_fire:C2:red-2',options)
        self.assertNotIn('occupy_cover:C2',options)
        self.answer('peek_fire',site='C1',target='red-1')
        self.assertEqual(self.state.commands[0]['target_id'],'red-1')

    def test_movement_history_is_bounded_real_observation_and_continue_sends_nothing(self):
        self.c.soldiers.observe(self.members,self.squad,{})
        for i in range(12):
            self.state.state['time']=float(i)
            self.members[0]['position']=[.1*(i%2),0.]
            self.c.soldiers.observe(self.members,self.squad,{})
        context=self.c.soldiers._context(self.members[0],self.squad)
        self.assertEqual(len(context['movement_history']),8)
        self.assertGreater(context['task_progress']['observed_path_length'],
                           context['task_progress']['observed_net_displacement'])
        self.assertTrue(context['task_progress']['local_arrival_is_not_task_completion'])
        self.launch();self.answer('continue_task')
        self.assertFalse(self.state.commands)

    def test_new_tank_opportunity_wakes_soldier_once(self):
        self.launch();self.answer('continue_task')
        agent=self.c.soldiers.agents['green-1']
        self.assertEqual(agent['next_at'],5.)
        self.members[0]['satchel_ready_in']=0
        self.members[0]['satchel_range']=.44
        position=self.members[0]['position']
        self.state.state['squad_behavior']['perception']['green']['contacts'] = [
            dict(id='red-tank',position=[position[0]+.3,position[1]],visible=True,
                 last_seen=1,kind='tank',weapon='cannon')]
        self.state.state['time']=1.;self.clock.now+=1
        self.tick()
        self.assertEqual(self.game.requests[-1]['state']['self']['id'],'green-1')
        self.assertIn('satchel:red-tank',self.game.requests[-1]['questions']['action']['criteria'])

    def test_stale_assignment_cannot_act(self):
        self.launch();self.squad['order_id']='order-2';self.answer('move_to_site',site='C1')
        self.assertFalse(self.state.commands);self.assertEqual(self.c.soldiers.discarded,1)

    def test_incoming_fire_invalidates_personal_movement(self):
        self.launch();self.members[0]['survival_reason']='incoming_fire'
        self.answer('move_to_site',site='C1')
        self.assertFalse(self.state.commands)
        self.assertEqual(self.c.soldiers.agents['green-1']['status'],'survival_interrupted')

    def test_dead_member_reply_cannot_act(self):
        self.launch();self.members=self.members[1:];self.answer('move_to_site',site='C1')
        self.assertFalse(self.state.commands);self.assertNotIn('green-1',self.c.soldiers.agents)

    def test_effective_work_does_not_reaffirm_same_member(self):
        for duty in self.squad['duties'].values():duty['role']='approach'
        self.launch();self.answer('continue_task')
        self.clock.now+=1;self.state.state['time']=5;self.tick()
        self.assertEqual([r['state']['self']['id'] for r in self.game.requests],['green-1','green-2'])

    def test_transient_fire_block_change_keeps_backoff_but_new_assignment_wakes(self):
        self.launch()
        self.answer('continue_task')
        agent = self.c.soldiers.agents['green-1']
        self.assertEqual(agent['next_at'], 5.)
        self.state.state['time'] = 1.
        self.clock.now += 1
        self.members[0]['combat'] = {'fire_block_reason': 'muzzle_cover'}
        self.tick()
        self.assertEqual(agent['next_at'], 5.)
        self.assertEqual(agent['memory'][-1]['reason'], 'muzzle_cover')
        self.squad['assignments']['green-1']['region_id'] = 'Nd'
        self.tick()
        self.assertEqual(self.game.requests[-1]['state']['self']['id'], 'green-1')
        self.assertEqual(self.game.requests[-1]['state']['assignment']['target_region_id'], 'Nd')

    def test_order_refresh_with_same_assignment_does_not_wake_every_soldier(self):
        self.launch(); self.answer('continue_task')
        before = len(self.game.requests)
        self.squad['order_id'] = 'order-2'
        self.state.state['time'] = 1.; self.clock.now += 1
        self.tick()
        self.assertEqual(len(self.game.requests), before)

    def test_candidate_model_view_drops_empty_native_bookkeeping(self):
        row = dict(id='C1', region_id='Nc', position=[.70000004, .00000001], kind='navigation_sample',
                   path_length=.70000004, goal_distance_gain=.123456, distance_from_self=.222222,
                   cover_key='', cover_id='', fire_targets=[], potential_attackers=0,
                   recently_visited=False, last_visited_seconds_ago=None)
        compact = self.c.soldiers._candidate_model_view(row)
        self.assertEqual(compact, dict(id='C1', region_id='Nc', position=[.7, 0.0],
                                       kind='navigation_sample', path_length=.7,
                                       goal_distance_gain=.123, distance_from_self=.222))

    def test_shared_budget_bounds_soldier_requests(self):
        self.c.config['shared_request_budget']=SharedRequestBudget(1)
        self.launch();self.answer('continue_task');self.clock.now+=3;self.tick()
        self.assertEqual(len(self.game.requests),1);self.assertTrue(self.c.budget_exhausted)

    def test_different_soldiers_can_decide_concurrently(self):
        self.launch()
        second=self.launch()
        self.assertEqual(second['state']['self']['id'],'green-2')
        self.assertEqual(set(self.c.soldiers.inflight),{'green-1','green-2'})
        self.game.requests[0]['future'].set_result({'answers':{'action':{'choice':'move_to_site:C1'}}})
        for _ in range(100):
            if self.c.soldiers.inflight['green-1']['future'].done():break
            time.sleep(.001)
        self.tick()
        self.assertEqual(self.state.commands[0]['unit_ids'],['green-1'])
        self.game.requests[1]['future'].set_result({'answers':{'action':{'choice':'move_to_site:C1'}}})
        for _ in range(100):
            if self.c.soldiers.inflight['green-2']['future'].done():break
            time.sleep(.001)
        self.tick()
        self.assertEqual([row['unit_ids'] for row in self.state.commands if row['action']=='soldier_order'],
                         [['green-1'],['green-2']])

    def test_rejected_engine_action_escalates(self):
        self.launch();self.answer('move_to_site',site='C1')
        self.state.results['command-1']={'accepted':False,'message':'no_route'};self.tick()
        self.assertEqual(self.c.soldiers.accepted,0)
        self.assertTrue(any(e['kind']=='participation_gap' for e in self.c.events))

    def test_invalid_site_is_rejected_without_command(self):
        self.launch();self.answer('move_to_site',site='C999')
        self.assertFalse(self.state.commands)
        self.assertEqual(self.c.soldiers.agents['green-1']['status'],'model_error')

    def test_timeout_response_is_discarded(self):
        self.launch();self.clock.now+=12;self.answer('move_to_site',site='C1')
        self.assertFalse(self.state.commands);self.assertEqual(self.c.soldiers.discarded,1)

    def test_blocked_report_does_not_repeat_immediately(self):
        self.launch();self.answer('report_blocked')
        self.state.results['command-1']={'accepted':True,'message':'applied'};self.tick()
        self.clock.now+=2;self.state.state['time']=6;self.tick()
        self.assertEqual(self.game.requests[-1]['state']['self']['id'],'green-2')

    def test_failed_local_attempt_escalates_after_five_game_seconds_once(self):
        self.c._update_progress(self.members)
        self.launch();self.answer('move_to_site',site='C1')
        self.state.results['command-1']={'accepted':True,'message':'applied'};self.tick()
        self.state.state['time']=5.1
        self.c._update_progress(self.members)
        self.assertEqual([e['reason'] for e in self.c.events if e['kind']=='participation_gap'],
                         ['local_attempt_no_contribution_5s'])
        self.c._update_progress(self.members)
        self.assertEqual(len([e for e in self.c.events if e['kind']=='participation_gap']),1)


if __name__=='__main__':unittest.main()
