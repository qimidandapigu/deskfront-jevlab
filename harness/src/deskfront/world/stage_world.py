"""World, tactics, and staged asset installation phases."""
import json
from pathlib import Path
import shutil

from .stage_contract import apply_hooks
from . import query_optimization

def _patch_world_and_tactics(destination: Path, here: Path, emoji_codes):
    from .catalog import CATALOG
    (destination / "data/world-components.json").write_text(json.dumps(CATALOG,ensure_ascii=False),encoding="utf-8")
    from .assembly import tools_for
    (destination / "data/world-build-parts.json").write_text(json.dumps({k:tools_for(k) for k in CATALOG},ensure_ascii=False),encoding="utf-8")
    from .region_graph import LIBRARY
    (destination / "data/world-regions.json").write_text(json.dumps(LIBRARY,ensure_ascii=False),encoding="utf-8")
    shutil.copyfile(here / 'region_graph.gd', destination / 'scripts/world_region_graph.gd')
    field = destination / 'scripts/battlefield.gd'
    code = field.read_text(encoding='utf-8')
    anchor = '\trevision += 1'
    floor_hook = '\tfor region in config.get("world_floor_regions",[]):\n\t\tvar floor_lo: Vector2i=to_cell(Vector2(region.left,0))+Vector2i(-1,0)\n\t\tvar floor_hi: Vector2i=to_cell(Vector2(region.right,0))+Vector2i(1,0)\n\t\tfor x in range(maxi(0,floor_lo.x),mini(grid.region.size.x,floor_hi.x+1)):\n\t\t\tfor y in range(grid.region.size.y):\n\t\t\t\tvar p=to_world(Vector2i(x,y))\n\t\t\t\tif p.x<region.left or p.x>region.right:continue\n\t\t\t\tsupported=false\n\t\t\t\tfor r in region.rects:\n\t\t\t\t\tif p.x>=r[0] and p.x<=r[2] and p.y>=r[1] and p.y<=r[3]:supported=true;break\n\t\t\t\tif not supported:grid.set_point_solid(Vector2i(x,y));tank_grid.set_point_solid(Vector2i(x,y))\n'
    if code.count(anchor)==1:
        code=code.replace(anchor, floor_hook+anchor)
    else:
        # Newer native revisions build the grids in the extracted navigation
        # helper. Patch that helper rather than requiring the old battlefield
        # implementation to be restored.
        navigation = destination / 'scripts/battlefield_navigation.gd'
        nav_code = navigation.read_text(encoding='utf-8') if navigation.exists() else ''
        nav_anchor = '\tbattlefield.tactical_cache.clear()\n\tbattlefield.revision += 1'
        # The extracted helper may carry a cache invalidation comment between
        # these statements. Fall back to the stable cover-miss line so staging
        # remains compatible with both native revisions.
        nav_insert = nav_anchor
        if nav_code.count(nav_anchor) != 1:
            nav_insert = '\tbattlefield.cover_misses.clear()'
        if nav_code.count(nav_insert) != 1:
            raise RuntimeError('Unsupported floor navigation hook')
        nav_floor = '\tfor region in battlefield.config.get("world_floor_regions",[]):\n'
        nav_floor += '\t\tvar floor_lo: Vector2i=battlefield.to_cell(Vector2(region.left,0))+Vector2i(-1,0)\n'
        nav_floor += '\t\tvar floor_hi: Vector2i=battlefield.to_cell(Vector2(region.right,0))+Vector2i(1,0)\n'
        nav_floor += '\t\tfor x in range(maxi(0,floor_lo.x),mini(battlefield.grid.region.size.x,floor_hi.x+1)):\n'
        nav_floor += '\t\t\tfor y in range(battlefield.grid.region.size.y):\n'
        nav_floor += '\t\t\t\tvar p=battlefield.to_world(Vector2i(x,y))\n'
        nav_floor += '\t\t\t\tif p.x<region.left or p.x>region.right:continue\n'
        nav_floor += '\t\t\t\tvar supported: bool=false\n'
        nav_floor += '\t\t\t\tfor r in region.rects:\n'
        nav_floor += '\t\t\t\t\tif p.x>=r[0] and p.x<=r[2] and p.y>=r[1] and p.y<=r[3]:supported=true;break\n'
        nav_floor += '\t\t\t\tif not supported:\n\t\t\t\t\tbattlefield.grid.set_point_solid(Vector2i(x,y));battlefield.tank_grid.set_point_solid(Vector2i(x,y))\n'
        nav_code=nav_code.replace(nav_insert, nav_floor+nav_insert)
        navigation.write_text(nav_code,encoding='utf-8')
    from . import field_perf, bounded_navigation
    field.write_text(bounded_navigation.patch(field_perf.patch(query_optimization.field(code))),encoding='utf-8')
    script = destination / 'scripts/game.gd'
    source = script.read_text(encoding='utf-8')
    engine_emotions='["calm","alert","nervous","afraid","determined","relieved"]'
    emotion_ttl='member.emotion=c.emotion;member.emotion_until=elapsed+12.0'
    if source.count(engine_emotions)==1 and source.count(emotion_ttl)==1:
        source = source.replace(engine_emotions,
                                '['+','.join(json.dumps(name) for name in emoji_codes if name != 'dead')+']')
        source=source.replace(emotion_ttl,
                              'member.emotion=c.emotion;member.emotion_until=elapsed+22.0')
    else:
        # Native command dispatch is extracted into harness_command.gd in newer
        # user-owned revisions. Patch that facade when available.
        command_path=destination / 'scripts/harness_command.gd'
        command_source=command_path.read_text(encoding='utf-8') if command_path.exists() else ''
        command_choices = '["calm", "alert", "nervous", "afraid", "determined", "relieved"]'
        command_ttl = 'member.emotion_until = game.elapsed + 12.0'
        if command_source.count(command_choices)!=1 or command_source.count(command_ttl)!=1:
            raise RuntimeError('Unsupported native emotion selection hook')
        command_source=command_source.replace(command_choices,
                                              '['+', '.join(json.dumps(name) for name in emoji_codes if name != 'dead')+']')
        command_source=command_source.replace(command_ttl,
                                              'member.emotion_until = game.elapsed + 22.0')
        command_path.write_text(command_source,encoding='utf-8')
    source=source.replace('"fps":Engine.get_frames_per_second()', '"frame_profile":{"process_ms":Performance.get_monitor(Performance.TIME_PROCESS)*1000,"physics_ms":Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS)*1000,"draw_calls":Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME),"objects":Performance.get_monitor(Performance.RENDER_TOTAL_OBJECTS_IN_FRAME),"nodes":Performance.get_monitor(Performance.OBJECT_NODE_COUNT)},"fps":Engine.get_frames_per_second()')
    bubble_anchor='\tvar bubbles=preload("res://scripts/emotion_bubbles.gd").new();bubbles.game=self;ui.add_child(bubbles)'
    if source.count(bubble_anchor)!=1:
        raise RuntimeError('Unsupported tactical/emotion visibility hook')
    source = source.replace('const CombatFX = preload("res://scripts/combat_fx.gd")', 'const CombatFX = preload("res://scripts/human_combat_fx.gd")')
    source=apply_hooks(source,json.loads((here / 'hooks.json').read_text(encoding='utf-8')))
    source=apply_hooks(source,[dict(name='explicit player posture source',
        before='for u in members:u.posture_order=value;u.posture_since=-10;u.update_posture(not u.route.is_empty())',
        after='for u in members:\n\t\t\t\tif u.has_method("harness_apply_posture_order"):u.harness_apply_posture_order(value,source in ["player","console"])\n\t\t\t\telse:u.posture_order=value;u.posture_since=-10;u.update_posture(not u.route.is_empty())'),
        dict(name='model posture clears player override',
        before='if c.has("posture") and c.get("action","")!="posture":u.posture_order=c.posture;u.posture_since=-10;u.update_posture(not u.route.is_empty())',
        after='if c.has("posture") and c.get("action","")!="posture":\n\t\t\t\t\tif u.has_method("harness_apply_posture_order"):u.harness_apply_posture_order(c.posture,false)\n\t\t\t\t\telse:u.posture_order=c.posture;u.posture_since=-10;u.update_posture(not u.route.is_empty())')])
    source=apply_hooks(source,[dict(name='infantry can acquire a hostile mortar',
        before='\treturn best\n\nvar execution_profile: Dictionary={}',
        after='''\t# A deployed mortar is a real tactical target. Keep the native weapon
\t# range for ordinary enemies, but let a rifleman acquire the nearby gun
\t# once the front line has reached its rear support socket.
\tvar mortar_best=null
\tvar mortar_score:float=-INF
\tfor gun in at_guns:
\t\tif not gun.has_method("is_mortar_target") or gun.faction==u.faction or gun.hp<=0:continue
\t\tvar mortar_distance:float=u.pos().distance_to(gun.pos())
\t\tif mortar_distance>minf(1.08,distance+.38):continue
\t\tif human_squad and human_squads and not human_squads.visible_to(u.faction,gun):continue
\t\tif not u.can_engage(gun):continue
\t\tvar score:float=1.9-mortar_distance+(0.45 if gun.phase in ["ready","single_operator"] else .12)
\t\tif gun.id==requested:score+=3.0
\t\tif score>mortar_score:mortar_best=gun;mortar_score=score
\tif mortar_best!=null and (best==null or mortar_score>best_score+.15):best=mortar_best
\treturn best

var execution_profile: Dictionary={}''')])
    infinite = '(get_tree().get_meta("infinite_world",false) or "--infinite-world" in OS.get_cmdline_user_args())'
    source = source.replace('target.visible=use_legacy_fixture', 'target.visible=use_legacy_fixture and not growth')
    office_anchor='office_root=office'
    source=apply_hooks(source,[dict(name='stationery source tabletop alignment',before=office_anchor,
        after=office_anchor+'\n\tif '+infinite+':\n\t\tpreload("res://scripts/world_office_cleanup.gd").strip_chairs(office)\n\t\tvar source_tabletop=office.find_child("warm gray laminate",true,false)\n\t\tif source_tabletop is MeshInstance3D:\n\t\t\tsource_tabletop.position.y+=.018\n\t\t\tsource_tabletop.material_override=preload("res://scripts/world_props.gd").material("c2a077")')])
    source = source.replace('if not demo and not tank_spawned and elapsed>config.rules.reinforce_after:',
        'if not growth and not demo and not tank_spawned and elapsed>config.rules.reinforce_after:')
    config_anchor = '\tconfig=JSON.parse_string(FileAccess.get_file_as_string("res://data/battle.json"))'
    if source.count(config_anchor) != 1:
        raise RuntimeError('Unsupported world health configuration hook')
    source = source.replace(config_anchor, config_anchor+'\n\tif '+infinite+':config.soldier.hp=50.0', 1)
    source=source.replace('var u=Unit.new()', 'var u=(preload("res://scripts/harness_unit.gd").new() if '+infinite+' else Unit.new())')
    source=source.replace('if not use_legacy_fixture:prepare_reserve_tank()', 'if not use_legacy_fixture and not '+infinite+':prepare_reserve_tank()')
    start = dict(id='world_start', name='远征出发区', bounds=[.65,.98,1.38,3.28], objective=[1.28,2.13], floor_color='#d6b98d',surface='tray',
        spawns=[[1.25,2.13],[1.25,2.13],[1.25,2.13]],objects=[dict(id='start_cover',kind='sandbag',position=[.84,2.13],size=[.16,.043,.045],color='#c2b98b',yaw=0,collision=True,destructible=True)])
    (destination/'data/world-start.json').write_text(json.dumps(start),encoding='utf-8')
    source=source.replace('arena.load_level(map_index,get_tree().get_meta("studio_level",{}))',
        'arena.load_level(map_index,JSON.parse_string(FileAccess.get_file_as_string("res://data/world-start.json")) if '+infinite+' else get_tree().get_meta("studio_level",{}))')
    source = source.replace('"0.6.5 / FLAG ALERT / "+str(build_info.id)',
        '("LIVE ENCOUNTER / " if '+infinite+' else "0.6.5 / FLAG ALERT / ")+str(build_info.id)')
    source = source.replace('map_data.name+" · 三阵营 / 新资源已接入 · F2 换图"',
        '(("绿色 Harness / 红色 "+("Harness" if OS.get_environment("HARNESS_RED_CONTROL")=="lm" else "本地 Bot")+"" if OS.get_environment("HARNESS_GREEN_CONTROL")=="lm" else "红绿双方本地 Bot / 整段实时构建") if '+infinite+' else map_data.name+" · 三阵营 / 新资源已接入 · F2 换图")')
    source = source.replace('\tfor f in config.factions:\n\t\tfor i in range(3):spawn_unit',
        '\tfor f in config.factions:\n\t\tif '+infinite+' and f.id!="green":continue\n\t\tfor i in range(5 if '+infinite+' else 3):spawn_unit')
    source = source.replace('func set_control_mode(team: String, mode: String) -> void:\n',
        'func set_control_mode(team: String, mode: String) -> void:\n\tif growth and not growth.allows_control(team,mode):return\n')
    source = source.replace('\tvar rejected: String="";var tactics: Array=',
        '\tif growth and str(c.get("action","")) in ["control","move","capture","flank","cover","hold","retreat","attack","grenade","posture","man_at_gun","leave_gun","garrison","leave_building"] and not growth.allows_command(c):return ack(c,false,"world_control_authority_denied")\n\tvar rejected: String="";var tactics: Array=')
    pole = '\tfield.cube(self,Vector3(objective.x,field.height+.12,objective.y),Vector3(.008,.24,.008),field.mat(Color(.70,.65,.45)))'
    source = source.replace(pole, '\tif not (get_tree().get_meta("infinite_world",false) or "--infinite-world" in OS.get_cmdline_user_args()):\n\t' + pole)
    lines = source.splitlines()
    for i, line in enumerate(lines):
        if 'selection_label.text=' in line and 'HOLD CENTRAL FLAG' in line:
            lines.insert(i+1, '\tif growth:\n\t\tscore_label.text="ENCOUNTER / "+str(growth.mission.get("name","展开前线"))\n\t\tflag_warning_panel.hide()\n\t\tselection_label.text=selected_faction.to_upper()+" / "+str(control[selected_faction])+" / 推进与遭遇任务"')
            break
    script.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    tactics = destination / 'scripts/tactics.gd'
    code = tactics.read_text(encoding='utf-8')
    anchor = 'func plan(team: String) -> void:\n'
    if code.count(anchor) != 1: raise RuntimeError('Unsupported tactics adapter version')
    code=code.replace(anchor, anchor+'\tif game.growth:\n\t\tgame.growth.plan(team);return\n')
    start=code.find('func plan_tank(tank) -> void:\n')
    end=code.find('\nfunc snapshot() -> Dictionary:',start)
    if start<0 or end<0:raise RuntimeError('Unsupported direct-fire positioning hook')
    code=code[:start]+'''func plan_tank(tank) -> void:
	if tank.deployment_phase!="active" or game.elapsed<float(tank_next.get(tank.id,-1)):return
	tank_next[tank.id]=game.elapsed+game.config.tactics.tank_replan_seconds
	var target=game.find_target(tank)
	if target==null:target=game.closest_enemy(tank)
	if target==null:return
	var targets: Array=[target]
	var others: Array=game.living().filter(func(u):return u.faction!=tank.faction and u!=target and (not game.human_squad or not game.human_squads or game.human_squads.visible_to(tank.faction,u)))
	others.sort_custom(func(a,b):return tank.pos().distance_to(a.pos())<tank.pos().distance_to(b.pos()))
	for other in others.slice(0,4):targets.append(other)
	var evaluator=preload("res://scripts/engagement_position.gd").new()
	var selection: Dictionary={}
	for enemy in targets:
		var candidate: Dictionary=evaluator.choose(game,tank,enemy,"fire_support")
		if selection.is_empty():selection=candidate
		if candidate.status=="ready":selection=candidate;target=enemy;break
	tank.focus_id=target.id
	selection["target_id"]=target.id
	selection["considered_targets"]=targets.size()
	tank.set_meta("engagement_position",selection)
	if selection.status!="ready":return
	var destination: Vector2=selection.position
	if tank.pos().distance_to(destination)<.035:
		if tank.route.is_empty():tank.goal=tank.pos();tank.order_mode="fire_support"
		return
	if tank.goal.distance_to(destination)<.035 and not tank.route.is_empty():return
	tank.move_to(destination);tank.order_mode="reposition";counters.tank_repositions+=1
''' + code[end:]
    tactics.write_text(code, encoding='utf-8')


