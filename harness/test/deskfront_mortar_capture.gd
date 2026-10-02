extends SceneTree
var checks:Array=[]
var game
var mortar
func _initialize()->void:call_deferred("run")
func check(ok:bool,label:String)->void:
	checks.append({"passed":ok,"test":label})
	if not ok:push_error(label)
func place(u,point:Vector2)->void:
	u.position=Vector3(point.x,game.field.height,point.y);u.actor.global_position=u.global_position
func step(dt:float)->void:
	game.elapsed+=dt;mortar.tick(dt)
func run()->void:
	set_meta("infinite_world",true);OS.set_environment("HARNESS_HUMAN_SQUAD","1")
	OS.set_environment("HARNESS_GREEN_CONTROL","lm");OS.set_environment("HARNESS_RED_CONTROL","lm")
	game=load("res://scenes/main.tscn").instantiate();root.add_child(game)
	game.set_physics_process(false);game.paused=false;game.fx.set_muted(true)
	var green:Array=game.living("green")
	var point:Vector2=green[0].pos()+Vector2(.35,0)
	for u in green:place(u,point+Vector2(-1.5,0))
	var tank=game.spawn_unit("red-capture-tank","red",point+Vector2(1.45,0),true)
	tank.hp=240;tank.max_hp=240
	mortar=load("res://scripts/world_mortar.gd").new();game.add_child(mortar);mortar.setup(game,point,tank)
	game.field.covers=[mortar.proxy];game.field.harness_index_covers()
	var guards:Array=game.living("red").filter(func(u):return u.id in mortar.crew_ids)
	check(mortar.faction=="red" and guards.size()==2,"mortar starts occupied by two real enemy soldiers")
	check(game.living("green").size()==green.size() and green.all(func(u):return u.gun_id==""),"deployment gives green neither a gun nor free crew")
	check(mortar.known_target_id=="" and not mortar.target_available,"enemy mortar cannot use allied tank as a target")
	place(green[0],mortar.crew_point(0));place(green[1],mortar.crew_point(1))
	for i in range(4):step(1.0)
	check(mortar.faction=="red" and mortar.capture_count==0,"approaching living guards cannot steal the mortar")
	guards[0].hp=0;step(1.0)
	check(mortar.faction=="red" and mortar.gunner_id==guards[1].id and mortar.guard_id=="","one surviving enemy crew member takes over and holds ownership")
	guards[1].hp=0;mortar.proxy.hp=60.0;step(.5)
	check(mortar.faction=="neutral" and mortar.snapshot().capturable,"killed crew leaves the damaged gun available in place")
	check(mortar.capture_progress>0 and mortar.capture_count==0,"capture requires a real holding period")
	place(green[1],point+Vector2(-1.0,0));step(.5)
	check(mortar.capture_progress>.5 and mortar.faction=="neutral","one soldier can continue a real capture without a second crew member")
	place(green[1],point+Vector2(-1.0,0))
	var contest=game.spawn_unit("red-contest","red",point+Vector2(.30,0))
	step(1.0)
	check(mortar.capture_progress==0 and mortar.faction=="neutral","nearby enemy contests capture")
	contest.hp=0
	var positions:Array=[green[0].pos(),green[1].pos()]
	# A live squad owns these soldiers before capture. Only the captured members
	# must leave that execution, preserving the other member's ongoing task.
	game.human_squads.squads["capture-test"]={"order_id":"capture-order","unit_ids":[green[0].id,green[1].id,green[2].id],"personal":{},"assignments":{},"destinations":{},"rally_destinations":{},"mover":green[0].id,"support_ids":[green[1].id]}
	game.human_squads.owners[green[0].id]="capture-test";game.human_squads.owners[green[1].id]="capture-test"
	for i in range(3):step(1.0)
	check(mortar.faction=="green" and mortar.capture_count==1,"one existing green soldier captures after three uncontested seconds")
	check(game.living("green").size()==green.size() and mortar.crew_ids.has(green[0].id) and not mortar.crew_ids.has(green[1].id),"capture binds one present soldier without spawning reinforcements")
	check(green[0].pos()==positions[0] and green[1].pos()==positions[1],"capture never teleports existing crew")
	check(mortar.hp==60.0,"capturing preserves real gun damage")
	check(game.human_squads.squads["capture-test"].unit_ids==[green[1].id,green[2].id] and not game.human_squads.owners.has(green[0].id),"native equipment ownership releases only the captured soldier from its squad")
	place(green[2],tank.pos()+Vector2(.38,.12))
	for i in range(200):
		for u in green:
			if u.gun_id==mortar.id:mortar.drive(u,.033);u.presentation_tick(.033)
		game.human_squads.update_perception();step(.033)
	check(mortar.shots>0 and mortar.last_target_id==tank.id,"captured crew completes setup and fires a real shell at the enemy tank")
	check("red" in mortar.snapshot().seen_by,"firing reveals the fixed gun position to its opponent")
	for i in range(90):game.fx.physics_tick(.033)
	check(tank.hp<240,"captured mortar's real projectile damages the tank")
	green[0].hp=0
	var red1=game.spawn_unit("red-recapture-1","red",mortar.crew_point(0))
	var red2=game.spawn_unit("red-recapture-2","red",mortar.crew_point(1))
	red1.equip("rifle");red2.equip("rifle")
	for i in range(3):step(1.0)
	check(mortar.faction=="red" and mortar.capture_count==2 and mortar.crew_ids.has(red1.id) and not mortar.crew_ids.has(red2.id),"one soldier can recapture an abandoned gun under the same rules")
	mortar.proxy.hp=0;step(1.0)
	check(mortar.phase=="destroyed" and not mortar.snapshot().capturable,"destroyed mortar cannot be captured or fire")
	var passed:bool=checks.all(func(row):return row.passed)
	print("DESKFRONT_MORTAR_CAPTURE "+JSON.stringify({"passed":passed,"checks":checks,"shots":mortar.shots,"tank_hp":tank.hp}))
	game.queue_free();await process_frame;quit(0 if passed else 1)
