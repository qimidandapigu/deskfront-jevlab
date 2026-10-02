extends SceneTree
func _initialize():call_deferred("run")
func run():
	set_meta("infinite_world",true);set_meta("deskfront_map",0)
	var g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
	g.set_physics_process(false);g.paused=false;g.fx.set_muted(true);g.set_camera("battle",true)
	var command={"action":"grow_world","run_id":g.run_id,"growth_revision":0,"operation_id":"rescue-visual","option":"gate_north_books_cross_tight","mission_kind":"rescue","assembly_kind":"region_graph_v1","build_operations":JSON.parse_string(FileAccess.get_file_as_string("res://data/rescue-scene.json")),"friendly_count":0,"enemy_count":3,"hormones":{"pressure":.5,"recovery":.5,"expansion":.5,"teaching":.5,"novelty":.5}}
	var receipt=g.command(command)
	if not receipt.accepted:push_error(str(receipt));quit(1);return
	g.growth.tick(1.6)
	var built:Dictionary=g.growth.active_regions[0]
	g.camera_target=Vector3((built.left+built.right)*.5,g.field.height,(g.config.bounds[1]+g.config.bounds[3])*.5)
	g.camera_size=2.3
	for i in range(55):await process_frame
	await RenderingServer.frame_post_draw
	DirAccess.make_dir_recursive_absolute("res://output/world")
	get_root().get_texture().get_image().save_png("res://output/world/rescue-before.png")
	for u in g.living("red"):u.hp=0
	g.growth.update_mission()
	for i in range(12):await process_frame
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("res://output/world/rescue-after.png")
	FileAccess.open("res://output/world/rescue-after.json",FileAccess.WRITE).store_string(JSON.stringify(g.snapshot(),"  "))
	print("WORLD_RESCUE_VISUAL ",g.growth.mission.rescue_status)
	g.queue_free();await process_frame;quit()
