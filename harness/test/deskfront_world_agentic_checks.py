"""Agent boundaries and unchanged JEV stationery placement."""
import sys
import unittest
from pathlib import Path

from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src/deskfront'),
              str(DESKFRONT_TOOLS)]

from world.director import validate_macro
from world.generation_agents import plan
from world.region_builder import build,assemble_props,graph_candidates,placement_menu,decode_placement,encode_placement
from world.region_graph import LIBRARY, SELECTABLE_MODULES
from world.catalog import DESCRIPTIONS
from world.design_memory import describe, similarity
from world.layout_patterns import PATTERNS, connections as pattern_connections
from world.template_cards import cards as template_cards, model_card


class RealShapeGame:
    config={'backend':'jev'}

    def __init__(self,invalid=False,close_edge=False):
        self.calls=[]
        self.records=[]
        self.invalid=invalid
        self.close_edge=close_edge

    def record(self,row):
        self.records.append(row)

    def ask(self,context,questions,role=None):
        self.calls.append((context,questions))
        number=len(self.calls)
        answers={}
        for key,question in questions.items():
            menu=question['criteria'];choice=next(iter(menu))
            if key=='blueprint':choice='gate_north_books_cross_tight'
            if key=='mission_kind':choice='assault'
            if key=='force_package':choice='f0_e3' if 'f0_e3' in menu else next(iter(menu))
            if key=='tactical_approach':choice='flank_pressure'
            if key=='entry_cell':choice='c0r0'
            if key=='exit_cell':choice='c2r0'
            if key=='template_c0r2':choice=encode_placement('code_laptop_island',0)
            if key=='edit_c0r2_action':choice='add' if self.invalid else 'remove_0'
            if key=='edit_c0r2_asset':choice='printer'
            if key=='edit_c0r2_x':choice='-0.16' if self.invalid else '0'
            if key=='edit_c0r2_z':choice='-0.18' if self.invalid else '0'
            if key.endswith('_rotation'):choice='0'
            if key=='deployment':choice='rear'
            if key=='layout_pattern' and self.close_edge:choice='central_gate'
            answers[key]=dict(type='choice',choice=choice,confidence=1,
                probabilities={option:int(option==choice) for option in menu})
        return dict(requestId=str(number),answers=answers)


