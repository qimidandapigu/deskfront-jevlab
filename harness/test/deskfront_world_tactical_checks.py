import sys,unittest,copy
from pathlib import Path
from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src/deskfront'),str(DESKFRONT_TOOLS)]
from world.tactical_quality import clear_ray,assess,compositions
from world.region_builder import select_graph_menu,region_roles

class TacticalChecks(unittest.TestCase):
    def test_height_and_blockage_change_actual_ray_result(self):
        wall=[[.6,0,.1,.5,'bookstack',.26]]
        self.assertFalse(clear_ray([0,0],[1,0],wall))
        self.assertTrue(clear_ray([0,.4],[1,.4],wall))
        self.assertTrue(clear_ray([0,0],[1,0],[[.6,0,.1,.5,'sandbag',.043]]))

    def test_cover_changes_route_exposure(self):
        spec=dict(design_card=dict(main_regions=['c0r1','c1r1','c2r1'],flank_regions=['c0r1','c0r0','c1r0','c2r0','c2r1']),
            defender_slots=[[1.3,0,'rifle','guard']],covers=[[.9,-.35,.5,.08,'bookstack',.26]])
        covered=assess(spec,1);spec['covers']=[];bare=assess(spec,1)
        self.assertLess(covered['flank']['exposed_fraction'],bare['flank']['exposed_fraction'])
        self.assertEqual(covered['main']['exposed_fraction'],bare['main']['exposed_fraction'])

    def test_joint_choices_are_playable_and_have_honest_metrics(self):
        graph=next(iter(select_graph_menu(dict(option='court_north_books_depth_tight')).values()))
        choices=compositions(graph,region_roles(graph),3)
        self.assertTrue(choices)
        for c in choices.values():
            self.assertTrue(c['validation']['ok'])
            self.assertTrue(c['quality']['distinct_routes'])
            self.assertIn('static',c['quality']['basis'])
            self.assertGreater(c['quality']['main']['samples'],0)

if __name__=='__main__':unittest.main()
