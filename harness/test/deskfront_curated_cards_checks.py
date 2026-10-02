"""Author-library regressions, not quotas on generated maps or JEV choices."""
import sys
import unittest
from collections import Counter, deque
from pathlib import Path

from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/deskfront'))
sys.path.insert(0, str(DESKFRONT_TOOLS))
from world.authored_cards import AUTHORED_CARDS, CURATED_CARDS, CURATED_ASSET_SCALE, SHAPES, current_dimensions
from world.region_graph import PROPS


def rotated(parts, turn):
    result = []
    for x, z, width, depth, asset, height in parts:
        for _ in range(turn):
            x, z, width, depth = -z, x, depth, width
        result.append((x, z, width, depth, asset, height))
    return result


class CuratedCardChecks(unittest.TestCase):
    def test_purpose_coverage_and_existing_asset_scales(self):
        self.assertEqual(len(CURATED_CARDS), 26)
        self.assertEqual(len(AUTHORED_CARDS), 32)  # Keep saved operations replayable.
        self.assertTrue(all(count >= 3 for count in Counter(c['purpose'] for c in CURATED_CARDS.values()).values()))
        self.assertEqual(len({c['purpose'] for c in CURATED_CARDS.values()}), 8)
        assets = Counter(p[4] for c in CURATED_CARDS.values() for p in c['parts'])
        self.assertEqual(set(assets), set(SHAPES))
        for name, card in CURATED_CARDS.items():
            with self.subTest(card=name):
                self.assertIn(len(card['parts']), (1, 2))
                self.assertTrue(card['composition'] and card['route_character'])
                self.assertTrue(set(card['hero_assets']) <= {p[4] for p in card['parts']})
                for _, _, width, depth, asset, height in card['parts']:
                    dimensions = current_dimensions(asset)
                    self.assertEqual(sorted((width, depth)),
                                     sorted(dimensions[:2]))
                    self.assertEqual(height, dimensions[2])
                self.assertEqual(card['allowed_rotations'], [0, 90, 180, 270])
        for asset in SHAPES:
            self.assertEqual(tuple(PROPS[asset][key] for key in ('width','depth','height')),
                             current_dimensions(asset))
        self.assertGreater(CURATED_ASSET_SCALE['laptop'], CURATED_ASSET_SCALE['mouse'])
        self.assertGreater(CURATED_ASSET_SCALE['warehouse'], CURATED_ASSET_SCALE['tape'])

    def test_binder_and_glue_reach_planner_builder_and_free_placement(self):
        from world.template_cards import cards, inventory, menu
        from world.desk_programmes import _hero_pools
        from world.region_builder import menu_for_cell
        from world.region_graph import CELLS, LIBRARY, validate_graph, compile_graph
        catalog = cards()
        for asset, purpose, card in [('concrete','archive','archive_ringbinder_notes'),
                                     ('drum','hobby','hobby_glue_notebook')]:
            self.assertIn(asset, PROPS)
            self.assertIn(asset, _hero_pools(catalog)[purpose])
            self.assertGreater(inventory()['asset_card_counts'][asset], 0)
            for cell in CELLS:
                self.assertIn(card, menu_for_cell(cell, menu()))
            base = [dict(op='set_ports',entry='c0r1',exit='c2r1')]
            base += [dict(op='place_region',cell=cell,module='study_book_terraces',rotation=0) for cell in CELLS]
            base += [dict(op='connect_regions',edge=edge) for edge in LIBRARY['edges']]
            base += [dict(op='deploy',module='rear')]
            replace = dict(op='edit_component',cell='c1r1',index=0,action='replace',asset=asset,x=.9,z=0,rotation=0)
            add = [dict(op='edit_component',cell='c1r1',index=0,action='remove'),
                   dict(op='place_prop',cell='c1r1',asset=asset,x=.9,z=0,rotation=0)]
            for edits in ([replace],add):
                receipt = validate_graph(base+edits)
                self.assertTrue(receipt['ok'],(asset,edits,receipt))
                actual = [row for row in compile_graph(base+edits)['covers'] if row[4]==asset]
                self.assertEqual(len(actual),1)
                self.assertEqual(tuple(actual[0][i] for i in (2,3,5)),current_dimensions(asset))

    def test_geometry_varies_without_relying_on_prop_names_or_rotation(self):
        # Ignore asset names and normalize rotation: changing a label or a mouse
        # into another tiny prop must not turn a duplicate layout into a new card.
        footprints = {}
        centre_occupied = 0
        counts = set()
        for name, card in CURATED_CARDS.items():
            forms = [tuple(sorted((round(x, 3), round(z, 3), width, depth, height)
                                  for x, z, width, depth, _, height in rotated(card['parts'], turn)))
                     for turn in range(4)]
            footprint = min(forms)
            self.assertNotIn(footprint, footprints, (name, footprints.get(footprint)))
            footprints[footprint] = name
            counts.add(len(card['parts']))
            centre_occupied += any(abs(x) < width / 2 and abs(z) < depth / 2
                                   for x, z, width, depth, _, _ in card['parts'])
        self.assertGreaterEqual(centre_occupied, 5)
        self.assertLess(centre_occupied, 20)
        self.assertEqual(counts, {1, 2})
        self.assertGreaterEqual(sum(len(card['parts']) == 1 for card in CURATED_CARDS.values()), 4)

    def test_all_rotations_have_supported_nonoverlapping_geometry(self):
        for name, card in CURATED_CARDS.items():
            for turn in range(4):
                with self.subTest(card=name, rotation=turn * 90):
                    rows = rotated(card['parts'], turn)
                    for i, (x, z, width, depth, _, _) in enumerate(rows):
                        # Keep the .025 closed-interface dividers clear too,
                        # including when the long desk side rotates to x.
                        self.assertLessEqual(abs(x) + width / 2, .275)
                        self.assertLessEqual(abs(z) + depth / 2, .275)
                        for other in rows[i + 1:]:
                            overlaps = (abs(x - other[0]) < (width + other[2]) / 2
                                        and abs(z - other[1]) < (depth + other[3]) / 2)
                            self.assertFalse(overlaps, (name, i, other))

    def test_each_orientation_connects_selected_edges_when_other_edges_close(self):
        # Same raster and conservative inflation used by the route layer. An
        # authored central obstacle is allowed; it must leave a real way around.
        # Closed interfaces have real .025-wide dividers. Checking only the
        # all-open table missed passages that depended on walking through the
        # neighbouring desk; check all 15 nonempty side combinations for each
        # orientation actually offered to the builder.
        for name, card in CURATED_CARDS.items():
            for turn in (angle // 90 for angle in card['allowed_rotations']):
                with self.subTest(card=name, rotation=turn * 90):
                    rows = rotated(card['parts'], turn)
                    open_nodes = {(i, j) for i in range(-12, 13) for j in range(-14, 15)
                                  if not any(abs(i * .025 - x) < width / 2 + .0401
                                             and abs(j * .025 - z) < depth / 2 + .0401
                                             for x, z, width, depth, _, _ in rows)}
                    for mask in range(1, 16):
                        free = {p for p in open_nodes
                                if (mask & 1 or p[0] >= -9) and (mask & 2 or p[0] <= 9)
                                and (mask & 4 or p[1] >= -11) and (mask & 8 or p[1] <= 11)}
                        connected = False
                        while free:
                            queue = deque([free.pop()])
                            sides = 0
                            while queue:
                                i, j = queue.popleft()
                                if i == -12: sides |= 1
                                if i == 12: sides |= 2
                                if j == -14: sides |= 4
                                if j == 14: sides |= 8
                                for point in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                                    if point in free:
                                        free.remove(point)
                                        queue.append(point)
                            if sides & mask == mask:
                                connected = True
                                break
                        self.assertTrue(connected, (name, turn * 90, mask))


if __name__ == '__main__':
    unittest.main()
