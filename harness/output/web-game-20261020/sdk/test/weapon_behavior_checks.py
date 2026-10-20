"""Actual controller requests, fake provider/native queries; no game/model calls.

Optionally set WEAPON_HABIT_EVIDENCE_DIR to save actual serialized wire cases.
"""
import copy
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock

sys.dont_write_bytecode = True
SDK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK / 'src/deskfront'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import model_led_coordination_checks as inherited
from human_squad import HumanSquadController
from combat_prompt import model_view, instructions
from coordinate_prompt import inspect_state
from weapon_behavior import build, HABITS
from combat_command_validation import validate

EVIDENCE = Path(os.environ['WEAPON_HABIT_EVIDENCE_DIR']) if os.environ.get('WEAPON_HABIT_EVIDENCE_DIR') else None
CAP = dict(supported=True, available=True, duration_seconds=3,
           requires_fireable_target=True, preserves_assignment_route=True)


def unit_weapon(unit, weapon):
    radius, damage, interval, accuracy, cone = {
        'rifle': (.7, 13., 1.05, .82, .0699),
        'smg': (.6, 5., .14, .58, .1061),
        'rocket': (.92, 30., 3.8, .85, .04015),
    }.get(weapon, (None, None, None, None, None))
    unit.update(weapon=weapon, hp=150, max_hp=150, weapon_range=radius,
                ammo_infinite=True, ammo=8, reload_remaining=0, suppression=0, posture='stand')
    combat = unit.setdefault('combat', {})
    if radius is not None:
        combat['weapon_profile'] = dict(schema='small_arms_profile/v1', range=radius,
            damage=damage, shot_interval_s=interval, accuracy_parameter=accuracy,
            base_cone_rad={'rifle':.060, 'smg':.083, 'rocket':.0319}[weapon],
            still_cone_rad=cone, current_cone_rad=cone,
            moving_accuracy_multiplier=.70 if weapon=='smg' else .55, moving=False)
    else:
        combat.pop('weapon_profile', None)


