import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'deskfront'))
from deskfront_test_paths import DESKFRONT_ROOT
from world.stage import apply_hooks, PASSING_HOOK

class HookChecks(unittest.TestCase):
    def test_native_avoidance_replaces_complete_expression_without_push_in_fallback(self):
        root=Path(__file__).resolve().parents[1]
        source=(DESKFRONT_ROOT/'scripts/unit.gd').read_text(encoding='utf-8')
        result=apply_hooks(source,[PASSING_HOOK])
        self.assertIn('formation_stability.gd',result)
        fallback=next(line for line in result.splitlines() if 'steered=target' in line)
        self.assertEqual(fallback.rsplit(':',1)[-1], 'steered=target')
        self.assertNotIn('steered=target+apart',result)

    def test_preserves_new_human_squad_guard(self):
        patches=json.loads((Path(__file__).resolve().parents[1]/'src/deskfront/world/hooks.json').read_text(encoding='utf-8'))
        patch=next(p for p in patches if p['name']=='disable_flag_emergency')
        original='func flag_emergency(team: String) -> bool:\n\treturn not human_squad and winner==""\n'
        result=apply_hooks(original,[patch])
        self.assertIn('if growth:return false',result)
        self.assertIn('return not human_squad and winner==""',result)
        for source in ('',original+original):
            with self.assertRaisesRegex(RuntimeError,'disable_flag_emergency'):apply_hooks(source,[patch])

    def test_current_game_all_anchors_match_and_keep_source_checks(self):
        root=Path(__file__).resolve().parents[1]
        source=(DESKFRONT_ROOT/'scripts/game.gd').read_text(encoding='utf-8')
        patches=json.loads((root/'src/deskfront/world/hooks.json').read_text(encoding='utf-8'))
        result=apply_hooks(source,patches)
        self.assertIn('not human_squad',result)
        self.assertLess(result.index('if rejected!="":return ack'),result.index('if action=="grow_world"'))
