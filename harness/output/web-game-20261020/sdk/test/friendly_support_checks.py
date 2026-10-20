"""SDK tactical observation contract for deployed friendly fixed support."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'deskfront'))
from actor_roster import roster, action_capabilities
from battlefield_equipment import equipment_brief, equipment_opportunities


def fixture():
    return dict(units=[dict(id=uid, faction='green', kind='infantry', weapon='rifle', hp=75,
                           max_hp=75, position=[0.1*i, 0], combat_ready=True)
                       for i, uid in enumerate(['gunner', 'guard', 'rifle'])],
                at_guns=[dict(id='friendly-gun', kind='mortar', faction='green', initial_owner='green',
                              hp=100, damageable=False, position=[.1, 0], crew_ids=['gunner', 'guard'],
                              gunner_id='gunner', guard_id='guard', crew_alive=2, operator_ready=True,
                              phase='ready', available_current_encounter=True, next_encounter_available=False,
                              available_for_next_encounter=False, capturable=False, range=5, minimum_range=.1)])


class FriendlySupportChecks(unittest.TestCase):
    def test_owned_gun_crew_are_support_not_extra_movable_rifles(self):
        world = fixture()
        modes = {u['id']: u for u in roster(world, 'green')}
        self.assertEqual(modes['gunner']['mode'], 'equipment_crew')
        self.assertFalse(modes['guard']['movable'])
        self.assertTrue(modes['rifle']['movable'])
        self.assertIn('support.support_area', action_capabilities(world, world['units'][0], 'green'))
        self.assertIn('support.release_crew', action_capabilities(world, world['units'][0], 'green'))

    def test_deployed_friendly_is_owned_not_a_fictitious_capture(self):
        world = fixture(); before = copy.deepcopy(world)
        brief = equipment_brief(world, 'green', [])
        self.assertEqual(len(brief), 1)
        self.assertEqual(brief[0]['control_status'], 'friendly_operated')
        self.assertEqual(brief[0]['operation_status'], 'ready')
        self.assertEqual(brief[0]['available_for_next_encounter'], False)
        self.assertEqual([c['identity_source'] for c in brief[0]['crew']], ['own_crew_state'] * 2)
        self.assertNotIn('已接管', brief[0]['note'])
        self.assertEqual(world, before)

    def test_completed_support_is_neither_available_asset_nor_capture_opportunity(self):
        world = fixture(); gun = world['at_guns'][0]
        gun.update(faction='neutral', crew_ids=[], crew_alive=0, support_completed=True,
                   phase='completed_support', available_current_encounter=False, capturable=False)
        self.assertEqual(equipment_brief(world, 'green', []), [])
        self.assertTrue(all(r['mode'] == 'infantry' for r in roster(world, 'green')))

    def test_owned_unavailable_old_gun_is_not_counted_as_current_support(self):
        world = fixture(); world['at_guns'][0]['available_current_encounter'] = False
        self.assertEqual(equipment_brief(world, 'green', []), [])
        self.assertFalse(any(r['support'] for r in roster(world, 'green')))

    def test_normal_neutral_unmanned_gun_stays_discoverable_and_capturable(self):
        world = fixture(); gun = world['at_guns'][0]
        gun.update(faction='neutral', crew_ids=[], crew_alive=0, seen_by=['green'], capturable=True,
                   available_current_encounter=False, capture_radius=.2, capture_seconds=3, capture_progress=0)
        brief = equipment_brief(world, 'green', [])
        self.assertEqual(brief[0]['control_status'], 'unmanned')
        self.assertEqual(len(equipment_opportunities(brief, world['units'], [])), 1)


if __name__ == '__main__':
    unittest.main()