def _install_world_assets(destination: Path, here: Path):
    shutil.copyfile(here/'engagement_position.gd',destination/'scripts/engagement_position.gd')
    shutil.copyfile(here/'engagement_profiles.json',destination/'data/engagement-profiles.json')
    shutil.copyfile(here / 'choke.gd', destination / 'scripts/world_choke.gd')
    shutil.copyfile(here / 'fortress.gd', destination / 'scripts/world_fortress.gd')
    shutil.copyfile(here / 'fortress.json', destination / 'data/world-fortress.json')
    shutil.copyfile(here / 'rescue-scene.json', destination / 'data/rescue-scene.json')
    shutil.copyfile(here.parent / 'spatial_queries.gd', destination / 'scripts/world_spatial.gd')
    shutil.copyfile(here.parent / 'execution_validation.gd', destination / 'scripts/world_execution_validation.gd')
    guarded=(here.parent / 'guarded_unit.gd').read_text(encoding='utf-8')
    guarded=guarded.replace('super.hit(amount,pressure,origin,impulse)',
        'super.hit(amount,pressure,origin,impulse)\n\tif game.human_squads and hp<=0:game.human_squads.intent_executor.observe(self,game.elapsed)')
    guarded=guarded.replace('harness_last_block = harness_fire_check.duplicate()',
        'harness_last_block = harness_fire_check.duplicate()\n\t\tif game.human_squads:game.human_squads.intent_executor.note_fire(self,"blocked",reason,enemy.id,game.elapsed)')
    guarded=guarded.replace('super.fire(enemy)\n',
        'var shot_before: float=last_shot_at\n\tsuper.fire(enemy)\n\tif game.human_squads:game.human_squads.intent_executor.note_fire(self,"fired" if last_shot_at>shot_before else "not_fired","" if last_shot_at>shot_before else "engine_rejected",enemy.id,game.elapsed)\n')
    (destination / 'scripts/harness_unit.gd').write_text(guarded,encoding='utf-8')
    shutil.copyfile(here.parent / 'human_unit.gd', destination / 'scripts/human_unit.gd')
    shutil.copyfile(here.parent / 'human_combat_fx.gd', destination / 'scripts/human_combat_fx.gd')
    shutil.copyfile(here / 'tank_damage_visual.gd', destination / 'scripts/tank_damage_visual.gd')
    shutil.copyfile(here / 'tank_burn.gdshader', destination / 'scripts/tank_burn.gdshader')
    spatial = destination / 'scripts/world_spatial.gd'
    spatial.write_text(spatial.read_text(encoding='utf-8').replace('arena.demo.phase != "battle"', '(arena.growth == null or arena.growth.mission.is_empty())'), encoding='utf-8')
    shutil.copyfile(here / 'stationery.gd', destination / 'scripts/world_props.gd')
    shutil.copyfile(here / 'office_cleanup.gd', destination / 'scripts/world_office_cleanup.gd')
    cover_art = destination / 'assets/deskfront'
    cover_art.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(here / 'assets/book-hengda-cover.png', cover_art / 'book-hengda-cover.png')
    # Start area shares the same art library as newly generated regions.
    arena = destination / 'scripts/sandbox_map.gd'
    arena_code = arena.read_text(encoding='utf-8')
    start_hook = "  if spec.kind=='sandbag':"
    arena_code = apply_hooks(arena_code,[dict(name='stationery start cover',before=start_hook,
        after="  if current.id=='world_start':\n   n.get_child(0).hide()\n   var stationery=Node3D.new();n.add_child(stationery);stationery.position.y=-sz.y*.5\n   preload(\"res://scripts/world_props.gd\").build(null,stationery,[0,0,sz.x,sz.z,spec.kind,sz.y])\n   continue\n"+start_hook)])
    arena_code=arena_code.replace("if current.get('surface','tray')=='desk':", "if current.get('surface','tray')=='desk' or current.id=='world_start':", 1)
    arena_code=arena_code.replace("Color('#747e6b')","Color('#b39367') if current.id=='world_start' else Color('#747e6b')")
    arena.write_text(arena_code,encoding='utf-8')

    shutil.copyfile(here / 'stationery_contract.gd', destination / 'tests/stationery_contract.gd')
    shutil.copyfile(here / 'stationery_visual.gd', destination / 'tests/stationery_visual.gd')
    shutil.copyfile(here / 'stationery_catalog_visual.gd', destination / 'tests/stationery_catalog_visual.gd')
    shutil.copyfile(here / 'stationery-scene.json', destination / 'data/stationery-scene.json')
    shutil.copyfile(here / 'region-graph-fixtures.json', destination / 'data/graph-test-fixtures.json')
    shutil.copyfile(here / 'scenery.gd', destination / 'scripts/world_scenery.gd')
    shutil.copyfile(here / 'growth.gd', destination / 'scripts/world_growth.gd')
    shutil.copyfile(here / 'growth_visual.gd', destination / 'scripts/world_growth_visual.gd')
    shutil.copyfile(here / 'growth_mission.gd', destination / 'scripts/world_growth_mission.gd')
    shutil.copyfile(here / 'growth_retirement.gd', destination / 'scripts/world_growth_retirement.gd')
    shutil.copyfile(here / 'growth_local_ai.gd', destination / 'scripts/world_growth_local_ai.gd')
    shutil.copyfile(here / 'growth_staging.gd', destination / 'scripts/world_growth_staging.gd')
    shutil.copyfile(here / 'growth_validation.gd', destination / 'scripts/world_growth_validation.gd')
    shutil.copyfile(here / 'mortar.gd', destination / 'scripts/world_mortar.gd')
    shutil.copyfile(here / 'mortar_presentation.gd', destination / 'scripts/mortar_presentation.gd')
    for source, target in [('rescue_contract.gd', 'world_rescue_contract.gd'),
                           ('rescue_visual.gd', 'world_rescue_visual.gd')]:
        if (here / source).exists():
            shutil.copyfile(here / source, destination / 'tests' / target)
    shutil.copyfile(here / 'reinforcements.gd', destination / 'scripts/world_reinforcements.gd')
    shutil.copyfile(here / 'contract.gd', destination / 'tests/world_growth_contract.gd')
    shutil.copyfile(here / 'harness_contract.gd', destination / 'tests/world_harness_contract.gd')
    shutil.copyfile(here.parents[2] / 'test/deskfront_selected_personal.gd',
                    destination / 'tests/deskfront_selected_personal.gd')
    shutil.copyfile(here.parents[2] / 'test/deskfront_moving_fire.gd',
                    destination / 'tests/deskfront_moving_fire.gd')
    shutil.copyfile(here.parents[2] / 'test/deskfront_posture_stability.gd',
                    destination / 'tests/deskfront_posture_stability.gd')
    shutil.copyfile(here.parents[2] / 'test/deskfront_emotion_evidence.gd',
                    destination / 'tests/deskfront_emotion_evidence.gd')
    shutil.copyfile(here.parents[2] / 'test/deskfront_validation_poll.gd',
                    destination / 'tests/deskfront_validation_poll.gd')
    shutil.copyfile(here / 'components_contract.gd', destination / 'tests/components_contract.gd')
    shutil.copyfile(here / 'assembly_contract.gd', destination / 'tests/assembly_contract.gd')
    shutil.copyfile(here / 'region_graph_contract.gd', destination / 'tests/region_graph_contract.gd')
    shutil.copyfile(here / 'layout_contrast_contract.gd', destination / 'tests/layout_contrast_contract.gd')
    shutil.copyfile(here / 'geometry_navigation_contract.gd', destination / 'tests/geometry_navigation_contract.gd')
    shutil.copyfile(here / 'geometry_unit_traversal_contract.gd', destination / 'tests/geometry_unit_traversal_contract.gd')
    shutil.copyfile(here / 'prop_placement_contract.gd', destination / 'tests/prop_placement_contract.gd')
    shutil.copyfile(here / 'traversal_contract.gd', destination / 'tests/world_traversal_contract.gd')
    shutil.copyfile(here / 'rolling_contract.gd', destination / 'tests/world_rolling_contract.gd')
    shutil.copyfile(here / 'forces_contract.gd', destination / 'tests/world_forces_contract.gd')
    shutil.copyfile(here / 'roster_contract.gd', destination / 'tests/world_roster_contract.gd')
    (destination / 'output/world').mkdir(parents=True, exist_ok=True)
    shutil.copyfile(here.parent/'commentary_overlay.gd', destination/'scripts/harness_commentary.gd')
    shutil.copyfile(here.parent/'danmaku_overlay.gd', destination/'scripts/harness_danmaku.gd')


