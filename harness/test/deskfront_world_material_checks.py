"""Material evidence must describe the built objects, not changing card names."""
import copy
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
from world.design_memory import describe, material_comparison, material_profile, similarity
from world.region_graph import CELLS, LIBRARY, compile_graph


def operations(module='advance_0'):
    return ([dict(op='set_ports', entry='c0r1', exit='c2r1')]
        + [dict(op='place_region', cell=cell, module=module, rotation=0) for cell in CELLS]
        + [dict(op='connect_regions', edge=edge) for edge in LIBRARY['edges']]
        + [dict(op='deploy', module='rear')])


class MaterialEvidenceChecks(unittest.TestCase):
    def test_profile_makes_dominant_materials_visible(self):
        profile = material_profile(dict(bookstack=9, crate=8, file_rack=9,
            mouse=1, desk_divider=1, concrete=1, sandbag=2))
        self.assertEqual(profile['total'], 31)
        self.assertEqual(profile['unique_types'], 7)
        self.assertEqual(profile['dominant_three'], ['bookstack', 'file_rack', 'crate'])
        self.assertAlmostEqual(profile['dominant_three_share'], 26/31, places=4)
        self.assertAlmostEqual(profile['shares']['mouse'], 1/31, places=4)

    def test_comparison_distinguishes_types_from_repeated_object_counts(self):
        current = dict(materials=dict(bookstack=9, crate=8, file_rack=9,
            mouse=1, desk_divider=1, concrete=1, sandbag=2))
        reference = dict(materials=dict(bookstack=9, crate=8, file_rack=7,
            fort_wall=7, sandbag=1))
        before = copy.deepcopy((current, reference))
        report = material_comparison(current, reference)
        self.assertEqual(report['type_jaccard'], .5)
        self.assertEqual(report['shared_object_count'], 25)
        self.assertAlmostEqual(report['shared_object_share_current'], 25/31, places=4)
        self.assertAlmostEqual(report['shared_object_share_reference'], 25/32, places=4)
        self.assertAlmostEqual(report['current_objects_using_reference_assets_share'], 28/31, places=4)
        self.assertEqual((current, reference), before)

    def test_card_changes_do_not_hide_complete_material_reuse(self):
        first = describe(operations('advance_0'))
        second = copy.deepcopy(first)
        for cell in second['cells'].values():
            cell['family'] = 'different_name'
        self.assertLess(similarity(first, second), 1)
        material = material_comparison(second, first)
        self.assertEqual(material['type_jaccard'], 1)
        self.assertEqual(material['shared_object_share_current'], 1)

    def test_per_cell_materials_include_remove_replace_and_add(self):
        ops = operations()
        original = describe(ops)
        cell = 'c1r1'
        cx, cz = LIBRARY['cells'][cell]['advance_0']['center']
        ops += [dict(op='edit_component', cell=cell, index=0, action='replace',
                    asset='printer', x=cx-.10, z=cz-.19, rotation=0),
                dict(op='edit_component', cell=cell, index=1, action='remove'),
                dict(op='place_prop', cell=cell, asset='phone', x=cx+.16, z=cz+.18, rotation=0)]
        actual = describe(ops)
        self.assertNotIn('bookstack', actual['cells'][cell]['props'])
        self.assertIn('printer', actual['cells'][cell]['props'])
        self.assertIn('phone', actual['cells'][cell]['props'])
        self.assertEqual(actual['cells']['c0r0']['props'], original['cells']['c0r0']['props'])
        per_cell = Counter(asset for part in actual['cells'].values() for asset in part['props'])
        self.assertEqual(dict(per_cell), actual['materials'])
        self.assertEqual(actual['materials'], dict(Counter(row[4] for row in compile_graph(ops)['covers'])))
        self.assertEqual(actual['cells'][cell]['visual_identity']['material_counts'],
            dict(Counter(actual['cells'][cell]['props'])))

    def test_edge_barrier_is_counted_without_assigning_it_to_a_desk(self):
        ops = operations()
        ops = [op for op in ops if not (op['op']=='connect_regions' and op['edge']=='c0r0__c1r0')]
        actual = describe(ops)
        self.assertEqual(actual['materials']['concrete'], 1)
        self.assertNotIn('concrete', [asset for part in actual['cells'].values() for asset in part['props']])

    def test_legacy_library_card_and_native_float_operations_still_describe(self):
        ops = operations('flank_3')
        for op in ops:
            if op['op'] == 'place_region':
                op['rotation'] = 0.0
        before = copy.deepcopy(ops)
        actual = describe(ops)
        self.assertEqual(len(actual['cells']), 9)
        self.assertEqual(actual['cells']['c1r1']['card'], 'flank_3')
        self.assertGreater(actual['material_profile']['total'], 0)
        self.assertEqual(ops, before)

    def test_rescue_walls_belong_to_rescue_cell(self):
        ops = operations()
        for op in ops:
            if op['op']=='place_region' and op['cell']=='c2r1':
                op['module']='fortress_base'
        actual = describe(ops)
        self.assertEqual(actual['cells']['c2r1']['props'].count('fort_wall'), 7)
        self.assertEqual(actual['materials']['fort_wall'], 7)

    def test_empty_evidence_does_not_claim_similarity(self):
        self.assertEqual(material_profile({})['dominant_three_share'], 0)
        self.assertIsNone(material_comparison(None, dict(materials={})))
        self.assertIsNone(material_comparison(dict(materials={}), dict(materials={}))['type_jaccard'])

    def test_native_geometry_overrides_current_catalog_and_old_edit_indices(self):
        ops = operations()
        # This was a valid historical component index, but the current card no
        # longer has it. Reading an authoritative receipt must not recompile it.
        ops.append(dict(op='edit_component', cell='c0r0', index=99, action='remove'))
        native = dict(covers=[[.3, -.7, .10, .10, 'mouse', .045],
                             [.9, 0, .20, .16, 'printer', .16]])
        before = copy.deepcopy((ops, native))
        actual = describe(ops, actual_spec=native)
        self.assertEqual(actual['materials'], dict(mouse=1, printer=1))
        self.assertEqual(actual['material_profile']['source'], 'native_spec')
        self.assertEqual(actual['cells']['c0r0']['props'], ['mouse'])
        self.assertEqual(actual['cells']['c1r1']['props'], ['printer'])
        self.assertEqual(actual['cells']['c2r2']['props'], [])
        self.assertEqual((ops, native), before)

    def test_native_fortress_and_boundary_objects_are_not_double_counted(self):
        ops = operations()
        for op in ops:
            if op['op']=='place_region' and op['cell']=='c2r1':
                op['module']='fortress_base'
        barrier = copy.deepcopy(LIBRARY['edges']['c0r0__c1r0']['barrier'])
        native = dict(covers=[barrier, [1.42, -.205, .055, .23, 'fort_wall', .2],
            [1.42, .205, .055, .23, 'fort_wall', .2],
            [.6, 0, .08, .08, 'tape', .05]])
        actual = describe(ops, actual_spec=native)
        self.assertEqual(actual['materials'], dict(concrete=1, fort_wall=2, tape=1))
        self.assertEqual(actual['material_profile']['total'], 4)
        self.assertEqual(actual['non_cell_materials'], dict(edge_barriers=dict(concrete=1),
            fortress_walls=dict(fort_wall=2), unassigned=dict(tape=1)))
        self.assertEqual(actual['cells']['c2r1']['props'], [])

    def test_empty_native_cover_list_remains_empty(self):
        actual = describe(operations(), actual_spec=dict(covers=[]))
        self.assertEqual(actual['materials'], {})
        self.assertEqual(actual['material_profile']['source'], 'native_spec')
        self.assertEqual(actual['material_profile']['total'], 0)
        self.assertTrue(all(not cell['props'] for cell in actual['cells'].values()))


if __name__ == '__main__':
    unittest.main()
