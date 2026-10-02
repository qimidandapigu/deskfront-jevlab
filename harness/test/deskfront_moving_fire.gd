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
	g.paused=true
	g.elapsed=2.0
	var u=g.living("green")[0]
	var enemy=g.spawn_unit("red-moving-fire-probe","red",Vector2(-9.6,0))
	check(enemy!=null,"probe enemy spawned")
	if enemy==null:quit(1);return
	u.deployment_phase="active";enemy.deployment_phase="active"
	u.position=Vector3(-10,g.field.height,0);u.actor.global_position=u.global_position
	enemy.position=Vector3(-9.6,g.field.height,0);enemy.actor.global_position=enemy.global_position
	u.weapon="rifle";u.ammo=8;u.cooldown=0;u.suppression=0;u.safety_until=0;u.order_mode="squad_advance"
	u.actor.update_weapon();enemy.actor.update_weapon()
	check(g.find_target(u)==enemy,"engine finds clear in-range contact")
	u.route=PackedVector2Array([Vector2(-9.4,0)])
	u.goal=Vector2(-9.4,0)
	u.rotation.y=atan2(-(enemy.pos()-u.pos()).x,-(enemy.pos()-u.pos()).y)
	u.locomotion="run"
	check(u.harness_mobile_fire_allowed(enemy,true),"rifle can fire during ordinary advance")
	u.locomotion="sprint"
	check(not u.harness_mobile_fire_allowed(enemy,true),"sprint never fires")
	u.locomotion="run";u.order_mode="retreat"
	check(not u.harness_mobile_fire_allowed(enemy,true),"retreat does not become contact fire")
	u.order_mode="squad_advance";u.weapon="rocket"
	check(not u.harness_mobile_fire_allowed(enemy,true),"rocket cannot fire on the move")
	check(u.harness_pause_for_fire(enemy,true),"rocket pauses briefly for aim")
	check(not u.route.is_empty(),"automatic aim pause retains assigned route")
	g.elapsed=u.harness_fire_pause_until+.01
	check(not u.harness_pause_for_fire(enemy,true),"pause ends without renewing immediately")
	u.weapon="rifle";u.harness_fire_pause_ready_at=0;u.cooldown=0
	u.harness_currently_moving=true
	var shots_before: int=g.shots
	var ammo_before: int=u.ammo
	u.fire(enemy)
	check(g.shots==shots_before+1 and u.ammo==ammo_before-1,"mobile rifle shot uses real engine firing")
	if g.shots>shots_before:
		var projectile: Dictionary=g.fx.projectiles[-1]
		check(is_equal_approx(float(projectile.cfg.accuracy),float(u.weapon_config().accuracy)*.55),"moving accuracy penalty reaches projectile")
	u.cooldown=0;u.harness_currently_moving=false
	u.fire(enemy)
	check(g.shots==shots_before+2,"stationary follow-up fires")
	if g.shots>shots_before+1:
		var projectile: Dictionary=g.fx.projectiles[-1]
		check(is_equal_approx(float(projectile.cfg.accuracy),float(u.weapon_config().accuracy)),"stationary accuracy restored")
	# Exercise the actual tick path with an assigned route, not just the helpers.
	u.cooldown=0;u.reload_timer=0;u.harness_fire_pause_until=0;u.harness_fire_pause_ready_at=g.elapsed+1
	u.order_mode="squad_advance";u.locomotion="run";u.aim_time=0
	var tick_shots: int=g.shots
	u.tick(.10)
	check(g.shots==tick_shots+1,"real tick fires during retained advance route")
	check(not u.route.is_empty(),"mobile shot does not cancel route")
	if g.shots>tick_shots:
		var projectile: Dictionary=g.fx.projectiles[-1]
		check(float(projectile.cfg.accuracy)<float(u.weapon_config().accuracy),"real tick shot carries moving penalty")
	u.cooldown=0;u.order_mode="soldier_rush_to_site";u.aim_time=0
	tick_shots=g.shots
	u.tick(.10)
	check(u.locomotion=="sprint" and g.shots==tick_shots,"explicit sprint keeps speed and does not fire")
	check(not u.route.is_empty(),"sprint retains destination")
	u.weapon="rocket";u.ammo=1;u.cooldown=0;u.order_mode="squad_advance"
	u.harness_fire_pause_ready_at=0;u.harness_fire_pause_until=0;u.aim_time=0
	g.elapsed+=1.0
	tick_shots=g.shots
	u.tick(.10)
	check(u.route.size()>0 and not u.harness_currently_moving,"rocket makes a bounded firing halt")
	g.elapsed+=.10
	u.tick(.10)
	check(g.shots==tick_shots+1,"rocket fires after stationary aim while route remains")
	g.elapsed=u.harness_fire_pause_until+.01
	u.tick(.10)
	check(u.harness_currently_moving and not u.route.is_empty(),"rocket resumes route after firing halt")
	g.human_squad=true
	g.human_squads.update_perception()
	u.posture_order="auto";u.cover_id="";u.cover_slot={};u.cqb_stance="open"
	u.safety_until=0;u.suppression=0;u.posture="stand";u.posture_since=g.elapsed-2
	var assigned_goal: Vector2=u.goal
	u.hit(5,.12,enemy.global_position)
	u.update_posture(true)
	check(u.posture=="prone" and u.locomotion=="crawl","confirmed damage causes immediate prone reaction")
	check(u.goal.distance_to(assigned_goal)<.001 and not u.route.is_empty(),"hit reaction does not cancel the route")
	u.reaction_at=0;u.survival_tick()
	check(u.safety_until<=g.elapsed,"single hit does not start prolonged survival override")
	check(u.goal.distance_to(assigned_goal)<.001 and not u.route.is_empty(),"single hit keeps assigned route after survival check")
	g.elapsed+=.6;u.update_posture(true)
	check(u.posture=="prone","injury prone reaction lasts beyond half a second")
	g.elapsed+=.7;u.suppression=0;u.safety_until=0
	u.update_posture(true)
	check(u.posture=="prone","hit reaction stays prone past the old 0.9 second expiry")
	u.hit(5,.12,enemy.global_position)
	check(g.elapsed<float(u.get_meta("harness_sustained_until",-1.0)),"second hit within two seconds records sustained fire")
	u.reaction_at=0;u.survival_tick()
	check(u.safety_until>g.elapsed,"repeated hits activate longer cover response")
	g.elapsed+=3.1;u.suppression=0;u.safety_until=0;u.order_mode="squad_advance"
	u.update_posture(true)
	check(u.posture=="stand","soldier stands when minimum hold and quiet recovery have elapsed")
	print("MOVING_FIRE_PROBE "+JSON.stringify({"failures":failures,"shots":g.shots-shots_before,"route_retained":not u.route.is_empty()}))
	g.queue_free()
	await process_frame
	quit(0 if failures.is_empty() else 1)
