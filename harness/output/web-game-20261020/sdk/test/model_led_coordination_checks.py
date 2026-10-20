"""Isolated SDK regression: real request builders and orders, fake transport only.

Run: python test/model_led_coordination_checks.py
No game source, native process, provider credentials or model calls are used.
"""
import copy
from concurrent.futures import Future
import json
from pathlib import Path
import sys
import threading
import time
import unittest

SDK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK / 'src/deskfront'))
from human_squad import HumanSquadController
from combat_prompt import instructions, share_executor_contract
from coordinate_prompt import inspect_state, Binding
from equipment_assignment import select_assignment
from squad_cooperation import build as cooperation


def world():
    return dict(run_id='test-run', tick=1, time=0., paused=False, winner='',
        control={'green': 'lm', 'red': 'game_ai'}, control_epochs={'green': 3},
        navigation_revision=1, demo={'phase': 'battle'}, objective={'position': [.7, 0.]},
        units=[dict(id='green-1', faction='green', hp=100, position=[0., 0.]),
               dict(id='green-2', faction='green', hp=100, position=[.075, 0.])],
        strategic_topology=dict(run_id='test-run', revision=1, step=.075,
            cells={'a': [0., 0.], 'b': [.075, 0.], 'c': [.7, 0.]}, edges=[['a', 'b'], ['b', 'c']]),
        squad_behavior={'squads': {}, 'perception': {'green': {'contacts': []}}, 'events': []})


class State:
    def __init__(self):
        self.state, self.lock, self.results, self.commands = world(), threading.RLock(), {}, []
    def submit(self, command, source=None):
        assert source == 'lm'
        self.commands.append(copy.deepcopy(command))
        return 202, {'id': 'command-' + str(len(self.commands))}


class Game:
    session_id = 'test-session'
    def __init__(self):
        self.requests, self.records = [], []
    def ask(self, state, questions, role=None):
        future = Future()
        self.requests.append(dict(state=copy.deepcopy(state), questions=copy.deepcopy(questions), future=future))
        return future.result()
    def record(self, row):
        self.records.append(copy.deepcopy(row))


def choice(value):
    return dict(type='choice', choice=value)


