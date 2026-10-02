extends Node3D
## Opt-in, bounded live construction. All gameplay changes commit in Godot.
var game
var revision: int = 0
var active_regions:Array=[]
var retired_regions:int=0
var retirement_blocked:bool=false
var next_retirement_check:float=0
const KEEP_BUILT_REGIONS=2
var completed: Array = []
var mission_results: Array = []
var pending: Dictionary = {}
var clock: float = 0
const BUILD_SECONDS := 1.5
var preview: Node3D
var preview_desks:Array=[]
var preview_covers:Array=[]
var hormones: Dictionary = {}
var seen: Array = []
var hud: Label
var reinforcements
var construction_failures: Array=[]
const MAX_GRID_CELLS = 65000
const Encounter=preload("res://scripts/world_choke.gd")
const GrowthValidation=preload("res://scripts/world_growth_validation.gd")
const GrowthVisual=preload("res://scripts/world_growth_visual.gd")
const GrowthStaging=preload("res://scripts/world_growth_staging.gd")
const GrowthMission=preload("res://scripts/world_growth_mission.gd")
const GrowthRetirement=preload("res://scripts/world_growth_retirement.gd")
const GrowthLocalAI=preload("res://scripts/world_growth_local_ai.gd")
const WIDTH=Encounter.WIDTH
var options:Array=[]
var mission: Dictionary={}
var marker: Node3D
var unit_roles: Dictionary={}
var encounter_events: Array=[]
var harness_green:bool=OS.get_environment("HARNESS_GREEN_CONTROL")=="lm"
var harness_red:bool=OS.get_environment("HARNESS_RED_CONTROL")=="lm"
var spatial=preload("res://scripts/world_spatial.gd").new()
var execution_validator=preload("res://scripts/world_execution_validation.gd").new()
var desk_panels:Array=[]
var rescue_label:Label3D
var mortar_support:Node3D
var mission_lifecycle=GrowthMission.new()
var retirement_manager=GrowthRetirement.new()
var local_ai=GrowthLocalAI.new()

func allows_control(team:String,mode:String)->bool:
	return mode==("lm" if ((harness_green and team=="green") or (harness_red and team=="red")) else "game_ai")

func allows_command(c:Dictionary)->bool:
	if c.get("action")=="control":return allows_control(str(c.get("faction","green")),str(c.get("mode","")))
	return allows_control(str(c.get("faction","")),"lm") and c.get("source")=="lm"

func setup(g):
	game=g
	for key in Encounter.catalog():
		if Encounter.validate(Encounter.specification(key),(game.config.bounds[3]-game.config.bounds[1])*.5).ok:options.append(key)
	game.edge_pan=false
	reinforcements=preload("res://scripts/world_reinforcements.gd").new();add_child(reinforcements);reinforcements.setup(game)
	for team in game.control:game.set_control_mode(team,"lm" if ((harness_green and team=="green") or (harness_red and team=="red")) else "game_ai")
	# Five existing members: two can serve a captured mortar, three keep fighting.
	var squad: Array=game.living("green")
	var starting_weapons: Array=["rifle","smg","rocket","rifle","smg"]
	for i in range(squad.size()):
		var entry=Vector2(game.config.bounds[2]-.18,(game.config.bounds[1]+game.config.bounds[3])*.5+(i-(squad.size()-1)*.5)*.22)
		entry=game.field.to_world(game.field.nearest(entry))
		squad[i].position.x=entry.x;squad[i].position.z=entry.y;squad[i].goal=entry;squad[i].route.clear();squad[i].equip(starting_weapons[i%starting_weapons.size()])
	game.flag_banner.hide()
	hud=Label.new();game.ui.add_child(hud)
	hud.position=Vector2(24,104);hud.add_theme_font_size_override("font_size",18)
	hud.add_theme_color_override("font_color",Color(.25,1,.9))
	var sidebar=preload("res://scripts/battle_sidebar.gd").new();game.ui.add_child(sidebar);sidebar.setup(game)
	show_status("LIVE WORLD / 空场地，等待JEV搭建首次遭遇")

func show_status(message: String):
	if hud:hud.hide()

