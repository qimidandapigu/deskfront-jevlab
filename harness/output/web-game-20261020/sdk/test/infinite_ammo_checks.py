"""Native-flag request compatibility checks; no model or engine calls."""
import copy
from pathlib import Path
import sys
import unittest

SDK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK/'src/deskfront'))
sys.path.insert(0, str(SDK/'test'))
from ammunition_rules import ammunition_rules
from combat_prompt import instructions, model_view
from coordinate_prompt import inspect_state
import model_led_coordination_checks as legacy
from prompt_cases import explain_request
from soldier_agents import native_breach_opportunities, native_grenade_opportunities
from soldier_emotion_scheduler import SoldierEmotionScheduler


class RuleChecks(unittest.TestCase):
    def test_native_flag_distinguishes_infinite_mixed_and_legacy_records(self):
        live = ammunition_rules([{'ammo_infinite': True}, {'ammo_infinite': True}])
        self.assertIs(live['infinite'], True)
        self.assertIs(live['reload_enabled'], False)
        self.assertEqual(live['ammo_field'], 'nominal_weapon_capacity')
        self.assertEqual(live['grenades'], 'finite_inventory')
        for old in ([{}], [{'ammo_infinite': False}], []):
            self.assertEqual(ammunition_rules(old)['ammo_field'], 'current_magazine_rounds')
        self.assertEqual(ammunition_rules([{'ammo_infinite': True}, {}])['infinite'], 'per_actor')

    def test_infinite_rocket_breach_respects_native_safety_instead_of_old_magazine(self):
        unit = dict(weapon='rocket', hp=100, ammo=0, reload_remaining=4,
                    ammo_infinite=True, weapon_range=1., combat={'cover_breach_checks': [
                        dict(target_id='wall', reason='', distance=.3, hp=100)]})
        self.assertEqual([r['target_id'] for r in native_breach_opportunities(unit)], ['wall'])
        unit['combat']['cover_breach_checks'][0]['reason'] = 'friendly_blast_risk'
        self.assertEqual(native_breach_opportunities(unit), [])
        unit['combat']['cover_breach_checks'][0]['reason'] = ''
        for value in (False, None):
            unit['ammo_infinite'] = value
            self.assertEqual(native_breach_opportunities(unit), [])

    def test_grenade_still_has_finite_stock_and_native_safety(self):
        contact = dict(id='red-1', visible=True, kind='infantry', hp=100, faction='red')
        unit = dict(ammo=0, reload_remaining=4, ammo_infinite=True, grenades=2,
                    grenade_range=.65, combat={'grenade_checks': [dict(target_id='red-1', reason='', distance=.3)]})
        self.assertEqual(len(native_grenade_opportunities({'units': []}, 'green', unit, [contact])), 1)
        unit['grenades'] = 0
        self.assertEqual(native_grenade_opportunities({'units': []}, 'green', unit, [contact]), [])
        unit['grenades'] = 2
        unit['combat']['grenade_checks'][0]['reason'] = 'friendly_blast_risk'
        self.assertEqual(native_grenade_opportunities({'units': []}, 'green', unit, [contact]), [])

    def test_request_explanation_does_not_present_nominal_capacity_as_remaining(self):
        new = explain_request('personal', {'self': dict(id='green-1', ammo=1, ammo_infinite=True)}, {})
        text = '\n'.join(row['text'] for row in new['facts'])
        self.assertIn('无限弹药，无需装填', text)
        self.assertNotIn('弹匣剩', text)
        old = explain_request('personal', {'self': dict(id='green-1', ammo=1)}, {})
        self.assertIn('当前弹匣剩 1 发', '\n'.join(row['text'] for row in old['facts']))


class RequestChecks(unittest.TestCase):
    setUp, tearDown, pump, start = legacy.Checks.setUp, legacy.Checks.tearDown, legacy.Checks.pump, legacy.Checks.start

    def make_infinite(self):
        for unit in self.state.state['units']:
            unit.update(weapon='rocket', ammo=1, ammo_infinite=True, reload_remaining=0.,
                        grenades=2, grenade_range=.65, max_hp=100)
        self.state.state['weapons'] = {'rocket': dict(magazine=1, reload=0., ammo_infinite=True)}

    def test_native_flag_and_rules_reach_commander_executor_and_personal(self):
        self.make_infinite()
        request = self.start(coordinates=True)
        for request in self.game.requests[:2]:
            state = inspect_state(request['state'])
            self.assertTrue(all(row['ammo_infinite'] is True for row in state['members']))
            self.assertIs(state['ammunition_rules']['infinite'], True)
            self.assertIs(state['ammunition_rules']['reload_enabled'], False)
            self.assertEqual(state['ammunition_rules']['ammo_field'], 'nominal_weapon_capacity')
        unit = self.c.world['units'][0]
        self.c.soldiers.agents[unit['id']] = dict(assignment={}, memory=[], engine_execution={})
        personal = self.c.soldiers._context(unit, {})
        self.assertIs(personal['self']['ammo_infinite'], True)
        self.assertIs(personal['ammunition_rules']['infinite'], True)
        projected = model_view(personal, 'personal')
        self.assertIs(projected['self']['ammo_infinite'], True)
        self.assertIs(projected['ammunition_rules']['reload_enabled'], False)
        for role, context in (('commander', self.game.requests[0]['state']),
                              ('executor', self.game.requests[1]['state']), ('personal', personal)):
            self.assertIn('无需装填', instructions(role, context))
        # Explanations and rule projection never mutate original observations.
        self.assertEqual(unit['ammo'], 1)
        self.assertEqual(unit['grenades'], 2)

    def test_emotion_self_preserves_native_infinite_fact(self):
        self.make_infinite()
        self.start()
        scheduler = SoldierEmotionScheduler(self.c)
        members = self.c._members(self.c.world)
        scheduler.observe(members)
        context = scheduler._context(members[0])
        self.assertIs(context['self']['ammo_infinite'], True)
        self.assertEqual(context['self']['ammo'], 1)


if __name__ == '__main__':
    unittest.main()
