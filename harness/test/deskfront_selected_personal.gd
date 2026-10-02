extends SceneTree
var failures: Array=[]

func _initialize() -> void:call_deferred("run")

func check(value: bool, label: String) -> void:
	if not value:
		failures.append(label)
		push_error(label)

func run() -> void:
	set_meta("infinite_world",true)
	var g=load("res://scenes/main.tscn").instantiate()
	root.add_child(g)
	g.set_physics_process(false)
	g.paused=false
	g.elapsed=3.0
	check(g.control.green=="lm" and g.human_squad,"Harness authority active")
	var u=g.living("green")[0]
	u.safety_until=0.0
	u.last_threat_at=-100.0
	var target=u.pos()
	for offset in [Vector2(.075,0),Vector2(-.075,0),Vector2(0,.075),Vector2(0,-.075)]:
		var candidate=u.pos()+offset
		if g.field.walkable(candidate) and not u.navigation_path(candidate).is_empty():
			target=candidate
			break
	check(target.distance_to(u.pos())>.02,"nearby native destination exists")
	var ids=g.living("green").map(func(member):return member.id)
	var assignments: Dictionary={}
	var other=g.living("green")[1]
	var flank=other.pos()
	for offset in [Vector2(0,.15),Vector2(0,-.15),Vector2(.15,0),Vector2(-.15,0)]:
		var candidate=other.pos()+offset
		if g.field.walkable(candidate) and not other.navigation_path(candidate).is_empty() and candidate.distance_to(target)>.12:
			flank=candidate
			break
	check(flank.distance_to(other.pos())>.02,"distinct native flank destination exists")
	for member in g.living("green"):
		var goal=flank if member.id==other.id else target
		assignments[member.id]={"role":"maneuver" if member.id==u.id else "fire_support", "region_id":"test-flank" if member.id==other.id else "test-target", "region_path":["test-origin","test-flank" if member.id==other.id else "test-target"],"position":[goal.x,goal.y],"route_positions":[[member.pos().x,member.pos().y],[goal.x,goal.y]]}
	var command={"action":"squad_order","source":"lm","faction":"green","squad_id":"green-squad","order_id":"test-order","unit_ids":ids,"intent":"advance","assignments":assignments,"position":[target.x,target.y],"radius":.10,"run_id":g.run_id,"seen_tick":g.tick_id,"control_epoch":g.control_epochs.green}
	var accepted=g.command(command)
	check(accepted.accepted,"per-member order accepted: "+str(accepted.message))
	if accepted.accepted:
		var invalid=command.duplicate(true)
		invalid.order_id="bad-member-route"
		invalid.assignments[u.id].position=[999.0,999.0]
		check(g.command(invalid).message=="invalid_member_route","unwalkable member route rejected")
		var squad=g.human_squads.squads["green-squad"]
		check(g.human_squads.member_final_goal(squad,u).distance_to(target)<.001,"member goal delivered")
		check(g.human_squads.member_next_goal(squad,other).distance_to(flank)<.001,"second member keeps distinct flank route")
		var base=ProjectSettings.globalize_path("res://output/world")
		DirAccess.make_dir_recursive_absolute(base)
		var file=FileAccess.open(base+"/soldier-candidates-green-request.json",FileAccess.WRITE)
		file.store_string(JSON.stringify({"id":"native-1","run_id":g.run_id,"unit_id":u.id,"navigation_revision":g.field.revision,"proposals":[{"id":"C1","region_id":"test-target","position":[target.x,target.y]}]}))
		file.close()
		file=FileAccess.open(base+"/soldier-candidates-green-request.id",FileAccess.WRITE)
		file.store_string("native-1");file.close()
		g.growth.execution_validator.candidate_tick(g,base,"green")
		var native=JSON.parse_string(FileAccess.get_file_as_string(base+"/soldier-candidates-green-response.json"))
		check(native.status=="fresh" and native.options.size()==1,"native candidate query returned reachable site")
		file=FileAccess.open(base+"/soldier-candidates-green-request.json",FileAccess.WRITE)
		file.store_string(JSON.stringify({"id":"native-2","run_id":g.run_id,"unit_id":other.id,"navigation_revision":g.field.revision,"proposals":[{"id":"C1","region_id":"test-flank","position":[flank.x,flank.y]}]}))
		file.close()
		g.growth.execution_validator.candidate_tick(g,base,"green")
		check(not g.human_squads.get_meta("candidate_results_green",{}).has("native-2"),"new request waits for matching atomic marker")
		file=FileAccess.open(base+"/soldier-candidates-green-request.id",FileAccess.WRITE)
		file.store_string("native-2");file.close()
		g.growth.execution_validator.candidate_tick(g,base,"green")
		check(g.human_squads.get_meta("candidate_results_green",{}).has("native-1") and g.human_squads.get_meta("candidate_results_green",{}).has("native-2"),"parallel soldier candidates retain separate tokens")
		var personal={"action":"soldier_order","source":"lm","faction":"green","squad_id":"green-squad","order_id":"test-order","unit_ids":[u.id],"intent":"move_to_site","site_id":"C1","candidate_query_id":"native-1","run_id":g.run_id,"seen_tick":g.tick_id,"control_epoch":g.control_epochs.green}
		var result=g.command(personal)
		check(result.accepted,"selected native site accepted: "+str(result.message))
		check(u.goal.distance_to(target)<.001,"selected action reached engine movement")
		personal.site_id="C999"
		check(g.command(personal).message in ["personal_action_active","invalid_site_id"],"invalid or active site cannot replace order")
		var stale=personal.duplicate();stale.order_id="old-order"
		check(g.command(stale).message=="stale_soldier_assignment","stale soldier order rejected")
		var enemy=g.spawn_unit("red-focus-probe","red",other.pos()+Vector2(.3,0))
		if enemy!=null:
			enemy.deployment_phase="active"
			var clear_target: bool=false
			for offset in [Vector2(.3,0),Vector2(-.3,0),Vector2(0,.3),Vector2(0,-.3),Vector2(.2,.2),Vector2(-.2,-.2)]:
				var point: Vector2=other.pos()+offset
				if not g.field.walkable(point):continue
				enemy.position.x=point.x;enemy.position.z=point.y
				if g.human_squads.visible_to("green",enemy) and other.can_engage(enemy):clear_target=true;break
			check(clear_target,"native clear personal fire target exists")
			if clear_target:
				other.safety_until=0.0;other.last_threat_at=-100.0
				other.move_to(flank)
				g.human_squads.intent_executor.start_motion(other,"test-order","formation",flank,g.elapsed)
				check(not other.route.is_empty(),"squad route active before focus fire")
				var focus={"action":"soldier_order","source":"lm","faction":"green","squad_id":"green-squad","order_id":"test-order","unit_ids":[other.id],"intent":"focus_fire","target_id":enemy.id,"run_id":g.run_id,"seen_tick":g.tick_id,"control_epoch":g.control_epochs.green}
				var focus_result=g.command(focus)
				check(focus_result.accepted,"clear focus fire accepted: "+str(focus_result.message))
				if focus_result.accepted:
					check(other.route.is_empty() and other.goal.distance_to(other.pos())<.001,"focus fire pauses movement to permit aiming")
					check(other.focus_id==enemy.id,"focus fire retains target")
	print("SELECTED_PERSONAL "+JSON.stringify({"failures":failures,"goal":[u.goal.x,u.goal.y]}))
	g.queue_free()
	await process_frame
	quit(0 if failures.is_empty() else 1)
