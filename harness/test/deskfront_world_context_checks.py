"""Regression checks for evidence supplied to procedural-generation models."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from world.context import macro_context, generator_context, observation_sample, context_chars


def unit(uid, faction, hp, **extra):
    return dict(id=uid, faction=faction, hp=hp, max_hp=50, weapon='rifle', **extra)


def state(at=60, units=None):
    return dict(tick=int(at*60), time=at, shots=at*2,
        control={'green': 'harness', 'red': 'game_ai'},
        units=units if units is not None else [unit('g1','green',50), unit('r1','red',50)],
        world_growth=dict(revision=1, phase='encounter', completed=[], mission=dict(
            option='gate_north_books_cross_tight', status='active', started=0,
            defenders=['r1','r2','r3'], enemies_remaining=1, last_progress=50)))


class ContextChecks(unittest.TestCase):
    def context(self, s, samples=()):
        return macro_context(s, samples, {'pressure': .4}, 'build_up')

    def test_analyst_sees_current_built_layout_not_only_old_option_name(self):
        from world.region_graph import CELLS, LIBRARY
        s=state()
        ops=[dict(op='set_ports',entry='c0r1',exit='c2r1')]
        ops += [dict(op='place_region',cell=cell,module='books' if cell=='c1r1' else 'open')
            for cell in CELLS]
        ops += [dict(op='connect_regions',edge=edge) for edge in LIBRARY['edges']]
        ops.append(dict(op='deploy',module='rear'))
        native_ops=copy.deepcopy(ops)
        for op in native_ops:
            if op['op']=='place_region':op['rotation']=0.0
        s['world_growth']['mission']['spec']=dict(build_operations=native_ops)
        current=self.context(s)['current_design']
        self.assertEqual(current['cells']['c1r1']['card'],'books')
        self.assertEqual(len(current['connections']),12)
        self.assertIn('book_city',current['materials'])
        s['world_growth']['mission'].pop('spec')
        s['world_growth']['mission']['operation_id']='built-1'
        s['world_growth']['completed']=[dict(operation_id='built-1',design=dict(build_operations=ops))]
        self.assertEqual(self.context(s)['current_design']['cells']['c1r1']['card'],'books')

    def test_analyst_keeps_native_materials_and_profile_across_catalog_versions(self):
        from world.region_graph import CELLS, LIBRARY
        s=state()
        ops=[dict(op='set_ports',entry='c0r1',exit='c2r1')]
        ops += [dict(op='place_region',cell=cell,module='open') for cell in CELLS]
        ops += [dict(op='connect_regions',edge=edge) for edge in LIBRARY['edges']]
        ops.append(dict(op='deploy',module='rear'))
        native=dict(build_operations=ops,covers=[[.3,-.7,.1,.1,'historical_mouse',.04]])
        s['world_growth']['mission']['spec']=native
        current=self.context(s)['current_design']
        self.assertEqual(current['materials'],dict(historical_mouse=1))
        self.assertEqual(current['material_profile']['source'],'native_spec')
        self.assertEqual(current['material_profile']['total'],1)
        self.assertEqual(current['cells']['c0r0']['props'],['historical_mouse'])
        s['world_growth']['mission'].pop('spec')
        s['world_growth']['mission']['operation_id']='native-materials'
        s['world_growth']['completed']=[dict(operation_id='native-materials',design=native)]
        self.assertEqual(self.context(s)['current_design']['materials'],dict(historical_mouse=1))

    def test_pressure_excludes_corpses_and_missing_observations(self):
        s = state(units=[unit('g1','green',25,suppression=.8), unit('g2','green',50),
                         unit('r1','red',50,suppression=.4), unit('r2','red',0,suppression=0)])
        sample = observation_sample(s)
        self.assertAlmostEqual(sample['mean_pressure'], .6)
        self.assertEqual(sample['teams']['green']['mean_pressure'], .8)
        self.assertEqual(sample['teams']['green']['pressure_observed'], 1)
        self.assertEqual(sample['teams']['green']['full_health_equivalents'], 1.5)
        self.assertEqual(sample['teams']['red']['observed_dead'], 1)

    def test_missing_health_and_pressure_stay_unknown(self):
        s = state(units=[dict(id='g', faction='green', hp=25)])
        team = self.context(s)['teams']['green']
        self.assertIsNone(team['hp_fraction'])
        self.assertIsNone(team['full_health_equivalents'])
        self.assertIsNone(team['mean_pressure'])
        self.assertEqual(team['hp_total'], 25)

    def test_legacy_pressure_is_not_treated_as_living_pressure(self):
        legacy = [dict(time=10, alive=10, mean_pressure=.1, shots=10),
                  dict(time=20, alive=5, mean_pressure=.05, shots=30)]
        context = self.context(state(), legacy)
        self.assertEqual(context['battle_trend']['teams'], {})
        self.assertEqual(context['battle_trend']['shots_delta'], 20)
        self.assertTrue(all(row['mean_pressure'] is None for row in context['recent_observations']))
        self.assertIn('旧样本', context['observation_limits'])

    def test_time_window_and_bucket_boundaries_preserve_activity(self):
        samples = [observation_sample(state(at=t)) for t in range(0, 101)]
        context = self.context(state(at=100), samples)
        trend = context['battle_trend']
        self.assertEqual(trend['observed_seconds'], 60)
        self.assertEqual(trend['samples'], 61)
        self.assertEqual(trend['shots_delta'], 120)
        self.assertLessEqual(len(context['recent_observations']), 6)
        self.assertEqual(sum(row['shots_delta'] or 0 for row in context['recent_observations']), 120)
        self.assertEqual(context['recent_observations'][0]['from_time'], 40)

    def test_reinforcements_and_removal_are_not_damage_or_casualties(self):
        before = state(at=50, units=[unit('g1','green',40), unit('g2','green',30), unit('r1','red',50)])
        after = state(at=60, units=[unit('g1','green',0), unit('g3','green',50), unit('r1','red',45)])
        trend = self.context(after, [observation_sample(before), observation_sample(after)])['battle_trend']['teams']['green']
        self.assertEqual(trend['observed_deaths'], 1)
        self.assertEqual(trend['newly_observed'], 1)
        self.assertEqual(trend['disappeared'], 1)
        self.assertEqual([trend['hp_start'], trend['hp_end']], [70,50])
        self.assertNotIn('damage_taken', trend)

    def test_clear_progress_uses_engine_guard_count_and_hp_coverage(self):
        s = state()
        mission = self.context(s)['mission']
        self.assertEqual(mission['enemies_total'], 3)
        self.assertEqual(mission['enemies_cleared'], 2)
        self.assertAlmostEqual(mission['clear_fraction'], .667)
        self.assertEqual(mission['defender_hp_remaining'], 50)
        s['units'] = [unit('g1','green',50)]
        self.assertIsNone(self.context(s)['mission']['defender_hp_remaining'])

    def test_completion_duration_stops_at_completion(self):
        s = state(at=100)
        s['world_growth']['mission'].update(status='completed', completed_at=40, enemies_remaining=0)
        self.assertEqual(self.context(s)['mission']['elapsed_seconds'], 40)

    def test_failed_duration_stops_at_failure_for_both_native_timestamps(self):
        for field in ('failed_at', 'ended_at'):
            s = state(at=100)
            s['world_growth']['mission'].update(status='failed', started=10, last_progress=20, **{field:40})
            mission = self.context(s)['mission']
            self.assertEqual(mission['elapsed_seconds'], 30)
            self.assertEqual(mission['seconds_without_progress'], 20)

    def test_planning_menu_is_available_while_commit_is_blocked(self):
        s = state()
        s['world_growth'].update(planning_options=['a','b','c'], options=[])
        context = self.context(s)
        for construction in (context['construction'], generator_context(context)['construction']):
            self.assertEqual(construction['planning_option_count'], 3)
            self.assertEqual(construction['commit_option_count'], 0)
            self.assertNotIn('eligible_engine_options', construction)
        s['world_growth'].pop('planning_options')
        s['world_growth']['options'] = ['a']
        self.assertEqual(self.context(s)['construction']['planning_option_count'], 1)

    def test_construction_receipts_are_separate_from_engine_outcomes(self):
        s = state()
        s['world_growth']['completed'] = [dict(option='gate_north_books_cross_tight', spawned=['r1'])]
        s['world_growth']['mission_results'] = [dict(index=i, option='gate_north_books_cross_tight',
            status='failed' if i == 5 else 'completed', duration_seconds=20+i,
            green_start=dict(alive=3, hp_total=150, raw_units='do not send'),
            green_end=dict(alive=2, hp_total=80), friendly_added=0, enemies_initial=3,
            enemies_remaining=1 if i == 5 else 0, spec='do not send') for i in range(6)]
        macro = self.context(s)
        generator = generator_context(macro)
        self.assertEqual(len(macro['recent_mission_results']), 4)
        self.assertEqual(len(generator['recent_mission_results']), 2)
        self.assertEqual(generator['recent_mission_results'][-1]['status'], 'failed')
        self.assertIn('not_proof_of_mission_clear', macro['recent_construction'][0]['status'])
        self.assertNotIn('spec', str(macro['recent_mission_results']))
        self.assertNotIn('raw_units', str(macro['recent_mission_results']))

    def test_model_views_are_bounded_and_do_not_infer_player_skill(self):
        s = state()
        s.update(covers=[dict(collision_geometry='x'*10000)]*100, strategic_topology='x'*10000)
        samples = [observation_sample(state(at=t)) for t in range(61)]
        original = copy.deepcopy(s)
        macro = self.context(s, samples)
        generator = generator_context(macro)
        self.assertEqual(s, original)
        self.assertEqual(macro['human_sample_count'], 0)
        self.assertIn('不能推断玩家技能', generator['evidence_limits'])
        self.assertNotIn('unit_life', str(macro))
        self.assertNotIn('recent_observations', generator)
        self.assertNotIn('collision_geometry', str(macro))
        self.assertLess(context_chars(macro), 5500)
        self.assertLess(context_chars(generator), context_chars(macro))


if __name__ == '__main__':
    unittest.main()
