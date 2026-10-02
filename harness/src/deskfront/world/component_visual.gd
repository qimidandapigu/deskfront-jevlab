extends SceneTree
func _initialize():call_deferred("run")
func run():
	set_meta("infinite_world",true)
	for key in ["gate_north_books_cross_tight","stagger_south_crates_depth_tight","court_north_books_depth_tight"]:
		var g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
		g.set_physics_process(false);g.paused=false;g.fx.set_muted(true)
		for u in g.units:u.actor.global_position=u.global_position
		var ack=g.command({"action":"grow_world","run_id":g.run_id,"growth_revision":0,"operation_id":key,"option":key,"hormones":{"pressure":.5,"recovery":.5,"expansion":.5,"teaching":.5,"novelty":.5}})
		if not ack.accepted:push_error(str(ack));quit(1);return
		g.growth.tick(3.1)
		for i in range(50):await process_frame
		await RenderingServer.frame_post_draw
		get_root().get_texture().get_image().save_png("res://output/world/"+key+".png")
		g.queue_free();await process_frame
	quit()
