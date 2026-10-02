extends SceneTree
var failures: Array=[]
var checks: int=0
var g
var escape_origin: Vector2

func _initialize() -> void:call_deferred("run")

func check(value: bool, label: String) -> void:
	checks+=1
	if not value:failures.append(label);push_error(label)

func reset(u, human: bool, at: float) -> void:
	g.human_squad=human;g.elapsed=at;g.control[u.faction]="game_ai"
	u.hp=u.max_hp;u.deployment_phase="active";u.position=Vector3(-10,g.field.height,0)
	u.actor.global_position=u.global_position;u.actor.stepping=false
	u.cover_id="";u.cover_slot={};u.cqb_stance="open";u.garrison_phase="";u.gun_id=""
	u.posture_order="auto";u.posture="stand";u.posture_since=at-10;u.last_clip=""
	u.suppression=0;u.safety_until=0;u.last_threat_at=-100;u.melee_until=0;u.grenade_time=-1
	u.explosive_notice_at=-100;u.explosive_until=0
	u.harness_last_damage=-100;u.harness_prone_hold_until=-1;u.harness_prone_hit_pending=false
	u.set_meta("harness_manual_posture",false);u.order_mode="squad_advance"
	u.goal=Vector2(-9.8,0);u.route=PackedVector2Array([u.goal])

func run() -> void:
	set_meta("infinite_world",true)
	g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
	g.set_physics_process(false);g.paused=true
	var u=g.living("green")[0]
	escape_origin=Vector2(1.04,2.18)
	var enemy=g.spawn_unit("red-posture-probe","red",Vector2(-9.5,0))
	enemy.deployment_phase="active"
	for human in [false,true]:
		var mode: String="harness" if human else "local"
		reset(u,human,20)
		u.update_posture(false)
		check(u.posture=="stand",mode+": sight alone does not force prone")
		u.hit(1,.12,enemy.global_position);u.update_posture(true)
		var first_since: float=u.posture_since
		var first_until: float=u.harness_prone_hold_until
		u.last_clip="prone_idle"
		check(u.posture=="prone" and is_equal_approx(first_until,23),mode+": hit enters three second hold")
		for elapsed in [20.1,21.2,22.9]:
			g.elapsed=elapsed;u.suppression=0;u.posture_order="crouch"
			u.update_posture(true)
			check(u.posture=="prone" and u.locomotion=="crawl",mode+": model crouch cannot break recovery")
			check(is_equal_approx(u.posture_since,first_since) and u.last_clip=="prone_idle",mode+": no hidden transition or animation restart")
		check(is_equal_approx(u.harness_prone_hold_until,first_until),mode+": queries and commands do not renew minimum")
		g.elapsed=23.01;u.posture_order="auto";u.update_posture(true)
		check(u.posture=="stand",mode+": resumes ordinary travel after three quiet seconds")
		reset(u,human,30)
		u.hit(1,.12,enemy.global_position);u.update_posture(false)
		g.elapsed=32.8;u.receive_pressure(.05,enemy.global_position);u.suppression=0
		g.elapsed=33.1;u.update_posture(true)
		check(u.posture=="prone",mode+": real near miss extends quiet recovery beyond minimum")
		check(is_equal_approx(u.harness_prone_hold_until,33),mode+": real threat does not renew fixed minimum")
		g.elapsed=34.31;u.update_posture(true)
		check(u.posture=="stand",mode+": resumes after 1.5 second quiet window")
		reset(u,human,40)
		u.posture_order="crouch"
		u.suppression=.8;u.last_threat_at=40;u.update_posture(false)
		check(u.posture=="prone",mode+": real pressure overrides defender crouch and enters same hold")
		g.elapsed=43.1;u.suppression=.3;u.update_posture(true)
		check(u.posture=="prone",mode+": unrecovered pressure keeps protection")
		g.elapsed=43.2;u.suppression=.1;u.posture_order="auto";u.update_posture(true)
		check(u.posture=="stand",mode+": recovered pressure releases protection")
		reset(u,human,50)
		u.position=Vector3(escape_origin.x,g.field.height,escape_origin.y)
		u.actor.global_position=u.global_position
		u.hit(1,.12,enemy.global_position);u.update_posture(false)
		g.elapsed=50.1;u.evade_explosive(u.pos(),enemy.pos(),.8,.12)
		u.update_posture(not u.route.is_empty())
		check(not u.route.is_empty() and u.order_mode=="evade_explosive",mode+": real warning selects an escape route")
		check(u.posture=="crouch" and u.locomotion=="crouch_run",mode+": escape bypasses crawl speed")
		reset(u,human,60)
		u.hit(1,.12,enemy.global_position);u.update_posture(false)
		u.actor.stepping=true;u.posture="stand";u.posture_since=-10
		u.update_posture(true)
		check(u.posture!="prone",mode+": traversal is not forced back prone")
		u.actor.stepping=false
		reset(u,human,70)
		u.hit(1,.12,enemy.global_position);u.update_posture(false)
		u.hp=0;u.update_posture(false)
		check(not u.harness_prone_hold_active(),mode+": death clears recovery")
	reset(u,true,80)
	# The endless harness locks direct player control; exercise the shared
	# command parser in its ordinary mode for the explicit human override.
	g.growth=null
	u.hit(1,.12,enemy.global_position);u.update_posture(false)
	u.last_clip="prone_idle"
	g.elapsed=81.2;g.control[u.faction]="agent"
	var ack: Dictionary=g.command({"action":"posture","faction":u.faction,"unit_ids":[u.id],"source":"agent","posture":"stand","run_id":g.run_id,"seen_tick":g.tick_id})
	check(ack.accepted and u.posture=="prone" and is_equal_approx(u.posture_since,80),"actual model command cannot cancel or restart hold")
	g.elapsed=81.5
	ack=g.command({"action":"posture","faction":u.faction,"unit_ids":[u.id],"source":"agent","posture":"stand","run_id":g.run_id,"seen_tick":g.tick_id})
	check(ack.accepted and is_equal_approx(u.harness_prone_hold_until,83),"equivalent model command does not renew dwell")
	ack=g.command({"action":"posture","faction":u.faction,"unit_ids":[u.id],"source":"player","posture":"stand"})
	check(ack.accepted and u.posture=="stand" and not u.harness_prone_hold_active(),"actual explicit player command takes control")
	print("POSTURE_STABILITY_PROBE "+JSON.stringify({"checks":checks,"failures":failures,"minimum_seconds":3.0,"quiet_seconds":1.5}))
	g.queue_free();await process_frame
	quit(0 if failures.is_empty() else 1)
