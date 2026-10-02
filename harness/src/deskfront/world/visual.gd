extends SceneTree
func _initialize():call_deferred("run")
func run():
	set_meta("infinite_world",true);set_meta("deskfront_map",0)
	var g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
	g.set_physics_process(false);g.paused=false;g.fx.set_muted(true)
	g.set_camera("battle",true)
	for u in g.units:u.actor.global_position=u.global_position
	var cmd={"action":"grow_world","run_id":g.run_id,"growth_revision":0,"operation_id":"visual-sample","option":"gate_north_books_cross_tight","hormones":{"pressure":.5,"recovery":.5,"expansion":.5,"teaching":.5,"novelty":.5}}
	print(g.command(cmd))
	g.growth.tick(2.3)
	for i in range(45):await process_frame
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("res://output/world/choke-preview.png")
	g.growth.tick(.8)
	for i in range(30):await process_frame
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("res://output/world/choke-ready.png")
	FileAccess.open("res://output/world/choke-ready.json",FileAccess.WRITE).store_string(JSON.stringify(g.snapshot(),"  "))
	g.set_physics_process(true)
	await create_timer(12).timeout
	await RenderingServer.frame_post_draw
	get_root().get_texture().get_image().save_png("res://output/world/choke-battle.png")
	FileAccess.open("res://output/world/choke-battle.json",FileAccess.WRITE).store_string(JSON.stringify(g.snapshot(),"  "))
	g.queue_free();await process_frame;quit()
