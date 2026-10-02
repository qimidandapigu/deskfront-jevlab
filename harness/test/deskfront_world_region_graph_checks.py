import copy
import json
import sys
import unittest
from pathlib import Path
from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/deskfront'))
sys.path.insert(0,str(DESKFRONT_TOOLS))
from world.region_graph import CELLS,LIBRARY,PROPS,SELECTABLE_MODULES,WORKSHOP_STYLE_COUNT,compile_graph,inspect_regions,validate_graph

def recipe(occupied,formation='rear'):
    ops=[dict(op='place_region',cell=k,module='open' if k in occupied else 'empty') for k in CELLS]
    ops += [dict(op='connect_regions',edge=k) for k,e in LIBRARY['edges'].items() if e['a'] in occupied and e['b'] in occupied]
    return ops+[dict(op='deploy',module=formation)]

class GraphChecks(unittest.TestCase):
    def test_intents_have_legal_graphs_without_overriding_jev_repetition_choice(self):
        from world.region_builder import select_graph_menu
        from world.catalog import CATALOG
        for option in CATALOG:
            task=dict(option=option)
            menu=select_graph_menu(task)
            self.assertTrue(menu,option)
            side='c1r0' if '_north_' in option else 'c1r2'
            for row in menu.values():
                self.assertIn(side,row['graph']['main_regions']+row['graph']['flank_regions'])
                if option.startswith('court_'):self.assertTrue(row['graph']['alternate_route'])
            first=next(iter(menu.values()))
            task['recent_builds']=[first['operations']]
            fresh=select_graph_menu(task)
            self.assertEqual(list(fresh),list(menu),option)

    def test_recent_route_remains_available_for_jev_to_choose(self):
        from world.region_builder import select_graph_menu
        task=dict(option='gate_north_books_depth_tight')
        first=next(iter(select_graph_menu(task).values()))
        ops=first['operations']+[dict(op='connect_regions',edge=e) for e in first['edges']]+[dict(op='deploy',module='rear')]
        task['recent_builds']=[ops]
        menu=select_graph_menu(task)
        self.assertTrue(any(v['graph']['main_regions']==first['graph']['main_regions'] for v in menu.values()))

    def test_every_composite_rotation_preserves_paths_and_deployment(self):
        for cell in CELLS:
            if cell in ('c0r1','c2r1'):continue  # Legacy default ports must remain clear.
            for module,part in LIBRARY['cells'][cell].items():
                if module=='empty' or 'family' not in part or part.get('ports',15)!=15:continue
                ops=recipe(set(CELLS),'distributed')
                next(o for o in ops if o.get('cell')==cell)['module']=module
                receipt=validate_graph(ops)
                self.assertTrue(receipt['ok'],(cell,module,receipt))
                self.assertGreaterEqual(len(part['covers']),1 if module in SELECTABLE_MODULES else 2)

    def test_ground_is_continuous_and_components_supply_shapes(self):
        from world.assembly import supported
        cell=LIBRARY['cells']['c1r1']
        elbow=cell['workshop_screen_9_0']
        cross=cell['workshop_screen_15_0']
        self.assertEqual(elbow['floors'],cross['floors'])
        self.assertTrue(supported(elbow['floors'],.65,-.25))
        self.assertTrue(supported(elbow['floors'],1.15,0))
        self.assertTrue(supported(elbow['floors'],.9,.3))
        assets={c[4] for p in cell.values() for c in p['covers']}
        self.assertTrue({'concrete','mouse','novel','tissues','mug','ruler','tape','gabion'}<=assets)

    def test_desks_have_distinct_compositions_and_consistent_scale(self):
        cell=LIBRARY['cells']['c1r1']
        layouts=[cell[f'workshop_screen_15_{style}']['covers'] for style in range(WORKSHOP_STYLE_COUNT)]
        signatures={tuple(sorted(item[4] for item in layout)) for layout in layouts}
        self.assertEqual(len(signatures),WORKSHOP_STYLE_COUNT)
        office={item[4]:item for item in layouts[3]}
        self.assertLessEqual(office['mouse'][2]*2,office['laptop'][2])
        self.assertLess(office['novel'][5],office['laptop'][5])
        self.assertLess(cell['empty']['covers'][0][2],.6)

    def test_every_selectable_desk_has_real_cover_and_all_cards_remain_selectable(self):
        from world.template_cards import cards, menu
        from world.region_builder import menu_for_cell
        catalog=cards();options=menu()
        self.assertEqual(len(options),26)
        self.assertNotIn('fortress_base',options)
        signatures={tuple((tuple(item['offset']),tuple(item['size']),item['asset'],item['height'])
                          for item in catalog[module]['items']) for module in options}
        self.assertEqual(len(signatures),26)
        for cell in CELLS:
            self.assertEqual(set(menu_for_cell(cell,options)),set(options))
        self.assertNotEqual(next(iter(menu_for_cell('c0r0',options))),
                            next(iter(menu_for_cell('c2r0',options))))
        for module in options:
            if module=='empty':continue  # Closed warehouse is an obstacle, not a traversable cell.
            self.assertIn(len(catalog[module]['items']),(1,2),module)
            self.assertEqual(catalog[module]['functional_cover_count'],sum(
                item['height']>=.07 and max(item['size'])>=.14 for item in catalog[module]['items']),module)
            # Low books are real objects, but must not count as high cover.
            effective_area=sum(item['size'][0]*item['size'][1] for item in catalog[module]['items']
                               if item['height']>=.04)
            self.assertGreaterEqual(effective_area+.00001,.025,module)
            ops=[dict(op='set_ports',entry='c0r1',exit='c2r1')]
            ops += [dict(op='place_region',cell=cell,
                module=module if cell=='c1r1' else 'code_laptop_island',
                rotation=catalog[module]['allowed_rotations'][0] if cell=='c1r1' else 270)
                for cell in CELLS]
            ops += [dict(op='connect_regions',edge=edge) for edge in LIBRARY['edges']]
            ops.append(dict(op='deploy',module='rear'))
            self.assertTrue(validate_graph(ops)['ok'],module)

    def test_rescue_perimeter_guards_fit_beside_every_selectable_card(self):
        from world.assembly import validate
        from world.fortress import apply as fortify
        from world.region_graph import SELECTABLE_MODULES
        for fortress_cell in ('c2r0','c2r1','c2r2'):
            for other in ('c2r0','c2r1','c2r2'):
                if other==fortress_cell:continue
                for module in SELECTABLE_MODULES:
                    if module=='empty':continue
                    ops=[dict(op='set_ports',entry='c0r1',exit=fortress_cell)]
                    ops += [dict(op='place_region',cell=cell,module=(
                        'fortress_base' if cell==fortress_cell else module if cell==other else 'open'))
                        for cell in CELLS]
                    ops += [dict(op='connect_regions',edge=edge) for edge in LIBRARY['edges']]
                    ops.append(dict(op='deploy',module='rear'))
                    receipt=validate(fortify(compile_graph(ops),3))
                    self.assertTrue(receipt['ok'],(fortress_cell,other,module,receipt))

    def test_builder_can_add_regions_branch_and_merge(self):
        straight={'c0r1','c1r1','c2r1'}
        ring=set(CELLS)-{'c1r1'}
        small=compile_graph(recipe(straight));large=compile_graph(recipe(ring))
        self.assertEqual(small['design_card']['regions'],3)
        self.assertFalse(small['design_card']['alternate_route'])
        self.assertEqual(large['design_card']['regions'],8)
        self.assertTrue(large['design_card']['alternate_route'])
        self.assertEqual(small['floors'],large['floors'])
        self.assertNotEqual(small['covers'],large['covers'])
        self.assertTrue(validate_graph(recipe(straight))['ok'])
        self.assertTrue(validate_graph(recipe(ring))['ok'])

    def test_ports_are_chosen_and_all_nine_cells_can_be_active(self):
        all_cells=set(CELLS)
        ops=[dict(op='set_ports',entry='c0r0',exit='c2r2')]+recipe(all_cells)
        spec=compile_graph(ops)
        self.assertEqual(spec['design_card']['regions'],9)
        self.assertEqual(spec['design_card']['entry_cell'],'c0r0')
        self.assertEqual(spec['design_card']['exit_cell'],'c2r2')
        self.assertEqual(spec['entry'],[.06,-.7])
        self.assertEqual(spec['exit'],[1.72,.7])
        self.assertTrue(validate_graph(ops)['ok'])
        top={'c0r0','c1r0','c2r0'}
        ops=[dict(op='set_ports',entry='c0r0',exit='c2r0')]+recipe(top)
        self.assertTrue(validate_graph(ops)['ok'])
        self.assertEqual(compile_graph(ops)['design_card']['regions'],3)

    def test_unselected_ground_is_solid_building_and_closed_edges_have_walls(self):
        ops=recipe({'c0r1','c1r1','c2r1'})
        spec=compile_graph(ops)
        self.assertEqual(spec['floors'],[[0,-1.05,1.8,1.05]])
        self.assertEqual(sum(c[4]=='warehouse' for c in spec['covers']),6)
        ops=recipe(set(CELLS))
        edge='c1r0__c1r1'
        ops=[o for o in ops if o.get('edge')!=edge]
        spec=compile_graph(ops)
        self.assertIn(LIBRARY['edges'][edge]['barrier'],spec['covers'])
        self.assertTrue(validate_graph(ops)['ok'])

    def test_disconnected_and_unknown_operations_rejected(self):
        ops=recipe({'c0r1','c1r1','c2r1'})
        ops=[o for o in ops if o.get('edge')!='c1r1__c2r1']
        self.assertEqual(validate_graph(ops)['reason'],'disconnected_regions')
        ops=recipe(set(CELLS));ops.append(dict(op='invented'))
        self.assertFalse(validate_graph(ops)['ok'])

    def test_placement_feedback_finds_isolated_module(self):
        ops=recipe({'c0r1','c2r1','c0r0'})
        receipt=inspect_regions(ops)
        self.assertFalse(receipt['ok']);self.assertIn('c2r1',receipt['unreachable'])

    def test_contents_and_deployment_are_derived_from_selected_regions(self):
        ops=recipe(set(CELLS),'distributed')
        for op in ops:
            if op.get('cell')=='c1r0':op['module']='books'
        spec=compile_graph(ops)
        self.assertEqual(len(spec['covers']),27)
        self.assertEqual(sum(row[4]=='bookstack' for row in spec['covers']),9)
        self.assertTrue(validate_graph(ops)['ok'])
        self.assertGreater(len({tuple(r[:2]) for r in spec['defender_slots']}),1)

    def test_individual_prop_choices_change_geometry_and_reject_bad_placements(self):
        ops=recipe(set(CELLS))
        prop=dict(op='place_prop',cell='c0r0',asset='bookstack',x=.14,z=-.7,rotation=0)
        one=ops+[prop]
        another=ops+[dict(prop,asset='mouse',x=.14,z=-.7,rotation=90)]
        self.assertTrue(validate_graph(one)['ok'])
        self.assertTrue(validate_graph(another)['ok'])
        self.assertNotEqual(compile_graph(one)['covers'],compile_graph(another)['covers'])
        self.assertEqual(compile_graph(one)['design_card']['placed_props'],1)
        self.assertEqual(validate_graph(ops+[dict(prop,x=.49)])['reason'],'prop_outside_cell')
        self.assertEqual(validate_graph(ops+[dict(prop,asset='unknown')])['reason'],'invalid_prop')

    def test_authored_book_and_archive_box_are_available_to_place_and_export(self):
        from world.authored_cards import current_dimensions
        exported=json.loads(json.dumps(LIBRARY))['props']
        for asset in ('novel','warehouse'):
            with self.subTest(asset=asset):
                item=PROPS[asset]
                self.assertEqual(tuple(item[k] for k in ('width','depth','height')),current_dimensions(asset))
                self.assertEqual(exported[asset],item)
                # The current warehouse is wider than the old socket. Use a
                # placement that remains legal for both current book and box.
                ops=recipe(set(CELLS))+[dict(op='place_prop',cell='c0r0',asset=asset,
                    x=.2,z=-.7,rotation=0)]
                self.assertTrue(validate_graph(ops)['ok'])
                self.assertIn([.2,-.7,item['width'],item['depth'],asset,item['height']],
                    compile_graph(ops)['covers'])

    def test_authored_book_and_archive_box_can_replace_a_template_component(self):
        original=LIBRARY['cells']['c0r0']['open']['covers'][0]
        for asset in ('novel','warehouse'):
            with self.subTest(asset=asset):
                item=PROPS[asset]
                ops=recipe(set(CELLS))+[dict(op='edit_component',cell='c0r0',index=0,
                    action='replace',asset=asset,x=original[0],z=original[1],rotation=90)]
                self.assertTrue(validate_graph(ops)['ok'])
                self.assertEqual(compile_graph(ops)['covers'][0],
                    [original[0],original[1],item['depth'],item['width'],asset,item['height']])

if __name__=='__main__':unittest.main()
