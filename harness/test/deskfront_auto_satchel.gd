extends SceneTree

var checks: Array=[]
func _initialize():call_deferred("run")
func check(ok: bool,label: String) -> void:
	checks.append({"passed":ok,"test":label})
	if not ok:push_error(label)

func run() -> void:
	set_meta("infinite_world",true)
	OS.set_environment("HARNESS_HUMAN_SQUAD","1")
	OS.set_environment("HARNESS_GREEN_CONTROL","lm")
	var game=load("res://scenes/main.tscn").instantiate();root.add_child(game)
	game.set_physics_process(false);game.paused=false;game.fx.set_muted(true)
	var friends: Array=game.living("green")
	var soldier=friends[0]
	for i in range(1,friends.size()):friends[i].position=Vector3(.9,game.field.height,2.75+i*.15)
	var tank=game.spawn_unit("red-auto-satchel","red",soldier.pos()+Vector2(0,-.56),true)
	game.set_control_mode("green","lm")
	var squad: Dictionary={"squad_id":"auto-satchel-squad","faction":"green","order_id":"auto-satchel-order","unit_ids":[soldier.id],"intent":"advance","phase":"advancing","goal":soldier.pos(),"radius":.1,"destinations":{},"rally_destinations":{},"assignments":{soldier.id:{"region_path":["antiarmor-test"]}},"personal":{}}
	game.human_squads.squads[squad.squad_id]=squad
	var approach: Vector2=soldier.pos()+Vector2(.075,0)
	var query_dir: String=ProjectSettings.globalize_path("res://output/world")
	DirAccess.make_dir_recursive_absolute(query_dir)
	var file=FileAccess.open(query_dir+"/soldier-candidates-green-request.json",FileAccess.WRITE)
	file.store_string(JSON.stringify({"id":"auto-satchel","run_id":game.run_id,"unit_id":soldier.id,"navigation_revision":game.field.revision,"proposals":[{"id":"C1","region_id":"antiarmor-test","position":[approach.x,approach.y],"kind":"anti_armor_approach","target_id":tank.id,"target_distance":approach.distance_to(tank.pos())}]}));file.close()
	file=FileAccess.open(query_dir+"/soldier-candidates-green-request.id",FileAccess.WRITE)
	file.store_string("auto-satchel");file.close()
	game.growth.execution_validator.candidate_tick(game,query_dir,"green")
	var receipt: Dictionary=game.command({"action":"soldier_order","source":"lm","faction":"green","unit_ids":[soldier.id],"squad_id":squad.squad_id,"order_id":squad.order_id,"intent":"rush_to_site","site_id":"C1","candidate_query_id":"auto-satchel","run_id":game.run_id,"seen_tick":game.tick_id,"control_epoch":game.control_epochs.green})
	check(receipt.accepted and soldier.harness_antiarmor_commit_active(),"model-approved rush carries a live tank target")
	soldier.safety_until=game.elapsed+.5
	var blocked: bool=game.human_squads.try_auto_satchel_on_charge(squad.personal[soldier.id],soldier)
	check(not blocked and soldier.grenade_time<0 and squad.personal[soldier.id].status=="active","urgent safety defers the automatic throw")
	soldier.safety_until=0
	game.human_squads.update_personal(squad,[soldier])
	check(soldier.grenade_time>=0 and squad.personal[soldier.id].status=="completed","safe throwing frame releases the approved charge without a second model call")
	check(not soldier.harness_antiarmor_commit_active() and soldier.snapshot().satchel_ready_in>0,"throw ends charge commitment and starts cooldown")
	var passed: bool=checks.all(func(row):return row.passed)
	print("DESKFRONT_AUTO_SATCHEL "+JSON.stringify({"passed":passed,"checks":checks}))
	game.queue_free();await process_frame;quit(0 if passed else 1)
