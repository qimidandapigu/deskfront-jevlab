"""Meaningful generation constraints, independent of provider quality."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/deskfront'))
from world.catalog import CATALOG, DESCRIPTIONS, eligible, shortlist
from world.forces import force_packages, validate_forces


def state(count, hp=50):
    return dict(units=[dict(id=f'g{i}',faction='green',hp=hp,max_hp=50) for i in range(count)])


class DesignChecks(unittest.TestCase):
    def test_tank_escort_is_two_and_infantry_rules_are_unchanged(self):
        current=state(3)
        self.assertTrue(validate_forces(current,dict(friendly_count=0,enemy_count=2,support_type='tank')))
        self.assertFalse(validate_forces(current,dict(friendly_count=0,enemy_count=3,support_type='tank')))
        self.assertFalse(validate_forces(current,dict(friendly_count=0,enemy_count=1)))
        self.assertTrue(validate_forces(current,dict(friendly_count=1,enemy_count=2),ensure_rocket=True,support_type='tank'))
        self.assertFalse(validate_forces(current,dict(friendly_count=0,enemy_count=2),ensure_rocket=True,support_type='tank'))

    def test_first_encounter_uses_five_person_start_without_auto_reinforcement(self):
        opening=state(5)
        opening['world_growth']=dict(revision=0,completed=[])
        rows=force_packages(opening,{},'explore')
        self.assertEqual({(r['friendly_count'],r['projected_friendly_count'],r['enemy_count'])
                          for r in rows.values()},{(0,5,3)})

    def test_second_stage_tank_rule_requires_replacement_rocket_when_lost(self):
        second=state(3)
        second['world_growth']=dict(revision=1,completed=[dict(index=0)])
        rows=force_packages(second,{},'explore',ensure_rocket=True)
        self.assertTrue(rows)
        self.assertTrue(all(r['friendly_count']==1 for r in rows.values()))
        self.assertTrue(validate_forces(second,dict(friendly_count=1,enemy_count=4),ensure_rocket=True))
        self.assertFalse(validate_forces(second,dict(friendly_count=0,enemy_count=3),ensure_rocket=True))

    def test_healthy_three_never_get_unrequested_growth(self):
        for phase in ('explore','build_up','peak','relax'):
            rows=force_packages(state(3),{},phase)
            self.assertTrue(rows)
            self.assertTrue(all(r['friendly_count']==0 for r in rows.values()))

    def test_five_healthy_units_never_face_two(self):
        for phase in ('explore','build_up','peak','relax'):
            for recovery in (0,.8):
                rows=force_packages(state(5),dict(recovery=recovery),phase)
                self.assertTrue(rows)
                self.assertTrue(all(4<=r['enemy_count']<=6 for r in rows.values()))

    def test_reinforcement_and_enemies_are_coupled(self):
        rows=force_packages(state(1),{},'explore')
        self.assertIn('f2_e3',rows)
        self.assertNotIn('f2_e2',rows)
        self.assertTrue(all(r['projected_friendly_count']==1+r['friendly_count'] for r in rows.values()))

    def test_recovery_and_peak_change_offered_pressure(self):
        low=force_packages(state(3,15),dict(recovery=.8),'relax')
        high=force_packages(state(3),dict(pressure=.8),'peak')
        self.assertEqual(max(r['enemy_count'] for r in low.values()),2)
        self.assertEqual(max(r['enemy_count'] for r in high.values()),4)

    def test_stale_package_is_not_silently_rebalanced(self):
        choice=dict(friendly_count=2,enemy_count=3)
        self.assertTrue(validate_forces(state(1),choice))
        self.assertFalse(validate_forces(state(3),choice))
        self.assertFalse(validate_forces(state(3),dict(friendly_count=False,enemy_count=3)))
        self.assertFalse(validate_forces(state(0),choice))

    def test_unknown_health_capacity_does_not_invent_injury_discount(self):
        s=state(5,10)
        for u in s['units']:u.pop('max_hp')
        rows=force_packages(s,{},'explore')
        self.assertEqual({r['enemy_count'] for r in rows.values()},{5})

    def test_shortlist_covers_gameplay_families_not_just_prop_swaps(self):
        menu=shortlist(DESCRIPTIONS,{})
        self.assertEqual(len(menu),8)
        self.assertEqual({CATALOG[k]['selection']['structure'] for k in menu},{'gate','stagger','court','breach'})
        self.assertEqual({CATALOG[k]['selection']['defense'] for k in menu},{'cross','depth'})
        self.assertEqual(menu,shortlist(DESCRIPTIONS,{}))

    def test_recent_structure_excluded_before_diverse_menu(self):
        world=dict(options=list(CATALOG),completed=[dict(option='breach_north_books_cross_tight')])
        before=copy.deepcopy(world)
        menu=shortlist(eligible(world),world)
        self.assertTrue(all(not k.startswith('breach_') for k in menu))
        self.assertEqual(world,before)

    def test_every_layout_has_capacity_and_explicit_intent(self):
        for spec in CATALOG.values():
            self.assertEqual(len(spec['defender_slots']),6)
            self.assertEqual(len(spec['defenders']),3)
            self.assertTrue(spec['design_card']['tactical_problem'])
            self.assertIn('combat_effect_requires_playtest',spec['design_card']['validation'])


if __name__=='__main__':unittest.main()