func tank_staging_point(left:float,z:float,spec:Dictionary)->Dictionary:
	return GrowthStaging.tank_staging_point(self,left,z,spec)

func mortar_staging_point(left:float,z:float,tank_unit)->Dictionary:
	return GrowthStaging.mortar_staging_point(self,left,z,tank_unit)

func mortar_arc_clear(point:Vector2,tank_unit)->bool:
	return GrowthStaging.mortar_arc_clear(self,point,tank_unit)

func tank_counter_available(planned_friendlies:int)->bool:
	return GrowthStaging.tank_counter_available(self,planned_friendlies)

func snapshot() -> Dictionary:
	var budget_ok: bool=(game.field.grid.region.size.x+int(WIDTH/game.field.cell))*game.field.grid.region.size.y<MAX_GRID_CELLS
	return {"enabled":true,"mode":"infinite","revision":revision,"active_region_count":active_regions.size(),"retired_regions":retired_regions,"retirement_blocked":retirement_blocked,"completed":completed.duplicate(true),"mission_results":mission_results.duplicate(true),"phase":"building" if not pending.is_empty() else ("encounter" if mission.get("status","completed")!="completed" else ("ready" if budget_ok and active_regions.size()<KEEP_BUILT_REGIONS+1 else "capacity_paused")),"pending":pending.get("option",""),"progress":minf(clock/BUILD_SECONDS,1.0) if not pending.is_empty() else 0.0,"hormones":hormones.duplicate(),"mission":mission.duplicate(true),"reinforcements":reinforcements.snapshot(),"mortar_support":mortar_support.snapshot() if mortar_support and is_instance_valid(mortar_support) else {},"construction_failures":construction_failures.duplicate(true),"unit_roles":unit_roles.duplicate(true),"encounter_events":encounter_events.duplicate(true),"planning_options":options if budget_ok else [],"options":options if budget_ok and active_regions.size()<KEEP_BUILT_REGIONS+1 and game.living().size()+2<=15 and pending.is_empty() and mission.get("status","completed")=="completed" else []}

func showcase_clear_opening(c:Dictionary)->String:
	if OS.get_environment("HARNESS_SECOND_STAGE_TANK_SHOWCASE")!="1":return "showcase_not_enabled"
	if c.get("run_id","")!=game.run_id:return "stale_run"
	if game.paused or game.winner!="":return "growth_game_not_running"
	if revision!=1 or mission.get("status","")!="active":return "showcase_opening_unavailable"
	if not game.living("green").any(func(u):return u.weapon=="rocket"):return "showcase_rocket_lost"
	for u in game.living("red"):
		if u.id in mission.defenders:u.hp=0
	update_mission()
	if mission.status!="completed":return "showcase_opening_not_cleared"
	game.add_event("坦克演示：已跳过首关交火，JEV 正在搭建第二关")
	return "showcase_opening_cleared"

