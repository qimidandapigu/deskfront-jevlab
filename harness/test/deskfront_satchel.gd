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
	for i in range(1,friends.size()):
		friends[i].position=Vector3(.9,game.field.height,2.75+i*.15)
	var tank=game.spawn_unit("red-satchel-test","red",soldier.pos()+Vector2(0,-.56),true)
	tank.hp=240;tank.max_hp=240
	check(soldier.can_satchel(tank),"tank at its preferred standoff distance is a legal satchel target")
	var grenades_before: int=soldier.grenade_count
	game.set_control_mode("green","lm")
	game.human_squads.squads["satchel-squad"]={"squad_id":"satchel-squad","faction":"green","order_id":"satchel-order","unit_ids":[soldier.id],"intent":"advance","phase":"advancing","goal":soldier.pos(),"radius":.1,"destinations":{},"rally_destinations":{},"assignments":{soldier.id:{"region_path":["antiarmor-test"]}},"personal":{}}
	var approach: Vector2=soldier.pos()
	for offset in [Vector2(.075,0),Vector2(-.075,0),Vector2(0,.075),Vector2(0,-.075)]:
		var candidate: Vector2=soldier.pos()+offset
		if game.field.walkable(candidate) and not soldier.navigation_path(candidate).is_empty() and candidate.distance_to(tank.pos())<=soldier.snapshot().satchel_range:
			approach=candidate;break
	check(approach.distance_to(soldier.pos())>.02,"short native anti-armor approach exists")
	var query_dir: String=ProjectSettings.globalize_path("res://output/world")
	DirAccess.make_dir_recursive_absolute(query_dir)
	var file=FileAccess.open(query_dir+"/soldier-candidates-green-request.json",FileAccess.WRITE)
	file.store_string(JSON.stringify({"id":"satchel-approach","run_id":game.run_id,"unit_id":soldier.id,"navigation_revision":game.field.revision,"proposals":[{"id":"C1","region_id":"antiarmor-test","position":[approach.x,approach.y],"kind":"anti_armor_approach","target_id":tank.id,"target_distance":approach.distance_to(tank.pos())}]}));file.close()
	file=FileAccess.open(query_dir+"/soldier-candidates-green-request.id",FileAccess.WRITE)
	file.store_string("satchel-approach");file.close()
	game.growth.execution_validator.candidate_tick(game,query_dir,"green")
	var rush: Dictionary={"action":"soldier_order","source":"lm","faction":"green","unit_ids":[soldier.id],"squad_id":"satchel-squad","order_id":"satchel-order","intent":"rush_to_site","site_id":"C1","candidate_query_id":"satchel-approach","run_id":game.run_id,"seen_tick":game.tick_id,"control_epoch":game.control_epochs.green}
	var rush_receipt: Dictionary=game.command(rush)
	check(rush_receipt.accepted and is_equal_approx(soldier.formation_speed,1.4) and soldier.posture_order=="stand","native fast approach uses real increased movement speed")
	check(soldier.harness_antiarmor_commit_active() and soldier.snapshot().antiarmor_charge_remaining>0,"validated tank rush starts a bounded charge")
	if not rush_receipt.accepted:
		print("DESKFRONT_SATCHEL_RUSH_FAILED "+JSON.stringify(rush_receipt))
		game.queue_free();await process_frame;quit(1);return
	soldier.reaction_at=0
	soldier.survival_tick()
	check(soldier.safety_reason!="armor_outmatched" and soldier.order_mode=="soldier_rush_to_site","tank proximity does not turn a committed charge into retreat")
	soldier.hit(2.0,.32,tank.global_position)
	soldier.reaction_at=0
	soldier.survival_tick()
	soldier.update_posture(true)
	check(soldier.safety_until<=game.elapsed and soldier.posture=="stand" and soldier.order_mode=="soldier_rush_to_site","ordinary hit and pressure do not force a committed rush to crawl")
	soldier.explosive_until=game.elapsed+1.0
	check(not soldier.harness_antiarmor_commit_active(),"imminent explosive suspends the charge exception")
	soldier.explosive_until=0.0
	var charge_time: float=game.elapsed
	game.elapsed=charge_time+4.6
	check(not soldier.harness_antiarmor_commit_active(),"charge commitment expires without repeated orders")
	game.elapsed=charge_time
	soldier.reload_timer=.8
	check(soldier.can_satchel(tank),"satchel throw may interrupt an ordinary weapon reload")
	var middle: Vector2=soldier.pos().lerp(tank.pos(),.22)
	var arc_cover: Dictionary={"id":"satchel-arc-check","position":[middle.x,middle.y],"size":[.055,.055],"normal":[0,1],"height":.11,"bottom":game.field.height,"yaw":0.0,"hp":100.0,"alive":true}
	game.field.covers.append(arc_cover)
	game.field.harness_index_covers()
	var spotter_position: Vector3=friends[1].position
	friends[1].position=tank.position+Vector3(.3,0,.3)
	var target_point: Vector3=tank.aim_point()
	var straight_hit: Dictionary=game.fx.trace(soldier.muzzle_position(target_point),target_point,soldier.id)
	check(straight_hit.get("kind","")=="cover" and soldier.can_satchel(tank),"low cover blocks a straight ray but the real throwing arc remains legal")
	var command: Dictionary={"action":"soldier_order","source":"lm","faction":"green","unit_ids":[soldier.id],"squad_id":"satchel-squad","order_id":"satchel-order","intent":"satchel","target_id":tank.id,"run_id":game.run_id,"seen_tick":game.tick_id,"control_epoch":game.control_epochs.green}
	var receipt: Dictionary=game.command(command)
	if not receipt.accepted:print("DESKFRONT_ARC_RECEIPT "+JSON.stringify(receipt))
	check(receipt.accepted and soldier.grenade_time>=0,"AI soldier order starts the real throw animation")
	check(game.human_squads.squads["satchel-squad"].personal[soldier.id].status=="completed" and is_equal_approx(soldier.formation_speed,1.0),"throw takes over an active fast approach")
	check(not soldier.harness_antiarmor_commit_active(),"charge commitment ends when the pack is thrown")
	check(not soldier.can_satchel(tank) and not game.command(command).accepted,"repeat throw is blocked during windup")
	# Pin this visual/impact fixture to a direct hit. The real combat path still
	# uses angular dispersion; the separate miss fixture below verifies that a
	# scattered landing does not get magnetically attached to the tank.
	game.fx.dispersion_rng.seed=1
	soldier.tick(.65)
	check(soldier.get_meta("harness_satchel_result",{}).get("status")=="launched","satchel projectile is launched by the native release frame")
	var satchel_projectile=game.fx.projectiles[0].node if game.fx.projectiles.size()==1 else null
	check(satchel_projectile!=null and satchel_projectile.get_meta("satchel_presentation","")=="satchel_charge" and satchel_projectile.get_child_count()>=6 and is_instance_valid(satchel_projectile.get_meta("satchel_indicator",null)),"projectile has a readable satchel pack, straps and fuse light")
	for i in range(30):
		game.fx.physics_tick(.1)
		if not game.fx.pending_satchels.is_empty():break
	check(tank.hp==240 and game.fx.pending_satchels.size()==1,"satchel attaches before its timed explosion")
	if game.fx.pending_satchels.is_empty():game.queue_free();await process_frame;quit(1);return
	game.field.covers.erase(arc_cover)
	game.field.harness_index_covers()
	friends[1].position=spotter_position
	var charge: Dictionary=game.fx.pending_satchels[0]
	check(charge.pack.get_meta("satchel_presentation","")=="satchel_charge" and charge.pack.get_child_count()>=6,"attached charge keeps the same layered presentation")
	check(is_instance_valid(charge.target) and charge.target==tank and charge.payload.get("collision",{}).get("kind","")=="unit","direct projectile hit is the only path that attaches a charge")
	var impact_normal:Vector3=charge.payload.get("collision",{}).get("normal",Vector3.UP)
	check(charge.pack.global_basis.y.normalized().dot(impact_normal.normalized())>.95,"attached pack local up follows the struck armour normal")
	var planted_at: Vector3=charge.pack.global_position
	var local_anchor: Vector3=charge.local_anchor
	tank.position+=Vector3(.07,0,0)
	tank.rotation.y+=.35
	game.fx.physics_tick(.2)
	check(charge.pack.global_position.distance_to(tank.to_global(local_anchor))<.001 and planted_at.distance_to(charge.pack.global_position)>.01,"attached charge stays on the struck armor while tank moves and turns")
	game.fx.physics_tick(1.4)
	var tank_damage: float=240.0-tank.hp
	check(tank.hp<170 and tank.hp>0,"native explosion deals substantial but non-instant tank damage")
	check(soldier.get_meta("harness_satchel_result",{}).get("status")=="detonated","authoritative receipt distinguishes launch from detonation")
	check(game.fx.pending_satchels.is_empty() and planted_at.distance_to(tank.global_position)>0,"attached charge detonates after the fuse")
	check(tank.harness_engine_damaged and tank.snapshot().combat.engine_damaged,"below-half-health satchel hit damages the engine")
	check(tank.snapshot().combat.damage_visual.stage=="critical","tank shows visible critical damage")
	var struck_side: String="left" if tank.model.to_local(tank.to_global(local_anchor)).z>0.0 else "right"
	check(tank.snapshot().combat.damage_visual.scar_side==struck_side,"burn and slipped track stay on the charge's impact side")
	check(soldier.grenade_count==grenades_before,"satchel cooldown does not consume ordinary grenades")
	soldier.reload_timer=0.0
	soldier.tick(.7)
	check(soldier.snapshot().satchel_ready_in>0,"cooldown is visible in the authoritative snapshot")
	game.elapsed+=14.1
	check(soldier.can_satchel(tank),"satchel becomes available after cooldown")
	var miss_tank=game.spawn_unit("red-satchel-near-miss","red",soldier.pos()+Vector2(0,-.56),true)
	miss_tank.hp=240;miss_tank.max_hp=240
	game.fx.dispersion_rng.seed=1
	check(game.fx.launch(soldier,miss_tank,"grenade",true,soldier.harness_satchel_config()),"near-miss fixture launches a satchel projectile")
	var miss_projectile=game.fx.projectiles[-1] if not game.fx.projectiles.is_empty() else null
	if miss_projectile!=null:
		# Deliberately place the scattered landing above the hit box; this models
		# a real miss without changing native collision or damage rules.
		miss_projectile.to=miss_tank.global_position+Vector3(0,.42,0)
		miss_projectile.duration=.01
		game.fx.physics_tick(.05)
	var miss_charge=game.fx.pending_satchels[-1] if not game.fx.pending_satchels.is_empty() else {}
	check(not miss_charge.is_empty() and not is_instance_valid(miss_charge.target) and miss_charge.payload.get("collision",{}).get("kind","")!="unit","scattered landing remains a ground charge and never magnetically attaches")
	if not miss_charge.is_empty():
		miss_charge.pack.queue_free();game.fx.pending_satchels.erase(miss_charge)
	miss_tank.hp=0;miss_tank.queue_free()
	friends[1].position=Vector3(tank.pos().x,game.field.height,tank.pos().y+.04)
	check(not soldier.can_satchel(tank),"friendly near blast blocks the throw")
	friends[1].position=Vector3(.9,game.field.height,2.9)
	var prone_soldier=friends[1]
	var crawl_to: Vector2=prone_soldier.pos()
	for offset in [Vector2(.075,0),Vector2(-.075,0),Vector2(0,.075),Vector2(0,-.075)]:
		var candidate: Vector2=prone_soldier.pos()+offset
		if game.field.walkable(candidate) and not prone_soldier.navigation_path(candidate).is_empty():
			crawl_to=candidate;break
	check(crawl_to.distance_to(prone_soldier.pos())>.02,"short native prone approach exists")
	game.human_squads.squads["prone-squad"]={"squad_id":"prone-squad","faction":"green","order_id":"prone-order","unit_ids":[prone_soldier.id],"intent":"advance","phase":"advancing","goal":prone_soldier.pos(),"radius":.1,"destinations":{},"rally_destinations":{},"assignments":{prone_soldier.id:{"region_path":["antiarmor-prone-test"]}},"personal":{}}
	file=FileAccess.open(query_dir+"/soldier-candidates-green-request.json",FileAccess.WRITE)
	file.store_string(JSON.stringify({"id":"satchel-prone","run_id":game.run_id,"unit_id":prone_soldier.id,"navigation_revision":game.field.revision,"proposals":[{"id":"C1","region_id":"antiarmor-prone-test","position":[crawl_to.x,crawl_to.y]}]}));file.close()
	file=FileAccess.open(query_dir+"/soldier-candidates-green-request.id",FileAccess.WRITE)
	file.store_string("satchel-prone");file.close()
	game.growth.execution_validator.candidate_tick(game,query_dir,"green")
	var prone_command: Dictionary={"action":"soldier_order","source":"lm","faction":"green","unit_ids":[prone_soldier.id],"squad_id":"prone-squad","order_id":"prone-order","intent":"prone_approach","site_id":"C1","candidate_query_id":"satchel-prone","run_id":game.run_id,"seen_tick":game.tick_id,"control_epoch":game.control_epochs.green}
	var prone_receipt: Dictionary=game.command(prone_command)
	check(prone_receipt.accepted and prone_soldier.posture_order=="prone" and prone_soldier.order_mode=="soldier_prone_approach","native low approach explicitly selects prone movement")
	check(soldier.request_grenade(tank),"ordinary grenades remain usable")
	soldier.tick(.65)
	check(game.fx.projectiles.size()==1 and not game.fx.projectiles[0].cfg.get("harness_satchel",false) and soldier.grenade_count==grenades_before-1,"ordinary grenade keeps its original payload and inventory")
	game.fx.physics_tick(1.0)
	soldier.tick(.7)
	tank.position=Vector3(soldier.pos().x,game.field.height,soldier.pos().y-1.0)
	check(not soldier.can_satchel(tank),"distant tank cannot be targeted")
	tank.hit(1000,0)
	check(tank.hp==0 and tank.snapshot().combat.damage_visual.stage=="melting","destroyed tank starts its melt animation")
	tank.tick(1.5)
	check(tank.model.visible and tank.model.scale.y<1.0,"destroyed model visibly sinks and collapses")
	game.winner="green"
	tank.harness_tank_damage_visual._process(1.6)
	check(tank.model.visible and tank.model.scale.y>.6 and tank.snapshot().combat.damage_visual.stage=="wreck","death leaves a raised wreck even after the match ends")
	var passed: bool=checks.all(func(row):return row.passed)
	print("DESKFRONT_SATCHEL "+JSON.stringify({"passed":passed,"tank_damage":tank_damage,"checks":checks}))
	game.queue_free();await process_frame;quit(0 if passed else 1)
