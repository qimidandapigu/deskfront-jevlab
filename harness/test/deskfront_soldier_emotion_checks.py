import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deskfront_human_squad_checks import State, Game, Clock
from human_squad import HumanSquadController, SharedRequestBudget
from soldier_emotions import EMOTIONS


class EmotionChecks(unittest.TestCase):
    def setUp(self):
        self.state, self.game, self.clock = State(), Game(), Clock()
        self.c = HumanSquadController(
            self.state, {'model': 'jev', 'max_requests': 100, 'timeout': 10},
            self.game, 'green', wall_clock=self.clock)
        self.c.world = self.state.state
        self.c.identity = ('run-1', 3, 'lm')
        self.members = self.c._members(self.c.world)
        for member in self.members:
            member['max_hp'] = 100
        self.order_id = 'order-1'

    def tearDown(self):
        self.c.stop()
        for request in self.game.requests:
            if not request['future'].done():
                request['future'].set_exception(RuntimeError('test_end'))

    def tick(self):
        self.c.emotions.tick(self.members, self.state.results,
                             active=True, squad_order_id=self.order_id)

    def launch(self):
        old = len(self.game.requests)
        self.tick()
        for _ in range(100):
            if len(self.game.requests) > old:
                return self.game.requests[-1]
            time.sleep(.001)
        self.fail('no emotion request')

    def answer(self, emotions=None):
        request = self.game.requests[-1]
        ids = request['state']['soldiers']
        emotions = emotions or {}
        answers = {'emotion_' + uid: {'choice': emotions.get(uid, 'calm')}
                   for uid in ids}
        request['future'].set_result({'answers': answers})
        for _ in range(100):
            if self.c.emotions.pending['future'].done():
                break
            time.sleep(.001)
        self.tick()

    def acknowledge(self):
        for index, _ in enumerate(self.state.commands, start=1):
            self.state.results['command-' + str(index)] = {
                'accepted': True, 'message': 'applied'}
        self.tick()

    def test_one_periodic_request_covers_all_soldiers_every_twenty_seconds(self):
        request = self.launch()
        self.assertEqual(set(request['questions']),
                         {'emotion_green-1', 'emotion_green-2'})
        self.assertEqual(set(request['questions']['emotion_green-1']['criteria']),
                         set(EMOTIONS))
        self.assertEqual(set(request['state']['soldiers']),
                         {'green-1', 'green-2'})
        self.assertNotIn('action', request['questions'])
        self.answer({'green-1': 'alert', 'green-2': 'calm'})
        self.assertEqual(len(self.state.commands), 2)
        self.assertEqual([row['emotion'] for row in self.state.commands],
                         ['alert', 'calm'])
        self.acknowledge()
        self.state.state['time'] = 19.9
        self.clock.now += 1
        self.tick()
        self.assertEqual(len(self.game.requests), 1)
        self.state.state['time'] = 20.
        self.launch()
        self.assertEqual(self.c.emotions.periodic_calls, 2)

    def test_injury_refreshes_emotion_without_touching_movement(self):
        self.launch()
        self.answer()
        self.acknowledge()
        self.state.state['time'] = 2.
        self.clock.now += 2
        self.members[0].update(hp=70, last_damage_at=2.)
        request = self.launch()
        self.assertEqual(set(request['questions']), {'emotion_green-1'})
        self.assertEqual(set(request['state']['soldiers']), {'green-1'})
        injured = request['state']['soldiers']['green-1']
        self.assertEqual(injured['emotion_evidence']['recent_events'][-1]['kind'],
                         'received_damage')
        self.assertGreater(injured['affect_appraisal']['pain'], 0)
        self.assertEqual(set(injured['emotion_support']), set(EMOTIONS))
        self.answer({'green-1': 'hurt'})
        self.assertEqual([row['action'] for row in self.state.commands],
                         ['unit_emotion'] * 3)
        self.assertEqual(self.state.commands[-1]['emotion'], 'hurt')
        self.assertEqual(self.c.emotions.event_calls, 1)

    def test_low_event_debounces_then_injury_refreshes_immediately(self):
        self.launch()
        self.answer()
        self.acknowledge()
        self.state.state['time'] = 2.
        self.clock.now += 2
        self.members[0].update(suppression=.5,
                               combat={'incoming_threats': ['shell-1']})
        self.tick()
        self.assertEqual(len(self.game.requests), 1)
        self.state.state['time'] = 2.5
        request = self.launch()
        events = request['state']['soldiers']['green-1']['emotion_evidence']['recent_events']
        self.assertEqual([row['kind'] for row in events],
                         ['suppression_started', 'incoming_threat'])
        self.assertEqual(self.game.records[-1]['priority'], 'normal')
        self.answer({'green-1': 'surprised'})
        self.acknowledge()
        self.state.state['time'] = 3.5
        self.clock.now += 1
        self.members[0].update(hp=80, last_damage_at=3.5)
        request = self.launch()
        self.assertEqual(self.game.records[-1]['priority'], 'high')
        self.assertEqual(request['state']['soldiers']['green-1']
                         ['emotion_evidence']['recent_events'][-1]['kind'],
                         'received_damage')
        self.assertEqual(self.c.emotions.event_calls, 2)

    def test_low_events_cannot_use_reserved_injury_slot(self):
        self.c.config['max_requests'] = 16  # two event batches, one low-priority
        self.launch()
        self.answer()
        self.acknowledge()
        self.state.state['time'] = 2.
        self.clock.now += 2
        self.members[0]['combat'] = {'incoming_threats': ['shell-1']}
        self.tick()
        self.state.state['time'] = 2.5
        self.launch()
        self.answer()
        self.acknowledge()
        self.state.state['time'] = 3.
        self.members[0]['combat'] = {'incoming_threats': []}
        self.tick()
        self.state.state['time'] = 9.
        self.clock.now += 7
        self.members[0]['combat'] = {'incoming_threats': ['shell-2']}
        self.tick()
        self.assertEqual(len(self.game.requests), 2)
        self.state.state['time'] = 10.
        self.clock.now += 1
        self.members[0].update(hp=75, last_damage_at=10.)
        self.launch()
        self.assertEqual(self.c.emotions.event_calls, 2)
        self.assertEqual(self.c.emotions.low_priority_event_calls, 1)

    def test_strong_stable_loss_holds_minor_hit_for_twenty_seconds(self):
        self.members[0]['combat'] = {'incoming_threats': ['shell-1']}
        self.launch()
        self.answer()
        self.acknowledge()
        self.state.state['time'] = 2.
        self.clock.now += 2
        self.members = self.members[:1]
        self.state.state['units'][1]['hp'] = 0
        loss = self.launch()
        self.assertEqual(set(loss['state']['soldiers']), {'green-1'})
        self.assertEqual(loss['state']['soldiers']['green-1']
                         ['emotion_evidence']['recent_events'][-1]['kind'], 'teammate_died')
        self.answer({'green-1': 'sad'})
        self.acknowledge()

        self.state.state['time'] = 3.
        self.clock.now += 1
        self.members[0].update(hp=95, last_damage_at=3., suppression=.5)
        self.tick()
        self.assertEqual(len(self.game.requests), 2)
        self.assertGreater(self.c.emotions.agents['green-1']['affect_state']['pain'], 0)
        self.assertEqual(self.c.emotions.held_events, 2)

        self.state.state['time'] = 20.
        self.clock.now += 17
        self.tick()
        self.assertEqual(len(self.game.requests), 2)
        self.state.state['time'] = 22.
        self.clock.now += 2
        baseline = self.launch()
        events = baseline['state']['soldiers']['green-1']['emotion_evidence']['recent_events']
        self.assertEqual([e['kind'] for e in events],
                         ['teammate_died', 'received_damage', 'suppression_started'])
        self.assertEqual(self.game.records[-1]['trigger'], 'periodic')
        self.answer({'green-1': 'hurt'})
        self.acknowledge()
        self.assertEqual(self.c.emotions.event_calls, 1)

        self.state.state['time'] = 23.
        self.clock.now += 1.
        self.members[0].update(hp=70, last_damage_at=23.)
        injury = self.launch()
        self.assertEqual(set(injury['state']['soldiers']), {'green-1'})
        self.assertEqual(self.game.records[-1]['priority'], 'high')

    def test_injury_holds_repeat_hits_but_new_teammate_loss_overrides(self):
        self.launch()
        self.answer()
        self.acknowledge()
        self.state.state['time'] = 2.
        self.clock.now += 2
        self.members[0].update(hp=80, last_damage_at=2.)
        self.launch()
        self.answer({'green-1': 'hurt'})
        self.acknowledge()

        self.state.state['time'] = 5.
        self.clock.now += 3
        self.members[0].update(hp=60, last_damage_at=5.)
        self.tick()
        self.assertEqual(len(self.game.requests), 2)

        self.state.state['time'] = 6.
        self.clock.now += 1
        self.members = self.members[:1]
        self.state.state['units'][1]['hp'] = 0
        loss = self.launch()
        events = loss['state']['soldiers']['green-1']['emotion_evidence']['recent_events']
        self.assertEqual([e['kind'] for e in events][-2:],
                         ['received_damage', 'teammate_died'])
        self.assertEqual(self.c.emotions.event_calls, 2)

    def test_periodic_batch_with_injury_starts_same_hold(self):
        self.launch()
        self.answer()
        self.acknowledge()
        self.state.state['time'] = 20.
        self.clock.now += 20
        self.members[0].update(hp=80, last_damage_at=20.)
        self.launch()
        self.answer({'green-1': 'hurt'})
        self.acknowledge()
        self.state.state['time'] = 21.
        self.clock.now += 1
        self.members[0].update(hp=75, last_damage_at=21.)
        self.tick()
        self.assertEqual(len(self.game.requests), 2)

    def test_one_soldiers_injury_hold_does_not_silence_another(self):
        self.launch()
        self.answer()
        self.acknowledge()
        self.state.state['time'] = 2.
        self.clock.now += 2
        self.members[0].update(hp=80, last_damage_at=2.)
        self.launch()
        self.answer({'green-1': 'hurt'})
        self.acknowledge()
        self.state.state['time'] = 5.
        self.clock.now += 3
        self.members[1].update(hp=70, last_damage_at=5.)
        second = self.launch()
        self.assertEqual(set(second['state']['soldiers']), {'green-2'})

    def test_event_refresh_does_not_delay_twenty_second_team_baseline(self):
        self.members[0]['combat'] = {'incoming_threats': ['shell-1']}
        self.launch()
        self.answer()
        self.acknowledge()
        self.state.state['time'] = 2.
        self.clock.now += 2
        self.members[0].update(hp=80, last_damage_at=2.)
        self.launch()
        self.answer({'green-1': 'hurt'})
        self.acknowledge()
        self.state.state['time'] = 19.9
        self.clock.now += 18
        self.tick()
        self.assertEqual(len(self.game.requests), 2)
        self.state.state['time'] = 20.
        baseline = self.launch()
        self.assertEqual(set(baseline['state']['soldiers']), {'green-2'})
        self.assertEqual(self.c.emotions.periodic_calls, 2)
        self.answer({'green-2': 'calm'})
        self.acknowledge()
        self.state.state['time'] = 22.
        self.clock.now += 2
        due = self.launch()
        self.assertEqual(set(due['state']['soldiers']), {'green-1'})

    def test_material_danger_reduction_refreshes_without_named_event(self):
        self.members[0]['combat'] = {'incoming_threats': ['shell-1']}
        self.launch()
        self.answer({'green-1': 'afraid'})
        self.acknowledge()
        self.state.state['time'] = 1.
        self.clock.now += 1
        self.members[0]['combat'] = {'incoming_threats': []}
        self.tick()
        self.state.state['time'] = 5.
        self.clock.now += 4
        self.tick()
        self.assertEqual(len(self.game.requests), 1)
        self.state.state['time'] = 5.5
        refreshed = self.launch()
        self.assertEqual(set(refreshed['state']['soldiers']), {'green-1'})
        self.assertEqual(self.game.records[-1]['trigger'], 'event')
        self.assertEqual(refreshed['state']['soldiers']['green-1']
                         ['emotion_evidence']['recent_events'], [])

    def test_event_on_periodic_deadline_uses_one_batch(self):
        self.launch()
        self.answer()
        self.acknowledge()
        self.state.state['time'] = 20.
        self.clock.now += 20
        self.members[0].update(hp=80, last_damage_at=20.)
        request = self.launch()
        self.assertEqual(set(request['questions']),
                         {'emotion_green-1', 'emotion_green-2'})
        self.assertEqual(self.game.records[-1]['trigger'], 'periodic')
        self.answer({'green-1': 'hurt'})
        self.acknowledge()
        self.tick()
        self.assertEqual(len(self.game.requests), 2)
        self.assertEqual(self.c.emotions.event_calls, 0)

    def test_low_event_at_periodic_deadline_does_not_buy_second_batch(self):
        self.launch()
        self.answer()
        self.acknowledge()
        self.state.state['time'] = 20.
        self.clock.now += 20
        self.members[0]['suppression'] = .5
        request = self.launch()
        self.assertEqual(self.game.records[-1]['trigger'], 'periodic')
        self.assertEqual(request['state']['soldiers']['green-1']
                         ['emotion_evidence']['recent_events'][-1]['kind'],
                         'suppression_started')
        self.answer({'green-1': 'nervous'})
        self.acknowledge()
        self.state.state['time'] = 20.5
        self.tick()
        self.assertEqual(len(self.game.requests), 2)

    def test_order_change_keeps_emotion_response(self):
        self.launch()
        self.order_id = 'order-2'
        self.answer({'green-1': 'alert'})
        self.assertEqual(self.state.commands[0]['emotion'], 'alert')
        self.assertEqual(self.c.emotions.discarded, 0)

    def test_dead_soldier_does_not_receive_emotion(self):
        self.launch()
        self.members = self.members[1:]
        self.answer({'green-1': 'hurt'})
        self.assertEqual([row['unit_ids'] for row in self.state.commands],
                         [['green-2']])

    def test_shared_request_budget_applies_to_batch(self):
        self.c.config['shared_request_budget'] = SharedRequestBudget(1)
        self.launch()
        self.answer()
        self.acknowledge()
        self.state.state['time'] = 20.
        self.clock.now += 20
        self.tick()
        self.assertEqual(len(self.game.requests), 1)
        self.assertTrue(self.c.budget_exhausted)

    def test_transient_503_is_visible_and_retries_with_fresh_context(self):
        request = self.launch()
        request['future'].set_exception(RuntimeError(
            'OpenRouter decisions 请求失败（HTTP 503）'))
        for _ in range(100):
            if self.c.emotions.pending['future'].done():
                break
            time.sleep(.001)
        self.tick()
        failures = [row for row in self.game.records
                    if row['type'] == 'emotion-decision-failed']
        self.assertEqual(failures[-1]['reason'], 'upstream_http_503')
        self.assertEqual(self.c.emotions.agents['green-1']['next_retry_at'], 2.)
        self.assertEqual(self.state.commands, [])
        self.state.state['time'] = 2.
        self.clock.now += 2
        self.members[0].update(hp=70, last_damage_at=2.)
        retry = self.launch()
        self.assertEqual(retry['state']['time'], 2.)
        self.assertEqual(retry['state']['soldiers']['green-1']['self']['hp'], 70)

    def test_late_reply_does_not_apply_old_emotion(self):
        self.launch()
        self.state.state['time'] = 6.
        self.clock.now += 1.
        self.answer({'green-1': 'calm'})
        self.assertEqual(self.state.commands, [])
        discarded = [row for row in self.game.records
                     if row['type'] == 'emotion-response-discarded']
        self.assertEqual(discarded[-1]['reason'], 'game_context_expired')
        self.state.state['time'] = 7.
        retry = self.launch()
        self.assertEqual(retry['state']['time'], 7.)

    def test_new_injury_invalidates_inflight_emotion(self):
        self.launch()
        self.state.state['time'] = 1.
        self.members[0].update(hp=70, last_damage_at=1.)
        self.tick()
        self.answer({'green-1': 'calm'})
        self.assertEqual([row['unit_ids'] for row in self.state.commands],
                         [['green-2']])
        discarded = [row for row in self.game.records
                     if row['type'] == 'emotion-response-discarded']
        self.assertEqual(discarded[-1]['reason'], 'game_context_changed')
        self.clock.now += 1.
        refreshed = self.launch()
        self.assertEqual(refreshed['state']['soldiers']['green-1']['self']['hp'], 70)


if __name__ == '__main__':
    unittest.main()
