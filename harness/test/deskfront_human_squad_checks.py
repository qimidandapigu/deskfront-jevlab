import copy
from concurrent.futures import Future
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from human_squad import EMOTIONS, HumanSquadController, validate_plan
from squad_region_choices import build as build_squad_region_choices


class Clock:
    now = 100.
    def __call__(self):
        return self.now


def world():
    return dict(run_id='run-1', tick=1, time=0., paused=False, winner='',
                control={'green': 'lm', 'red': 'game_ai'}, control_epochs={'green': 3},
                navigation_revision=1, demo={'phase': 'battle'}, objective={'position': [.7, 0.]},
                units=[dict(id='green-1', faction='green', hp=100, position=[0., 0.]),
                       dict(id='green-2', faction='green', hp=100, position=[.075, 0.]),
                       dict(id='red-hidden', faction='red', hp=100, position=[9., 9.])],
                strategic_topology=dict(run_id='run-1', revision=1, step=.075,
                                        cells={'a': [0., 0.], 'b': [.075, 0.], 'c': [.7, 0.], 'd': [3., 0.]},
                                        edges=[['a', 'b'], ['b', 'c']]),
                squad_behavior={'squads': {}, 'perception': {'green': {'contacts': []}}, 'events': []})


class State:
    def __init__(self):
        self.state = world()
        self.lock = threading.RLock()
        self.results = {}
        self.commands = []

    def submit(self, command, source=None):
        assert source == 'lm'
        self.commands.append(copy.deepcopy(command))
        return 202, {'id': 'command-' + str(len(self.commands))}


class Game:
    session_id = 'session-1'
    def __init__(self):
        self.requests = []
        self.records = []
        self.lock = threading.Lock()

    def ask(self, state, questions, role=None):
        future = Future()
        with self.lock:
            self.requests.append(dict(state=copy.deepcopy(state), questions=copy.deepcopy(questions), role=role, future=future))
        return future.result()

    def record(self, row):
        self.records.append(copy.deepcopy(row))


def plan(region='Nc'):
    return dict(region_id=region, objective='沿目标区域结伴推进', risk='敌人未知',
                replan_when='道路受阻', completion='到达并建立位置')


def answer_plan(value=None):
    return dict(requestId='commander-provider', answers={'plan': dict(type='json', value=value or plan())})


def answer_intent(choice='bound', **extra):
    return dict(requestId='executor-provider', answers={'intent': dict(type='choice', choice=choice, confidence=.001, **extra)})


def side_route_options(units):
    regions = {
        'Na': dict(center=[0., 0.], radius=.1, neighbors=['Nb']),
        'Nb': dict(center=[.3, 0.], radius=.1, neighbors=['Na', 'Nc', 'Ns']),
        'Nc': dict(center=[.7, 0.], radius=.1, neighbors=['Nb', 'Ns']),
        'Ns': dict(center=[.5, .3], radius=.1, neighbors=['Nb', 'Nc']),
    }
    return build_squad_region_choices(units, regions, None, 'Nc')


