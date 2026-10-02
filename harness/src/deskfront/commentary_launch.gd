extends SceneTree
func _initialize():call_deferred("launch")
func launch():
	var arena=load("res://scenes/main.tscn").instantiate()
	root.add_child(arena);current_scene=arena
	root.add_child(load(get_script().resource_path.get_base_dir()+"/commentary_overlay.gd").new())
