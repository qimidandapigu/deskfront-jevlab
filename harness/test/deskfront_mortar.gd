extends SceneTree
var checks:Array=[]
func _initialize():call_deferred("run")
func check(ok:bool,label:String)->void:
	checks.append({"passed":ok,"test":label})
	if not ok:push_error(label)
func run()->void:
	set_meta("infinite_world",true)
	OS.set_environment("HARNESS_HUMAN_SQUAD","1")
	OS.set_environment("HARNESS_GREEN_CONTROL","lm")
	var game=load("res://scenes/main.tscn").instantiate();root.add_child(game)
	game.set_physics_process(false);game.paused=false;game.fx.set_muted(true)
	var soldier=game.living("green")[2];soldier.equip("rifle")
	var origin:Vector2=soldier.pos()
	for other in game.living("green"):
		if other!=soldier:other.position=Vector3(soldier.position.x+.9,game.field.height,soldier.position.z+.9)
	var tank=game.spawn_unit("red-mortar-test","red",origin+Vector2(0,-.68),true)
	tank.hp=240;tank.max_hp=240
	var mortar=load("res://scripts/world_mortar.gd").new();game.add_child(mortar)
	mortar.setup(game,origin+Vector2(0,.35),tank,"green")
	check(mortar.crew_ids.size()==2,"two real soldiers crew the mortar")
	check(game.at_guns.has(mortar) and game.living("green").any(func(u):return u.gun_id==mortar.id),"crew operate through the native team-weapon path")
	soldier.position=Vector3(origin.x+1.1,game.field.height,origin.y+1.1)
	game.elapsed+=5.1
	mortar.tick(.1)
	check(mortar.shots==1 and mortar.snapshot().ammunition_policy=="unlimited_reserve","crewed mortar fires with unlimited ordinary reserve")
	check(game.fx.projectiles.size()==1 and game.fx.projectiles[0].cfg.get("harness_arc_height",0)>.5,"mortar shell uses a high indirect arc")
	check(is_equal_approx(float(game.fx.projectiles[0].cfg.accuracy),.84),"crewed mortar keeps its bounded accuracy payload")
	check(game.fx.projectiles[0].get("dispersion_weapon","")=="mortar","mortar uses an artillery dispersion cone")
	check(game.fx.projectiles[0].to.distance_to(tank.aim_point())>.001,"mortar round can miss around the observed point")
	mortar.tick(.1)
	check(mortar.shots==1,"cooldown prevents immediate repeated fire")
	for i in range(90):game.fx.physics_tick(.033)
	check(tank.hp<240,"real projectile and explosion damage the tank")
	check(game.fx.hit_log.any(func(row):return row.weapon=="mortar"),"impact log identifies the mortar round")
	game.elapsed+=11.0;mortar.tick(.1)
	check(mortar.shots==1 and mortar.phase=="waiting_target","unobserved deployment intelligence cannot repeat shells at an old point")
	# Give a real scout sight of the tank and an unobstructed test firing lane.
	game.field.covers=[mortar.proxy];game.field.harness_index_covers()
	soldier.position=Vector3(tank.position.x+.38,game.field.height,tank.position.z+.12)
	game.elapsed+=.3;game.human_squads.update_perception();mortar.tick(.1)
	check(mortar.shots==2 and mortar.known_source=="spotted","shared scout sight resumes ordinary fire")
	for i in range(90):game.fx.physics_tick(.033)
	var old_yaw:float=mortar.yaw
	tank.position=Vector3(mortar.position.x+1.45,game.field.height,mortar.position.z)
	soldier.position=Vector3(tank.position.x+.38,game.field.height,tank.position.z+.12)
	game.elapsed+=10.1;game.human_squads.update_perception();mortar.tick(.1)
	check(mortar.shots==2 and mortar.phase=="aiming" and absf(wrapf(mortar.yaw-old_yaw,-PI,PI))>.1,"tube traverses visibly and waits until aligned before firing")
	for i in range(15):
		game.elapsed+=.1;mortar.tick(.1)
	check(mortar.shots==3 and Vector2(mortar.known_point.x,mortar.known_point.z).distance_to(tank.pos())<.001,"next shell follows the moving visible tank instead of its spawn point")
	check(mortar.muzzle_position(Vector3.ZERO).x>mortar.global_position.x+.02,"real muzzle follows tube traverse")
	for i in range(90):game.fx.physics_tick(.033)
	for i in range(4):
		tank.hp=240;game.elapsed+=10.1;game.human_squads.update_perception();mortar.tick(.1)
		for frame in range(90):game.fx.physics_tick(.033)
	check(mortar.shots==7,"ordinary fire continues beyond five shells while retaining reload")
	# A contact can vanish between perception and launch; the live sight gate wins.
	soldier.position=Vector3(tank.position.x+2.0,game.field.height,tank.position.z+2.0)
	for other in game.living("green"):
		if other.gun_id=="":other.position=soldier.position
	game.elapsed+=10.1;mortar.tick(.1)
	check(mortar.shots==7 and mortar.phase=="waiting_target","stale visible contact does not authorize a shot through lost sight")
	game.human_squads.update_perception()
	# Another visible enemy replaces a dead designated tank.
	tank.hp=0
	var replacement=game.spawn_unit("red-mortar-next","red",mortar.pos()+Vector2(1.45,0))
	soldier.position=Vector3(replacement.position.x+.38,game.field.height,replacement.position.z+.12)
	game.human_squads.update_perception();game.elapsed+=.3;mortar.tick(.1)
	check(mortar.shots==8 and mortar.last_target_id==replacement.id,"dead tank releases the target and mortar engages another visible enemy")
	for i in range(90):game.fx.physics_tick(.033)
	check(replacement.hp>0 and replacement.hp<replacement.max_hp,"real mortar impact damages full-health infantry without instantly killing it")
	var loader=game.units.filter(func(u):return u.id==mortar.crew_ids[1])[0]
	loader.hp=0;game.elapsed+=11.0
	mortar.tick(.1)
	check(mortar.guard_id=="" and mortar.shots==9 and mortar.snapshot().fire_mode=="single_operator","one surviving operator keeps the mortar firing with a slower, less accurate cycle")
	tank.hp=240;tank.position=Vector3(origin.x,game.field.height,origin.y-.68)
	soldier.position=Vector3(origin.x,game.field.height,origin.y)
	game.field.covers.clear();game.field.harness_index_covers()
	game.human_squads.update_perception()
	soldier.route.clear();soldier.order_mode="hold";soldier.reaction_at=0
	soldier.survival_tick()
	check(soldier.order_mode=="self_preserve" and soldier.goal.distance_to(tank.pos())>soldier.pos().distance_to(tank.pos())+.07,"outmatched soldier makes a short retreat when no cover blocks the tank")
	# The exposed armor fallback must lower a soldier even if no path is found.
	soldier.order_mode="pinned";soldier.safety_reason="armor_outmatched"
	soldier.posture="stand";soldier.posture_order="auto"
	soldier.update_posture(false)
	check(soldier.posture=="prone" and soldier.harness_posture_snapshot().reason=="armor_pinned","armor-pinned infantry no longer stands idle")
	soldier.harness_prone_hold_until=-1;soldier.posture="stand"
	soldier.safety_reason="incoming_fire";soldier.safety_until=game.elapsed+1.0
	soldier.update_posture(false)
	check(soldier.posture=="prone" and soldier.harness_posture_snapshot().reason=="fire_pinned","infantry pinned by incoming fire also gets down")
	var passed=checks.all(func(item):return item.passed)
	print("DESKFRONT_MORTAR "+JSON.stringify({"passed":passed,"checks":checks,"tank_hp":tank.hp,"shots":mortar.shots}))
	game.queue_free();await process_frame;quit(0 if passed else 1)