def save(name, request, **extra):
    if EVIDENCE:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        value = dict(id=name, scope='Controlled offline actual SDK request; fake native facts, not live match',
                     state=request['state'], questions=request['questions'], **extra)
        (EVIDENCE/(name+'.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


class Personal:
    def __init__(self, weapon='rifle', caps=CAP, team='green', coordinates=True):
        self.state, self.game = inherited.State(), inherited.Game()
        world = self.state.state
        for unit in world['units']:
            unit['id'] = unit['id'].replace('green', team); unit['faction'] = team
            unit_weapon(unit, weapon)
        world['control'] = {team:'lm'}; world['control_epochs'] = {team:3}
        world['squad_behavior']['perception'] = {team:dict(contacts=[dict(
            id='enemy', faction='red' if team=='green' else 'green', kind='infantry',
            hp=100, position=[.4, 0.], visible=True, last_seen=0)])}
        self.c = HumanSquadController(self.state,
            dict(coordinate_protocol=coordinates, model='jev', max_requests=100, timeout=10),
            self.game, team, wall_clock=lambda:100.)
        self.c.world = world; self.c.identity = ('test-run', 3, 'lm')
        uid = team+'-1'
        self.squad = dict(order_id='order-1', intent='advance', assignments={uid:dict(
            role='establish_fire', region_id='Nc', region_path=['Na','Nc'])},
            assignment_tokens={uid:dict(version=1)}, duties={uid:dict(role='blocked',reason='muzzle_cover')})
        world['squad_behavior']['squads'][team+'-squad'] = self.squad
        self.members = self.c._members(world)[:1]
        combat = self.members[0]['combat']
        combat.update(engageable_targets=['enemy'], path_active=True,
            firing_awareness=dict(target_id='enemy', clear=True, distance=.4, reason='', time=0))
        if caps is not None:
            combat['personal_action_capabilities'] = dict(hold_fire_position=copy.deepcopy(caps))
        self.query = Mock(return_value=dict(status='fresh', id='controlled-native-query', options=[
            dict(id='C1', region_id='Nc', position=[.2,0.], path_length=.2,
                 fire_targets=['enemy'], fire_checks=[dict(target_id='enemy', distance=.2, clear=True, reason='')],
                 fire_check_posture='stand', sampled_at=0, cover_key='', cover_id='')]))
        self.c.config['candidate_query'] = self.query
    def tick(self): self.c.soldiers.tick(self.members, self.squad, self.state.results, active=True)
    def launch(self):
        self.tick()
        for _ in range(200):
            if self.game.requests: return self.game.requests[-1]
            time.sleep(.001)
        raise AssertionError('actual personal request not sent')
    def answer(self, value, provider_id='provider-hold-1'):
        request = self.game.requests[-1]
        response = dict(answers={'action':dict(choice=value)})
        if provider_id is not None: response['requestId'] = provider_id
        request['future'].set_result(response)
        for _ in range(200):
            if self.c.soldiers.pending['future'].done(): break
            time.sleep(.001)
        self.tick()
    def close(self):
        self.c.stop()
        for request in self.game.requests:
            if not request['future'].done(): request['future'].set_exception(RuntimeError('test-end'))


class Checks(unittest.TestCase):
    def test_mixed_green_and_red_actual_shared_questions(self):
        for team in ('green','red'):
            with self.subTest(team=team):
                f=inherited.Checks(); f.setUp()
                try:
                    world=f.state.state
                    world['units'].append(dict(id='green-3', faction='green', hp=100, position=[.075,0.]))
                    for unit,weapon in zip(world['units'], ('rifle','smg','rocket')):
                        unit['id']=unit['id'].replace('green',team);unit['faction']=team;unit_weapon(unit,weapon)
                    world['control']={team:'lm'};world['control_epochs']={team:3}
                    world['squad_behavior']['perception']={team:{'contacts':[]}}
                    f.c.stop(); f.c=HumanSquadController(f.state,
                        dict(coordinate_protocol=False,model='jev',timeout=10,max_requests=100,soldier_agents=False),
                        f.game,team,wall_clock=lambda:f.wall)
                    request=f.start(coordinates=True)
                    context=inspect_state(request['state']); slots=context['weapon_behavior_slots']
                    self.assertEqual(set(slots['habits']),{'rifle','smg','rocket'})
                    for number,weapon in enumerate(('rifle','smg','rocket'),1):
                        uid=team+'-'+str(number)
                        self.assertEqual(slots['actors'][uid]['habit_id'],weapon)
                        self.assertIn('weapon_behavior_slots.actors.'+uid,request['questions']['task_'+uid]['instructions'])
                        self.assertEqual(context['execution_evidence']['members'][uid]['weapon_profile']['damage'],
                                         {'rifle':13.,'smg':5.,'rocket':30.}[weapon])
                        choices=request['questions']['task_'+uid]['criteria']
                        for role in ('maneuver','establish_fire','fire_support'):
                            self.assertTrue(any(k.startswith(role+':') for k in choices))
                    for question in request['questions'].values():
                        self.assertIn('prompt_contract.shared_instructions', question['instructions'])
                    self.assertIn('当前兵种行为习惯插槽',context['prompt_contract']['shared_instructions'])
                    self.assertEqual(len(f.game.requests),2);self.assertEqual(f.state.commands,[])
                    save('mixed-'+team,request)
                finally:f.tearDown()

    def test_personal_weapon_specific_current_context_and_no_extra_calls(self):
        for weapon in ('rifle','smg','rocket','unknown'):
            with self.subTest(weapon=weapon):
                f=Personal(weapon)
                try:
                    request=f.launch(); context=inspect_state(request['state'])
                    slot=context['weapon_behavior_slots']['actors']['green-1']
                    self.assertEqual(slot['current_weapon'],weapon)
                    self.assertEqual(slot['habit_id'],None if weapon=='unknown' else weapon)
                    self.assertEqual(set(context['weapon_behavior_slots']['habits']),set() if weapon=='unknown' else {weapon})
                    for key in ('hold_fire_position','continue_task','focus_fire:enemy'):
                        self.assertIn(key,request['questions']['action']['criteria'])
                    for intent in ('rush_to_site:', 'move_to_site:'):
                        self.assertTrue(any(key.startswith(intent) for key in request['questions']['action']['criteria']))
                    self.assertEqual(context['execution_evidence']['personal_action_capabilities']['hold_fire_position'],CAP)
                    for _ in range(10):f.tick()
                    self.assertEqual(len(f.game.requests),1);self.assertEqual(f.query.call_count,1)
                    save('personal-'+weapon,request)
                finally:f.close()

    def test_unknown_or_unavailable_native_capability_only_removes_new_action(self):
        criteria=[]
        for caps in (None,{},dict(CAP,available=False),dict(CAP,supported=False),dict(CAP,available=1),CAP):
            f=Personal(caps=caps)
            try:
                request=f.launch(); keys=set(request['questions']['action']['criteria'])
                self.assertEqual('hold_fire_position' in keys,isinstance(caps,dict) and caps.get('supported') is True and caps.get('available') is True)
                criteria.append(keys-{'hold_fire_position'})
                save('caps-'+str(len(criteria)),request)
            finally:f.close()
        self.assertTrue(all(row==criteria[0] for row in criteria))

    def test_provider_identity_and_local_fallback_map_to_actual_command(self):
        for provider_id in ('real-provider-request',None,''):
            with self.subTest(provider_id=provider_id):
                f=Personal()
                try:
                    request=f.launch(); local=f.c.soldiers.pending['local_decision_id']
                    f.answer('hold_fire_position',provider_id)
                    self.assertEqual(len(f.state.commands),1)
                    command=f.state.commands[0]
                    self.assertEqual(command['action_id'],provider_id or local)
                    self.assertEqual(command['intent'],'hold_fire_position')
                    self.assertEqual(command['assignment_token'],{'version':1})
                    self.assertNotIn('target_id',command);self.assertNotIn('site_id',command)
                    row=next(r for r in f.game.records if r.get('type')=='soldier-decision')
                    self.assertEqual(row['local_decision_id'],local)
                    self.assertEqual(row['provider_request_id'],provider_id or None)
                    save('command-'+('provider' if provider_id else 'fallback'),request,parsed_command=command,
                         identity_mapping={k:row[k] for k in ('local_decision_id','provider_request_id','action_id')})
                finally:f.close()

    def test_personal_weapon_change_discards_late_response(self):
        f=Personal()
        try:
            f.launch(); unit_weapon(f.members[0],'rocket')
            f.answer('hold_fire_position')
            self.assertEqual(f.state.commands,[])
            self.assertTrue(any(r.get('reason')=='weapon_changed' for r in f.game.records))
        finally:f.close()

    def test_equipment_change_wakes_once_without_replacing_task_or_cooldown(self):
        f=Personal()
        try:
            f.c.soldiers.observe(f.members,f.squad,{})
            agent=f.c.soldiers.agents['green-1']
            self.assertFalse(agent.get('weapon_wake',False))
            task=copy.deepcopy(agent['task_signature']);version=agent['task_version']
            agent.update(next_at=1000.,next_wall_at=200.,last_review=0.)
            unit_weapon(f.members[0],'smg');f.tick()
            self.assertTrue(agent['weapon_wake']);self.assertEqual(agent['next_at'],0.)
            self.assertEqual(f.game.requests,[])  # Existing wall-clock cooldown still applies.
            self.assertEqual(agent['task_signature'],task);self.assertEqual(agent['task_version'],version)
            agent['next_wall_at']=0.;request=f.launch()
            self.assertFalse(agent['weapon_wake'])
            self.assertEqual(inspect_state(request['state'])['weapon_behavior_slots']['actors']['green-1']['habit_id'],'smg')
            for _ in range(10):f.tick()
            self.assertEqual(len(f.game.requests),1);self.assertEqual(f.query.call_count,1)
            self.assertEqual(f.state.commands,[])
        finally:f.close()

    def test_focus_and_hold_costs_are_explicit_in_actual_personal_wire(self):
        f=Personal()
        try:
            request=f.launch();state=inspect_state(request['state'])
            text=state['action_definitions']['focus_fire']
            self.assertIn('取消当前运动执行',text)
            self.assertIn('保留上级路线',state['action_definitions']['hold_fire_position'])
            self.assertIn('不强制选择保持射位',request['questions']['action']['instructions'])
        finally:f.close()

    def test_squad_weapon_change_discards_late_response(self):
        f=inherited.Checks();f.setUp()
        try:
            for unit in f.state.state['units']:unit_weapon(unit,'rifle')
            request=f.start(coordinates=True)
            unit_weapon(f.c.world['units'][0],'rocket')
            f.harvest(request,f.response(request))
            self.assertEqual(f.state.commands,[])
            self.assertTrue(any(r.get('reason')=='weapon_changed' for r in f.game.records))
        finally:f.tearDown()

    def test_current_weapon_rebind_and_unknown_are_read_only(self):
        context=dict(members=[dict(id='u',weapon='rifle',weapon_range=.7)],
                     engine_squad=dict(assignments={'u':dict(role='fire_support')}))
        before=copy.deepcopy(context); row=build(context,'commander')['actors']['u']
        self.assertEqual(row['assignment_path'],'engine_squad.assignments.u')
        self.assertIsNone(row['candidates_path']);self.assertEqual(context,before)
        context['members'][0]['weapon']='rocket';self.assertEqual(build(context,'executor')['actors']['u']['habit_id'],'rocket')
        context['members'][0]['weapon']='sniper';self.assertIsNone(build(context,'executor')['actors']['u']['habit_id'])
        for habit in HABITS.values():
            self.assertTrue({'role_tendency','spacing','continue_approach_when','stop_or_hold_when','review_when'} <= set(habit))

    def test_firing_hold_terminal_facts_reach_actual_personal_request(self):
        f=Personal(caps=dict(CAP,available=False))
        try:
            fact=dict(action_id='past',state='completed',reason='no_clear_firing_lane',until=3.,review_due=True)
            f.members[0]['combat']['firing_hold']=copy.deepcopy(fact)
            context=inspect_state(f.launch()['state'])
            self.assertEqual(context['execution_evidence']['firing_hold'],fact)
        finally:f.close()

    def test_native_envelope_validation_preserves_hold_command_and_identity(self):
        command=dict(action='soldier_order',intent='hold_fire_position',action_id='req',unit_ids=['u'])
        before=copy.deepcopy(command); calls=[]
        native=lambda c,a:calls.append(c)
        self.assertIsNone(validate(command,{},native))
        self.assertEqual(calls[-1],command)
        calls.clear();self.assertIsNone(validate(command,{'id':'agent'},native))
        self.assertEqual(command,before);self.assertEqual(calls[-1]['action_id'],'req')
        self.assertEqual(calls[-1]['intent'],'adjust_position')
        del command['action_id'];self.assertEqual(validate(command,{'id':'agent'},native),'action_id_required')


if __name__=='__main__':unittest.main(verbosity=2)
