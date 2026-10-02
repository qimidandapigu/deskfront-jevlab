extends SceneTree
var checks: Array=[]
func _initialize():call_deferred("run")
func check(condition: bool,label: String):
	checks.append({"test":label,"passed":condition})
	if not condition:push_error(label)
func run():
	set_meta("infinite_world",true)
	var game=load("res://scenes/main.tscn").instantiate();root.add_child(game)
	game.set_physics_process(false);game.paused=false;game.fx.set_muted(true)
	var command={"action":"grow_world","run_id":game.run_id,"growth_revision":game.growth.revision,
		"operation_id":"support-opening","option":"gate_north_books_cross_tight","enemy_count":3,
		"friendly_count":0,"defender_mix":"balanced","support_type":"infantry",
		"hormones":{"pressure":.5,"recovery":.5,"expansion":.5,"teaching":.5,"novelty":.5}}
	check(game.command(command).accepted,"encounter starts")
	game.growth.tick(2.0)
	var rocket=game.living("green").filter(func(u):return u.weapon=="rocket").front()
	var rifle=game.living("green").filter(func(u):return u.weapon=="rifle").front()
	var target=game.living("red").front()
	var placed: bool=false
	for radius in [.75,1.0]:
		if placed:break
		for i in range(24):
			var point: Vector2=rocket.pos()+Vector2.from_angle(TAU*float(i)/24.0)*float(radius)
			if not game.field.walkable(point) or not game.field.line_of_sight(rocket.pos(),point):continue
			target.position=Vector3(point.x,target.position.y,point.y);placed=true;break
	check(placed,"known target can be placed on walkable visible desk")
	for enemy in game.living("red"):
		if enemy!=target:enemy.hp=0
	var helper=preload("res://scripts/support_fire_position.gd").new()
	var controller=game.human_squads
	var squad={"order_id":"support-test","squad_id":"green-squad","intent":"cover",
		"assignments":{rocket.id:{"role":"fire_support"}},"mover":"","support_ids":[],
		"destinations":{},"rally_destinations":{}}
	check(helper.eligible(controller,rocket,squad),"explosive support role is eligible")
	check(not helper.eligible(controller,rifle,squad),"ordinary rifle does not take support-position authority")
	var status={"since":0.0,"state":"no_fire_lane"}
	var handled: bool=helper.recover(controller,rocket,squad,status)
	var chosen: Dictionary=rocket.get_meta("engagement_position",{})
	check(handled and chosen.get("status")=="ready","support soldier receives a validated local firing site")
	if chosen.get("status")=="ready":
		var point: Vector2=chosen.position
		check(point.distance_to(rocket.pos())<=.42,"local adjustment respects travel bound")
		check(rocket.firing_solution_at(target,point,"crouch").clear or rocket.firing_solution_at(target,point,"stand").clear,"chosen site has a real muzzle lane")
		check(status.state in ["holding_fire_position","relocating"],"support fire position enters execution")
	var blocked_case: bool=false
	var evaluator=preload("res://scripts/engagement_position.gd").new()
	for radius in [.55,.7,.85,1.0,1.15]:
		if blocked_case:break
		for i in range(32):
			var candidate: Vector2=rocket.pos()+Vector2.from_angle(TAU*float(i)/32.0)*float(radius)
			if not game.field.walkable(candidate):continue
			target.position=Vector3(candidate.x,target.position.y,candidate.y)
			if not controller.visible_to(rocket.faction,target):continue
			if rocket.firing_solution_at(target,rocket.pos(),"crouch").clear or rocket.firing_solution_at(target,rocket.pos(),"stand").clear:continue
			var alternate: Dictionary=evaluator.choose(game,rocket,target,"fire_support",.42)
			if alternate.get("status")!="ready" or rocket.pos().distance_to(alternate.position)<.035:continue
			blocked_case=true;break
	check(blocked_case,"desk fixture has a blocked rocket lane with a reachable alternative")
	if blocked_case:
		squad["fire_positions"]={rocket.id:{"since":-5.0,"next_check":0.0,"state":"no_fire_lane"}}
		controller.maintain_fire_position(rocket,squad)
		var receipt: Dictionary=rocket.get_meta("engagement_position",{})
		check(receipt.get("status")=="ready" and rocket.pos().distance_to(receipt.position)>.035,
			"blocked rocket receives a different valid firing site")
		check(not rocket.route.is_empty(),"fire-position motion is actually submitted to navigation")
		for tick_index in range(240):
			game.elapsed+=1.0/60.0;game.field.simulation_time=game.elapsed
			rocket.tick(1.0/60.0);game.fx.physics_tick(1.0/60.0)
			if rocket.last_shot_at>=0:break
		check(rocket.last_shot_at>=0,"rocket moves into the new lane and actually fires")
	var clear_long_lane: bool=false
	for radius in [.78,.83,.88]:
		if clear_long_lane:break
		for i in range(32):
			var candidate: Vector2=rocket.pos()+Vector2.from_angle(TAU*float(i)/32.0)*float(radius)
			if not game.field.walkable(candidate):continue
			target.position=Vector3(candidate.x,target.position.y,candidate.y)
			if not controller.visible_to(rocket.faction,target) or not rocket.firing_solution_at(target,rocket.pos(),rocket.posture).clear:continue
			clear_long_lane=true;break
	check(clear_long_lane,"fixture has a clear long-range support lane")
	if clear_long_lane:
		squad.intent="advance"
		rocket.move_to(rocket.pos()+Vector2(.18,0))
		check(not rocket.route.is_empty(),"support soldier has a forward route before fire hold")
		controller.maintain_fire_position(rocket,squad)
		var held: Dictionary=rocket.get_meta("engagement_position",{})
		check(held.get("mode")=="holding_valid_fire" and rocket.goal.distance_to(rocket.pos())<.035,
			"moving support soldier stops at a clear long-range firing lane")
	var passed: bool=checks.all(func(row):return row.passed)
	print("SUPPORT_FIRE_POSITION_CONTRACT "+JSON.stringify({"passed":passed,"checks":checks,"selection":chosen}))
	game.queue_free();await process_frame;quit(0 if passed else 1)
