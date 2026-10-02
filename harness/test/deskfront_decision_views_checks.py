"""Decision input compression preserves evidence and construction authority."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from world.decision_views import builder_view, design_view
from world.template_cards import MODEL_CARD_COLUMNS, cards, model_card_row


class DecisionViewsChecks(unittest.TestCase):
    def test_only_equal_redundant_counts_are_removed(self):
        original = dict(cells={'c0r0': dict(props=['mouse', 'mouse'],
            props_basis='native observation', visual_identity=dict(material_counts={'mouse': 2})),
            'c1r0': dict(props=['mouse'], props_basis='compiled observation',
                visual_identity=dict(material_counts={'mouse': 9}))},
            materials={'mouse': 3}, material_profile=dict(counts={'mouse': 3}, shares={'mouse': 1}, source='native_spec'),
            battle_result=dict(deaths=None, shots=12), static_exposure=dict(main=None))
        frozen = copy.deepcopy(original)
        view = design_view(original)
        self.assertEqual(original, frozen)
        self.assertNotIn('material_counts', view['cells']['c0r0']['visual_identity'])
        self.assertEqual(view['cells']['c1r0']['visual_identity']['material_counts'], {'mouse': 9})
        self.assertEqual(view['cell_material_basis'], {'c0r0': 'native observation', 'c1r0': 'compiled observation'})
        self.assertNotIn('counts', view['material_profile'])
        self.assertEqual(view['materials'], original['materials'])
        self.assertEqual(view['battle_result'], original['battle_result'])
        self.assertEqual(view['static_exposure'], original['static_exposure'])

    def test_custom_tasks_are_preserved_and_structured_goals_are_complete(self):
        legacy = dict(task=dict(build_directive='保留特别指令', custom_design='特殊要求'))
        self.assertEqual(builder_view(legacy), legacy)
        goal = dict(tactical_relation='掩护侧路', scene='左右错列', visual='阅读与办公',
            next_goal=dict(layout_change='增加遮挡', uncertainty=None))
        context = dict(task=dict(option='x', mission_kind='assault', forces=dict(enemy_count=3),
            spatial_goal=goal, build_directive='重复文字', request_id='trace'))
        self.assertEqual(builder_view(context)['task']['spatial_goal'], goal)
        self.assertNotIn('build_directive', builder_view(context)['task'])
        self.assertIn('build_directive', context['task'])

    def test_builder_preserves_names_and_card_geometry_while_sharing_dimensions(self):
        full = {key: model_card_row(value) for key, value in cards().items()}
        context = dict(stage='layout_draft', template_columns=list(MODEL_CARD_COLUMNS),
            template_item_columns=['asset', 'offset_x', 'offset_z', 'width', 'depth', 'height'],
            templates=full, asset_catalog={'mouse': ['鼠标', .1, .08, .04]},
            asset_columns=['name', 'width', 'depth', 'height'])
        frozen = copy.deepcopy(context)
        for stage in ('layout_draft', 'batch_revision'):
            view = builder_view(dict(context, stage=stage))
            self.assertEqual(view['templates'], full)
            self.assertEqual(view['template_columns'], list(MODEL_CARD_COLUMNS))
            self.assertEqual(view['template_item_columns'], context['template_item_columns'])
            self.assertEqual(view['asset_catalog'], {'mouse': ['鼠标']})
            self.assertEqual(view['asset_columns'], ['name'])
        detail = builder_view(dict(context, stage='prop_edit_details'))
        self.assertEqual(detail['asset_catalog'], frozen['asset_catalog'])
        self.assertEqual(detail['asset_columns'], frozen['asset_columns'])
        self.assertEqual(context, frozen)



if __name__ == '__main__':
    unittest.main()
