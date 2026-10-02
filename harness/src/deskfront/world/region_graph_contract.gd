extends SceneTree
var checks:Array=[]
func _initialize():call_deferred("run")
func check(ok:bool,label:String):
	checks.append({"passed":ok,"test":label})
	if not ok:push_error(label)
func same_covers(actual:Array,expected:Array)->bool:
	if actual.size()!=expected.size():return false
	for i in range(actual.size()):
		if actual[i].size()!=expected[i].size():return false
		for j in range(actual[i].size()):
			var a=actual[i][j];var b=expected[i][j]
			if a is float or a is int:
				if not (b is float or b is int) or abs(float(a)-float(b))>0.000001:return false
			elif a!=b:return false
	return true
func run():
	var builder=load("res://scripts/world_region_graph.gd")
	var validator=load("res://scripts/world_choke.gd")
	var fixtures=JSON.parse_string(FileAccess.get_file_as_string("res://data/graph-test-fixtures.json"))
	for fixture in fixtures:
		var actual=builder.assemble(fixture.operations)
		check(not actual.is_empty(),fixture.name+" assembles")
		if actual.is_empty():continue
		check(actual.floors==fixture.expected.floors,fixture.name+" floor replay matches host")
		check(same_covers(actual.covers,fixture.expected.covers),fixture.name+" cover replay matches host")
		check(actual.defender_slots==fixture.expected.defender_slots,fixture.name+" deployment replay matches host")
		check(actual.flank==fixture.expected.flank,fixture.name+" routes match host")
		var validation=validator.validate(actual,1.15)
		if not validation.ok:print("VALIDATION_FAILURE "+fixture.name+" "+JSON.stringify(validation))
		check(validation.ok,fixture.name+" native navigation")
	var ops=fixtures[4].operations
	var broken=ops.filter(func(op):return op.op!="connect_regions")
	check(builder.assemble(broken).is_empty(),"disconnected graph rejected")
	set_meta("infinite_world",true)
	var g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
	g.set_physics_process(false);g.paused=false;g.fx.set_muted(true)
	var chairs:Array=g.office_root.get_meta("chair_triangle_counts",[])
	check(chairs.size()==2 and chairs[0]>500 and chairs[1]>500,"both imported office chairs are removed without hiding the office")
	var old_surface=g.arena.map_root.find_child("map_surface",true,false)
	check(old_surface!=null and not old_surface.get_child(0).visible,"opening tray surface hidden beneath office desk")
	check(g.growth.desk_panels.is_empty(),"startup has no generated desk leaves")
	check(g.growth.mission.is_empty() and g.living("red").is_empty(),"startup is empty, no authored enemy encounter")
	var command={"action":"grow_world","run_id":g.run_id,"growth_revision":0,"operation_id":"graph-test","option":"court_north_books_cross_tight","assembly_kind":"region_graph_v1","build_operations":ops,"friendly_count":0,"enemy_count":3,"hormones":{"pressure":.3,"recovery":.4,"expansion":.6,"teaching":.3,"novelty":.5}}
	var applied=g.command(command)
	if not applied.accepted:
		print("COMMAND_FAILURE "+JSON.stringify(applied));quit(1);return
	check(applied.accepted,"graph operations accepted by engine")
	var staged_desk:Node3D=g.growth.preview_desks[0]
	var staged_cover:Node3D=g.growth.preview_covers[0]
	check(g.growth.desk_panels.is_empty() and g.living("red").is_empty(),"visible desk preview has no collision or active defenders")
	g.growth.tick(1.6)
	check(g.growth.revision==1 and g.living("red").size()==3,"first generated encounter contains defenders")
	check(g.growth.desk_panels[0]==staged_desk and g.field.covers.any(func(c):return c.id=="growth_0_0" and c.node==staged_cover),"preview art becomes the committed desk and cover without rebuilding")
	var art_inside_cover:bool=true
	for cover in g.field.covers:
		if not str(cover.id).begins_with("growth_"):continue
		for child in cover.node.find_children("*","MeshInstance3D",true,false):
			var transform=child.transform;var ancestor=child.get_parent()
			while ancestor!=cover.node:transform=ancestor.transform*transform;ancestor=ancestor.get_parent()
			var bounds:AABB=transform*child.get_aabb()
			if bounds.position.x< -float(cover.size[0])*.5-.002 or bounds.end.x>float(cover.size[0])*.5+.002 or bounds.position.z< -float(cover.size[1])*.5-.002 or bounds.end.z>float(cover.size[1])*.5+.002 or bounds.end.y>float(cover.height)+.002:
				art_inside_cover=false
	check(art_inside_cover,"desk-specific rotations remain inside tactical cover bounds")
	check(g.growth.desk_panels.size()==9,"one 3x3 region creates nine individual desks")
	var dressing=g.growth.active_regions[0].tiles[-1]
	var details=dressing.get_children().filter(func(child):return child.has_meta("desk_detail"))
	check(details.size()==1,"each region receives one sparse, non-colliding stationery detail")
	var detail_kinds:Dictionary={}
	for detail in details:detail_kinds[detail.get_meta("desk_detail")]=true
	check(detail_kinds.size()==1,"the sparse desk detail has one clear motif")
	check(detail_kinds.has("cartoon_roach"),"first generated region includes one rare decorative roach")
	check(dressing.find_children("*","MeshInstance3D",true,false).size()<=32,"desk details share a bounded draw-call budget")
	check(dressing.find_children("*","CollisionShape3D",true,false).is_empty(),"desk details add no invisible navigation obstacles")
	var desk=g.growth.desk_panels[0]
	var deck=desk.find_children("*","MeshInstance3D",true,false)
	check(deck.size()>0 and desk.name.begins_with("Desk_"),"each desk has its own top, apron and legs")
	var cells:Dictionary={};var woods:Dictionary={};var heights:Dictionary={}
	for panel in g.growth.desk_panels:
		cells[panel.get_meta("cell")]=true;woods[panel.get_meta("wood_color")]=true;heights[panel.get_meta("desk_top")]=true
	check(cells.size()==9 and woods.size()>=5 and heights.size()>=3,"nine positions show distinct wood colors and heights")
	var floor_bodies=g.growth.active_regions[0].tiles.filter(func(tile):return tile is StaticBody3D)
	check(floor_bodies.all(func(tile):return tile.find_children("*","MeshInstance3D",true,false).is_empty()),"region collision floors do not render as separate tables")
	check(g.growth.mission.status=="active","building is not mission completion")
	if g.growth.completed.size():
		check(g.growth.completed[0].design.design_card.alternate_route,"branch and merge retained in native map")
	var solid=g.field.covers.filter(func(c):return c.alive and c.height>.12 and c.id.begins_with("growth_"))
	check(not solid.is_empty(),"tactical sample contains real opaque covers")
	var tall=g.field.covers.filter(func(c):return c.alive and c.height>=.22 and c.id.begins_with("growth_"))
	check(tall.size()>=2,"sample has both real tall desk cover types")
	if not solid.is_empty():
		var c=solid[0];var x:float=c.position[0];var z:float=c.position[1]
		var hit=g.field.trace_cover(Vector3(x-c.size[0]*.5-.02,g.field.height+.068,z),Vector3(x+c.size[0]*.5+.02,g.field.height+.068,z))
		check(not hit.is_empty(),"native projectile trace blocked by generated wall")
	g.elapsed+=3.0
	for u in g.living():u.safety_until=0
	g.growth.plan("green");g.growth.plan("red")
	var flanking:int=0
	for row in g.growth.unit_roles.values():
		if row.get("role","")=="侧翼组":flanking+=1
	check(flanking==2,"local squad allocates two flankers on dual route")
	var passed=checks.all(func(row):return row.passed)
	print("REGION_GRAPH_CONTRACT "+JSON.stringify({"passed":passed,"checks":checks}))
	quit(0 if passed else 1)
