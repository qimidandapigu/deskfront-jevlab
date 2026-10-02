extends SceneTree

func _initialize() -> void:
	call_deferred("run")

func capture(name: String) -> bool:
	await process_frame
	await process_frame
	var output: String=OS.get_environment("HARNESS_TANK_VISUAL_OUTPUT")
	if output!="":
		var image: Image=root.get_viewport().get_texture().get_image()
		if image==null:return false
		return image.save_png(output.path_join(name+".png"))==OK
	return true

func run() -> void:
	set_meta("infinite_world",true)
	OS.set_environment("HARNESS_HUMAN_SQUAD","1")
	var game=load("res://scenes/main.tscn").instantiate();root.add_child(game)
	game.set_process(false);game.set_physics_process(false);game.paused=false
	var tank=game.spawn_unit("red-visual-test","red",Vector2(-.2,.1),true)
	game.camera.position=tank.global_position+Vector3(.65,.55,.75)
	game.camera.look_at(tank.global_position+Vector3(0,.07,0))
	game.camera.size=.78
	if not await capture("intact"):quit(1);return
	tank.hit(tank.max_hp*.55,0)
	assert(tank.snapshot().combat.damage_visual.stage=="critical")
	var left_track: MeshInstance3D=tank.model.find_child("TrackMesh_L",true,false)
	var right_track: MeshInstance3D=tank.model.find_child("TrackMesh_R",true,false)
	var turret: MeshInstance3D=tank.model.find_child("Tank_Turret",true,false)
	var body: MeshInstance3D=tank.model.find_child("Tank_body",true,false)
	assert(left_track.material_override is StandardMaterial3D,"one track must retain the original paint")
	assert(right_track.material_override is ShaderMaterial,"damaged track needs a local mark rather than a full-part recolor")
	assert(turret.material_override is ShaderMaterial,"turret needs a local mark rather than a full-part recolor")
	assert(body.material_override.get_shader_parameter("burn_strength")>.5,"body must show a local burn patch")
	assert(right_track.material_override.get_shader_parameter("burn_strength")>.5,"track damage must follow hull damage")
	assert(right_track.position.z<-.1 and right_track.position.y<-.1,"critical track must visibly slip outward and down")
	tank.tick(.6)
	if not await capture("damaged"):quit(1);return
	var start: Vector2=tank.pos()
	var destination: Vector2=start+Vector2(0,-.24)
	tank.target_id="";tank.focus_id="";tank.rotation.y=0
	tank.route=PackedVector2Array([destination]);tank.goal=destination;tank.route_revision=game.field.revision
	tank.set_meta("harness_engine_damaged",false);tank.tick(.3)
	var full_speed_step: float=start.distance_to(tank.pos())
	tank.position=Vector3(start.x,game.field.ground_height(start),start.y)
	tank.rotation.y=0;tank.route=PackedVector2Array([destination]);tank.goal=destination;tank.route_revision=game.field.revision
	tank.set_meta("harness_engine_damaged",true);tank.tick(.3)
	var damaged_step: float=start.distance_to(tank.pos())
	assert(full_speed_step>.01 and damaged_step/full_speed_step<.65,"engine damage must actually reduce tank movement")
	tank.hit(tank.max_hp,0)
	tank.tick(1.5)
	assert(tank.snapshot().combat.damage_visual.stage=="melting")
	if not await capture("melting"):quit(1);return
	tank.tick(1.6)
	assert(tank.snapshot().combat.damage_visual.stage=="wreck")
	assert(tank.model.visible and tank.model.scale.y>.6)
	if not await capture("wreck"):quit(1);return
	var left_tank=game.spawn_unit("blue-left-hit","blue",Vector2(1.0,1.0),true)
	var left_origin: Vector3=left_tank.model.to_global(Vector3(0,0,6))
	left_tank.hit(left_tank.max_hp*.55,0,left_origin)
	assert(left_tank.snapshot().combat.damage_visual.scar_side=="left")
	assert(left_tank.model.find_child("TrackMesh_L",true,false).material_override is ShaderMaterial)
	assert(left_tank.model.find_child("TrackMesh_R",true,false).material_override is StandardMaterial3D)
	game.camera.position=left_tank.global_position+Vector3(-.65,.55,.75)
	game.camera.look_at(left_tank.global_position+Vector3(0,.07,0))
	if not await capture("damaged-left"):quit(1);return
	print("DESKFRONT_TANK_VISUAL_PASS intact damaged melting raised_wreck")
	quit(0)