class AgenticChecks(unittest.TestCase):
    def test_shared_card_columns_preserve_geometry_and_explicit_cell_tasks(self):
        game=RealShapeGame()
        task=dict(option='gate_north_books_cross_tight',mission_kind='assault',forces=dict(enemy_count=3),
                  layout_brief=dict(desks={'c0r0':dict(purpose='coding',hero_assets=['laptop'],
                      role='掩护推进',neighbor_relation='连接隔壁工作区')}))
        build(game,task,lambda:None)
        draft,questions=game.calls[0]
        from world.region_builder import CARD_ALIAS
        for module,alias in CARD_ALIAS.items():
            decoded=dict(zip(draft['template_columns'],draft['templates'][alias]))
            self.assertEqual(decoded,model_card(template_cards()[module]))
        self.assertIn('用途=coding',questions['template_c0r0']['instructions'])
        self.assertIn('笔记本电脑',questions['template_c0r0']['instructions'])
        self.assertIn('连接隔壁工作区',questions['template_c0r0']['instructions'])
        revision=game.calls[1][0]
        logged=game.records[0]['technical_preview']
        self.assertIn('walkable_cells',logged)
        self.assertNotIn('walkable_cells',revision['technical_preview'])
        self.assertEqual(logged['tactical_estimate'],revision['technical_preview']['tactical_estimate'])
        self.assertEqual(logged['graph']['region_anchors'],revision['technical_preview']['graph']['region_anchors'])

    def test_structured_builder_goal_keeps_exact_geometry_and_local_instructions(self):
        game=RealShapeGame()
        goal=dict(tactical_relation='正面牵制，侧路推进',scene='左右错列',visual='办公与阅读相邻',
            next_goal=dict(route_preference='flank',avoid='不重复上一关'))
        task=dict(option='gate_north_books_cross_tight',forces=dict(enemy_count=3),
            spatial_goal=goal,build_directive='重复目标文字',
            layout_brief=dict(desks={'c0r0':dict(purpose='coding',hero_assets=['laptop'],
                role='掩护推进',neighbor_relation='连接隔壁工作区')}))
        build(game,task,lambda:None)
        draft,questions=game.calls[0]
        self.assertEqual(draft['task']['spatial_goal'],goal)
        self.assertNotIn('build_directive',draft['task'])
        self.assertIn('用途=coding',questions['template_c0r0']['instructions'])
        self.assertIn('连接隔壁工作区',questions['template_c0r0']['instructions'])
        from world.region_builder import CARD_ALIAS
        for module,alias in CARD_ALIAS.items():
            summary=dict(zip(draft['template_columns'],draft['templates'][alias]))
            self.assertEqual(summary,model_card(template_cards()[module]))
        expected={encode_placement(module,turn) for module in CARD_ALIAS
            for turn in template_cards()[module]['allowed_rotations']}
        self.assertEqual(set(questions['template_c0r0']['criteria']),expected)

    def test_tank_support_is_a_real_planner_option_only_with_rocket_counter(self):
        game=RealShapeGame()
        # This case checks the planner's ordinary infantry fallback.  The
        # product default now enables the second-stage tank rule, so pin the
        # legacy fallback explicitly instead of inheriting that default.
        game.config={'backend':'jev','gameOptions':{'secondStageTankRule':False}}
        context=dict(hormones={},phase='explore')
        choices={'gate_north_books_cross_tight':DESCRIPTIONS['gate_north_books_cross_tight']}
        troops=[dict(id=f'g{i}',faction='green',hp=30,max_hp=30,
            weapon='rocket' if i==2 else 'rifle') for i in range(3)]
        task=plan(game,context,choices,dict(units=troops,world_growth=dict(revision=1,completed=[])))
        self.assertIn('tank',game.calls[0][1]['support_type']['criteria'])
        self.assertEqual(task['support_type'],'infantry')
        without_rocket=[dict(row,weapon='rifle') for row in troops]
        other=RealShapeGame()
        other.config={'backend':'jev','gameOptions':{'secondStageTankRule':False}}
        plan(other,context,choices,dict(units=without_rocket,world_growth=dict(revision=1,completed=[])))
        self.assertNotIn('tank',other.calls[0][1]['support_type']['criteria'])

    def test_second_stage_tank_showcase_keeps_jev_spatial_planning(self):
        game=RealShapeGame()
        game.config={'backend':'jev','gameOptions':{'secondStageTankShowcase':True}}
        troops=[dict(id=f'g{i}',faction='green',hp=30,max_hp=30,
            weapon='rocket' if i==2 else 'rifle') for i in range(3)]
        choice={'gate_north_books_cross_tight':DESCRIPTIONS['gate_north_books_cross_tight']}
        task=plan(game,dict(hormones={},phase='explore'),choice,
            dict(units=troops,world_growth=dict(revision=1,completed=[])))
        self.assertEqual(set(game.calls[0][1]['support_type']['criteria']),{'tank'})
        self.assertEqual(task['support_type'],'tank')
        self.assertIn('desk_programme',game.calls[0][1])

    def test_second_stage_tank_rule_replaces_lost_rocket_without_skipping_combat(self):
        game=RealShapeGame()
        game.config={'backend':'jev','gameOptions':{'secondStageTankRule':True}}
        troops=[dict(id=f'g{i}',faction='green',hp=30,max_hp=30,weapon='rifle') for i in range(3)]
        choice={'gate_north_books_cross_tight':DESCRIPTIONS['gate_north_books_cross_tight']}
        task=plan(game,dict(hormones={},phase='explore'),choice,
            dict(units=troops,world_growth=dict(revision=1,completed=[])))
        self.assertEqual(task['support_type'],'tank')
        self.assertEqual(task['forces']['friendly_count'],1)

    def test_atomic_card_angle_choices_and_deliberate_repetition_are_preserved(self):
        class RepeatingGame(RealShapeGame):
            def ask(self,context,questions,role=None):
                result=super().ask(context,questions,role)
                for key,question in questions.items():
                    choice=None
                    if key.startswith('template_'):choice=encode_placement('code_laptop_island',270)
                    elif key.startswith('edit_') and key.endswith('_action'):choice='keep'
                    if choice:
                        result['answers'][key]=dict(type='choice',choice=choice,confidence=1,
                            probabilities={option:int(option==choice) for option in question['criteria']})
                return result
        game=RepeatingGame()
        task=dict(option='gate_north_books_cross_tight',mission_kind='assault',forces=dict(enemy_count=3))
        ops,ids,receipt=build(game,task,lambda:None)
        placements=[op for op in ops if op['op']=='place_region']
        self.assertEqual(len(ids),2)
        self.assertEqual(len(placements),9)
        self.assertTrue(all(op['module']=='code_laptop_island' and op['rotation']==270 for op in placements))
        self.assertEqual(receipt['design_observations']['largest_card_repeat'],9)
        self.assertEqual(receipt['design_observations']['edited_cells'],0)
        self.assertEqual(len(game.calls),2)
        self.assertEqual(len(game.calls[1][1]),13)
        self.assertFalse(any(key.endswith(('_item','_asset','_x','_z','_item_rotation'))
            for key in game.calls[1][1]))
        for context,questions in game.calls:
            self.assertTrue(all(len(q['criteria'])<=255 for q in questions.values()))

    def test_jev_selected_whole_board_passages_reach_the_engine_unchanged(self):
        game=RealShapeGame(close_edge=True)
        task=dict(option='gate_north_books_cross_tight',mission_kind='assault',
            forces=dict(enemy_count=3),route_preference='varied',recent_builds=[])
        operations,_,receipt=build(game,task,lambda:None)
        self.assertTrue(receipt['ok'])
        self.assertNotIn('c0r0__c1r0',[op.get('edge') for op in operations
            if op['op']=='connect_regions'])
        self.assertEqual(receipt['graph']['connections'],8)
        self.assertEqual(receipt['design_observations']['layout_pattern'],'central_gate')

    def test_whole_card_revision_needs_no_prop_detail_request(self):
        class SwapGame(RealShapeGame):
            def ask(self,context,questions,role=None):
                result=super().ask(context,questions,role)
                key='edit_c1r1_action'
                if key in questions:
                    choice=encode_placement('archive_central_files',90)
                    result['answers'][key]=dict(type='choice',choice=choice,confidence=1,
                        probabilities={option:int(option==choice) for option in questions[key]['criteria']})
                    keep='edit_c0r2_action'
                    result['answers'][keep]=dict(type='choice',choice='keep',confidence=1,
                        probabilities={option:int(option=='keep') for option in questions[keep]['criteria']})
                return result
        game=SwapGame()
        task=dict(option='gate_north_books_cross_tight',mission_kind='assault',forces=dict(enemy_count=3))
        operations,ids,receipt=build(game,task,lambda:None)
        self.assertEqual(len(ids),2)
        self.assertEqual(len(game.calls),2)
        self.assertEqual(len(game.calls[1][1]),13)
        changed=next(row for row in operations if row.get('op')=='place_region' and row.get('cell')=='c1r1')
        self.assertEqual((changed['module'],changed['rotation']),('archive_central_files',90))
        self.assertTrue(receipt['ok'])

    def test_next_assault_offers_contrasting_whole_board_choices(self):
        first=RealShapeGame()
        task=dict(option='gate_north_books_cross_tight',mission_kind='assault',
            forces=dict(enemy_count=3),recent_builds=[])
        first_ops,_,_=build(first,task,lambda:None)
        previous=describe(first_ops)
        second=RealShapeGame()
        second_task=dict(task,recent_designs=[previous],recent_builds=[first_ops],generation_index=1)
        second_ops,_,receipt=build(second,second_task,lambda:None)
        first_edges={op['edge'] for op in first_ops if op['op']=='connect_regions'}
        second_edges={op['edge'] for op in second_ops if op['op']=='connect_regions'}
        self.assertGreaterEqual(len(first_edges ^ second_edges),3)
        self.assertNotEqual(receipt['design_observations']['layout_pattern'],'open_field')
        self.assertNotIn('open_field',second.calls[0][1]['layout_pattern']['criteria'])
        self.assertFalse(any(key.startswith('edge_') for key in second.calls[0][1]))
        third=RealShapeGame()
        third_ops,_,_=build(third,dict(task,recent_designs=[previous,describe(second_ops)],
            recent_builds=[first_ops,second_ops],generation_index=2),lambda:None)
        third_edges={op['edge'] for op in third_ops if op['op']=='connect_regions'}
        self.assertGreaterEqual(len(third_edges ^ first_edges),3)
        self.assertGreaterEqual(len(third_edges ^ second_edges),3)

    def test_all_whole_board_patterns_have_reachable_entry_exit_variants(self):
        from world.region_graph import CELLS, compile_graph
        from world.assembly import validate
        for pattern in PATTERNS:
            for entry in ('c0r0','c0r1','c0r2'):
                for exit_cell in ('c2r0','c2r1','c2r2'):
                    with self.subTest(pattern=pattern,entry=entry,exit=exit_cell):
                        operations=([dict(op='set_ports',entry=entry,exit=exit_cell)]
                            + [dict(op='place_region',cell=cell,module='open',rotation=0) for cell in CELLS]
                            + [dict(op='connect_regions',edge=edge) for edge in pattern_connections(pattern)]
                            + [dict(op='deploy',module='rear')])
                        spec=compile_graph(operations)
                        self.assertTrue(validate(spec)['ok'])
                        self.assertLessEqual(len(spec['design_card']['main_regions']),7)

    def test_same_nine_cells_can_still_be_a_different_design(self):
        from world.region_graph import CELLS
        def layout(module):
            return ([dict(op='set_ports',entry='c0r1',exit='c2r1')]
                + [dict(op='place_region',cell=cell,module=module) for cell in CELLS]
                + [dict(op='connect_regions',edge=edge) for edge in LIBRARY['edges']]
                + [dict(op='deploy',module='rear')])
        books=describe(layout('books'))
        printer=describe(layout('printer_coffee_station'))
        self.assertEqual(set(books['cells']),set(printer['cells']))
        self.assertEqual(similarity(books,books),1)
        self.assertLess(similarity(books,printer),1)

    def test_macro_has_current_analysis_and_forward_goal(self):
        row=validate_macro(dict(phase='explore',hormones=dict(pressure=.3,recovery=.5,
            expansion=.6,teaching=.4,novelty=.7),current_analysis='当前关卡住并有人负伤',
            next_goal=dict(experience='先整队再进攻',tactical_problem='开放受掩护侧路',
                avoid='两路同时暴露',layout_change='改变中央书堆形成的直射线',route_preference='flank')))
        self.assertEqual(row['next_goal']['route_preference'],'flank')
        self.assertIn('当前关',row['current_analysis'])
        with self.assertRaisesRegex(ValueError,'missing_current_level_analysis'):
            validate_macro(dict(row,current_analysis=''))

    def test_planner_directive_reaches_builder_without_quality_repair(self):
        game=RealShapeGame()
        state=dict(units=[dict(id=f'g{i}',faction='green',hp=30,max_hp=30) for i in range(3)],
            world_growth=dict(revision=2,completed=[]))
        context=dict(hormones={},phase='explore',experience_report=dict(next_goal=dict(
            experience='形成可见侧路',tactical_problem='前进时有掩护',avoid='全部暴露',route_preference='varied')))
        task=plan(game,context,{'gate_north_books_cross_tight':DESCRIPTIONS['gate_north_books_cross_tight']},state)
        self.assertIn('一次选定九格',task['build_directive'])
        self.assertEqual(task['route_preference'],'varied')
        task.update(recent_builds=[],generation_index=2)
        calls=[]
        operations,ids,receipt=build(game,task,lambda:calls.append('reserved'))
        self.assertEqual(len(ids),2)
        self.assertEqual(len(calls),1)
        self.assertEqual(sum(o['op']=='edit_component' and o['action']=='remove' for o in operations),1)
        self.assertTrue(receipt['ok'])
        builder=[r for r in game.records if r['type']=='world-builder']
        self.assertEqual([r['stage'] for r in builder],['layout_draft','batch_revision'])
        self.assertEqual(builder[-1]['proposal']['edits'][0]['action'],'remove')
        self.assertEqual(receipt['graph']['entry_cell'],'c0r0')
        self.assertEqual(receipt['graph']['exit_cell'],'c2r0')
        self.assertEqual(len(game.calls[2][1]),13)
        self.assertEqual(len([key for key in game.calls[1][1] if key.startswith('template_')]),9)
        choices=game.calls[1][1]['template_c0r0']['criteria']
        self.assertEqual(len(choices),4*len(SELECTABLE_MODULES))
        self.assertTrue(all(len(choice)==4 for choice in choices))
        self.assertIn(encode_placement('archive_central_files',0),choices)
        self.assertIn(encode_placement('archive_central_files',90),choices)
        self.assertEqual({decode_placement(choice)['template'] for choice in choices},set(SELECTABLE_MODULES))
        self.assertEqual({decode_placement(choice)['rotation'] for choice in choices},{0,90,180,270})
        self.assertNotIn('flank_0',game.calls[1][1]['template_c0r0']['criteria'])
        self.assertNotEqual(game.calls[1][1]['template_c0r0']['instructions'],game.calls[1][1]['template_c1r1']['instructions'])
        self.assertIn('tactical_estimate',receipt)
        feedback=game.calls[2][0]['draft_design_feedback']
        self.assertIn('material_profile',feedback)
        self.assertEqual(len(feedback['materials_by_cell']),9)
        self.assertIn('material_profile',receipt['design_observations'])
        self.assertEqual(game.calls[0][0]['available_stationery']['card_count'],26)
        self.assertEqual(game.calls[1][0]['planner_desks'],task['layout_brief']['desks'])
        self.assertEqual(len(game.calls[1][0]['planner_desks']),9)

    def test_previous_blocked_bookstack_layout_can_be_chosen_at_table_edges(self):
        graph=graph_candidates(False)['g183']
        props=[]
        for cell in graph['cells']:
            cx,cz=LIBRARY['cells'][cell]['open']['center']
            props.append(dict(cell=cell,asset='bookstack',x=round(cx-.16,3),z=round(cz,3),rotation=0))
        operations,receipt=assemble_props(graph,dict(props=props,deployment='rear'),3)
        self.assertTrue(receipt['ok'])
        self.assertEqual([o['asset'] for o in operations if o['op']=='place_prop'],['bookstack']*5)

    def test_all_exposed_routes_remain_a_diagnostic_not_a_veto(self):
        graph=graph_candidates(False)['g58']
        props=[]
        for cell in ('c0r0','c1r0','c1r1','c2r0'):
            cx,cz=LIBRARY['cells'][cell]['open']['center']
            props.append(dict(cell=cell,asset='desk_divider',x=round(cx-.12,3),z=round(cz+.08,3),rotation=0))
        proposal=dict(props=props,deployment='layered')
        _,receipt=assemble_props(graph,proposal,5)
        self.assertTrue(receipt['ok'])
        self.assertEqual(receipt['tactical_estimate']['main']['exposed_fraction'],1)

    def test_unbuildable_jev_choice_is_recorded_and_never_replaced(self):
        game=RealShapeGame(invalid=True)
        task=dict(option='gate_north_books_cross_tight',mission_kind='assault',
            forces=dict(enemy_count=3),route_preference='varied',recent_builds=[])
        with self.assertRaisesRegex(ValueError,'unbuildable_jev_design:prop_outside_cell'):
            build(game,task,lambda:None)
        builder=[r for r in game.records if r['type']=='world-builder']
        self.assertEqual([r['stage'] for r in builder],['layout_draft','prop_edit_details','batch_revision'])
        self.assertEqual(set(game.calls[-1][1]),{'edit_c0r2_asset','edit_c0r2_x',
            'edit_c0r2_z','edit_c0r2_item_rotation'})
        self.assertEqual(builder[-1]['proposal']['edits'][0]['asset'],'printer')
        self.assertEqual(builder[-1]['tool_receipt']['reason'],'prop_outside_cell')



if __name__=='__main__':unittest.main()
