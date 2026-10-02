extends SceneTree
var checks:Array=[]
func _initialize():call_deferred("run")
func check(ok:bool,label:String):
	checks.append({"passed":ok,"test":label})
	if not ok:push_error(label)
func command(g,id:String,support:String="infantry",enemies:int=3,mix:String="balanced",friends:int=0)->Dictionary:
	return {"action":"grow_world","run_id":g.run_id,"growth_revision":g.growth.revision,
		"operation_id":id,"option":"gate_north_books_cross_tight","enemy_count":enemies,
		"friendly_count":friends,"defender_mix":mix,"support_type":support,"hormones":{"pressure":.5,"recovery":.5,
		"expansion":.5,"teaching":.5,"novelty":.5}}
func run():
	set_meta("infinite_world",true)
	var g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
	g.set_physics_process(false);g.paused=false;g.fx.set_muted(true)
	var starting:Array=g.living("green").map(func(u):return u.weapon)
	check(starting.size()==5 and starting.count("rifle")==2 and starting.count("smg")==2 and starting.count("rocket")==1,"opening has five members: two rifles two smgs one rocket")
	check(g.command(command(g,"first","infantry",6)).accepted,"six-person infantry encounter starts")
	g.growth.tick(2.0)
	var defenders:Array=g.living("red")
	check(defenders.size()==6 and defenders.any(func(u):return u.weapon=="rifle") and defenders.any(func(u):return u.weapon=="smg") and defenders.any(func(u):return u.weapon=="pistol"),"ordinary defender roster includes rifle smg and pistol")
	var previous_showcase:String=OS.get_environment("HARNESS_SECOND_STAGE_TANK_SHOWCASE")
	OS.set_environment("HARNESS_SECOND_STAGE_TANK_SHOWCASE","1")
	var skip_result:String=g.growth.showcase_clear_opening({"run_id":g.run_id})
	OS.set_environment("HARNESS_SECOND_STAGE_TANK_SHOWCASE",previous_showcase)
	check(skip_result=="showcase_opening_cleared" and g.growth.mission.status=="completed" and g.living("red").is_empty(),"showcase clears first battle with authoritative mission receipt")
	check(g.command(command(g,"armor","tank",2)).accepted,"armored encounter starts after opening")
	g.growth.tick(2.0)
	check(g.living("red").filter(func(u):return not u.tank and u.id not in g.at_guns[0].crew_ids).size()==2,"tank has exactly two infantry escorts outside the mortar crew")
	var tanks:Array=g.living("red").filter(func(u):return u.tank)
	check(tanks.size()==1 and (tanks[0].weapon=="cannon" if tanks.size()>0 else false),"tank with cannon enters generated table")
	check(g.growth.mission.support_status=="deployed" and (g.growth.mission.defenders.has(tanks[0].id) if tanks.size()>0 else false),"tank participates in mission receipt")
	if tanks.size()>0:
		g.tactics_ai.plan_tank(tanks[0])
		check(not tanks[0].route.is_empty() or tanks[0].pos().distance_to(g.living("green")[0].pos())<=g.config.weapons.cannon.range,"tank can navigate or already engage")
	check(g.at_guns.size()==1 and g.at_guns[0].faction=="red" and g.at_guns[0].crew_ids.size()==2,"enemy mortar shares the tank encounter without adding green crew")
	check(g.at_guns[0].pos().x> tanks[0].pos().x+.25 and g.at_guns[0].snapshot().staging_role=="rear_support","mortar occupies the rear support band behind the tank")
	for u in g.living("red"):
		if not u.tank:u.hp=0
	g.growth.update_mission()
	check(g.growth.mission.status=="active","living tank prevents premature clear")
	if tanks.size()>0:tanks[0].hp=0
	g.growth.update_mission()
	check(g.growth.mission.status=="completed","destroying tank completes encounter")
	check(g.command(command(g,"rocket","rocket_team",3,"close_patrol")).accepted,"rocket support encounter starts")
	g.growth.tick(2.0)
	var rocket_defenders:Array=g.living("red")
	check(rocket_defenders.size()==3 and rocket_defenders[0].weapon=="smg" and rocket_defenders[1].weapon=="pistol" and rocket_defenders[2].weapon=="rocket","selected close patrol and rocket support deploy exactly")
	g.queue_free();await process_frame
	var h=load("res://scenes/main.tscn").instantiate();root.add_child(h)
	h.set_physics_process(false);h.paused=false;h.fx.set_muted(true)
	check(h.command(command(h,"replacement-opening","infantry",2)).accepted,"replacement scenario opens")
	h.growth.tick(2.0)
	for u in h.living("red"):u.hp=0
	h.growth.update_mission()
	for u in h.living("green"):
		if u.weapon=="rocket":u.hp=0
	var previous_rule:String=OS.get_environment("HARNESS_SECOND_STAGE_TANK_RULE")
	OS.set_environment("HARNESS_SECOND_STAGE_TANK_RULE","1")
	check(h.command(command(h,"replacement-tank","tank",2,"balanced",1)).accepted,"tank rule accepts planned rocket replacement")
	h.growth.tick(2.0)
	check(h.living("green").any(func(u):return u.weapon=="rocket") and h.living("red").any(func(u):return u.tank),"rocket reinforcement enters before tank encounter")
	OS.set_environment("HARNESS_SECOND_STAGE_TANK_RULE",previous_rule)
	var passed:bool=checks.all(func(row):return row.passed)
	print("WORLD_ROSTER_CONTRACT "+JSON.stringify({"passed":passed,"checks":checks}))
	h.queue_free();await process_frame;quit(0 if passed else 1)
