extends SceneTree
var failures: Array=[]
var checks: Array=[]
func _initialize():call_deferred("run")
func check(ok: bool, name: String):
	checks.append({"test":name,"passed":ok})
	if not ok:failures.append(name);push_error(name)
func run():
	var g=load("res://scenes/main.tscn").instantiate();g.use_legacy_fixture=true;root.add_child(g);g.set_physics_process(false);g.fx.set_muted(true)
	g.human_squad=true;g.elapsed=30
	for c in g.field.covers:c.alive=false
	g.field.obstacles.clear();g.field.rebuild()
	for u in g.units:u.hp=0;u.actor.collision_layer=0
	var a=g.units[0];var b=g.units[1];var enemy=g.units[6]
	a.hp=100;b.hp=100
	a.position=Vector3(.3,g.field.height,.2);b.position=Vector3(.3,g.field.height,.28)
	g.set_control_mode("green","lm")
	var c={"action":"squad_order","source":"lm","faction":"green","unit_ids":[a.id,b.id],"squad_id":"green-squad","order_id":"one","intent":"advance","position":[.65,.2],"radius":.10,"run_id":g.run_id,"seen_tick":g.tick_id,"control_epoch":g.control_epochs.green}
	check(g.command(c).accepted,"authorized squad accepted")
	var s=g.human_squads.squads["green-squad"]
	g.human_squads.tick(.2)
	check(a.goal.distance_to(b.goal)>.025,"stable separated formation destinations")
	var anchor: Vector2=s.anchor
	c.order_id="two";check(g.command(c).accepted and s.anchor==anchor,"equivalent review keeps virtual leader progress")
	var conflict=c.duplicate(true);conflict.squad_id="other"
	check(g.command(conflict).message=="squad_member_already_owned","one intent owner per soldier")
	conflict=c.duplicate(true);conflict.unit_ids=[a.id,enemy.id]
	check(not g.command(conflict).accepted,"cross faction squad rejected")
	a.last_threat_at=30;a.suppression=1;a.safety_until=33;a.posture_order="auto";a.cover_id="";a.cover_slot={};a.cqb_stance="open";a.update_posture(true)
	check(a.posture=="prone" and a.locomotion=="crawl","real automatic suppressed crawl")
	g.flag_objective.holder="red"
	check(not g.flag_emergency("green"),"flag countdown cannot disable human self preservation")
	a.safety_until=0;a.suppression=0
	enemy.hp=100;enemy.position=Vector3(.9,g.field.height,.2)
	enemy.deployment_phase="parked"
	check(not g.human_squads.visible_to("green",enemy) and g.find_target(a)!=enemy,"parked nonparticipant cannot be perceived or targeted")
	var previous_shots: int=g.shots
	a.fire(enemy)
	check(g.shots==previous_shots,"final firing guard rejects parked targets")
	enemy.deployment_phase="active"
	g.human_squads.update_perception()
	check(g.human_squads.perception.green.has(enemy.id),"visible contact acquired")
	var observed: Array=g.human_squads.perception.green[enemy.id].position.duplicate()
	enemy.position=Vector3(3,g.field.height,3);g.elapsed+=1;g.human_squads.update_perception()
	check(not g.human_squads.perception.green[enemy.id].visible and g.human_squads.perception.green[enemy.id].position==observed,"hidden contact keeps last observed position")
	g.elapsed+=7;g.human_squads.update_perception()
	check(not g.human_squads.perception.green.has(enemy.id),"old contact expires")
	enemy.position=Vector3(1.35,g.field.height,.2);a.route.clear();b.route.clear();a.goal=a.pos();b.goal=b.pos()
	g.human_squads.tick(.2)
	check(s.phase=="advancing","visible but distant enemy does not deadlock support")
	enemy.position=Vector3(.7,g.field.height,.2);a.last_threat_at=-100;b.last_threat_at=-100;a.safety_until=0;b.safety_until=0
	g.human_squads.tick(.2)
	check(s.phase=="advancing","in-range contact alone keeps ordinary advance moving")
	s.cover_detours={a.id:{"until":g.elapsed-1}};s.cover_cooldowns={}
	check(not g.human_squads.moving_cover(a,s,s.goal) and s.cover_detours.is_empty() and s.cover_cooldowns[a.id]>g.elapsed,"expired cover deviation resumes formation with cooldown")
	a.last_threat_at=g.elapsed
	a.ammo=0;b.ammo=0;a.route.clear();b.route.clear();s.phase="establishing_support";s.since=g.elapsed-6
	g.human_squads.tick(.2)
	check(g.human_squads.events.any(func(e):return e.kind=="route_failed" and e.get("reason","")=="support_unavailable"),"missing support emits replanning event")
	check(s.phase=="blocked","unsupported movement timeout is not a successful standing order")
	a.last_threat_at=-100
	a.ammo=10;b.ammo=10;enemy.position=Vector3(1.12,g.field.height,.2);a.route.clear();b.route.clear();s.since=g.elapsed-2;s.phase="establishing_support";s.mover=""
	g.human_squads.bound("green-squad",s,[a,b])
	for u in [a,b]:
		var next: Vector2=g.field.soft_offset(u.pos(),u.pos().move_toward(s.goal,.16),.17)
		var path: PackedVector2Array=g.field.tactical_path(u.pos(),next,g.human_squads.threat_points(s.faction),s.faction)
		print("DEBUG ",u.id," pos ",u.pos()," next ",next," safety ",u.safety_until," time ",g.elapsed," sup ",u.suppression," reload ",u.reload_timer," range ",u.weapon_config().range," length ",g.field.route_length(path)," exposure ",g.field.route_exposure(path,g.human_squads.threat_points(s.faction))," lane ",g.human_squads.has_firing_lane(u,next)," solution ",u.firing_solution_at(enemy,next,"crouch")," phase ",s.phase," goal ",s.goal)
	g.human_squads.squads.clear();g.queue_free();await process_frame;quit()
