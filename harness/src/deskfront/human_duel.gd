extends SceneTree
# Engine owns behavior. This adapter exports only verified navigation topology.
var arena
var spatial
var opening_run := ""
var opening_released := false
func _initialize():call_deferred("launch")
func launch():
	spatial=load(get_script().resource_path.get_base_dir()+"/spatial_queries.gd").new()
	arena=load("res://scenes/main.tscn").instantiate()
	root.add_child(arena);current_scene=arena
	root.add_child(load(get_script().resource_path.get_base_dir()+"/commentary_overlay.gd").new())
func _process(_delta):
	if not is_instance_valid(current_scene):return false
	arena=current_scene
	var output=OS.get_environment("HARNESS_SPATIAL_OUTPUT")
	if output!="" and arena.demo!=null and arena.demo.phase=="battle":
		var gate=OS.get_environment("HARNESS_OPENING_GATE")
		if opening_run!=arena.run_id:
			opening_run=arena.run_id;opening_released=false
			arena.config.weapons.rifle.range=1.15
			arena.config.weapons.smg.range=.90
			arena.config.weapons.rocket.range=1.35
			arena.config["human_vision_range"]=1.60

		if gate!="" and not opening_released:
			arena.paused=true
			if FileAccess.file_exists(gate):
				var permission=JSON.parse_string(FileAccess.get_file_as_string(gate))
				if permission is Dictionary and permission.get("run_id")==arena.run_id:
					opening_released=true;arena.paused=false
		spatial.export_topology(arena,output+".topology.json")
	return false
