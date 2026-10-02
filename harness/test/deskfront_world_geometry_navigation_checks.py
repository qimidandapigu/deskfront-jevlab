"""A desk's route follows its final obstacles, rather than a reserved centre."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/deskfront'))
from world.assembly import validate
from world.region_graph import (CELLS,LIBRARY,compile_graph,clear_grid,nav_index,
    SELECTABLE_MODULES)


def recipe(module='code_laptop_island',turn=0,formation='distributed'):
    return ([dict(op='place_region',cell=cell,module=module,rotation=turn) for cell in CELLS]
        +[dict(op='connect_regions',edge=edge) for edge in LIBRARY['edges']]
        +[dict(op='deploy',module=formation)])


class GeometryNavigationChecks(unittest.TestCase):
    def assert_routes_clear(self,spec):
        nodes=clear_grid(tuple(tuple(row) for row in spec['covers']))
        for route in (spec['main_route'],spec['flank']):
            for a,b in zip(route,route[1:]):
                first,last=nav_index(a),nav_index(b)
                self.assertTrue(first[0]==last[0] or first[1]==last[1],(a,b))
                count=abs(last[0]-first[0])+abs(last[1]-first[1])
                for step in range(count+1):
                    point=(first[0]+(0 if first[0]==last[0] else 1 if first[0]<last[0] else -1)*step,
                           first[1]+(0 if first[1]==last[1] else 1 if first[1]<last[1] else -1)*step)
                    self.assertIn(point,nodes,(a,b,point))

    def test_central_hero_is_preserved_and_routes_bend_around_it(self):
        operations=recipe();spec=compile_graph(operations)
        expected=[row for cell in CELLS for row in LIBRARY['cells'][cell]['code_laptop_island']['covers']]
        self.assertEqual(spec['covers'],expected)
        self.assertEqual(spec['build_operations'],operations)
        self.assertEqual(spec['design_card']['navigation'],'geometry_grid_v1')
        self.assertNotEqual(spec['design_card']['region_anchors']['c1r1'],[.9,0])
        self.assertGreater(len(spec['main_route']),3)
        spec['friendlies']=spec['friendly_slots']
        self.assertTrue(validate(spec)['ok'],validate(spec))
        self.assert_routes_clear(spec)

    def test_all_curated_rotations_have_clear_native_route_segments_and_deployments(self):
        for module in SELECTABLE_MODULES:
            for turn in (0,90,180,270):
                with self.subTest(module=module,turn=turn):
                    spec=compile_graph(recipe(module,turn))
                    spec['friendlies']=spec['friendly_slots']
                    self.assertTrue(validate(spec)['ok'],validate(spec))
                    self.assert_routes_clear(spec)

    def test_actual_blocked_edge_is_reported_not_rerouted_or_repaired(self):
        cell='c1r1';module='geometry_test_sealed'
        source=LIBRARY['cells'][cell]['open']
        temporary=copy.deepcopy(source)
        temporary.update(layout='sealed_test',covers=[[.9,0,.52,.055,'desk_divider',.25]])
        LIBRARY['cells'][cell][module]=temporary
        try:
            operations=recipe()
            next(op for op in operations if op.get('cell')==cell)['module']=module
            with self.assertRaisesRegex(ValueError,'blocked_region_connection'):
                compile_graph(operations)
        finally:del LIBRARY['cells'][cell][module]

    def test_rescue_routes_are_recomputed_after_the_real_fortress_walls_exist(self):
        from world.fortress import apply
        for row in range(3):
            operations=recipe()
            exit_cell=f'c2r{row}'
            next(op for op in operations if op.get('cell')==exit_cell)['module']='fortress_base'
            operations.insert(0,dict(op='set_ports',entry='c0r1',exit=exit_cell))
            original=compile_graph(operations);spec=apply(original)
            self.assertEqual(spec['exit'],[1.6,(row-1)*.7])
            self.assertNotEqual(spec['main_route'],original['main_route'])
            self.assertTrue(validate(spec)['ok'],validate(spec))
            self.assert_routes_clear(spec)


if __name__=='__main__':unittest.main()
