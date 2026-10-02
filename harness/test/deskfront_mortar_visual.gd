extends SceneTree
func _initialize()->void:call_deferred("run")
func run()->void:
	set_meta("infinite_world",true)
	OS.set_environment("HARNESS_HUMAN_SQUAD","1")
	var game=load("res://scenes/main.tscn").instantiate();root.add_child(game)
	game.set_process(false);game.set_physics_process(false);game.paused=false
	var soldier=game.living("green")[0]
	var point:Vector2=soldier.pos()+Vector2(.20,0)
	var tank=game.spawn_unit("red-mortar-visual","red",point+Vector2(.52,-.1),true)
	var mortar=load("res://scripts/world_mortar.gd").new();game.add_child(mortar)
	mortar.setup(game,point,tank,"red")
	game.camera.position=mortar.global_position+Vector3(.38,.36,.42)
	game.camera.look_at(mortar.global_position+Vector3(.13,.085,-.04))
	game.camera.size=.67
	for i in range(30):
		game.elapsed+=.033
		for u in game.living():
			if u.id in mortar.crew_ids:mortar.drive(u,.033);u.presentation_tick(.033)
		await process_frame
	await process_frame;await process_frame;await process_frame
	var image:Image=root.get_viewport().get_texture().get_image()
	var result:Error=image.save_png(OS.get_environment("HARNESS_MORTAR_VISUAL_OUTPUT"))
	print("DESKFRONT_MORTAR_VISUAL "+str(result))
	quit(0 if result==OK else 1)