func execute(c: Dictionary) -> String:
	if c.get("run_id","")!=game.run_id:return "stale_run"
	if game.paused or game.winner!="":return "growth_game_not_running"
	if seen.has(c.get("operation_id","")):return "growth_duplicate"
	if not pending.is_empty():return "growth_busy"
	if int(c.get("growth_revision",-1))!=revision:return "growth_revision_changed"
	if snapshot().options.is_empty():return "growth_encounter_or_capacity_pending"
	if not c.get("option","") in options:return "invalid_growth_option"
	var mission_kind:String=str(c.get("mission_kind","assault"))
	if not mission_kind in ["assault","rescue"]:return "invalid_mission_kind"
	var defender_mix:String=str(c.get("defender_mix","balanced"))
	var infantry_rosters:Dictionary={
		"balanced":["rifle","smg","pistol","rifle","smg","pistol"],
		"rifle_screen":["rifle","rifle","smg","pistol","rifle","smg"],
		"close_patrol":["smg","pistol","rifle","smg","pistol","rifle"]}
	if not infantry_rosters.has(defender_mix):return "invalid_defender_mix"
	var support_type:String=str(c.get("support_type","infantry"))
	if not support_type in ["infantry","rocket_team","tank"]:return "invalid_support_type"
	if support_type!="infantry" and revision==0:return "support_not_available_in_opening"
	if not c.get("operation_id") is String or c.operation_id.length()<1:return "invalid_operation_id"
	var h=c.get("hormones",{})
	if not h is Dictionary:return "invalid_hormones"
	for key in ["pressure","recovery","expansion","teaching","novelty"]:
		if not h.has(key) or not (h[key] is float or h[key] is int) or not is_finite(float(h[key])) or h[key]<0 or h[key]>1:return "invalid_hormones"
	var right: float=game.config.bounds[2]
	var z: float=(game.config.bounds[1]+game.config.bounds[3])*.5
	var friendly_value=c.get("friendly_count",0);var enemy_value=c.get("enemy_count",3)
	if not GrowthValidation.valid_count(friendly_value,0,2) or not GrowthValidation.valid_count(enemy_value,2,2 if support_type=="tank" else 6):return "invalid_force_count"
	var friendly_count=int(friendly_value);var enemy_count=int(enemy_value)
	if support_type=="tank" and not tank_counter_available(friendly_count):return "no_friendly_anti_armor"
	var captive_count:int=1 if mission_kind=="rescue" else 0
	if game.living("green").size()+friendly_count+captive_count>6 or game.living().size()+friendly_count+enemy_count+captive_count+(3 if support_type=="tank" else 0)>15:return "force_capacity"
	var spec:Dictionary=Encounter.specification(c.option)
	if c.has("build_operations"):
		if c.get("assembly_kind","")=="region_graph_v1":spec=preload("res://scripts/world_region_graph.gd").assemble(c.build_operations)
		else:spec=Encounter.assemble(c.option,c.build_operations)
		if spec.is_empty():return "invalid_build_operations"
	if mission_kind=="rescue":
		spec=preload("res://scripts/world_fortress.gd").apply(spec,enemy_count)
		if spec.is_empty():return "invalid_fortress_force"
	var visual_pattern:String=str(c.get("visual_pattern","open_field"))
	if not visual_pattern in ["open_field","north_screen","south_screen","central_gate","zigzag","diagonal","rescue"]:
		visual_pattern="open_field"
	spec.design_card["visual_pattern"]=visual_pattern
	var slots:Array=spec.get("defender_slots",spec.defenders)
	if enemy_count>slots.size():return "insufficient_defender_slots"
	spec.defenders=slots.slice(0,enemy_count)
	var roster:Array=infantry_rosters[defender_mix]
	for i in range(spec.defenders.size()):spec.defenders[i][2]=roster[i]
	if support_type=="rocket_team":spec.defenders[-1][2]="rocket"
	var friendlies:Array=[]
	if spec.has("friendly_slots"):
		if spec.friendly_slots.size()<friendly_count:return "insufficient_friendly_slots"
		friendlies=spec.friendly_slots.slice(0,friendly_count)
	else:
		for i in range(friendly_count):friendlies.append([.12,float(spec.entry[1])+(i*2-1)*.28])
	spec["friendlies"]=friendlies.duplicate(true)
	var validation=Encounter.validate(spec,(game.config.bounds[3]-game.config.bounds[1])*.5)
	if not validation.ok:return "invalid_compiled_encounter:"+str(validation.reason)
	if not construction_safe(right,spec,1 if support_type=="tank" else 0):return "growth_site_occupied"
	pending={"option":c.option,"operation_id":c.operation_id,"left":right,"z":z,"spec":spec,"friendlies":friendlies,"mission_kind":mission_kind,"defender_mix":defender_mix,"support_type":support_type}
	hormones=h.duplicate();seen.append(c.operation_id);clock=0
	while seen.size()>128:seen.pop_front()
	preview=Node3D.new();add_child(preview)
	# Preview the actual wood and stationery once, then transfer those nodes at
	# commit. This prevents cyan proxy boxes and avoids rebuilding the art twice.
	preview_desks=GrowthVisual.build(game,revision,right,preview,visual_pattern,spec.design_card.get("main_regions",[]))
	preview_covers=[]
	for item in pending.spec.covers:
		var prop=Node3D.new();preview.add_child(prop)
		prop.position=Vector3(right+item[0],game.field.height,z+item[1])
		preload("res://scripts/world_props.gd").build(game.field,prop,item)
		preview_covers.append(prop)
	for i in range(preview_desks.size()):
		var piece=preview_desks[i]
		piece.set_meta("build_origin",piece.position)
		piece.set_meta("build_delay",float(i)*.075)
		piece.set_meta("build_duration",.30)
		piece.set_meta("build_desk",true)
		piece.visible=false
	for i in range(preview_covers.size()):
		var piece=preview_covers[i]
		piece.set_meta("build_origin",piece.position)
		piece.set_meta("build_delay",.78+float(i)/maxf(1,preview_covers.size()-1)*.43)
		piece.set_meta("build_duration",.24)
		piece.visible=false
	# Preview has no collision and lies outside the still unchanged navigation bounds.
	game.camera_target=Vector3(right+.8,game.field.height,z)
	game.camera_size=3.0
	show_status("桌面接入 / "+pending.spec.name+" · 木桌与文具依次落位"+"\n节奏 pressure %.2f / recovery %.2f"%[h.pressure,h.recovery])
	# Hold the hidden preview before the first reveal, so recording includes construction.
	if revision==0 and OS.get_environment("HARNESS_RECORDING_COUNTDOWN")=="1":recording_countdown()
	game.add_event("实时构建开始："+str(c.option));return "growth_started"

