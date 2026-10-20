"""Real controller request -> typed answers -> native payload, no model calls.

The fixture replaces transport and engine receipts only. It exports complete
coordinate-projected requests for the real TypeScript JEV schema validator.
It cannot establish real model tactical quality or native gameplay results.
"""
import copy
import json
import re
from pathlib import Path
import sys
import time
import unittest

SDK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK / 'src/deskfront'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_led_coordination_checks import Checks as Legacy, choice
from coordinate_prompt import inspect_state, Binding as CoordinateBinding
from squad_task_contract import prepare, relevance, selected_hold, make_review, PURPOSES, REVIEW_TRIGGERS

OUT = SDK / 'output' / 'tactical-no-wait-regression' / 'squad-tests'
OUT.mkdir(parents=True, exist_ok=True)


class Checks(unittest.TestCase):
    setUp, tearDown, pump, start, accept = Legacy.setUp, Legacy.tearDown, Legacy.pump, Legacy.start, Legacy.accept

    def response(self, request, intent='bound', role='maneuver', purpose='wait_contact', **overrides):
        answers = {}
        for key, question in request['questions'].items():
            self.assertEqual(question['type'], 'choice', key)
            options = question['criteria']
            selected = next(iter(options))
            if key == 'intent': selected = intent
            elif key.startswith('task_'):
                selected = next((value for value in options if value.startswith(role + ':')), selected)
            elif key == 'hold_purpose': selected = purpose
            elif key == 'hold_review': selected = 'contact_or_route_changed'
            elif key == 'equipment_actor': selected = 'unassigned'
            elif key.startswith('equipment_support_'): selected = 'not_assigned'
            selected = overrides.get(key, selected)
            answers[key] = dict(type='choice', choice=selected, confidence=1, probabilities={selected: 1})
        return dict(requestId='controlled-' + str(len(self.game.requests)), answers=answers)

    def harvest(self, request, response):
        slot = self.c.slots['executor']
        request['future'].set_result(response)
        for _ in range(200):
            if slot['future'].done(): break
            time.sleep(.001)
        self.assertTrue(slot['future'].done(), 'real request worker did not finish')
        self.c._harvest('executor', self.c._tactical_members(self.c.world))

    def next_request(self):
        self.c.next_at['executor'] = self.c.world.get('time', 0)
        self.c.next_wall['executor'] = 0
        self.c._launch('executor', self.c._tactical_members(self.c.world))
        for _ in range(200):
            if len(self.game.requests) >= 3: return self.game.requests[-1]
            time.sleep(.001)
        self.fail('continuation request not published')

    def export(self, name, request, answer):
        path = OUT / (name + '.json')
        path.write_text(json.dumps(dict(scenario=name, source='controlled actual HumanSquadController._launch; no paid model',
            state=request['state'], questions=request['questions'], answers=answer['answers']), ensure_ascii=False, indent=2), encoding='utf-8')
        return path

    def test_real_request_uses_supported_choices_and_no_independent_role_route_override(self):
        request = self.start(coordinates=True)
        self.assertIn('task_green-1', request['questions'])
        self.assertNotIn('role_green-1', request['questions'])
        self.assertNotIn('route_green-1', request['questions'])
        self.assertNotIn('flank_mover', request['questions'])
        self.assertNotIn('flank_fire_base', request['questions'])
        for key, question in request['questions'].items():
            self.assertEqual(question['type'], 'choice', key)
            self.assertIn('prompt_contract.shared_instructions', question['instructions'])
        task = request['questions']['task_green-1']['criteria']
        self.assertTrue(any(key.startswith('maneuver:(') and '/via' in key for key in task))
        self.assertFalse(any('P1' in key or 'Nc' in key for key in task))
        self.harvest(request, self.response(request))
        self.assertFalse(self.c.error, self.c.error)
        self.assertTrue(all(row['role'] == 'maneuver' for row in self.state.commands[-1]['assignments'].values()))

    def test_three_reloading_rockets_can_move_and_hold_forward_authored_area(self):
        self.state.state['units'].append(dict(id='green-3', faction='green', hp=100, position=[.15, 0.]))
        for unit in self.state.state['units']:
            unit.update(weapon='rocket', ammo=0, reload_remaining=3.8, weapon_range=.35, last_shot_at=-1.)
        request = self.start(coordinates=True)
        self.assertTrue({'hold', 'advance', 'bound', 'flank', 'cover', 'regroup'} <= request['questions']['intent']['criteria'].keys())
        answer = self.response(request, 'hold', purpose='wait_contact')
        for key, question in request['questions'].items():
            if key.startswith('task_'):
                forward = [value for value in question['criteria'] if value.startswith('maneuver:(')]
                chosen = max(forward, key=lambda value: float(re.search(r'\(([-\d.]+),', value).group(1)))
                answer['answers'][key] = dict(type='choice', choice=chosen, confidence=1, probabilities={chosen: 1})
        self.export('rear-three-rockets-forward-task', request, answer)
        self.harvest(request, answer)
        self.assertFalse(self.c.error, self.c.error)
        command = self.state.commands[-1]
        self.assertEqual(command['intent'], 'hold')
        self.assertEqual(len(command['assignments']), 3)
        self.assertTrue(all(row['position'][0] > .15 for row in command['assignments'].values()))
        self.assertEqual(command['task_contract']['purpose'], 'wait_contact')
        self.assertEqual(set(command['task_contract']['member_areas']), {'green-1', 'green-2', 'green-3'})
        self.assertTrue(all('task_area' in row for row in command['assignments'].values()))

    def test_meaningful_defence_without_current_enemy_can_reaffirm_same_hold(self):
        for index, unit in enumerate(self.state.state['units']):
            unit.update(position=[.7 + index * .01, 0.], weapon='rifle', ammo=6, weapon_range=.4)
        self.state.state['objective']['flag'] = dict(owner='green', held_seconds=3, required_seconds=20)
        first = self.start(coordinates=True)
        self.harvest(first, self.response(first, 'hold', purpose='defend_area'))
        self.assertFalse(self.c.error, self.c.error)
        self.accept()
        old = copy.deepcopy(self.state.commands[-1])
        self.c.world['squad_behavior']['squads'][self.c.squad_id]['phase'] = 'review_due'
        request = self.next_request()
        answer = self.response(request, 'continue_order', purpose='defend_area')
        self.export('valid-defence-wait-for-contact', request, answer)
        self.harvest(request, answer)
        self.assertFalse(self.c.error, self.c.error)
        new = self.state.commands[-1]
        self.assertEqual(new['order_id'], old['order_id'])
        self.assertEqual(new['assignments'], old['assignments'])
        self.assertEqual(new['position'], old['position'])
        self.assertEqual(new['task_review']['decision'], 'continue_hold')
        self.assertTrue(new['task_review']['id'])
        self.assertEqual(new['task_contract']['purpose'], 'defend_area')

    def test_continue_while_moving_ignores_invalid_unused_member_and_hold_branches(self):
        first = self.start()
        self.harvest(first, self.response(first, 'advance'))
        self.accept()
        request = self.next_request()
        answer = self.response(request, 'continue_order')
        for key in answer['answers']:
            if key.startswith('task_') or key.startswith('hold_'):
                answer['answers'][key]['choice'] = 'unused-invalid-branch'
        old_commands = len(self.state.commands)
        self.harvest(request, answer)
        self.assertFalse(self.c.error, self.c.error)
        self.assertEqual(len(self.state.commands), old_commands)

    def test_elapsed_review_is_a_model_review_not_a_forced_charge(self):
        first = self.start()
        self.harvest(first, self.response(first, 'hold', purpose='wait_contact'))
        self.accept()
        self.c.world['time'] = 25.
        self.c.stage_review_at = 20.
        for unit in self.c._members(self.c.world):
            self.c.unit_history[unit['id']].update(stationary_at=0., progress_at=0.)
        self.assertTrue(self.c._mission_status(self.c._members(self.c.world))['wait_expired'])
        request = self.next_request()
        self.assertIn('hold', request['questions']['intent']['criteria'])
        self.assertIn('continue_order', request['questions']['intent']['criteria'])
        self.assertIn('hold_purpose', request['questions'])
        self.harvest(request, self.response(request, 'continue_order', purpose='wait_contact'))
        self.assertFalse(self.c.error, self.c.error)
        self.assertEqual(self.state.commands[-1]['task_review']['decision'], 'continue_hold')
        self.assertEqual(self.state.commands[-1]['intent'], 'hold')

    def test_personal_receives_authored_area_purpose_and_native_progress(self):
        request = self.start()
        self.harvest(request, self.response(request, 'hold', purpose='wait_contact'))
        self.accept()
        command = self.state.commands[-1]
        squad = self.c.world['squad_behavior']['squads'][self.c.squad_id]
        squad['task_contract'] = copy.deepcopy(command['task_contract'])
        squad['assignment_execution'] = {'green-1': dict(status='moving', position=[.7, 0.], distance=.4, has_route=True)}
        members = self.c._members(self.c.world)
        self.c.soldiers.observe(members, squad, {})
        personal = self.c.soldiers._context(members[0], squad)
        self.assertEqual(personal['assignment']['task_contract']['purpose'], 'wait_contact')
        self.assertEqual(personal['assignment']['task_area']['position'], command['assignments']['green-1']['position'])
        self.assertEqual(personal['assignment']['assignment_execution']['status'], 'moving')

    def test_authored_cover_and_regroup_use_same_explicit_review_protocol(self):
        for intent in ('cover', 'regroup'):
            with self.subTest(intent=intent):
                if self.game.requests:
                    self.tearDown(); self.setUp()
                first = self.start(coordinates=True)
                self.harvest(first, self.response(first, intent, purpose='recover_then_review'))
                self.assertFalse(self.c.error, self.c.error)
                old = copy.deepcopy(self.state.commands[-1])
                self.assertEqual(old['task_contract']['task_kind'], intent)
                self.accept()
                request = self.next_request()
                answer = self.response(request, 'continue_order', purpose='recover_then_review')
                for key in answer['answers']:
                    if key.startswith('task_'): answer['answers'][key]['choice'] = 'unused-invalid-branch'
                self.harvest(request, answer)
                self.assertFalse(self.c.error, self.c.error)
                review = self.state.commands[-1]
                self.assertEqual(review['order_id'], old['order_id'])
                self.assertEqual(review['assignments'], old['assignments'])
                self.assertEqual(review['task_review']['decision'], 'continue_' + intent)

    def test_advance_ignores_area_purpose_focus_and_review_answers(self):
        request = self.start()
        answer = self.response(request, 'advance')
        for key in ('hold_purpose', 'hold_focus', 'hold_review'):
            answer['answers'][key]['choice'] = 'unused-invalid-branch'
        self.harvest(request, answer)
        self.assertFalse(self.c.error, self.c.error)
        self.assertNotIn('task_contract', self.state.commands[-1])

    def test_consumed_invalid_joint_choice_is_rejected_without_substitution(self):
        request = self.start()
        answer = self.response(request)
        answer['answers']['task_green-1']['choice'] = 'maneuver:not-offered'
        self.harvest(request, answer)
        self.assertIn('squad_member_task_not_offered:green-1', self.c.error)
        self.assertEqual(self.state.commands, [])

    def test_consumed_hold_requires_explicit_purpose_but_does_not_hide_hold(self):
        request = self.start()
        answer = self.response(request, 'hold')
        answer['answers'].pop('hold_purpose')
        self.harvest(request, answer)
        self.assertIn('squad_hold_contract_not_offered', self.c.error)
        self.assertEqual(self.state.commands, [])

    def test_member_roles_are_joint_with_exact_selected_routes_for_mixed_weapons(self):
        self.state.state['units'][0].update(weapon='rocket', ammo=0, reload_remaining=3.8)
        self.state.state['units'][1].update(weapon='smg', ammo=30)
        request = self.start(coordinates=True)
        answer = self.response(request, 'bound')
        key = next(value for value in request['questions']['task_green-1']['criteria'] if value.startswith('fire_support:'))
        answer['answers']['task_green-1'] = dict(type='choice', choice=key)
        self.harvest(request, answer)
        self.assertFalse(self.c.error, self.c.error)
        self.assertEqual(self.state.commands[-1]['assignments']['green-1']['role'], 'fire_support')
        self.assertEqual(self.state.commands[-1]['assignments']['green-2']['role'], 'maneuver')

    def test_conditional_binding_preserves_same_coordinate_different_via(self):
        state = dict(engine_squad={}, current_plan={})
        questions = dict(intent=dict(type='choice', criteria={'bound': '轮换'}),
            role_u=dict(type='choice', criteria={'maneuver': '机动', 'fire_support': '支援', 'establish_fire': '射位'}),
            route_u=dict(type='choice', criteria={'(1,2)/via1': '甲路径', '(1,2)/via2': '乙路径'}))
        wire, tasks, binding = prepare(state, questions)
        grid = dict(cell_size_world=.1, coordinate_frame='global-display-grid/v1', bounds=[0, 0, 1, 1])
        coordinate = CoordinateBinding(grid)
        coordinate.choices['route_u'] = {'(1,2)/via1': 'P1', '(1,2)/via2': 'P2'}
        answer = dict(answers={'intent': choice('bound'), 'task_u': choice('maneuver:(1,2)/via2')})
        decoded = coordinate.decode(binding.decode(answer))
        self.assertEqual(decoded['answers']['role_u']['choice'], 'maneuver')
        self.assertEqual(decoded['answers']['route_u']['choice'], 'P2')
        self.assertEqual(len(tasks['task_u']['criteria']), 6)
        self.assertNotIn('flank_mover', tasks)

    def test_authored_area_is_not_the_commander_reference(self):
        response = dict(requestId='r', answers={'intent': choice('hold'), 'route_u': choice('P2'),
            'hold_purpose': choice('wait_contact'), 'hold_review': choice('contact_or_route_changed')})
        request = dict(serial=1, token={'identity': ['run', 'green']}, member_region_choices={'u': {'P2':
            dict(region_id='local-area', position=[.3, .1], endpoint_id='site')}}, accepted_assignments={})
        context = dict(time=5, current_plan=dict(region_id='far-goal', position=[4, 2]), contacts=[])
        contract = selected_hold(response, request, context, 'hold')
        self.assertEqual(contract['member_areas']['u']['position'], [.3, .1])
        self.assertEqual(contract['commander_reference_area']['position'], [4, 2])
        self.assertNotIn('area_position', contract)
        review = make_review(response, request, context, 'hold')
        self.assertEqual(review['basis']['member_areas'], contract['member_areas'])
        other = make_review(dict(response, requestId='r2'), request, context, 'hold')
        self.assertNotEqual(review['id'], other['id'])

    def test_relevance_no_distance_gate_or_false_fire_for_reloading_rocket(self):
        context = dict(current_plan={'position': [5, 0]}, members=[dict(id='u', position=[0, 0], weapon='rocket', ammo=0, reload_remaining=3.8)],
            contacts=[], execution_evidence={'members': {'u': dict(seconds_since_last_shot=4, engageable_visible_targets=[])}})
        fact = relevance(context)
        self.assertEqual(fact['members']['u']['distance_to_commander_area'], 5)
        self.assertEqual(fact['members']['u']['engageable_visible_targets'], [])
        self.assertNotIn('allowed', fact['members']['u'])
        self.assertNotIn('must_advance', fact)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Checks)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    (OUT / 'coherence-results.json').write_text(json.dumps(dict(tests=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), success=result.wasSuccessful(), import_path=str(SDK / 'src/deskfront'),
        limits='controlled transport and receipts; no paid model and no native gameplay'), indent=2), encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
