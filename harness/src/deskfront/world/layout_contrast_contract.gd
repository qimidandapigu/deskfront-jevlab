extends SceneTree

var checks:Array=[]

func check(ok:bool,label:String):
	checks.append({"passed":ok,"test":label})
	if not ok:push_error(label)

func _initialize():call_deferred("run")

func painted(panel:Node3D,color:Color)->bool:
	for mesh in panel.find_children("*","MeshInstance3D",true,false):
		var material=mesh.material_override
		if material is StandardMaterial3D and material.albedo_color.is_equal_approx(color):return true
	return false

func run():
	set_meta("infinite_world",true)
	var g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
	g.set_physics_process(false);g.paused=false;g.fx.set_muted(true)
	var library=JSON.parse_string(FileAccess.get_file_as_string("res://data/world-regions.json"))
	var closed=["c0r0__c1r0","c0r1__c1r1","c1r0__c2r0","c1r2__c2r2"]
	var ops:Array=[{"op":"set_ports","entry":"c0r0","exit":"c2r2"}]
	for cell in library.cells:
		ops.append({"op":"place_region","cell":cell,"module":"code_laptop_island","rotation":0})
	for edge in library.edges:
		if not edge in closed:ops.append({"op":"connect_regions","edge":edge})
	ops.append({"op":"deploy","module":"rear"})
	var command={"action":"grow_world","run_id":g.run_id,"growth_revision":0,
		"operation_id":"contrast-test","option":"gate_north_books_cross_tight",
		"assembly_kind":"region_graph_v1","visual_pattern":"zigzag",
		"build_operations":ops,"friendly_count":0,"enemy_count":3,
		"hormones":{"pressure":.3,"recovery":.4,"expansion":.6,"teaching":.3,"novelty":.5}}
	var result=g.command(command)
	check(result.accepted,"connected contrasting graph accepted by native engine")
	if result.accepted:
		check(g.growth.pending.spec.design_card.visual_pattern=="zigzag","selected visual identity reaches construction")
		check(g.growth.pending.spec.design_card.connections==8,"selected passages remain physically closed")
		check(g.growth.preview_desks[0].get_meta("wood_color")=="b8aeb4","stage palette changes desktop color")
		check(painted(g.growth.preview_desks[0],Color("e4d7a0")),"colored route stripe exists on the real preview")
		check(g.growth.preview_desks.all(func(panel):return panel.find_children("*","CollisionShape3D",true,false).is_empty()),"paint adds no collision")
		g.growth.tick(1.6)
		check(g.growth.revision==1 and g.growth.desk_panels.size()==9,"painted preview commits as nine desks")
	var passed=checks.all(func(row):return row.passed)
	print("LAYOUT_CONTRAST_CONTRACT "+JSON.stringify({"passed":passed,"checks":checks}))
	quit(0 if passed else 1)