func tick(dt: float):
	if game.paused or game.winner!="":return
	if game.elapsed>=next_retirement_check:
		next_retirement_check=game.elapsed+1;retire_old_regions()
	if harness_green or harness_red:
		var validation_started: int=Time.get_ticks_usec()
		execution_validator.tick(game,OS.get_environment("HARNESS_SPATIAL_OUTPUT"))
		game.record_cost("world_execution_validation",validation_started)
		var spatial_started: int=Time.get_ticks_usec()
		spatial.tick(game,OS.get_environment("HARNESS_SPATIAL_OUTPUT"),"topology")
		game.record_cost("world_spatial",spatial_started)
	reinforcements.tick(dt)
	# Infantry can be JEV controlled on either side; the existing vehicle
	# navigation/targeting AI drives tanks, which are outside Soldier Agents.
	if harness_red:
		for unit in game.living("red"):
			if unit.tank:game.tactics_ai.plan_tank(unit)
	for region in completed:
		for order in reinforcements.orders:
			if order.operation_id==region.operation_id:
				for id in order.spawned:
					if not id in region.spawned:region.spawned.append(id)
	update_mission()
	if pending.is_empty():return
	clock+=dt
	for piece in preview.get_children():
		var t=clampf((clock-float(piece.get_meta("build_delay",0)))/float(piece.get_meta("build_duration",.24)),0,1)
		piece.visible=t>0
		var smooth=t*t*(3-2*t)
		if piece.has_meta("build_desk"):
			piece.scale=Vector3(1,maxf(.001,smooth),1)
			piece.position=piece.get_meta("build_origin")
		else:
			piece.scale=Vector3.ONE*maxf(.001,smooth)
			piece.position=piece.get_meta("build_origin")+Vector3(0,.06*(1-smooth),0)
	if clock<BUILD_SECONDS:return
	commit()

