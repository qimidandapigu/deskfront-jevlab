extends SceneTree
func _initialize():call_deferred("run")
func run():
	set_meta("infinite_world",true);set_meta("deskfront_map",0)
	var g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
	g.set_physics_process(false);g.paused=false;g.fx.set_muted(true)
	g.set_camera("battle",true)
	for u in g.units:u.actor.global_position=u.global_position
	var cmd={"action":"grow_world","run_id":g.run_id,"growth_revision":0,"operation_id":"visual-sample","option":"gate_north_books_cross_tight","hormones":{"pressure":.5,"recovery":.5,"expansion":.5,"teaching":.5,"novelty":.5}}
	cmd["assembly_kind"]="region_graph_v1"
	cmd["build_operations"]=JSON.parse_string(FileAccess.get_file_as_string("res://data/stationery-scene.json"))
	cmd["enemy_count"]=3;cmd["friendly_count"]=0
	var receipt=g.command(cmd);print(receipt)
	if not receipt.accepted:quit(1);return
	g.growth.tick(.4)
	for i in range(30):await process_frame
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("res://output/world/stationery-assembling.png")
	g.growth.tick(.5)
	for i in range(45):await process_frame
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("res://output/world/stationery-preview.png")
	g.growth.tick(1.6)
	for i in range(30):await process_frame
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("res://output/world/stationery-ready.png")
	FileAccess.open("res://output/world/stationery-ready.json",FileAccess.WRITE).store_string(JSON.stringify(g.snapshot(),"  "))
	# A player-reachable wheel zoom, so desk-level readability can be judged
	# without enlarging the actual props or changing the default battle view.
	var normal_target:Vector3=g.camera_target
	var normal_size:float=g.camera_size
	var built:Dictionary=g.growth.active_regions[0]
	g.camera_target=Vector3((built.left+built.right)*.5,g.field.height,(g.config.bounds[1]+g.config.bounds[3])*.5)
	g.camera_size=2.2
	for i in range(55):await process_frame
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("res://output/world/stationery-desks.png")
	g.camera_target=normal_target;g.camera_size=normal_size
	for i in range(45):await process_frame
	g.set_physics_process(true)
	await create_timer(12).timeout
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("res://output/world/stationery-battle.png")
	FileAccess.open("res://output/world/stationery-battle.json",FileAccess.WRITE).store_string(JSON.stringify(g.snapshot(),"  "))
	g.queue_free();await process_frame;quit()
