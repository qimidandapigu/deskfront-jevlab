extends SceneTree

func _initialize(): call_deferred("run")

func run():
	set_meta("infinite_world", true)
	OS.set_environment("HARNESS_HUMAN_SQUAD", "1")
	OS.set_environment("HARNESS_GREEN_CONTROL", "lm")
	var icons = load("res://scripts/emotion_bubbles.gd").new()
	root.add_child(icons)
	assert(icons.textures.size() == 14)
	for feeling in icons.CODES:
		var texture = icons.textures.get(feeling)
		assert(texture is Texture2D and texture.get_size() == Vector2(72,72))
	assert(icons.CODES.has("dead"))
	var game = load("res://scenes/main.tscn").instantiate()
	root.add_child(game)
	game.set_physics_process(false)
	assert(game.human_squad and game.control.green == "lm")
	icons.game = game
	var soldier = game.living("green")[0]
	var unit_id = soldier.id
	assert(icons._feeling(soldier) == "")
	game.control.green = "game_ai"
	assert(icons._feeling(soldier) == "calm")
	soldier.suppression = .5
	assert(icons._feeling(soldier) == "nervous")
	soldier.suppression = .8
	assert(icons._feeling(soldier) == "afraid")
	soldier.suppression = 0
	soldier.hp = soldier.max_hp * .3
	assert(icons._feeling(soldier) == "hurt")
	soldier.hp = soldier.max_hp
	game.control.green = "lm"
	assert(icons._feeling(soldier) == "")
	for feeling in icons.CODES:
		if feeling == "dead": continue
		var result = game.command({"action":"unit_emotion", "source":"lm", "faction":"green",
			"unit_ids":[unit_id], "emotion":feeling, "run_id":game.run_id,
			"seen_tick":game.tick_id, "control_epoch":game.control_epochs.green})
		assert(result.accepted, "Engine rejected emotion " + feeling)
	soldier.emotion = "happy"
	soldier.emotion_until = game.elapsed + 1
	assert(icons._feeling(soldier) == "happy")
	var renew_result = game.command({"action":"unit_emotion", "source":"lm", "faction":"green",
		"unit_ids":[unit_id], "emotion":"happy", "run_id":game.run_id,
		"seen_tick":game.tick_id, "control_epoch":game.control_epochs.green})
	assert(renew_result.accepted)
	assert(soldier.emotion_until >= game.elapsed + 21.9)
	soldier.emotion_until = game.elapsed
	assert(icons._feeling(soldier) == "")
	soldier.hp = 1
	assert(icons._feeling(soldier) == "")
	soldier.hp = soldier.max_hp
	var dead_result = game.command({"action":"unit_emotion", "source":"lm", "faction":"green",
		"unit_ids":[unit_id], "emotion":"dead", "run_id":game.run_id,
		"seen_tick":game.tick_id, "control_epoch":game.control_epochs.green})
	assert(not dead_result.accepted)
	soldier.hp = 0
	assert(icons._feeling(soldier) == "dead")
	var head_id = soldier.actor.skeleton.find_bone("Head")
	assert(head_id >= 0)
	var head_position: Vector3 = (soldier.actor.skeleton.global_transform * soldier.actor.skeleton.get_bone_global_pose(head_id)).origin
	assert(icons._world_anchor(soldier).distance_to(head_position) < .0001)
	print("TWEMOJI_ASSETS_PASS emotions=", icons.textures.size())
	quit()
