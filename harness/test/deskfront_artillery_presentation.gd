extends SceneTree
var checks:Array=[]
var game
func _initialize()->void:call_deferred("run")
func check(ok:bool,label:String)->void:
	checks.append({"passed":ok,"test":label})
	if not ok:push_error(label)
func place(u,point:Vector2)->void:
	u.position=Vector3(point.x,game.field.height,point.y)
	if u.actor:u.actor.global_position=u.global_position
func capture(name:String)->void:
	var folder:String=OS.get_environment("HARNESS_ARTILLERY_VISUAL_OUTPUT")
	if folder=="" or DisplayServer.get_name()=="headless":return
	await process_frame;await process_frame
	check(root.get_viewport().get_texture().get_image().save_png(folder.path_join(name+".png"))==OK,"save "+name)
func advance(seconds:float)->void:
	for i in range(ceili(seconds/.0166667)):
		game.elapsed+=.0166667;game.fx.physics_tick(.0166667);game.fx._process(.0166667)
func run()->void:
	set_meta("infinite_world",true);OS.set_environment("HARNESS_HUMAN_SQUAD","1")
	game=load("res://scenes/main.tscn").instantiate();root.add_child(game)
	game.set_process(false);game.set_physics_process(false);game.paused=false;game.fx.set_muted(true);game.fx.set_process(false)
	check(game.living("green").size()==5,"new expedition starts with exactly five green soldiers")
	game.ui.hide()
	var point:Vector2=Vector2(1.15,2.00)
	var target=game.living("green")[0]
	for u in game.living("green"):place(u,point+Vector2(-2.0,1.0))
	place(target,point+Vector2(0,-1.05));target.equip("rifle")
	var tank=game.spawn_unit("red-artillery-test","red",point+Vector2(.72,.10),true)
	var mortar=load("res://scripts/world_mortar.gd").new();game.add_child(mortar);mortar.setup(game,point,tank)
	for i in range(20):
		for u in game.living("red"):
			if u.id in mortar.crew_ids:mortar.drive(u,.033);u.presentation_tick(.033)
	game.field.covers=[mortar.proxy];game.field.harness_index_covers()
	game.field.cube(game,Vector3(point.x,game.field.height-.015,point.y-.15),Vector3(2.6,.025,2.6),game.field.mat(Color(.65,.56,.39)))
	game.camera.position=Vector3(point.x+1.9,game.field.height+1.6,point.y+1.9)
	game.camera.look_at(Vector3(point.x+.20,game.field.height+.30,point.y-.10));game.camera.size=2.6
	mortar.yaw=0;mortar.desired_yaw=0;mortar.visual.rotation.y=0
	check(mortar.visual_kit.has("gunner_anchor") and mortar.visual_kit.has("guard_anchor"),"mortar exposes separate gunner and guard anchors")
	check(mortar.base_root.find_child("BasePlate",true,false)!=null and mortar.base_root.find_child("BaseRim",true,false)!=null,"mortar has a readable fixed base plate and rim")
	check(mortar.visual.find_child("BipodLeft",true,false)!=null and mortar.visual.find_child("BipodRight",true,false)!=null and mortar.visual.find_child("RearSpade",true,false)!=null,"mortar has a V bipod and rear spade silhouette")
	check(mortar.visual.find_child("TubeAssembly",true,false)!=null and mortar.visual.find_child("MuzzlePoint",true,false)!=null,"mortar has a traversable tube and physical muzzle marker")
	var gunner=game.units.filter(func(u):return u.id==mortar.gunner_id).front()
	var guard=game.units.filter(func(u):return u.id==mortar.guard_id).front()
	check(gunner!=null and guard!=null and gunner.id!=guard.id,"mortar deploys two distinct crew members")
	check(gunner.posture=="crouch" and guard.posture=="stand","gunner crouches to operate while guard stands watch")
	check(not gunner.actor.weapon.visible and guard.actor.weapon.visible,"operator holds the tube while the guard keeps a rifle")
	check(gunner.pos().distance_to(Vector2(mortar.visual_kit.gunner_anchor.global_position.x,mortar.visual_kit.gunner_anchor.global_position.z))<.14 and guard.pos().distance_to(Vector2(mortar.visual_kit.guard_anchor.global_position.x,mortar.visual_kit.guard_anchor.global_position.z))<.14,"crew positions follow the rendered gunner and guard anchors")
	# A focused frame is kept beside the trajectory captures so visual review can
	# inspect the crew-served silhouette without the full battlefield shrinking it.
	game.camera.position=Vector3(point.x+.55,game.field.height+.48,point.y+.62)
	game.camera.look_at(Vector3(point.x,game.field.height+.10,point.y+.02));game.camera.size=1.25
	await capture("mortar-crew")
	game.camera.position=Vector3(point.x+1.9,game.field.height+1.6,point.y+1.9)
	game.camera.look_at(Vector3(point.x+.20,game.field.height+.30,point.y-.10));game.camera.size=2.6
	game.elapsed=5.0;game.human_squads.update_perception();mortar.tick(.0166667)
	check(mortar.shots==1,"enemy mortar fires a real round after observing infantry")
	if game.fx.projectiles.is_empty():quit(1);return
	var round:Dictionary=game.fx.projectiles[0]
	check(round.presentation_kind=="mortar_shell" and round.node.get_child_count()==0,"mortar projectile is a directional shell rather than a hand grenade")
	var tube_axis:Vector3=(mortar.tube.global_basis*Vector3.UP).normalized()
	var launch_tangent:Vector3=round.to-round.from
	launch_tangent.y+=PI*float(round.cfg.get("harness_arc_height",0.0))
	check(tube_axis.dot(launch_tangent.normalized())>.90,"mortar tube and shell share the same initial elevation")
	await capture("mortar-north")
	advance(float(round.duration)*.45)
	check(round.node.position.y>game.field.height+.60,"actual shell visibly rises above the battlefield")
	check(round.trail_segments>=int(round.age/.033)-1,"continuous trail follows every swept physics segment")
	await capture("mortar-arc")
	advance(2.0)
	check(game.fx.hit_log.any(func(row):return row.weapon=="mortar"),"visible mortar arc ends in an authoritative impact")
	place(target,point+Vector2(1.05,0));target.hp=50;target.suppression=0
	game.elapsed+=11.0;game.human_squads.update_perception()
	for i in range(8):
		game.elapsed+=.05;mortar.tick(.05)
	check(absf(mortar.base_root.rotation.y)<.001 and absf(mortar.visual.rotation.y)>.5,"tube traverses while the ground plate stays fixed")
	check(mortar.shots==1 and mortar.phase=="aiming","mortar waits for physical alignment")
	await capture("mortar-turning")
	for i in range(30):game.elapsed+=.05;mortar.tick(.05)
	check(mortar.shots==2 and mortar.muzzle_position(Vector3.ZERO).x>point.x+.02,"eastward round leaves the rotated physical muzzle")
	await capture("mortar-east")
	advance(3.0)
	# Separate the tank check from any damage left by the mortar fixture.
	for u in game.living("red"):
		if not u.tank:u.hp=0
	game.field.covers.clear();game.field.harness_index_covers()
	place(tank,point+Vector2(-.30,0));place(target,tank.pos()+Vector2(.78,-.15));target.hp=50;target.suppression=0
	tank.rotation.y=0;tank.turret.rotation.y=0
	check(not tank.turn_weapon(target,true,.02),"tank cannot align its turret instantly")
	var aligned:bool=false
	for i in range(70):aligned=tank.turn_weapon(target,true,.02)
	var barrel_direction:Vector2=Vector2(tank.muzzle.global_position.x-tank.turret.global_position.x,tank.muzzle.global_position.z-tank.turret.global_position.z).normalized()
	check(aligned and barrel_direction.dot((target.pos()-tank.pos()).normalized())>.98,"tank's real muzzle points in the traversed turret direction")
	tank.fire(target)
	check(not game.fx.projectiles.is_empty(),"aligned tank launches a real cannon round")
	if game.fx.projectiles.is_empty():quit(1);return
	var shell:Dictionary=game.fx.projectiles[-1]
	check(shell.presentation_kind=="tank_shell" and shell.from.distance_to(tank.muzzle.global_position)<.001,"cannon shell starts at the rendered barrel tip")
	advance(float(shell.duration)*.42)
	var expected:Vector3=shell.from.lerp(shell.to,shell.age/shell.duration)
	check(shell.node.position.distance_to(expected)<.001 and shell.trail_segments>0,"tank shell and its continuous trail follow the actual direct-fire path")
	await capture("tank-shell")
	advance(1.0)
	check(game.fx.hit_log.any(func(row):return row.weapon=="cannon") and target.hp<50,"tank round impacts and damages infantry through native collision")
	check(game.fx.peak_visuals<=int(game.fx.budget.visuals),"artillery presentation respects the existing effect budget")
	var passed:bool=checks.all(func(row):return row.passed)
	print("DESKFRONT_ARTILLERY_PRESENTATION "+JSON.stringify({"passed":passed,"checks":checks}))
	game.queue_free();await process_frame;quit(0 if passed else 1)
