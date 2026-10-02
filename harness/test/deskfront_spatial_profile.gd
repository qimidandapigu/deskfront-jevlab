extends SceneTree
func _initialize():call_deferred("run")
func run():
	set_meta("infinite_world",true)
	var g=load("res://scenes/main.tscn").instantiate()
	root.add_child(g)
	g.set_physics_process(false)
	var spatial=load("res://scripts/world_spatial.gd").new()
	var path="res://output/spatial-profile-probe.json"
	DirAccess.make_dir_recursive_absolute("res://output")
	var started=Time.get_ticks_usec()
	spatial.tick(g,path,"topology")
	var cold=Time.get_ticks_usec()-started
	assert(FileAccess.file_exists(path+".topology.json"))
	assert(not FileAccess.file_exists(path))
	var worst=0
	for i in range(1000):
		started=Time.get_ticks_usec()
		spatial.tick(g,path,"topology")
		worst=maxi(worst,Time.get_ticks_usec()-started)
	var previous=spatial.topology_key
	g.field.revision+=1
	spatial.tick(g,path,"topology")
	assert(spatial.topology_key!=previous)
	var report=JSON.parse_string(FileAccess.get_file_as_string(path+".topology.json"))
	assert(int(report.revision)==g.field.revision)
	spatial.tick(g,path+"-other","topology")
	assert(FileAccess.file_exists(path+"-other.topology.json"))
	print("SPATIAL_SHARED_PASS cold_us=",cold," cached_max_us=",worst," cells=",report.cells.size()," edges=",report.edges.size())
	quit()