func commit():
	var p=pending.duplicate();var left: float=p.left;var z: float=p.z
	var validation=Encounter.validate(p.spec,(game.config.bounds[3]-game.config.bounds[1])*.5)
	var failure=""
	if not validation.ok:failure="invalid_compiled_encounter:"+str(validation.reason)
	elif p.friendlies!=p.spec.get("friendlies",[]) or not GrowthValidation.valid_count(p.spec.defenders.size(),2,2 if p.support_type=="tank" else 6) or not GrowthValidation.valid_count(p.friendlies.size(),0,2):failure="invalid_force_count"
	elif game.living("green").size()+p.friendlies.size()+(1 if p.mission_kind=="rescue" else 0)>6 or game.living().size()+p.friendlies.size()+p.spec.defenders.size()+(1 if p.mission_kind=="rescue" else 0)+(3 if p.support_type=="tank" else 0)>15:failure="force_capacity_before_commit"
	elif p.support_type=="tank" and not tank_counter_available(p.friendlies.size()):failure="no_friendly_anti_armor_before_commit"
	elif not construction_safe(left,p.spec,1 if p.support_type=="tank" else 0):failure="site_occupied_before_commit"
	if failure!="":
		construction_failures.append({"operation_id":p.operation_id,"option":p.option,"reason":failure,"tick":game.tick_id})
		if construction_failures.size()>32:construction_failures.pop_front()
		preview.queue_free();preview_desks.clear();preview_covers.clear();pending.clear();show_status("施工取消 / "+failure);return
	var rects:Array=[]
	var region_tiles:Array=[]
	var new_desks:Array=[]
	for panel in preview_desks:
		preview.remove_child(panel);add_child(panel)
		panel.position=panel.get_meta("build_origin");panel.scale=Vector3.ONE;panel.visible=true
		new_desks.append(panel);desk_panels.append(panel)
	region_tiles.append_array(new_desks)
	for r in p.spec.floors:
		var tile=StaticBody3D.new();add_child(tile);region_tiles.append(tile)
		var size=Vector3(r[2]-r[0],.018,r[3]-r[1])
		tile.position=Vector3(left+(r[0]+r[2])/2,game.field.height-.009,z+(r[1]+r[3])/2)
		# Invisible collision support; the single desk mesh supplies the surface.
		var shape=CollisionShape3D.new();var box=BoxShape3D.new();box.size=size;shape.shape=box;tile.add_child(shape)
		rects.append([left+r[0],z+r[1],left+r[2],z+r[3]])
	if not game.config.has("world_floor_regions"):game.config["world_floor_regions"]=[]
	game.config.world_floor_regions.append({"left":left,"right":left+WIDTH,"rects":rects})
	# Distinct route compositions: short exposed approach versus longer protected flank.
	var layout: Array=p.spec.covers
	for i in range(layout.size()):
		var item: Array=layout[i]
		var fort_wall:bool=item[4]=="fort_wall"
		var cover={"id":"growth_%d_%d"%[revision,i],"position":[left+item[0],z+item[1]],"size":[item[2],item[3]],"normal":[-1,0] if item[3]>item[2] else [0,-1],"height":item[5],"hp":(240.0 if fort_wall else (160.0 if item[4]=="sandbag" else -1.0)),"max_hp":240.0 if fort_wall else 160.0,"kind":"hard" if item[4]!="sandbag" else "sandbag","alive":true,"damage_stage":"intact","node":null}
		cover.node=preview_covers[i]
		preview.remove_child(cover.node);game.field.add_child(cover.node)
		cover.node.position=cover.node.get_meta("build_origin");cover.node.scale=Vector3.ONE;cover.node.visible=true
		game.field.covers.append(cover)
	var dressing=preload("res://scripts/world_scenery.gd").new()
	add_child(dressing);region_tiles.append(dressing)
	var decoration_receipt:Dictionary=dressing.build(game,p.spec,left,z,new_desks)
	active_regions.append({"index":revision,"left":left,"right":left+WIDTH,"tiles":region_tiles})
	game.config.bounds[2]=left+WIDTH
	if game.camera_mode=="battle":
		game.camera_target=Vector3(left+WIDTH*.5,game.field.height,z)
		game.camera_size=3.45
	game.field.rebuild()
	var green_before=team_summary("green")
	var friendly_spawned:Array=[]
	for i in range(p.friendlies.size()):
		var row=p.friendlies[i];var id="green-"+str(100+revision*10+i)
		var weapon:String="rifle"
		if not game.living("green").any(func(member):return member.weapon=="rocket"):weapon="rocket"
		elif not game.living("green").any(func(member):return member.weapon=="smg"):weapon="smg"
		var u=game.spawn_unit(id,"green",Vector2(left+row[0],z+row[1]));u.equip(weapon)
		friendly_spawned.append(id)
	var captive_id:String=""
	if p.mission_kind=="rescue":
		var point:Array=p.spec.rescue.captive
		captive_id="green-"+str(900+revision)
		var captive=game.spawn_unit(captive_id,"green",Vector2(left+point[0],z+point[1]))
		captive.equip("pistol");captive.deployment_phase="captive";captive.posture="crouch"
		captive.posture_order="crouch";captive.order_mode="waiting_rescue";captive.animate("crouch")
		rescue_label=Label3D.new();captive.add_child(rescue_label)
		rescue_label.text="待救援";rescue_label.position.y=.19;rescue_label.font_size=40
		rescue_label.pixel_size=.0014;rescue_label.billboard=BaseMaterial3D.BILLBOARD_ENABLED
		rescue_label.modulate=Color(.4,1,.7)
	var spawned:Array=[]
	unit_roles.clear()
	for i in range(p.spec.defenders.size()):
		var row:Array=p.spec.defenders[i]
		var id:String="red-"+str(100+revision*10+i)
		var u=game.spawn_unit(id,"red",Vector2(left+row[0],z+row[1]));u.equip(row[2]);u.rotation.y=PI/2
		u.order_mode="prepared_defense";u.posture_order="crouch";spawned.append(id)
		unit_roles[id]={"role":row[3],"anchor":[left+row[0],z+row[1]],"phase":"驻守"}
	var support_status:String="none"
	if p.support_type=="tank":
		var staging:Dictionary=tank_staging_point(left,z,p.spec)
		if staging.ok:
			var tank_id:String="red-tank-"+str(revision)
			var tank=game.spawn_unit(tank_id,"red",staging.point,true)
			tank.hp=240.0;tank.max_hp=240.0;tank.order_mode="armored_support"
			spawned.append(tank_id);support_status="deployed"
			game.add_event("坦克增援：敌方装甲进入本段；可用火箭兵、炸药包或夺取敌方迫击炮反制")
			# Keep the crew within this encounter and away from enemy spawn points.
			var mortar_site:Dictionary=mortar_staging_point(left,z,tank)
			if mortar_site.ok:
				if mortar_support==null:
					mortar_support=preload("res://scripts/world_mortar.gd").new()
					add_child(mortar_support);mortar_support.setup(game,mortar_site.point,tank)
				else:mortar_support.redeploy(mortar_site.point,tank)
				spawned.append_array(mortar_support.crew_ids)
				game.add_event("敌方后方迫击炮据点：一名操作手即可勉强开火，警戒兵会在侧后方掩护；清空炮班后一名我方士兵即可接管")
			else:game.add_event("迫击炮组未部署：本段没有避开敌方出生点的安全炮位")
		else:
			support_status=str(staging.reason)
			game.add_event("坦克未部署：本段没有安全的装甲站位")
	completed.append({"index":revision,"option":p.option,"operation_id":p.operation_id,"tick":game.tick_id,"bounds":game.config.bounds.duplicate(),"defender_mix":p.defender_mix,"support_type":p.support_type,"support_status":support_status,"spawned":spawned,"friendly_spawned":friendly_spawned,"captive_id":captive_id,"design":p.spec,"decoration":decoration_receipt,"validation":Encounter.validate(p.spec,(game.config.bounds[3]-game.config.bounds[1])*.5)})
	revision+=1;preview.queue_free();preview_desks.clear();preview_covers.clear();pending.clear()
	# Advance the rally point into the new traversable corridor, preserving the run.
	# Rescue encounters have a second, more specific objective: the captive. The
	# old code always exposed the fortress exit as `mission.target`, which made
	# Harness route the squad to the empty area above the fortress and then mark
	# it as arrived while the captive remained behind the defenders. Keep the
	# normal exit for assault, but derive the rescue target from the spawned
	# captive so commander/JEV receive the same point the engine uses to finish
	# the mission.
	game.objective=Vector2(left+p.spec.exit[0],z+p.spec.exit[1])
	if p.mission_kind=="rescue" and captive_id!="":
		var captive_target:Array=p.spec.rescue.captive
		game.objective=Vector2(left+captive_target[0],z+captive_target[1])
	game.config.objective=[game.objective.x,game.objective.y]
	mission={"index":revision,"operation_id":p.operation_id,"name":p.spec.name,"option":p.option,"mission_kind":p.mission_kind,"defender_mix":p.defender_mix,"support_type":p.support_type,"support_status":support_status,"captive_id":captive_id,"rescue_status":"trapped" if captive_id!="" else "none","status":"active","green_before_reinforcement":green_before,"green_start":team_summary("green"),"friendly_added":friendly_spawned.size(),"enemies_initial":spawned.size(),"target":[game.objective.x,game.objective.y],"started":game.elapsed,"arrived":0,"required":0,"enemies_remaining":spawned.size(),"defenders":spawned.duplicate(),"left":left,"center_z":z,"spec":p.spec,"flanker":"","entry":[left+p.spec.entry[0],z+p.spec.entry[1]],"last_progress":game.elapsed,"best_distance":999.0,"least_enemy_hp":99999.0,"recovery_count":0}
	if marker:marker.queue_free()
	marker=Node3D.new();add_child(marker)
	var material=game.field.mat(Color(.15,.85,.75))
	for dz in [-.16,.16]:game.field.cube(marker,Vector3(game.objective.x,game.field.height+.01,z+dz),Vector3(.12,.012,.035),material)
	for u in game.living("green"):u.route.clear();u.focus_id="";u.target_id=""
	if harness_green:game.control_epochs.green+=1
	# Newly spawned defenders must not inherit the previous stage's squad plan
	# or accept a late command produced for dead defenders.
	if harness_red:game.control_epochs.red+=1
	show_status(p.spec.name+" / "+str(spawned.size())+" 名守军已就位\n"+("绿色 Harness 指挥与执行" if harness_green else "本地 Bot 演练")+" · 清除守军后展开下一段")
	game.add_event("新区域接入完成，通路与掩体生效："+str(p.option))
	if captive_id!="":game.add_event("解救任务：文件堡垒内有被困友军；先清除外围守军")


