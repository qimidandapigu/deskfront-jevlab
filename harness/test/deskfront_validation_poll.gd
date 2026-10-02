extends SceneTree
var failures: Array=[]

func _initialize() -> void:call_deferred("run")

func check(value: bool, label: String) -> void:
	if not value:
		failures.append(label)
		push_error(label)

func write_text(path: String, value: String) -> void:
	var file=FileAccess.open(path,FileAccess.WRITE)
	if file:file.store_string(value);file.close()

func run() -> void:
	set_meta("infinite_world",true)
	var g=load("res://scenes/main.tscn").instantiate()
	root.add_child(g)
	g.set_physics_process(false)
	g.paused=true
	var validator=load("res://scripts/world_execution_validation.gd").new()
	var base=ProjectSettings.globalize_path("res://output/validation-poll")
	DirAccess.make_dir_recursive_absolute(base)
	var output=base+"/spatial.json"
	var request=base+"/soldier-candidates-green-request.json"
	var marker=base+"/soldier-candidates-green-request.id"
	var response=base+"/soldier-candidates-green-response.json"
	var unit=g.living("green")[0]
	write_text(request,JSON.stringify({"id":"poll-1","run_id":g.run_id,"unit_id":unit.id,"navigation_revision":g.field.revision,"proposals":[]}))
	write_text(marker,"poll-1")
	validator.tick(g,output)
	check(JSON.parse_string(FileAccess.get_file_as_string(response)).id=="poll-1","first marked candidate request answered")
	write_text(request,JSON.stringify({"id":"poll-2","run_id":g.run_id,"unit_id":unit.id,"navigation_revision":g.field.revision,"proposals":[]}))
	OS.delay_msec(55)
	validator.tick(g,output)
	check(JSON.parse_string(FileAccess.get_file_as_string(response)).id=="poll-1","uncommitted request cannot replace marked request")
	write_text(marker,"poll-2")
	OS.delay_msec(55)
	validator.tick(g,output)
	check(JSON.parse_string(FileAccess.get_file_as_string(response)).id=="poll-2","same-second marked request answered")
	var destination=unit.pos()+Vector2(.075,0)
	var move_id="move-"+g.run_id
	write_text(base+"/move-check-request.json",JSON.stringify({"id":move_id,"run_id":g.run_id,"unit_id":unit.id,"position":[destination.x,destination.y]}))
	write_text(base+"/move-check-request.id",move_id)
	OS.delay_msec(55)
	validator.tick(g,output)
	var move_response=JSON.parse_string(FileAccess.get_file_as_string(base+"/move-check-response.json"))
	check(move_response.id==move_id and move_response.valid,"move admission validates the chosen tactical route")
	var started=Time.get_ticks_usec()
	for i in range(1000):validator.tick(g,output)
	var cached_us=Time.get_ticks_usec()-started
	print("VALIDATION_POLL "+JSON.stringify({"failures":failures,"cached_1000_us":cached_us,"poll_interval_us":validator.next_poll_usec-Time.get_ticks_usec()}))
	g.queue_free()
	await process_frame
	quit(0 if failures.is_empty() else 1)