class Checks(unittest.TestCase):
    def setUp(self):
        self.state, self.game, self.clock = State(), Game(), Clock()
        self.c = HumanSquadController(self.state, {'model': 'jev', 'timeout': 10, 'max_requests': 100, 'soldier_agents': False},
                                     self.game, 'green', wall_clock=self.clock)

    def tearDown(self):
        self.c.stop()
        for request in self.game.requests:
            if not request['future'].done():
                request['future'].set_exception(RuntimeError('test-end'))

    def pump(self, condition, message='condition not reached'):
        for _ in range(150):
            self.c.tick()
            if condition():
                return
            time.sleep(.001)
        self.fail(message)

    def start_executor(self):
        self.pump(lambda: len(self.game.requests) == 1)
        self.game.requests[0]['future'].set_result(answer_plan())
        self.pump(lambda: len(self.game.requests) == 2)
        return self.game.requests[1]

    def accepted_order(self):
        request = self.start_executor()
        request['future'].set_result(answer_intent())
        self.pump(lambda: len(self.state.commands) == 1)
        self.state.results['command-1'] = {'id': 'command-1', 'accepted': True, 'message': 'squad_started'}
        command = self.state.commands[-1]
        self.state.state['squad_behavior']['squads']['green-squad'] = dict(order_id=command['order_id'],
            goal=command['position'], intent=command['intent'], radius=command['radius'], phase='advancing')
        self.c.tick()

    def event(self, seq, kind, **extra):
        self.state.state['squad_behavior']['events'].append(dict(seq=seq, kind=kind, faction='green', squad_id='', **extra))

    def test_new_stage_removes_old_destinations_but_preserves_entry_navigation(self):
        self.c.world = world()
        self.c.world['world_growth'] = dict(enabled=True, revision=2,
                                           mission=dict(left=.5, status='active'))
        members = self.c._members(self.c.world)
        self.c._load_regions(members)
        regions, issue = self.c._eligible_regions(members)
        self.assertFalse(issue)
        self.assertEqual(set(regions), {'Nc'})
        self.assertIn('Na', self.c.regions)  # Transit geometry, not a destination.
        choices = build_squad_region_choices(members, self.c.regions, self.c.topology,
            'Nc', destination_ids=self.c._active_destination_ids())
        for options in choices.values():
            self.assertTrue(options)
            self.assertTrue(all(row['region_id'] == 'Nc' for row in options.values()))
            self.assertTrue(any('Na' in row['region_path'] for row in options.values()))
        self.c.world['world_growth']['mission']['left'] = .8
        self.assertNotIn('Nc', self.c._active_destination_ids())
        self.assertEqual(self.c._eligible_regions(members)[0], {})

    def test_new_generated_stage_restarts_planning_without_old_target_or_cooldown(self):
        current = self.state.state
        current['world_growth'] = dict(enabled=True, revision=1, phase='encounter', mission=dict(status='active'))
        self.pump(lambda: len(self.game.requests) == 1)
        self.c.plan = dict(region_id='Nc', position=[.7, 0.], radius=.1, stage='hold',
                           objective='等待 red-old', review_after_s=20.)
        self.c.next_wall['commander'] = self.clock.now + 60.
        current['units'].append(dict(id='red-old', faction='red', hp=0, position=[.6, 0.]))
        current['squad_behavior']['perception']['green']['contacts'] = [
            dict(id='red-old', position=[.6, 0.], visible=False, last_seen=0.)]
        current['world_growth']['revision'] = 2
        current['navigation_revision'] = 2
        current['strategic_topology']['revision'] = 2
        self.game.requests[0]['future'].set_result(answer_plan())
        self.c.tick()
        self.assertEqual(self.c.plan, {})
        self.assertEqual(self.c.next_wall['commander'], 0.)
        self.assertEqual(self.c._context(self.c._members(self.c.world))['contacts'], [])
        self.pump(lambda: len(self.game.requests) >= 2)
        self.assertEqual(self.game.requests[-1]['state']['current_plan'], {})
        self.assertEqual(self.game.requests[-1]['state']['contacts'], [])

    def test_clear_stage_reached_waypoint_offers_forward_neighbour(self):
        current = self.state.state
        current['task_mode'] = 'clear_exit'
        current['world_growth'] = dict(enabled=True, revision=2, phase='encounter',
                                       mission=dict(status='active', target=[1., 0.]))
        self.c.world = current
        self.c.regions = {
            'Na': dict(center=[0., 0.], radius=.1, neighbors=['Nb']),
            'Nb': dict(center=[.3, 0.], radius=.1, neighbors=['Na', 'Nc', 'Ns']),
            'Nc': dict(center=[.7, 0.], radius=.1, neighbors=['Nb']),
            'Ns': dict(center=[.3, .2], radius=.1, neighbors=['Nb']),
        }
        self.c.plan = dict(region_id='Nb', position=[.3, 0.], radius=.1,
                           stage='approach', objective='中间区域', review_after_s=20.)
        self.c.arrived_at = 0.
        self.c._launch('commander', self.c._members(current), self.c.regions)
        for _ in range(100):
            if self.game.requests:
                break
            time.sleep(.001)
        self.assertEqual(len(self.game.requests), 1)
        context = self.game.requests[0]['state']
        self.assertEqual(set(context['regions']), {'Nc'})
        self.assertEqual(context['generated_stage']['target'], [1., 0.])

    def test_clear_exit_commander_receives_no_flag_objective(self):
        self.state.state['task_mode'] = 'clear_exit'
        self.pump(lambda: len(self.game.requests) == 1)
        request = self.game.requests[0]
        self.assertIn('清除本段全部守军', request['state']['mission'])
        self.assertNotIn('守住旗圈', request['state']['mission'])
        self.assertEqual(request['state']['objective'], {})
        self.assertIn('无尽推进没有占旗任务', request['questions']['plan']['instructions'])
        self.assertNotIn('持续主任务是进入旗圈', request['questions']['plan']['instructions'])

    def test_same_failed_cover_does_not_rewake_both_models(self):
        self.c.world = self.state.state
        self.c._wake('cover_destroyed', dict(unit_id='green-1', cover_id='cover-a'))
        original = self.c.revision.copy()
        self.state.state['time'] = 2.
        self.c._wake('cover_destroyed', dict(unit_id='green-1', cover_id='cover-a'))
        self.assertEqual(self.c.revision, original)
        self.c._wake('cover_destroyed', dict(unit_id='green-1', cover_id='cover-b'))
        self.assertGreater(self.c.revision['executor'], original['executor'])
        self.assertGreater(self.c.revision['commander'], original['commander'])

    def test_local_protection_failure_wakes_commander_without_discarding_inflight_plan(self):
        self.c.world = self.state.state
        commander_token = self.c.critical['commander']
        executor_token = self.c.critical['executor']
        commander_revision = self.c.revision['commander']
        self.c._wake('path_blocked', dict(unit_id='green-2', reason='no_reachable_protection'))
        self.assertEqual(self.c.critical['commander'], commander_token)
        self.assertEqual(self.c.critical['executor'], executor_token + 1)
        self.assertGreater(self.c.revision['commander'], commander_revision)

    def test_leaving_exposed_old_cover_does_not_wake_models(self):
        self.c.world = self.state.state
        self.c._member_ids = ('green-1', 'green-2')
        self.c._navigation_revision = self.state.state['navigation_revision']
        members = self.state.state['units'][:2]
        self.event(1, 'cover_invalidated', unit_id='green-1', cover_id='cover-a', reason='flanked')
        self.c._observe(members)
        self.assertEqual(self.c.revision['executor'], 0)
        self.assertEqual(self.c.revision['commander'], 0)
        self.state.state['time'] = 1.
        self.event(2, 'cover_invalidated', unit_id='green-1', cover_id='cover-a', reason='flanked')
        self.c._observe(members)
        self.assertEqual(self.c.revision['executor'], 0)
        self.event(3, 'cover_invalidated', unit_id='green-1', cover_id='cover-b', reason='destroyed')
        self.c._observe(members)
        self.assertEqual(self.c.revision['executor'], 1)
        self.assertEqual(self.c.revision['commander'], 1)
        self.assertEqual(self.c.events[-1]['kind'], 'cover_destroyed')

    def test_roles_region_ownership_and_real_receipt(self):
        request = self.start_executor()
        self.assertEqual(self.game.requests[0]['role'], 'commander')
        self.assertIsNone(request['role'])
        self.assertNotIn('regions', request['state'])
        self.assertEqual(list(request['questions']), ['intent', 'flank_mover', 'flank_fire_base', 'role_green-1', 'route_green-1', 'role_green-2', 'route_green-2'])
        # A provider cannot smuggle a different region/position through an intent answer.
        request['future'].set_result(answer_intent(region_id='Nd', position=[3, 0]))
        self.pump(lambda: len(self.state.commands) == 1)
        command = self.state.commands[0]
        self.assertEqual(command['position'], [.7, 0.])
        self.assertEqual(command['unit_ids'], ['green-1', 'green-2'])
        self.assertEqual(command['control_epoch'], 3)
        self.assertEqual(self.c.accepted_orders, 0)  # 202 is not execution evidence.
        self.state.results['command-1'] = {'accepted': True}
        self.c.tick()
        self.assertEqual(self.c.accepted_orders, 1)
        self.assertTrue(any(r['type'] == 'human-engine-receipt' for r in self.game.records))

    def test_non_flank_intent_can_leave_member_pair_unused_without_extra_call(self):
        request = self.start_executor()
        for key in ('flank_mover', 'flank_fire_base'):
            self.assertIn('not_applicable', request['questions'][key]['criteria'])
        result = answer_intent('advance')
        result['answers'].update({
            'flank_mover': {'choice': 'not_applicable'},
            'flank_fire_base': {'choice': 'not_applicable'},
            'role_green-1': {'choice': 'establish_fire'},
            'role_green-2': {'choice': 'maneuver'},
            'route_green-1': {'choice': 'P1'},
            'route_green-2': {'choice': 'P1'},
        })
        request['future'].set_result(result)
        self.pump(lambda: bool(self.state.commands))
        self.assertEqual(len(self.game.requests), 2)  # Commander + one squad call.
        command = self.state.commands[0]
        self.assertEqual(command['intent'], 'advance')
        self.assertEqual(command['assignments']['green-1']['role'], 'establish_fire')
        self.assertEqual(command['assignments']['green-2']['role'], 'maneuver')
        self.assertFalse(any(row['type'] == 'human-flank-selection-audit' for row in self.game.records))

    def test_commander_and_squad_receive_loaded_rounds_and_live_magazine_capacity(self):
        self.state.state['units'][0].update(weapon='rifle', ammo=7, reload_remaining=0.)
        self.state.state['units'][1].update(weapon='smg', ammo=6, reload_remaining=1.2)
        self.state.state['weapons'] = {
            'rifle': {'magazine': 8, 'reload': 2.},
            'smg': {'magazine': 24, 'reload': 2.5},
        }
        request = self.start_executor()
        for context in (self.game.requests[0]['state'], request['state']):
            self.assertEqual(context['ammunition_rules']['ammo_field'], 'current_magazine_rounds')
            self.assertEqual(context['ammunition_rules']['reserve'], 'unlimited')
            self.assertEqual(context['ammunition_rules']['reload_result'], 'refill_magazine')
            members = {row['id']: row for row in context['members']}
            self.assertEqual((members['green-1']['ammo'], members['green-1']['magazine_capacity']), (7, 8))
            self.assertEqual((members['green-2']['ammo'], members['green-2']['magazine_capacity']), (6, 24))
            self.assertEqual(members['green-2']['reload_remaining'], 1.2)
            self.assertEqual(members['green-2']['reload_duration_s'], 2.5)
        self.assertNotIn('magazine_capacity', self.state.state['units'][0])

    def test_missing_weapon_configuration_does_not_invent_magazine_capacity(self):
        self.state.state['units'][0].update(weapon='custom', ammo=7)
        request = self.start_executor()
        unit = request['state']['members'][0]
        self.assertEqual(unit['ammo'], 7)
        self.assertNotIn('magazine_capacity', unit)
        self.assertNotIn('reload_duration_s', unit)

    def test_commander_view_drops_agent_history_but_keeps_planning_evidence(self):
        self.pump(lambda: len(self.game.requests) == 1)
        request = self.game.requests[0]
        model = request['state']
        full = self.c.slots['commander']['context']
        self.assertIn('regions', model)
        self.assertIn('execution_evidence', model)
        self.assertIn('ammunition_rules', model)
        self.assertLess(len(json.dumps(model, ensure_ascii=False)),
                        len(json.dumps(full, ensure_ascii=False)))
        self.assertNotIn('soldier_reports', model)
        self.assertNotIn('assignments', model.get('engine_squad', {}))
        if full.get('engine_squad', {}).get('duties'):
            self.assertIn('duties', model.get('engine_squad', {}))

    def test_team_roles_repair_circular_wait_and_reach_command(self):
        self.state.state['units'][0].update(weapon='rifle',weapon_range=1.15)
        self.state.state['units'][1].update(weapon='smg',weapon_range=.9)
        request = self.start_executor()
        result = answer_intent()
        result['answers'].update({'role_green-1': {'choice': 'maneuver'}, 'role_green-2': {'choice': 'maneuver'}})
        request['future'].set_result(result)
        self.pump(lambda: bool(self.state.commands))
        assignments = self.state.commands[-1]['assignments']
        self.assertEqual((assignments['green-1']['role'], assignments['green-1']['source']), ('establish_fire','dependency_repair'))
        self.assertEqual((assignments['green-2']['role'], assignments['green-2']['source']), ('maneuver','jev'))
        self.assertEqual(assignments['green-1']['region_id'], 'Nc')
        self.assertEqual(assignments['green-2']['region_path'], ['Na', 'Nc'])

    def test_team_roles_repair_all_fire_without_removing_last_supporter(self):
        self.state.state['units'][0].update(weapon='rifle', weapon_range=1.15)
        self.state.state['units'][1].update(weapon='smg', weapon_range=.9)
        request = self.start_executor()
        result = answer_intent()
        result['answers'].update({'role_green-1': {'choice': 'establish_fire'},
                                  'role_green-2': {'choice': 'establish_fire'}})
        request['future'].set_result(result)
        self.pump(lambda: bool(self.state.commands))
        assignments = self.state.commands[-1]['assignments']
        self.assertEqual(assignments['green-1']['role'], 'establish_fire')
        self.assertEqual((assignments['green-2']['role'], assignments['green-2']['source']), ('maneuver', 'dependency_repair'))
        self.assertEqual(assignments['green-2']['region_id'], 'Nc')

    def test_jev_can_assign_different_member_regions_and_paths(self):
        request = self.start_executor()
        choices = request['questions']['route_green-1']['criteria']
        flank = next(key for key, label in choices.items() if '目标邻区' in label)
        result = answer_intent('advance')
        result['answers']['route_green-1'] = {'choice': flank}
        result['answers']['route_green-2'] = {'choice': 'P1'}
        request['future'].set_result(result)
        self.pump(lambda: bool(self.state.commands))
        rows = self.state.commands[-1]['assignments']
        self.assertNotEqual(rows['green-1']['region_id'], rows['green-2']['region_id'])
        self.assertNotEqual(rows['green-1']['position'], rows['green-2']['position'])
        self.assertEqual(rows['green-1']['route_positions'][-1], rows['green-1']['position'])

    def test_same_region_menu_exposes_member_specific_native_endpoints(self):
        regions = {
            'S': dict(center=[0., 0.], radius=.1, neighbors=['G'],
                      cells=[[0., 0.], [.075, 0.], [0., .075]]),
            'G': dict(center=[.45, 0.], radius=.1, neighbors=['S'],
                      cells=[[.375, 0.], [.45, 0.], [.375, .075], [.45, .075]]),
        }
        topology = dict(cells={
            's0': [0., 0.], 's1': [.075, 0.], 'g0': [.375, 0.],
            'g1': [.45, 0.], 'g2': [.375, .075], 'g3': [.45, .075]},
            edges=[['s0', 's1'], ['s1', 'g0'], ['g0', 'g1'], ['g0', 'g2'], ['g2', 'g3']])
        units = [dict(id='green-1', position=[0., 0.]),
                 dict(id='green-2', position=[.075, 0.])]
        choices = build_squad_region_choices(units, regions, topology, 'G')
        p1 = choices['green-1']['P1']
        p2 = choices['green-2']['P1']
        self.assertEqual((p1['region_id'], p2['region_id']), ('G', 'G'))
        self.assertNotEqual(p1['position'], p2['position'])
        self.assertEqual(p1['route_positions'][-1], p1['position'])
        self.assertEqual(p2['route_positions'][-1], p2['position'])
        self.assertEqual(p1['endpoint_basis'], 'native_region_cell')
        self.assertNotEqual(p1['endpoint_id'], p2['endpoint_id'])

    def test_side_neighbor_route_does_not_pass_through_goal_first(self):
        options = side_route_options(self.state.state['units'][:2])
        for routes in options.values():
            for row in routes.values():
                if row['region_id'] != 'Nc':
                    self.assertNotIn('Nc', row['region_path'][:-1])

    def test_long_backtracking_loop_is_not_offered_as_flank(self):
        regions = {
            'start': dict(center=[0., 0.], radius=.1, neighbors=['front', 'rear']),
            'front': dict(center=[.3, 0.], radius=.1, neighbors=['start', 'goal']),
            'goal': dict(center=[.6, 0.], radius=.1, neighbors=['front', 'side']),
            'rear': dict(center=[-.6, .5], radius=.1, neighbors=['start', 'side']),
            'side': dict(center=[.6, .5], radius=.1, neighbors=['rear', 'goal']),
        }
        options = build_squad_region_choices([{'id': 'green-1', 'position': [0., 0.]}],
                                             regions, None, 'goal')['green-1']
        self.assertTrue(any(row['region_path'] == ['start', 'front', 'goal']
                            for row in options.values()))
        self.assertFalse(any('rear' in row['region_path'] for row in options.values()))

    def test_known_contact_filters_rearward_lateral_approach(self):
        regions = {
            'start': dict(center=[0., 0.], radius=.1, neighbors=['goal', 'rear']),
            'goal': dict(center=[.6, 0.], radius=.1, neighbors=['start', 'rear']),
            'rear': dict(center=[-.5, 0.], radius=.1, neighbors=['start', 'goal']),
        }
        units = [dict(id='green-1', position=[0., 0.], weapon_range=.8)]
        contacts = [dict(id='red-known', position=[.8, 0.], visible=True)]
        options = build_squad_region_choices(units, regions, None, 'goal', contacts=contacts, now=10.)['green-1']
        self.assertTrue(any(row['region_id'] == 'goal' for row in options.values()))
        self.assertFalse(any(row['region_id'] == 'rear' or 'rear' in row['region_path'] for row in options.values()))

    def test_contact_evidence_reports_gain_and_range_without_changing_routes(self):
        regions = {
            'start': dict(center=[0., 0.], radius=.1, neighbors=['goal']),
            'goal': dict(center=[.7, 0.], radius=.1, neighbors=['start']),
        }
        units = [dict(id='green-1', position=[0., 0.], weapon_range=.5)]
        plain = build_squad_region_choices(units, regions, None, 'goal')
        self.assertTrue(all(row['contact_approach'] is None for row in plain['green-1'].values()))
        contacts = [dict(id='red-known', position=[1., 0.], visible=False, last_seen=8.)]
        enriched = build_squad_region_choices(units, regions, None, 'goal', contacts=contacts, now=10.)
        fact = enriched['green-1']['P1']['contact_approach']
        self.assertEqual(fact['target_id'], 'red-known')
        self.assertFalse(fact['visible'])
        self.assertEqual(fact['age_s'], 2.)
        self.assertEqual(fact['destination_distance'], .3)
        self.assertEqual(fact['distance_gain'], .7)
        self.assertTrue(fact['in_weapon_range'])
        self.assertEqual(fact['firing_line'], 'unverified')
        for key, row in plain['green-1'].items():
            self.assertEqual({k: v for k, v in row.items() if k != 'contact_approach'},
                             {k: v for k, v in enriched['green-1'][key].items() if k != 'contact_approach'})
        behind = build_squad_region_choices(units, regions, None, 'goal',
            contacts=[dict(id='red-behind', position=[-.4, 0.], visible=True)], now=10.)
        self.assertEqual(set(behind['green-1']), set(plain['green-1']))
        self.assertEqual(behind['green-1']['P1']['contact_approach']['distance_gain'], -.7)
        self.assertFalse(behind['green-1']['P1']['contact_approach']['in_weapon_range'])

    def test_fire_support_can_choose_current_line_when_commander_goal_is_too_close(self):
        regions = {
            'start': dict(center=[.2, 0.], radius=.1, neighbors=['mid']),
            'mid': dict(center=[.45, 0.], radius=.1, neighbors=['start', 'goal']),
            'goal': dict(center=[.7, 0.], radius=.1, neighbors=['mid']),
        }
        contacts = [dict(id='red-known', position=[1., 0.], visible=True)]
        support = dict(id='green-rocket', position=[.2, 0.], weapon_range=.92,
                       position_role='fire_support')
        options = build_squad_region_choices([support], regions, None, 'goal',
                                             contacts=contacts, now=10.)[support['id']]
        by_region = {row['region_id']: row for row in options.values()}
        self.assertEqual(by_region['start']['contact_approach']['range_fit'], 'preferred')
        self.assertEqual(by_region['goal']['contact_approach']['range_fit'], 'too_close')
        self.assertEqual(by_region['start']['contact_approach']['firing_line'], 'unverified')
        ordinary = build_squad_region_choices([dict(support, position_role='maneuver')],
                                              regions, None, 'goal')[support['id']]
        self.assertFalse(any(row['region_id'] == 'start' for row in ordinary.values()))

    def test_route_exposes_infantry_screen_relative_to_known_tank_target(self):
        regions = {
            'start': dict(center=[.2, 0.], radius=.1, neighbors=['mid']),
            'mid': dict(center=[.45, 0.], radius=.1, neighbors=['start', 'goal']),
            'goal': dict(center=[.7, 0.], radius=.1, neighbors=['mid']),
        }
        rifle = dict(id='green-rifle', position=[.2, 0.], weapon_range=.55,
                     position_role='establish_fire')
        tank = dict(id='green-tank', position=[.2, 0.],
                    engagement_position={'target_id': 'red-known'})
        contacts = [dict(id='red-known', position=[1., 0.], visible=True)]
        options = build_squad_region_choices([rifle], regions, None, 'goal',
            contacts=contacts, support_assets=[tank])['green-rifle']
        by_region = {row['region_id']: row for row in options.values()}
        self.assertEqual(by_region['goal']['support_screen']['position'], 'ahead')
        self.assertEqual(by_region['goal']['support_screen']['ahead_by'], .5)
        self.assertEqual(by_region['goal']['support_screen']['target_id'], 'red-known')
        hidden = build_squad_region_choices([rifle], regions, None, 'goal',
            contacts=[], support_assets=[tank])['green-rifle']
        self.assertIsNone(next(iter(hidden.values()))['support_screen'])

    def test_executor_receives_tank_and_screening_route_evidence(self):
        self.state.state['units'].append(dict(id='green-tank', faction='green',
            kind='tank', weapon='cannon', hp=240, position=[.2, 0.],
            combat={'engagement_position': {'target_id': 'red-known', 'status': 'ready'}}))
        self.state.state['squad_behavior']['perception']['green']['contacts'] = [
            dict(id='red-known', position=[1., 0.], visible=True, last_seen=0.)]
        request = self.start_executor()
        self.assertEqual(request['state']['support_assets'][0]['id'], 'green-tank')
        routes = request['state']['member_region_choices']['green-1']
        self.assertTrue(any(row.get('support_screen', {}).get('asset_id') == 'green-tank'
                            for row in routes.values()))
        self.assertTrue(any('相对载具=' in row for row in request['questions']['route_green-1']['criteria'].values()))

    def test_squad_route_evidence_uses_filtered_contacts_not_hidden_enemies(self):
        self.state.state['time'] = 8.
        self.state.state['units'][0]['weapon_range'] = .5
        self.state.state['squad_behavior']['perception']['green']['contacts'] = [
            dict(id='red-known', position=[1., 0.], visible=True, last_seen=8.),
            dict(id='red-stale', position=[.01, 0.], visible=False, last_seen=0.),
        ]
        request = self.start_executor()
        fact = request['state']['member_region_choices']['green-1']['P1']['contact_approach']
        self.assertEqual(fact['target_id'], 'red-known')
        self.assertTrue(fact['visible'])
        self.assertEqual(fact['age_s'], 0.)
        self.assertEqual(fact['distance_gain'], .7)
        label = request['questions']['route_green-1']['criteria']['P1']
        self.assertIn('接近 0.700', label)
        self.assertIn('几何射程内', label)
        self.assertIn('射线未验证', label)
        self.assertNotIn('red-hidden', str(request['state']['member_region_choices']))
        self.assertNotIn('red-stale', str(request['state']['member_region_choices']))

    def test_mock_clear_mode_uses_stage_direction_instead_of_spawn(self):
        self.c.world = dict(self.state.state, world_growth={
            'enabled': True, 'mission': {'target': [1., 0.]}})
        request = dict(role='commander', serial=1, context={
            'objective': {}, 'members': [{'position': [0., 0.]}],
            'current_plan': {}}, regions={
                'rear': {'center': [0., 0.]}, 'forward': {'center': [.8, 0.]}})
        answer = self.c._baseline(request)['answers']['plan']['value']
        self.assertEqual(answer['region_id'], 'forward')
        self.assertEqual(answer['stage'], 'approach')

    def test_same_route_flank_executes_and_records_quality_gap(self):
        options = side_route_options(self.state.state['units'][:2])
        self.assertTrue(any(row['flankable'] and row['region_id'] == 'Nc'
                            for row in options['green-2'].values()))
        with patch('human_squad.build_squad_region_choices', return_value=options):
            request = self.start_executor()
        self.assertIn('flank', request['questions']['intent']['criteria'])
        result = answer_intent('flank')
        result['answers'].update({'role_green-1': {'choice': 'establish_fire'},
                                  'role_green-2': {'choice': 'maneuver'},
                                  'flank_mover': {'choice': 'green-2'},
                                  'flank_fire_base': {'choice': 'green-1'},
                                  'route_green-1': {'choice': 'P1'},
                                  'route_green-2': {'choice': 'P1'}})
        request['future'].set_result(result)
        self.pump(lambda: bool(self.state.commands))
        command = self.state.commands[0]
        self.assertEqual(command['intent'], 'flank')
        self.assertEqual(command['assignments']['green-1']['region_path'], ['Na', 'Nb', 'Nc'])
        self.assertEqual(command['assignments']['green-2']['region_path'], ['Na', 'Nb', 'Nc'])
        self.assertEqual(command['assignments']['green-2']['role'], 'maneuver')
        self.assertEqual(command['assignments']['green-1']['role'], 'establish_fire')
        self.assertEqual(command['assignments']['green-2']['source'], 'jev_flank_member')
        self.assertEqual(command['assignments']['green-2']['route_source'], 'jev')
        audit = next(row for row in self.game.records if row['type'] == 'human-flank-selection-audit')
        self.assertFalse(audit['region_paths_split'])
        self.assertTrue(audit['diagnostic_only'])
        self.assertFalse(any(row['type'] == 'human-model-failed' for row in self.game.records))
        self.assertFalse(any(row['type'] == 'human-flank-route-repaired' for row in self.game.records))

    def test_flank_without_side_candidate_still_executes(self):
        request = self.start_executor()
        self.assertFalse(request['state']['flank_path_feasibility']['split_candidate_available'])
        self.assertIn('flank', request['questions']['intent']['criteria'])
        result = answer_intent('flank')
        result['answers'].update({'flank_mover': {'choice': 'green-2'},
                                  'flank_fire_base': {'choice': 'green-1'},
                                  'route_green-1': {'choice': 'P1'},
                                  'route_green-2': {'choice': 'P1'}})
        request['future'].set_result(result)
        self.pump(lambda: bool(self.state.commands))
        self.assertEqual(self.state.commands[0]['intent'], 'flank')
        self.assertFalse(next(row for row in self.game.records
                              if row['type'] == 'human-flank-selection-audit')['region_paths_split'])

    def test_jev_selects_member_and_neighbor_region_for_flank(self):
        options = side_route_options(self.state.state['units'][:2])
        with patch('human_squad.build_squad_region_choices', return_value=options):
            request = self.start_executor()
        side_key = next(key for key, row in options['green-2'].items()
                        if row['flankable'] and row['region_id'] == 'Ns')
        result = answer_intent('flank')
        result['answers'].update({'flank_mover': {'choice': 'green-2'},
                                  'flank_fire_base': {'choice': 'green-1'},
                                  'route_green-1': {'choice': 'P1'},
                                  'route_green-2': {'choice': side_key}})
        request['future'].set_result(result)
        self.pump(lambda: bool(self.state.commands))
        command = self.state.commands[0]
        self.assertEqual(command['intent'], 'flank')
        self.assertEqual(command['assignments']['green-2']['region_id'], 'Ns')
        self.assertEqual(command['assignments']['green-2']['role'], 'maneuver')
        self.assertEqual(command['assignments']['green-1']['role'], 'establish_fire')
        self.assertEqual(command['assignments']['green-2']['route_id'], side_key)

    def test_two_unsplit_flank_selections_stay_available_and_execute(self):
        options = side_route_options(self.state.state['units'][:2])
        with patch('human_squad.build_squad_region_choices', return_value=options):
            request = self.start_executor()
        result = answer_intent('flank')
        result['answers'].update({'role_green-1': {'choice': 'establish_fire'},
                                  'role_green-2': {'choice': 'maneuver'},
                                  'flank_mover': {'choice': 'green-2'},
                                  'flank_fire_base': {'choice': 'green-1'},
                                  'route_green-1': {'choice': 'P2'},
                                  'route_green-2': {'choice': 'P2'}})
        request['future'].set_result(result)
        self.pump(lambda: bool(self.state.commands))
        self.assertEqual(self.state.commands[0]['assignments']['green-2']['region_path'], ['Na', 'Nb', 'Ns', 'Nc'])
        self.state.results['command-1'] = {'id': 'command-1', 'accepted': True, 'message': 'squad_started'}
        command = self.state.commands[0]
        self.state.state['squad_behavior']['squads']['green-squad'] = dict(
            order_id=command['order_id'], goal=command['position'], intent=command['intent'],
            radius=command['radius'], phase='advancing')
        self.c.tick()
        self.clock.now += 3
        self.state.state['time'] = 5.1
        with patch('human_squad.build_squad_region_choices', return_value=options):
            self.pump(lambda: len(self.game.requests) == 3)
        self.assertIn('flank', self.game.requests[-1]['questions']['intent']['criteria'])

    def test_continue_flank_with_unused_pair_keeps_members_after_route_ids_change(self):
        options = side_route_options(self.state.state['units'][:2])
        with patch('human_squad.build_squad_region_choices', return_value=options):
            request = self.start_executor()
        side_key = next(key for key, row in options['green-2'].items()
                        if row['flankable'] and row['region_id'] == 'Ns')
        result = answer_intent('flank')
        result['answers'].update({
            'flank_mover': {'choice': 'green-2'},
            'flank_fire_base': {'choice': 'green-1'},
            'route_green-1': {'choice': 'P1'},
            'route_green-2': {'choice': side_key},
        })
        request['future'].set_result(result)
        self.pump(lambda: bool(self.state.commands))
        command = copy.deepcopy(self.state.commands[0])
        self.state.results['command-1'] = {'accepted': True, 'message': 'squad_started'}
        self.state.state['squad_behavior']['squads']['green-squad'] = dict(
            order_id=command['order_id'], goal=command['position'], intent='flank',
            radius=command['radius'], phase='advancing')
        self.c.tick()
        self.clock.now += 3
        self.state.state['time'] = 5.1
        # Stable geometry with entirely new per-request labels: the accepted
        # named pair must not depend on looking up yesterday's P1/P2.
        renamed = {uid: {'Q' + str(i): row for i, row in enumerate(routes.values())}
                   for uid, routes in options.items()}
        with patch('human_squad.build_squad_region_choices', return_value=renamed):
            self.pump(lambda: len(self.game.requests) == 3)
        continued = answer_intent('continue_order')
        continued['answers'].update({
            'flank_mover': {'choice': 'not_applicable'},
            'flank_fire_base': {'choice': 'not_applicable'},
        })
        self.game.requests[-1]['future'].set_result(continued)
        self.pump(lambda: self.c.kept_orders > 0)
        self.assertEqual(len(self.state.commands), 1)
        self.assertEqual(self.c.last_order['assignments'], command['assignments'])
        audit = [row for row in self.game.records if row['type'] == 'human-flank-selection-audit'][-1]
        self.assertEqual((audit['mover_id'], audit['fire_base_id']), ('green-2', 'green-1'))
        self.assertTrue(audit['named_pair'])
        self.assertTrue(audit['region_paths_split'])

    def test_continue_with_new_roles_updates_engine_assignment(self):
        self.accepted_order()
        self.state.state['time'] = 5.1
        self.clock.now += 2
        self.pump(lambda: len(self.game.requests) == 3)
        result = answer_intent('continue_order')
        result['answers'].update({'role_green-1': {'choice':'establish_fire'}, 'role_green-2': {'choice':'maneuver'}})
        self.game.requests[-1]['future'].set_result(result)
        self.pump(lambda: len(self.state.commands) == 2)
        self.assertEqual(self.state.commands[-1]['assignments']['green-1']['role'], 'establish_fire')
        self.assertEqual(self.state.commands[-1]['intent'], self.state.commands[0]['intent'])

    def test_squad_request_does_not_choose_soldier_emotions(self):
        request = self.start_executor()
        result = answer_intent()
        result['answers']['emotion_green-1'] = dict(type='choice', choice='afraid', confidence=.001)
        result['answers']['emotion_green-2'] = dict(type='choice', choice='alert', confidence=.001)
        request['future'].set_result(result)
        self.pump(lambda: len(self.state.commands) == 1)
        self.assertNotIn('emotion_green-1', request['questions'])
        self.assertEqual([c['action'] for c in self.state.commands], ['squad_order'])
        self.assertTrue(self.c.pending_commands)

    def test_invalid_emotion_does_not_block_valid_movement(self):
        request = self.start_executor()
        result = answer_intent()
        result['answers']['emotion_green-1'] = dict(type='choice', choice='invincible')
        request['future'].set_result(result)
        self.pump(lambda: len(self.state.commands) == 1)
        self.assertEqual(self.state.commands[0]['action'], 'squad_order')
        self.assertFalse(any(command['action'] == 'unit_emotion'
                             for command in self.state.commands))

    def test_squad_routes_are_offered_per_member_regardless_of_health(self):
        self.state.state['units'][0].update(hp=35, max_hp=100, suppression=.6)
        self.state.state['units'][1].update(max_hp=100, suppression=0)
        request = self.start_executor()
        self.assertTrue(request['questions']['route_green-1']['criteria'])
        self.assertTrue(request['questions']['route_green-2']['criteria'])

    def test_extra_emotion_answer_is_ignored_by_squad_layer(self):
        request = self.start_executor()
        result = answer_intent()
        result['answers']['emotion_green-1'] = dict(type='choice', choice='happy')
        request['future'].set_result(result)
        self.pump(lambda: len(self.state.commands) == 1)
        self.assertEqual(self.state.commands[-1]['action'], 'squad_order')

    def test_flag_region_is_real_sample_inside_capture_circle(self):
        self.state.state['objective'].update(radius=.17)
        self.c.tick()
        region = self.c.regions['objective_flag']
        self.assertEqual(region['center'], [.7, 0.])
        self.assertIn('Nc', region['neighbors'])
        selected = validate_plan(plan('objective_flag'), self.c.regions)
        self.assertLess(selected['radius'], .17)

    def test_idle_wait_expires_but_actual_defense_and_danger_do_not(self):
        self.accepted_order()
        self.state.state['time'] = 40
        self.c.world = copy.deepcopy(self.state.state)
        self.c.stage_review_at = 20
        members = self.c._members(self.c.world)
        for history in self.c.unit_history.values():history['stationary_at'] = 0
        self.assertTrue(self.c._mission_status(members)['wait_expired'])
        self.c.world['objective']['flag'] = {'owner': 'green', 'held_seconds': 12}
        self.assertFalse(self.c._mission_status(members)['wait_expired'])
        self.c.world['objective']['flag']['owner'] = 'red'
        members[0]['suppression'] = .8
        self.assertFalse(self.c._mission_status(members)['wait_expired'])
        members[0]['suppression'] = 0
        members[0]['hp'] = 5
        self.assertTrue(self.c._mission_status(members)['wait_expired'])
        members[0]['survival_reason'] = 'incoming_fire'
        self.assertFalse(self.c._mission_status(members)['wait_expired'])
        members[0]['survival_reason'] = ''
        self.assertTrue(self.c._mission_status(members)['wait_expired'])

    def test_prolonged_pressure_replans_and_remembers_failed_region(self):
        self.accepted_order()
        self.c.plan['stage'] = 'engage'
        self.c.world = copy.deepcopy(self.state.state)
        self.c.world['time'] = 20
        self.c.region_started = 0
        members = self.c._members(self.c.world)
        members[0]['survival_reason'] = 'incoming_fire'
        self.c.unit_history[members[0]['id']]['pressure_since'] = 0
        self.c._update_progress(members)
        self.assertTrue(self.c._mission_status(members)['prolonged_pressure'])
        current = self.c.plan['region_id']
        regions = {current: dict(center=[0., 0.]), 'alternate': dict(center=[1., 1.])}
        self.c._launch('commander', members, regions)
        self.assertNotIn(current, self.c.slots['commander']['regions'])
        self.assertEqual(self.c.failed_regions[current]['until'], 50)
        members[0]['survival_reason'] = ''
        self.c.world['time'] = 21
        self.c._update_progress(members)
        self.assertFalse(self.c._mission_status(members)['prolonged_pressure'])
        self.c._launch('commander', members, regions)
        self.assertNotIn(current, self.c.slots['commander']['regions'])
        self.c.world['time'] = 51
        self.c._launch('commander', members, regions)
        self.assertIn(current, self.c.slots['commander']['regions'])

    def test_completed_intermediate_region_requires_next_region(self):
        self.accepted_order()
        self.c.world = copy.deepcopy(self.state.state)
        self.c.plan['stage'] = 'approach'
        self.c.arrived_at = 1
        members = self.c._members(self.c.world)
        self.assertTrue(self.c._mission_status(members)['intermediate_complete'])
        current = self.c.plan['region_id']
        self.c._launch('commander', members, {current: dict(center=[0., 0.]), 'objective_flag': dict(center=[1., 1.])})
        self.assertEqual(set(self.c.slots['commander']['regions']), {'objective_flag'})
        self.c.plan['region_id'] = 'objective_flag'
        self.assertFalse(self.c._mission_status(members)['intermediate_complete'])

    def test_completed_cover_returns_to_approach_choices(self):
        self.accepted_order()
        self.c.world = copy.deepcopy(self.state.state)
        self.c.plan['stage'] = 'approach'
        self.c.world['squad_behavior']['squads']['green-squad'].update(intent='cover', phase='cover_ready')
        self.c._launch('executor', self.c._members(self.c.world))
        choices = self.c.slots['executor']['choices']
        self.assertTrue({'advance', 'bound'} <= choices.keys())
        self.assertIn('flank', choices)  # The absent side route is diagnostic, not an action filter.
        self.assertFalse(self.c.slots['executor']['context']['flank_path_feasibility']['split_candidate_available'])
        self.assertFalse({'cover', 'hold', 'regroup', 'continue_order'} & choices.keys())

    def test_fire_and_cover_do_not_reset_approach_progress(self):
        self.accepted_order()
        self.c.world = copy.deepcopy(self.state.state)
        self.c.world['time'] = 100
        self.c.plan.update(stage='approach', position=[9., 9.], radius=.1)
        self.c.stage_review_at = 20
        members = self.c._members(self.c.world)
        for u in members:
            history = self.c.unit_history[u['id']]
            history.update(region_id=self.c.plan['region_id'], best_distance=0., approach_at=0)
            u.update(last_shot_at=100, in_cover=True)
        self.c._update_progress(members)
        self.assertTrue(self.c._mission_status(members)['approach_stalled'])
        self.assertTrue(all(h['approach_at'] == 0 for h in self.c.unit_history.values()))
        current = self.c.plan['region_id']
        regions = {current: dict(center=[9., 9.]), 'alternate': dict(center=[1., 1.])}
        self.c._launch('commander', members, regions)
        self.assertNotIn(current, self.c.slots['commander']['regions'])
        self.assertIn('alternate', self.c.slots['commander']['regions'])
        self.assertIn(current, regions)
        self.c.world['objective']['flag'] = {'owner': 'green'}
        self.assertFalse(self.c._mission_status(members)['approach_stalled'])

    def test_expired_wait_cannot_offer_endless_cover_or_continue(self):
        self.accepted_order()
        self.state.state['time'] = 40
        self.c.world = copy.deepcopy(self.state.state)
        self.c.stage_review_at = 20
        for history in self.c.unit_history.values():history['stationary_at'] = 0
        self.c._launch('executor', self.c._members(self.c.world))
        choices = self.c.slots['executor']['choices']
        self.assertNotIn('continue_order', choices)
        self.assertNotIn('hold', choices)
        self.assertNotIn('cover', choices)
        self.assertIn('advance', choices)

    def test_perception_has_only_visible_or_recent_positions_not_global_truth(self):
        self.state.state['time'] = 10.
        self.state.state['squad_behavior']['perception']['green']['contacts'] = [
            dict(id='red-hidden', position=[1., 0.], visible=False, last_seen=7.),
            dict(id='red-expired', position=[2., 0.], visible=False, last_seen=2.)]
        self.pump(lambda: bool(self.game.requests))
        context = self.game.requests[0]['state']
        self.assertEqual(context['contacts'], [dict(id='red-hidden', position=[1., 0.], visible=False, last_seen=7.)])
        self.assertNotIn('[9.0, 9.0]', json.dumps(context))
        self.assertNotIn('red-expired', json.dumps(context))

    def test_only_native_connected_regions_are_offered(self):
        self.pump(lambda: bool(self.game.requests))
        self.assertIn('Nc', self.game.requests[0]['state']['regions'])
        self.assertNotIn('Nd', self.game.requests[0]['state']['regions'])
        self.game.requests[0]['future'].set_result(answer_plan(plan('Nd')))
        self.pump(lambda: bool(self.c.error))
        self.assertEqual(self.state.commands, [])
        self.assertFalse(self.c.plan)

    def test_stale_native_geometry_waits_without_inventing_catalog(self):
        self.state.state['strategic_topology']['revision'] = 0
        self.c.tick()
        self.assertFalse(self.game.requests)
        self.assertEqual(self.c.feedback, 'unit_navigation_anchor_unresolved:green-1')

    def test_five_game_seconds_and_wall_cooldown_are_separate(self):
        self.accepted_order()
        self.state.state['time'] = 4.9
        self.clock.now += 100.
        self.c.tick()
        self.assertEqual(len(self.game.requests), 2)
        self.state.state['time'] = 5.
        self.pump(lambda: len(self.game.requests) == 3)
        self.assertIsNone(self.game.requests[-1]['role'])

    def test_same_selected_intent_keeps_persistent_order(self):
        self.accepted_order()
        self.clock.now += 2.
        self.state.state['time'] = 5.
        self.pump(lambda: len(self.game.requests) == 3)
        self.game.requests[-1]['future'].set_result(answer_intent())
        self.pump(lambda: self.c.kept_orders == 1)
        self.assertEqual(len(self.state.commands), 1)

    def test_same_region_changed_center_cannot_continue_old_engine_goal(self):
        self.accepted_order()
        self.c.plan['position'] = [.625, 0.]
        self.clock.now += 2.
        self.state.state['time'] = 5.
        self.pump(lambda: len(self.game.requests) == 3)
        self.assertNotIn('continue_order', self.game.requests[-1]['questions']['intent']['criteria'])
        self.game.requests[-1]['future'].set_result(answer_intent())
        self.pump(lambda: len(self.state.commands) == 2)
        self.assertEqual(self.state.commands[-1]['position'], [.625, 0.])

    def test_missing_or_blocked_engine_task_is_not_offered_as_valid_continue(self):
        self.accepted_order()
        self.state.state['squad_behavior']['squads']['green-squad']['phase'] = 'blocked'
        self.clock.now += 2.
        self.state.state['time'] = 5.
        self.pump(lambda: len(self.game.requests) == 3)
        self.assertNotIn('continue_order', self.game.requests[-1]['questions']['intent']['criteria'])

    def test_continue_reply_rechecks_actual_engine_task(self):
        self.accepted_order()
        self.clock.now += 2.
        self.state.state['time'] = 5.
        self.pump(lambda: len(self.game.requests) == 3)
        self.assertIn('continue_order', self.game.requests[-1]['questions']['intent']['criteria'])
        self.state.state['squad_behavior']['squads'].clear()
        self.game.requests[-1]['future'].set_result(answer_intent('continue_order'))
        self.pump(lambda: bool(self.c.error))
        self.assertEqual(self.c.kept_orders, 0)
        self.assertEqual(len(self.state.commands), 1)

    def test_stage_deadline_wakes_planner_without_forcing_movement(self):
        self.accepted_order()
        self.c.stage_review_at = 4.
        self.clock.now += 5.
        self.state.state['time'] = 4.
        self.pump(lambda: self.c.commander_calls == 2)
        request = next(r for r in reversed(self.game.requests) if r['role'] == 'commander')
        self.assertTrue(request['state']['stage_status']['review_due'])
        self.assertEqual(len(self.state.commands), 1)
        self.assertEqual([e['kind'] for e in self.c.events].count('stage_review_due'), 1)

    def test_rewording_same_region_does_not_hide_elapsed_stage_or_arrival(self):
        self.accepted_order()
        self.c.plan['stage'] = 'observe'
        self.c.arrived_at = 2.
        self.c.stage_review_at = 4.
        self.clock.now += 5.
        self.state.state['time'] = 4.
        self.pump(lambda: self.c.commander_calls == 2)
        request = next(r for r in reversed(self.game.requests) if r['role'] == 'commander')
        value = plan()
        value['objective'] = '换一种说法继续观察'
        value['stage'] = 'observe'
        request['future'].set_result(answer_plan(value))
        self.pump(lambda: self.c.region_renewals == 1)
        context = self.c._context(self.c._members(self.state.state))
        self.assertEqual(context['stage_status']['same_region_s'], 4.)
        self.assertEqual(context['stage_status']['elapsed_s'], 4.)
        self.assertEqual(context['stage_status']['arrived_at'], 2.)

    def test_approach_rewording_preserves_deadline_without_review_storm(self):
        self.accepted_order()
        original_version = self.c.version
        self.c.plan['stage'] = 'approach'
        self.c.stage_review_at = 4.
        self.clock.now += 5.
        self.state.state['time'] = 4.
        self.pump(lambda: self.c.commander_calls == 2)
        request = next(r for r in reversed(self.game.requests) if r['role'] == 'commander')
        value = plan()
        value.update(stage='approach', objective='继续接近，同一目标换个说法', review_after_s=12)
        request['future'].set_result(answer_plan(value))
        self.pump(lambda: self.c.region_renewals == 1)
        self.assertEqual(self.c.stage_review_at, 4.)
        self.assertEqual(self.c.version, original_version)
        for _ in range(5):
            self.c.tick()
        self.assertEqual([e['kind'] for e in self.c.events].count('stage_review_due'), 1)

    def test_completed_intermediate_region_cannot_be_approach_again(self):
        self.accepted_order()
        self.c.plan['stage'] = 'approach'
        self.c.arrived_at = 2.
        self.c.stage_review_at = 4.
        self.clock.now += 5.
        self.state.state['time'] = 4.
        self.pump(lambda: self.c.commander_calls == 2)
        request = next(r for r in reversed(self.game.requests) if r['role'] == 'commander')
        value = plan()
        value.update(stage='approach', objective='继续到已经到达的跳板')
        request['future'].set_result(answer_plan(value))
        self.pump(lambda: bool(self.c.error))
        self.assertTrue('intermediate_region_exhausted' in self.c.error or
                        'commander_region_not_in_native_catalog' in self.c.error)
        self.assertEqual(self.c.region_renewals, 0)

    def test_periodic_review_skips_progress_but_events_and_stalls_wake(self):
        self.accepted_order()
        self.c.world['time'] = 6.
        self.clock.now += 10.
        self.c.consumed['executor'] = self.c.revision['executor']
        self.c.next_at['executor'] = 5.
        for row in self.c.unit_history.values():
            row['progress_at'] = 5.
        self.assertFalse(self.c._due('executor'))
        self.c._wake('danger_close', dict(target_id='red-1'))
        self.assertTrue(self.c._due('executor'))
        self.c.consumed['executor'] = self.c.revision['executor']
        self.c.world['time'] = 12.
        self.assertTrue(self.c._due('executor'))

    def test_duplicate_blockage_coalesces_across_reasons_and_members(self):
        self.accepted_order()
        self.c.world['time'] = 2.
        self.c._wake('participation_gap', dict(unit_id='green-1', reason='muzzle_cover'))
        revision = self.c.revision['executor']
        self.c.world['time'] = 5.
        self.c._wake('participation_gap', dict(unit_id='green-1', reason='muzzle_cover'))
        self.assertEqual(self.c.revision['executor'], revision)
        self.c._wake('participation_gap', dict(unit_id='green-1', reason='no_safe_route'))
        self.c._wake('participation_gap', dict(unit_id='green-2', reason='no_effective_fire'))
        self.assertEqual(self.c.revision['executor'], revision)

    def test_coalesced_local_gap_still_escalates_on_measured_squad_stall(self):
        self.accepted_order()
        self.c.world['time'] = 2.
        self.c._wake('participation_gap', dict(unit_id='green-1', reason='muzzle_cover'))
        before = self.c.revision['commander']
        self.c.world['time'] = 6.
        self.c.unit_history['green-2']['progress_at'] = -7.
        self.c._wake('participation_gap', dict(unit_id='green-1', reason='no_effective_fire'))
        self.assertGreater(self.c.revision['commander'], before)

    def test_local_blockage_escalates_only_after_measured_stall(self):
        self.accepted_order()
        before = self.c.revision['commander']
        local = self.c.revision['executor']
        self.c.world['time'] = 2.
        self.c.unit_history['green-1']['progress_at'] = 0.
        self.c._wake('participation_gap', dict(unit_id='green-1', reason='muzzle_cover'))
        self.assertEqual(self.c.revision['commander'], before)
        self.assertGreater(self.c.revision['executor'], local)
        self.c.world['time'] = 14.
        self.c._wake('participation_gap', dict(unit_id='green-1', reason='muzzle_cover'))
        self.assertGreater(self.c.revision['commander'], before)

    def test_wounded_idle_member_still_triggers_participation_review(self):
        unit = self.state.state['units'][0]
        unit.update(hp=8, max_hp=30, weapon_range=.6, last_shot_at=-10)
        self.state.state['squad_behavior']['perception']['green']['contacts'] = [
            dict(id='red-visible', position=[.9, 0.], visible=True, last_seen=0.)]
        self.c.tick()
        self.state.state['time'] = 13.
        self.c.tick()
        row = self.c._context(self.c._members(self.state.state))['execution_evidence']['members']['green-1']
        self.assertTrue(row['wounded'])
        self.assertFalse(row['needs_recovery'])
        self.assertTrue(self.c.participation_notified)
        unit['survival_reason'] = 'incoming_fire'
        self.c.tick()
        row = self.c._context(self.c._members(self.state.state))['execution_evidence']['members']['green-1']
        self.assertTrue(row['needs_recovery'])

    def test_two_out_of_range_members_are_not_masked_by_one_firing_rocket(self):
        for u, distance in zip(self.state.state['units'][:2], [.7, .6]):
            u.update(weapon_range=distance, last_shot_at=-10, max_hp=100)
        self.state.state['units'].append(dict(id='green-3', faction='green', hp=100, max_hp=100,
            position=[0., 0.], weapon_range=.92, weapon='rocket', last_shot_at=-10,
            combat={'engageable_targets': ['red-visible', 'red-hidden']}))
        self.state.state['squad_behavior']['perception']['green']['contacts'] = [
            dict(id='red-visible', position=[.8, 0.], visible=True, last_seen=0.)]
        self.c.tick()
        self.state.state['time'] = 13.
        self.state.state['units'][-1]['last_shot_at'] = 12.
        self.c.tick()
        context = self.c._context(self.c._members(self.state.state))
        rows = context['execution_evidence']['members']
        self.assertEqual(rows['green-1']['range_status'], 'all_visible_contacts_outside_weapon_range')
        self.assertEqual(rows['green-1']['outside_visible_enemy_range_for_s'], 13.)
        self.assertFalse(rows['green-2']['has_fired_this_run'])
        self.assertEqual(rows['green-2']['seconds_without_measured_progress'], 13.)
        self.assertTrue(rows['green-3']['recent_fire_observed'])
        self.assertEqual(rows['green-3']['engageable_visible_targets'], ['red-visible'])
        event = next(e for e in self.c.events if e['kind'] == 'participation_gap')
        self.assertIn('green-1,green-2', event['reason'])
        self.assertNotIn('green-3', event['reason'])
        self.assertFalse(self.state.commands)

    def test_stage_review_is_harness_owned_and_bounded(self):
        for value in (float('inf'), float('nan'), 0, 3600):
            selected = validate_plan(dict(plan(), review_after_s=value), {'Nc': {'center': [.7, 0.]}})
            self.assertEqual(selected['review_after_s'], 20)

    def test_native_contact_event_wakes_before_five_seconds_and_coalesces(self):
        self.accepted_order()
        self.clock.now += 2.
        self.state.state['time'] = .2
        self.event(1, 'contact_acquired', target_id='red-1')
        self.event(2, 'contact_acquired', target_id='red-1')
        self.pump(lambda: len(self.game.requests) == 3)
        self.assertEqual(self.c.trigger_count, 1)
        self.assertIsNone(self.game.requests[-1]['role'])
        for _ in range(5):
            self.c.tick()
        self.assertEqual(len(self.game.requests), 3)

    def test_restored_support_wakes_team_without_strategic_replan(self):
        self.accepted_order()
        self.clock.now += 2.
        self.state.state['time'] = .2
        self.event(1, 'support_restored')
        self.pump(lambda: len(self.game.requests) == 3)
        self.assertEqual(self.c.trigger_count, 1)
        self.assertIsNone(self.game.requests[-1]['role'])
        for _ in range(5):
            self.c.tick()
        self.assertEqual(len(self.game.requests), 3)

    def test_critical_event_discards_slow_reply_and_wakes_commander(self):
        request = self.start_executor()
        self.clock.now += 5.
        self.state.state['time'] = 1.
        self.event(1, 'route_failed', unit_id='green-1')
        self.c.tick()
        request['future'].set_result(answer_intent())
        self.pump(lambda: self.c.discarded == 1)
        self.assertFalse(self.state.commands)
        self.assertGreaterEqual(self.c.commander_calls, 2)

    def test_visible_danger_approach_invalidates_reply_without_hidden_enemy_queries(self):
        request = self.start_executor()
        self.state.state['squad_behavior']['perception']['green']['contacts'] = [
            dict(id='red-1', visible=True, position=[.3, 0.], last_seen=0.)]
        self.event(1, 'contact_acquired', target_id='red-1')
        self.c.tick()
        request['future'].set_result(answer_intent())
        self.pump(lambda: self.c.discarded == 1)
        self.assertFalse(self.state.commands)
        self.assertEqual(self.c.trigger_count, 1)
        self.assertEqual(self.c.events[-1]['kind'], 'danger_close')

    def test_new_plan_invalidates_old_executor_response(self):
        request = self.start_executor()
        self.c.plan.update(region_id='Na', position=[0., 0.])
        self.c.version += 1
        request['future'].set_result(answer_intent())
        self.pump(lambda: self.c.discarded == 1)
        self.assertFalse(self.state.commands)

    def test_control_transfer_discards_reply(self):
        request = self.start_executor()
        self.state.state['control_epochs']['green'] = 4
        self.c.tick()
        request['future'].set_result(answer_intent())
        self.pump(lambda: self.c.discarded >= 1)
        self.assertFalse(self.state.commands)

    def test_timeout_during_pause_is_wall_based_no_second_inflight(self):
        request = self.start_executor()
        self.state.state['paused'] = True
        self.clock.now += 12.
        self.c.tick()
        self.assertTrue(self.c.slots['executor']['expired'])
        for _ in range(4):
            self.c.tick()
        self.assertEqual(len(self.game.requests), 2)
        self.assertFalse(self.state.commands)
        request['future'].set_result(answer_intent())
        self.state.state['paused'] = False
        self.pump(lambda: self.c.discarded == 1)
        self.assertFalse(self.state.commands)

    def test_completed_reply_during_pause_uses_transport_deadline_when_harvest_is_late(self):
        request = self.start_executor()
        serial = self.c.slots['executor']['serial']
        self.state.state['paused'] = True
        request['future'].set_result(answer_intent())
        for _ in range(100):
            if self.c.slots['executor'].get('completed_at') is not None:
                break
            time.sleep(.001)
        self.assertIsNotNone(self.c.slots['executor'].get('completed_at'))
        # The provider completed promptly, but the paused simulation does not
        # harvest the reply until much later.
        self.clock.now += 40.
        self.c.tick()
        self.assertFalse(self.c.slots['executor']['expired'])
        self.state.state['paused'] = False
        self.pump(lambda: len(self.state.commands) == 1)
        response = next(row for row in self.game.records
                        if row.get('type') == 'human-model-response'
                        and row.get('request_serial') == serial)
        self.assertGreater(response['harvest_wait_s'], 0.)
        self.assertLess(response['transport_elapsed_s'], 20.)

    def test_provider_failure_preserves_accepted_order(self):
        self.accepted_order()
        self.clock.now += 2.
        self.state.state['time'] = 5.
        self.pump(lambda: len(self.game.requests) == 3)
        self.game.requests[-1]['future'].set_exception(RuntimeError('provider unavailable'))
        self.pump(lambda: bool(self.c.error))
        self.assertEqual(self.c.last_order['intent'], 'bound')
        self.assertTrue(self.c.last_order['accepted'])
        self.assertEqual(len(self.state.commands), 1)

    def test_request_timeout_reason_is_safe_and_preserves_accepted_order(self):
        self.accepted_order()
        self.clock.now += 2.
        self.state.state['time'] = 5.
        self.pump(lambda: len(self.game.requests) == 3)
        self.game.requests[-1]['future'].set_exception(RuntimeError('request-timeout'))
        self.pump(lambda: bool(self.c.error))
        self.assertIn('executor_request_failed:request-timeout', self.c.error)
        self.assertEqual(self.c.last_order['intent'], 'bound')
        self.assertEqual(len(self.state.commands), 1)

    def test_engine_rejection_wakes_replanning_and_does_not_claim_execution(self):
        request = self.start_executor()
        request['future'].set_result(answer_intent())
        self.pump(lambda: len(self.state.commands) == 1)
        self.state.results['command-1'] = {'accepted': False, 'message': 'unreachable'}
        self.c.tick()
        self.assertEqual(self.c.accepted_orders, 0)
        self.assertFalse(self.c.last_order['accepted'])
        self.assertGreater(self.c.revision['commander'], 0)

    def test_model_pause_freezes_reviews(self):
        self.state.state['paused'] = True
        self.c.tick()
        self.assertFalse(self.game.requests)

    def test_opening_pause_allows_only_first_accepted_order_then_freezes(self):
        with tempfile.TemporaryDirectory() as directory:
            self.c.config.update(opening_gate=True, opening_release_path=str(Path(directory) / 'release.json'))
            self.state.state['paused'] = True
            self.accepted_order()
            self.assertEqual(self.c.run_accepted_orders, 1)
            self.clock.now += 10.
            self.state.state['time'] = 6.
            self.c.tick()
            self.assertEqual(len(self.game.requests), 2)
            self.assertTrue(self.c.ready)

    def test_already_released_gate_does_not_bypass_manual_pause(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'release.json'
            path.write_text(json.dumps({'run_id': 'run-1'}), encoding='utf-8')
            self.c.config.update(opening_gate=True, opening_release_path=str(path))
            self.state.state['paused'] = True
            self.c.tick()
            self.assertFalse(self.game.requests)

    def test_explosive_warning_invalidates_pending_squad_decision(self):
        self.accepted_order()
        before = self.c.critical['executor']
        self.event(1, 'incoming_explosive', unit_id='green-1', estimated_position=[.3, 0.], eta=.6, expires_at=2.)
        self.c.world = copy.deepcopy(self.state.state)
        self.c._observe(self.c._members(self.state.state))
        self.assertEqual(self.c.critical['executor'], before + 1)
        self.assertEqual(self.c.events[-1]['eta'], .6)
        self.c._observe(self.c._members(self.state.state))
        self.assertEqual(self.c.critical['executor'], before + 1)

    def test_death_observation_and_engine_event_coalesce(self):
        self.accepted_order()
        self.state.state['units'][1]['hp'] = 0
        self.event(1, 'ally_down', unit_id='green-2')
        self.c.tick()
        deaths = [e for e in self.c.events if e['kind'] == 'member_lost']
        self.assertEqual(len(deaths), 1)

    def test_mock_is_explicit_rule_baseline_without_provider_requests(self):
        self.c.model = 'mock'
        self.pump(lambda: bool(self.state.commands))
        self.assertFalse(self.game.requests)
        self.assertEqual(self.c.plan['source'], 'local_rules_baseline')
        snapshot = self.c.snapshot()
        self.assertEqual(snapshot['controller'], 'human_squad')
        self.assertEqual(snapshot['squad']['source'], 'local_rules_baseline')
        self.assertEqual(snapshot['squad']['plan']['goal'], [.7, 0.])

    def test_topology_file_requires_current_run_and_revision(self):
        topo = self.state.state.pop('strategic_topology')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'spatial.json'
            self.c.config['spatial_path'] = str(path)
            target = Path(str(path) + '.topology.json')
            target.write_text(json.dumps(dict(topo, run_id='other-run')), encoding='utf-8')
            self.c.tick()
            self.assertFalse(self.game.requests)
            target.write_text(json.dumps(topo), encoding='utf-8')
            self.pump(lambda: bool(self.game.requests))


if __name__ == '__main__':
    unittest.main()