func update_mission():
	mission_lifecycle.update(self)

func team_summary(team:String)->Dictionary:
	return mission_lifecycle.team_summary(self,team)

func finish_mission(status:String,reason:String):
	mission_lifecycle.finish(self,status,reason)

func plan(team: String):
	local_ai.plan(self,team)

func construction_safe(left: float, spec: Dictionary, support_units:int=0) -> bool:
	var friendlies:Array=spec.get("friendlies",[])
	if absf(left-float(game.config.bounds[2]))>.001 or game.living().size()+spec.defenders.size()+friendlies.size()+(1 if spec.has("rescue") else 0)+support_units+(2 if support_units==1 else 0)>15:return false
	if game.living("green").size()+friendlies.size()+(1 if spec.has("rescue") else 0)>6:return false
	if not GrowthValidation.valid_count(spec.defenders.size(),2,2 if support_units==1 else 6) or friendlies.size()>2:return false
	if not Encounter.validate(spec,(game.config.bounds[3]-game.config.bounds[1])*.5).ok:return false
	var center:float=(game.config.bounds[1]+game.config.bounds[3])*.5
	for item in spec.covers:
		var p=Vector2(left+item[0],center+item[1]);var half=Vector2(item[2],item[3])*.5
		for u in game.living():
			if absf(u.pos().x-p.x)<half.x+.12 and absf(u.pos().y-p.y)<half.y+.12:return false
	for rows in [spec.defenders,friendlies]:
		var spacing:float=.2 if rows==spec.defenders else .12
		for row in rows:
			var p=Vector2(left+row[0],center+row[1])
			if game.living().any(func(u):return u.pos().distance_to(p)<spacing):return false
	if spec.has("rescue"):
		var point=Vector2(left+spec.rescue.captive[0],center+spec.rescue.captive[1])
		if game.living().any(func(u):return u.pos().distance_to(point)<.16):return false
	return true


func retire_old_regions():
	retirement_manager.retire(self)

func recording_countdown():
	game.paused=true
	var layer=CanvasLayer.new();layer.layer=100;add_child(layer)
	var label=Label.new();layer.add_child(label)
	label.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	label.horizontal_alignment=HORIZONTAL_ALIGNMENT_CENTER
	label.vertical_alignment=VERTICAL_ALIGNMENT_CENTER
	label.add_theme_font_size_override("font_size",100)
	label.add_theme_color_override("font_color",Color(1,.91,.55))
	label.add_theme_color_override("font_outline_color",Color(.08,.10,.09))
	label.add_theme_constant_override("outline_size",12)
	for word in ["3","2","1"]:
		label.text=word
		await get_tree().create_timer(1.0).timeout
	layer.queue_free()
	game.paused=false