class Checks(unittest.TestCase):
    def setUp(self):
        self.state, self.game, self.wall = State(), Game(), 100.
        self.c = HumanSquadController(self.state,
            {'coordinate_protocol': False, 'model': 'jev', 'timeout': 10, 'max_requests': 100, 'soldier_agents': False},
            self.game, 'green', wall_clock=lambda: self.wall)
    def tearDown(self):
        self.c.stop()
        for request in self.game.requests:
            if not request['future'].done(): request['future'].set_exception(RuntimeError('test-end'))
    def pump(self, condition):
        for _ in range(200):
            self.c.tick()
            if condition(): return
            time.sleep(.001)
        self.fail('SDK did not reach expected state')
    def start(self, *, coordinates=False, equipment=False):
        if equipment:
            self.state.state['at_guns'] = [dict(id='m', kind='mortar', faction='neutral', seen_by=['green'],
                position=[.7, 0.], crew_ids=[], gunner_id='', guard_id='', capturable=True, capture_radius=.2)]
        # This suite isolates the existing commander-led equipment/route
        # contract. The separate tactical-no-wait suite exercises concurrent
        # initial goal selection and commander failures.
        due = self.c._due
        self.c._due = lambda role: role != 'executor' and due(role)
        try:
            self.pump(lambda: len(self.game.requests) == 1)
            value = dict(region_id='Nc', objective='推进至接敌区域', risk='旧观察：green-2正在装填', stage='approach')
            if equipment: value['equipment_goal'] = dict(equipment_id='m', phase='capture', risk='射界未知', reason='比较支援机会')
            self.c.config['coordinate_protocol'] = coordinates
            self.game.requests[0]['future'].set_result(dict(requestId='plan', answers={'plan': dict(type='json', value=value)}))
            self.pump(lambda: bool(self.c.plan))
        finally:
            del self.c._due
        self.pump(lambda: len(self.game.requests) == 2)
        return self.game.requests[1]
    def response(self, request, intent='bound', actor='green-2', supports=True):
        answers = {}
        for key, question in request['questions'].items():
            selected = next(iter(question['criteria']))
            if key == 'intent': selected = intent
            elif key.startswith('role_'): selected = 'maneuver'
            elif key.startswith('route_'): selected = next(k for k in question['criteria'] if k != 'keep_assignment')
            elif key.startswith('task_'): selected = next(k for k in question['criteria'] if k.startswith('maneuver:'))
            elif key == 'equipment_actor': selected = actor
            elif key.startswith('equipment_support_'): selected = 'support' if supports else 'not_assigned'
            answers[key] = choice(selected)
        return dict(requestId='selected', answers=answers)
    def harvest(self, request, response):
        request['future'].set_result(response)
        for _ in range(200):
            if self.c.slots['executor']['future'].done(): break
            time.sleep(.001)
        self.c._harvest('executor', self.c._tactical_members(self.c.world))
    def accept(self):
        command = self.state.commands[-1]
        squad = dict(order_id=command['order_id'], plan_version=command['plan_version'], goal=command['position'],
            intent=command['intent'], radius=command['radius'], assignments=copy.deepcopy(command['assignments']), phase='advancing')
        self.c.world['squad_behavior']['squads'][self.c.squad_id] = squad
        self.state.state['squad_behavior']['squads'][self.c.squad_id] = copy.deepcopy(squad)
        ident = next(reversed(self.c.pending_commands))
        self.c._receipts({ident: dict(accepted=True, tick=self.c.world['tick'])})

    def test_every_independent_question_gets_shared_contract_after_coordinate_projection(self):
        request = self.start(coordinates=True, equipment=True)
        contract = request['state']['prompt_contract']
        common = contract['shared_instructions']
        self.assertEqual(contract['question_evaluation'], 'independent_same_state')
        self.assertIn('统一地图坐标协议', common)
        self.assertIn('原生', common)
        self.assertIn('battlefield_equipment', common)
        self.assertIn('以本轮事实为准', common)
        wire = json.dumps({'state': request['state'], 'questions': request['questions']}, ensure_ascii=False)
        self.assertEqual(wire.count('# 统一地图坐标协议'), 1)
        self.assertEqual(wire.count('# 当前装备能力'), 1)
        for key, question in request['questions'].items():
            self.assertIn('prompt_contract.shared_instructions', question['instructions'], key)
            self.assertIn('本题独立判断', question['instructions'], key)
        self.assertIn('green-1', request['questions']['task_green-1']['instructions'])
        self.assertNotIn('role_green-1', request['questions'])
        self.assertNotIn('route_green-1', request['questions'])
        self.assertIn('green-1', request['questions']['equipment_support_green-1']['instructions'])
        self.assertEqual(len(self.game.requests), 2)

    def test_native_coordination_survives_actual_both_requests_and_personal_board(self):
        coordination = dict(motion_policy='selected_routes_alternating', support_confirmed=False,
                            support_ids=[], blocks_movement=False)
        squad = dict(phase='advancing', coordination=copy.deepcopy(coordination))
        self.state.state['squad_behavior']['squads'] = {
            'green-squad': squad,
            'red-squad': dict(coordination={'private_enemy_sentinel': 'never-send'})}
        request = self.start(coordinates=True)
        for sent in self.game.requests:
            state = inspect_state(sent['state'])
            self.assertEqual(state['engine_squad']['coordination'], coordination)
            self.assertEqual(state['cooperation_board']['native_handoff']['coordination'], coordination)
            self.assertNotIn('private_enemy_sentinel', json.dumps(state))
        members = self.c._members(self.c.world)
        self.c.soldiers.observe(members, squad, {})
        personal = self.c.soldiers._context(members[0], squad)
        self.assertEqual(personal['cooperation_board']['native_handoff']['coordination'], coordination)
        self.assertIn('未确认掩护，不表示禁止移动', request['state']['prompt_contract']['shared_instructions'])

    def test_legacy_snapshot_does_not_fabricate_coordination(self):
        self.start(coordinates=True)
        for sent in self.game.requests:
            state = inspect_state(sent['state'])
            self.assertNotIn('coordination', state['engine_squad'])
            self.assertNotIn('coordination', state['cooperation_board']['native_handoff'])
        members = self.c._members(self.c.world)
        self.c.soldiers.observe(members, {}, {})
        personal = self.c.soldiers._context(members[0], {})
        self.assertNotIn('coordination', personal['cooperation_board']['native_handoff'])

    def test_shared_projection_preserves_legal_criteria_and_input(self):
        context = dict(prompt_contract={'version': 'coordinates/v1'}, members=[{'id': 'u', 'ammo': 0}])
        questions = {'intent': dict(type='choice', criteria={'bound': '轮换', 'hold': '驻守'}, instructions='共同说明'),
                     'route_u': dict(type='choice', criteria={'(1,2)': '合法路径'}, instructions='为u预选')}
        before = copy.deepcopy((context, questions))
        state, offered = share_executor_contract(context, questions)
        self.assertEqual((context, questions), before)
        for key in questions: self.assertEqual(offered[key]['criteria'], questions[key]['criteria'])
        self.assertEqual(state['members'], context['members'])

    def test_reloading_rockets_still_offer_and_submit_model_selected_bound(self):
        for unit in self.state.state['units']:
            unit.update(weapon='rocket', ammo=0, reload_remaining=3.8, last_shot_at=-1.)
        request = self.start()
        self.assertTrue({'advance', 'bound', 'hold', 'cover', 'regroup', 'flank'} <= request['questions']['intent']['criteria'].keys())
        self.harvest(request, self.response(request, 'bound'))
        self.assertFalse(self.c.error)
        self.assertEqual(self.state.commands[-1]['intent'], 'bound')
        self.assertTrue(all(row['role'] == 'maneuver' for row in self.state.commands[-1]['assignments'].values()))

    def test_hold_remains_model_choice_not_forced_advance(self):
        request = self.start()
        self.harvest(request, self.response(request, 'hold'))
        self.assertFalse(self.c.error)
        self.assertEqual(self.state.commands[-1]['intent'], 'hold')

    def test_history_basis_survives_both_views_and_live_members_remain_current(self):
        request = self.start()
        self.c.world['time'] = 25.
        self.c.world['units'][1].update(hp=80, ammo=1, reload_remaining=0)
        context = self.c._context(self.c._members(self.c.world))
        for view in (self.c._executor_context(context), self.c._commander_context(context)):
            self.assertEqual(view['current_plan']['assessment_basis']['observed_game_time'], 0.)
            self.assertEqual(view['current_plan']['risk'], '旧观察：green-2正在装填')
            unit = next(u for u in view['members'] if u['id'] == 'green-2')
            self.assertEqual((unit['hp'], unit['ammo'], unit['reload_remaining']), (80, 1, 0))
        self.assertIn('时间未记录则视为历史时刻未知', request['state']['prompt_contract']['shared_instructions'])

    def test_recent_shot_survives_reload_without_claiming_readiness_or_cover(self):
        w = world(); w['time'] = 10.
        u = dict(w['units'][0], weapon='rocket', ammo=0, reload_remaining=3.3, last_shot_at=9.5, last_shot_target='enemy')
        board = cooperation(w, 'green', [u], [dict(id='enemy', visible=True)], {}, {}, {}, {})
        self.assertEqual(board['recent_fire_by_target'], {'enemy': ['green-1']})
        self.assertEqual(board['members']['green-1']['interruption'], 'reloading')
        self.assertFalse(board['members']['green-1']['recent_uninterrupted_target_fire'])
        self.assertFalse(board['effective_assignment_member_ids'])
        board = cooperation(w, 'green', [u], [dict(id='enemy', visible=False)], {}, {}, {}, {})
        self.assertFalse(board['recent_fire_by_target'])

    def test_equipment_self_support_branch_ignored_and_real_other_support_retained(self):
        request = self.start(equipment=True)
        self.harvest(request, self.response(request))
        self.assertFalse(self.c.error)
        self.assertIsNone(self.c.equipment_assignment)
        self.accept()
        self.assertEqual(self.c.equipment_assignment['actor_id'], 'green-2')
        self.assertEqual(self.c.equipment_assignment['support_ids'], ['green-1'])

    def test_unassigned_actor_ignores_all_speculative_support_without_autopick(self):
        request = self.start(equipment=True)
        self.harvest(request, self.response(request, actor='unassigned'))
        self.assertFalse(self.c.error)
        self.accept()
        self.assertEqual(self.c.equipment_assignment['status'], 'unassigned')
        self.assertIsNone(self.c.equipment_assignment['actor_id'])
        self.assertEqual(self.c.equipment_assignment['support_ids'], [])

    def test_capture_keeps_native_weapon_qualification(self):
        self.state.state['units'][0]['weapon'] = 'rocket'
        request = self.start(equipment=True)
        self.assertNotIn('green-1', request['questions']['equipment_actor']['criteria'])
        self.harvest(request, self.response(request, actor='green-1'))
        self.assertIn('invalid_equipment_assignment', self.c.error)
        self.assertFalse(self.state.commands)

    def test_used_support_still_requires_explicit_valid_route(self):
        request = self.start(equipment=True)
        response = self.response(request)
        response['answers']['task_green-1'] = choice('maneuver:invented-route')
        self.harvest(request, response)
        self.assertIn('squad_member_task_not_offered', self.c.error)
        self.assertFalse(self.state.commands)

    def test_used_support_answer_still_must_be_legal(self):
        request = self.start(equipment=True)
        response = self.response(request)
        response['answers']['equipment_support_green-1'] = choice('invented')
        self.harvest(request, response)
        self.assertIn('invalid_equipment_assignment', self.c.error)
        self.assertFalse(self.state.commands)

    def test_changed_equipment_state_discards_pending_choice(self):
        request = self.start(equipment=True)
        self.c.world['at_guns'][0]['faction'] = 'red'
        self.harvest(request, self.response(request))
        self.assertFalse(self.state.commands)
        self.assertTrue(any(r.get('reason') == 'equipment_control_changed' for r in self.game.records))

    def test_continue_ignores_member_and_equipment_preselections(self):
        request = self.start(equipment=True)
        self.harvest(request, self.response(request)); self.accept()
        old = copy.deepcopy((self.c.equipment_assignment, self.c.last_order))
        self.c._launch('executor', self.c._tactical_members(self.c.world))
        self.pump(lambda: len(self.game.requests) == 3)
        request = self.game.requests[-1]
        self.harvest(request, self.response(request, intent='continue_order', actor='green-1', supports=False))
        self.assertFalse(self.c.error)
        self.assertEqual((self.c.equipment_assignment, self.c.last_order), old)
        self.assertEqual(len(self.state.commands), 1)

    def test_lost_control_does_not_submit_pending_bound(self):
        request = self.start()
        self.state.state['control']['green'] = 'game_ai'
        self.state.state['control_epochs']['green'] += 1
        request['future'].set_result(self.response(request))
        self.c.tick()
        self.assertFalse(self.state.commands)

    def test_coordinate_decoder_rejects_unoffered_route(self):
        binding = Binding({'cell_size_world': .1, 'bounds': [0, 0, 10, 10]})
        binding.choices['route_u'] = {'(1,2)': 'P1'}
        with self.assertRaises(ValueError):
            binding.decode(dict(answers={'route_u': choice('(99,99)')}))


if __name__ == '__main__':
    unittest.main(verbosity=2)
