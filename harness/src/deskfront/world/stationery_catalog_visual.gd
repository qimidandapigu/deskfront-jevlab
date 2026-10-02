extends SceneTree

func _initialize():call_deferred("run")

func run():
	var scene=Node3D.new();root.add_child(scene)
	var env=WorldEnvironment.new();scene.add_child(env)
	env.environment=Environment.new();env.environment.background_mode=Environment.BG_COLOR
	env.environment.background_color=Color("d9d8c8")
	env.environment.ambient_light_source=Environment.AMBIENT_SOURCE_COLOR
	env.environment.ambient_light_color=Color("ffffff")
	env.environment.ambient_light_energy=.9
	var sun=DirectionalLight3D.new();scene.add_child(sun)
	sun.rotation_degrees=Vector3(-48,-30,0);sun.light_energy=1.2
	var ground=MeshInstance3D.new();scene.add_child(ground)
	var plane=PlaneMesh.new();plane.size=Vector2(2.5,1.2);ground.mesh=plane
	var wood=StandardMaterial3D.new();wood.albedo_color=Color("c89560");ground.material_override=wood
	var art=preload("res://scripts/world_props.gd")
	var props:Array=[]
	for entry in [["warehouse",-.48,.48,.36,.22],["novel",.28,.25,.18,.09]]:
		var prop=Node3D.new();scene.add_child(prop);prop.position=Vector3(entry[1],.001,0)
		props.append(prop)
		art.build(null,prop,[0,0,entry[2],entry[3],entry[0],entry[4]])
	var camera=Camera3D.new();scene.add_child(camera)
	camera.projection=Camera3D.PROJECTION_ORTHOGONAL;camera.size=1.2
	camera.position=Vector3(1.25,1.05,1.2);camera.look_at(Vector3(-.05,.10,0));camera.current=true
	for i in range(10):await process_frame
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("res://output/world/stationery-closeup.png")
	for prop in props:prop.queue_free()
	await process_frame
	var details:Array=[]
	for entry in [["sandbag",-.60,0,.22,.11,.08],["crate",0,0,.29,.15,.10],["mouse",.60,0,.14,.20,.075],["tissues",-.60,.45,.28,.17,.14],["laptop",0,.45,.28,.20,.16],["tank",.60,.45,.13,.13,.24]]:
		var prop=Node3D.new();scene.add_child(prop);prop.position=Vector3(entry[1],.001,entry[2])
		details.append(prop)
		art.build(null,prop,[0,0,entry[3],entry[4],entry[0],entry[5]])
	camera.size=1.9;camera.position=Vector3(1.5,1.55,1.8);camera.look_at(Vector3(0,.09,.20))
	for i in range(10):await process_frame
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("res://output/world/stationery-details.png")
	for prop in details:prop.queue_free()
	await process_frame
	var controls:Array=[]
	for entry in [["mouse",-.43,.23,.12,.08,.045],["laptop",0,0,.30,.21,.17],["ruler",.43,.05,.28,.04,.012]]:
		var prop=Node3D.new();scene.add_child(prop);prop.position=Vector3(entry[1],.001,entry[2])
		controls.append(prop)
		art.build(null,prop,[0,0,entry[3],entry[4],entry[0],entry[5]])
	camera.size=1.25;camera.position=Vector3(1.2,1.12,1.6);camera.look_at(Vector3(0,.09,.05))
	for i in range(10):await process_frame
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("res://output/world/stationery-controls.png")
	camera.size=.29;camera.position=Vector3(-.25,.32,.72);camera.look_at(Vector3(-.43,.025,.23))
	for i in range(10):await process_frame
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("res://output/world/stationery-mouse.png")
	for prop in controls:prop.queue_free()
	await process_frame
	var roach=Node3D.new();scene.add_child(roach);roach.position=Vector3(0,.001,0)
	var roach_art=preload("res://scripts/world_scenery.gd").new();scene.add_child(roach_art)
	roach_art.draw_detail(roach,"cartoon_roach")
	camera.size=.27;camera.position=Vector3(.28,.26,.32);camera.look_at(Vector3(-.01,.014,0))
	for i in range(10):await process_frame
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("res://output/world/stationery-roach.png")
	roach.queue_free();roach_art.queue_free()
	await process_frame
	for entry in [["book_city",-.43],["novel",0],["book_atlas",.43]]:
		var prop=Node3D.new();scene.add_child(prop);prop.position=Vector3(entry[1],.001,0)
		art.build(null,prop,[0,0,.25,.18,entry[0],.09])
	camera.size=1.15;camera.position=Vector3(1.1,.9,1.5);camera.look_at(Vector3(0,.045,0))
	for i in range(10):await process_frame
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("res://output/world/stationery-books.png")
	quit()
