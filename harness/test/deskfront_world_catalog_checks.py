"""Regressions for real catalogue variety and freely selected rotations.

These checks concern the authored asset library, never disallow a JEV choice.
"""
import random
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/deskfront'))
from world.authored_cards import AUTHORED_CARDS, CURATED_CARDS, SHAPES
from world.region_graph import (CELLS,LIBRARY,SELECTABLE_MODULES,
    LEGACY_SELECTABLE_MODULES,rotate_cover,validate_graph)


def operations(modules,rotations=None,formation='rear',links=None,entry='c0r1',exit='c2r1'):
    result=[dict(op='set_ports',entry=entry,exit=exit)]
    result += [dict(op='place_region',cell=cell,module=modules[cell],rotation=(rotations or {}).get(cell,0))
               for cell in CELLS]
    result += [dict(op='connect_regions',edge=edge) for edge in (LIBRARY['edges'] if links is None else links)]
    return result+[dict(op='deploy',module=formation)]


class AuthoredCatalogueChecks(unittest.TestCase):
    def test_selectable_cards_are_distinct_even_after_rotation(self):
        sample=LIBRARY['cells']['c1r1'];center=sample['open']['center']
        def signature(rows):
            return tuple(sorted((round(x-center[0],3),round(z-center[1],3),w,d,asset,h)
                                for x,z,w,d,asset,h in rows))
        normalized={}
        for module in SELECTABLE_MODULES:
            variants=[signature([rotate_cover(row,center,turn) for row in sample[module]['covers']])
                      for turn in (0,90,180,270)]
            key=min(variants)
            self.assertNotIn(key,normalized,(module,normalized.get(key)))
            normalized[key]=module
        self.assertEqual(len(normalized),26)
        self.assertEqual(set(SELECTABLE_MODULES),set(CURATED_CARDS))
        self.assertEqual(len(AUTHORED_CARDS),32)

    def test_rich_asset_library_is_represented_without_one_generic_filler(self):
        sample=LIBRARY['cells']['c1r1']
        counts=Counter(row[4] for module in SELECTABLE_MODULES for row in sample[module]['covers'])
        old_filler=sum(counts[k] for k in ('bookstack','crate','file_rack','sandbag'))
        self.assertLess(old_filler/sum(counts.values()),.35)
        self.assertEqual(set(counts),set(SHAPES))
        for hero in ('printer','laptop','tissues','desk_divider','book_city','book_atlas','novel'):
            self.assertGreaterEqual(sum(any(row[4]==hero for row in sample[m]['covers'])
                                        for m in SELECTABLE_MODULES),2,hero)
        for module in SELECTABLE_MODULES:
            part=sample[module]
            self.assertTrue(part.get('purpose'),module)
            self.assertTrue(set(part['hero_assets']) <= {row[4] for row in part['covers']},module)
            self.assertIn(len(part['covers']),(1,2),module)
            # Thin books are intentional low cover; don't force them into
            # tall bricks just to satisfy a high-cover density metric.
            substantial=[row for row in part['covers'] if row[5]>=.04 and max(row[2:4])>=.14]
            self.assertGreaterEqual(len(substantial),1,module)
            self.assertGreaterEqual(sum(row[2]*row[3] for row in substantial),.025,module)

    def test_every_offered_rotation_can_build_in_a_mixed_board(self):
        # A card can be offered even when nine identical copies would collide
        # with a deployment point; validate an actual mixed placement instead.
        for module in SELECTABLE_MODULES:
            for turn in CURATED_CARDS[module]['allowed_rotations']:
                with self.subTest(module=module,turn=turn):
                    modules=dict.fromkeys(CELLS,'code_laptop_island')
                    modules['c1r1']=module
                    rotations=dict.fromkeys(CELLS,270)
                    rotations['c1r1']=turn
                    result=validate_graph(operations(modules,rotations))
                    self.assertTrue(result['ok'],result)

    def test_mixed_rotations_and_closed_connections_preserve_authored_geometry(self):
        rng=random.Random(9282026)
        modules=[m for m in SELECTABLE_MODULES if m!='empty']
        # A spanning snake gives real closed interfaces as well as all-open
        # examples. Objects must stay clear of those actual divider footprints.
        route=['c0r0','c0r1','c0r2','c1r2','c1r1','c1r0','c2r0','c2r1','c2r2']
        links=[next(key for key,edge in LIBRARY['edges'].items() if {edge['a'],edge['b']}=={a,b})
               for a,b in zip(route,route[1:])]
        for index in range(32):
            chosen={cell:rng.choice(modules) for cell in CELLS}
            turns={cell:rng.choice((0,90,180,270)) for cell in CELLS}
            result=validate_graph(operations(chosen,turns,formation=('rear','distributed','forward','layered')[index%4],
                links=links if index%2 else None,entry='c0r0',exit='c2r2'))
            self.assertTrue(result['ok'],(index,result))

    def test_old_rotated_ids_remain_available_for_saved_operation_replay(self):
        old_ids=[m for m in LEGACY_SELECTABLE_MODULES if m.rsplit('_',1)[-1] in ('0','1','2','3')]
        self.assertEqual(len(old_ids),32)
        self.assertFalse(set(old_ids)&set(SELECTABLE_MODULES))
        for module in old_ids:
            self.assertIn(module,LIBRARY['cells']['c1r1'])
        # Preserve the historically exact duplicate, rather than rewriting it
        # on replay to masquerade as a new card.
        self.assertEqual(sorted(LIBRARY['cells']['c1r1']['advance_0']['covers']),
                         sorted(LIBRARY['cells']['c1r1']['advance_2']['covers']))


if __name__=='__main__':unittest.main()
