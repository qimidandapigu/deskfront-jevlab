extends SceneTree

func _initialize() -> void:
	call_deferred("run")

func run() -> void:
	var library=JSON.parse_string(FileAccess.get_file_as_string("res://data/world-regions.json"))
	var builder=load("res://scripts/world_region_graph.gd")
	var validator=load("res://scripts/world_choke.gd")
	var ops:Array=[]
	for cell in library.cells:
		ops.append({"op":"place_region","cell":cell,"module":"open"})
	for edge in library.edges:
		ops.append({"op":"connect_regions","edge":edge})
	ops.append({"op":"place_prop","cell":"c0r0","asset":"bookstack","x":.16,"z":-.87,"rotation":0})
	ops.append({"op":"place_prop","cell":"c1r0","asset":"mouse","x":.76,"z":-.87,"rotation":90})
	ops.append({"op":"deploy","module":"rear"})
	# Exercise the same JSON decode path used by the live HTTP command.
	ops=JSON.parse_string(JSON.stringify(ops))
	var result=builder.assemble(ops)
	var good:bool=not result.is_empty()
	if good:
		good=validator.validate(result,1.15).ok
		good=good and result.design_card.placed_props==2
		good=good and result.covers.any(func(row):return row[4]=="bookstack" and is_equal_approx(float(row[0]),.16))
		good=good and result.covers.any(func(row):return row[4]=="mouse" and is_equal_approx(float(row[2]),.08))
	var bad=ops.duplicate(true)
	bad[-3]["x"]=.49
	var rejects_outside:bool=builder.assemble(bad).is_empty()
	var unknown=ops.duplicate(true)
	unknown[-3]["asset"]="unknown"
	var rejects_unknown:bool=builder.assemble(unknown).is_empty()
	var passed:bool=good and rejects_outside and rejects_unknown
	print("PROP_PLACEMENT_CONTRACT "+JSON.stringify({"passed":passed,"native_valid":good,
		"rejects_outside":rejects_outside,"rejects_unknown":rejects_unknown}))
	quit(0 if passed else 1)
