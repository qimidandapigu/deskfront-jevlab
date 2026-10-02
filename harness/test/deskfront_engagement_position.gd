extends SceneTree
var checks: Array=[]
func _initialize():call_deferred("run")
func check(condition: bool,label: String):
	checks.append({"test":label,"passed":condition})
	if not condition:push_error(label)
func command(g,identifier: String,support: String="infantry") -> Dictionary:
	return {"action":"grow_world","run_id":g.run_id,"growth_revision":g.growth.revision,
		"operation_id":identifier,"option":"gate_north_books_cross_tight","enemy_count":2 if support=="tank" else 3,
		"friendly_count":0,"defender_mix":"balanced","support_type":support,
		"hormones":{"pressure":.5,"recovery":.5,"expansion":.5,"teaching":.5,"novelty":.5}}
func run():
	set_meta("infinite_world",true)
	var game=load("res://scenes/main.tscn").instantiate();root.add_child(game)
	game.set_physics_process(false);game.paused=false;game.fx.set_muted(true)
	var evaluator=preload("res://scripts/engagement_position.gd").new()
	var rifle=game.living("green").filter(func(unit):return unit.weapon=="rifle").front()
	var rocket=game.living("green").filter(func(unit):return unit.weapon=="rocket").front()
	check(float(evaluator.envelope(rocket,"fire_support").preferred_min)>float(evaluator.envelope(rifle,"maneuver").preferred_min),"longer weapon support band remains farther away")
	check(game.command(command(game,"opening")).accepted,"opening encounter starts")
	game.growth.tick(2.0)
	for unit in game.living("red"):unit.hp=0
	game.growth.update_mission()
	var armored: Dictionary=game.command(command(game,"armored","tank"))
	if not armored.accepted:print("ENGAGEMENT_SETUP "+JSON.stringify({"command":armored,"mission":game.growth.mission}))
	check(armored.accepted,"tank encounter starts")
	game.growth.tick(2.0)
	var tanks=game.living("red").filter(func(unit):return unit.tank)
	check(tanks.size()==1,"tank is physically spawned")
	if tanks.size()==1:
		var tank=tanks[0]
		game.tactics_ai.tank_next.erase(tank.id)
		game.tactics_ai.plan_tank(tank)
		var selection: Dictionary=tank.get_meta("engagement_position",{})
		check(selection.get("status")=="ready","support position has an executable firing lane")
		check(float(selection.get("distance",0))>=float(evaluator.envelope(tank,"fire_support").minimum),"tank respects shared minimum range")
		check(not tank.route.is_empty() or tank.pos().distance_to(game.living("green")[0].pos())<float(tank.weapon_config().range),"tank either moves toward a firing site or can already engage")
	var passed: bool=checks.all(func(row):return row.passed)
	print("ENGAGEMENT_POSITION_CONTRACT "+JSON.stringify({"passed":passed,"checks":checks}))
	game.queue_free();await process_frame;quit(0 if passed else 1)
