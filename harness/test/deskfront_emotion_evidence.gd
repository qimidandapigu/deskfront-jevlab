extends SceneTree

func _initialize(): call_deferred("run")

func run():
	set_meta("infinite_world", true)
	OS.set_environment("HARNESS_HUMAN_SQUAD", "1")
	OS.set_environment("HARNESS_GREEN_CONTROL", "lm")
	var game=load("res://scenes/main.tscn").instantiate()
	root.add_child(game)
	game.set_physics_process(false)
	var soldier=game.living("green")[0]
	var before=soldier.snapshot()
	assert(before.last_damage_at < 0)
	soldier.hit(5.0,.25)
	var after=soldier.snapshot()
	assert(after.hp < before.hp)
	assert(after.last_damage_at == game.elapsed)
	assert(after.last_hit_at == before.last_hit_at)
	print("EMOTION_EVIDENCE_PASS damage_received_at=",after.last_damage_at)
	game.queue_free()
	await process_frame
	quit()
