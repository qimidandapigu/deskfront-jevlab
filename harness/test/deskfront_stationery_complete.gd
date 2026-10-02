extends SceneTree
func triangles(parent:Node3D)->int:
	var count:int=0
	for child in parent.find_children("*","MeshInstance3D",true,false):
		for surface in range(child.mesh.get_surface_count()):
			var a=child.mesh.surface_get_arrays(surface);var indices=a[Mesh.ARRAY_INDEX]
			count+=(a[Mesh.ARRAY_VERTEX].size() if indices==null or indices.is_empty() else indices.size())/3
	return count
# Real meshes at canonical catalogue dimensions, including transposed footprints.
# Position must not change their shape/scale; geometry must remain static and bounded.
func _initialize():
	var art = load("res://scripts/world_props.gd")
	var shapes:Dictionary = {}
	var data=JSON.parse_string(FileAccess.get_file_as_string("res://stationery-audit.json"))
	for row in data: shapes[JSON.stringify(row)] = [0,0,row[0],row[1],row[2],row[3]]
	var failures:Array = []; var checks:int = 0; var max_meshes:int = 0
	var covered:Dictionary={}
	for kind in shapes:
		var part:Array = shapes[kind]
		var asset:String = part[4]
		covered[asset]=true
		for turn in range(2):
			var w:float = part[2 + turn]; var d:float = part[3 - turn]; var h:float = part[5]
			var first:Array = []
			for position in [Vector2.ZERO, Vector2(1.275, -.475)]:
				var parent = Node3D.new()
				art.build(null, parent, [position.x, position.y, w, d, asset, h])
				var meshes = parent.find_children("*", "MeshInstance3D", true, false)
				max_meshes = maxi(max_meshes, meshes.size())
				if meshes.is_empty() or meshes.size() > 12: failures.append([kind, "mesh_budget", meshes.size()])
				var signature:Array = []
				for child in meshes:
					var t:Transform3D = child.transform; var ancestor = child.get_parent()
					while ancestor != parent: t = ancestor.transform * t; ancestor = ancestor.get_parent()
					var bounds:AABB = t * child.get_aabb()
					signature.append([bounds.position, bounds.size])
					if bounds.position.x < -w/2-.002 or bounds.end.x > w/2+.002 or bounds.position.z < -d/2-.002 or bounds.end.z > d/2+.002 or bounds.position.y < -.002 or bounds.end.y > h+.002:
						failures.append([kind, turn, "out_of_bounds", str(bounds), [w,d,h]])
					if child.is_processing(): failures.append([kind,"not_static"])
				if position == Vector2.ZERO: first = signature
				elif signature != first: failures.append([kind, "position_changes_scale"])
				checks += 1; parent.free()
	var dressing=load("res://scripts/world_scenery.gd").new()
	for kind in dressing.DETAILS:
		var parent=Node3D.new();dressing.draw_detail(parent,kind);art.batch(parent)
		if not parent.find_children("*","CollisionShape3D",true,false).is_empty():failures.append([kind,"decoration_collision"])
		for mesh in parent.find_children("*","MeshInstance3D",true,false):
			if mesh.is_processing():failures.append([kind,"not_static"])
		checks+=1;parent.free()
	dressing.free()
	for key in art.IDENTITIES:
		if not covered.has(key):failures.append([key,"missing_from_full_inventory"])
	# Regression: a non-indexed tube followed by an indexed box of the same
	# material used to retain only some triangles while still passing bounds.
	var combined=Node3D.new()
	art.tube(combined,Vector3.ZERO,.03,.02,.04,"e8bd58")
	art.box(combined,Vector3(.04,0,0),Vector3(.02,.01,.02),"e8bd58","paper")
	var before:int=triangles(combined);art.batch(combined)
	if triangles(combined)!=before:failures.append(["batch_lost_triangles",before,triangles(combined)])
	if combined.get_child_count()!=1:failures.append(["same_material_not_batched"])
	combined.free()
	print("STATIONERY_COMPLETE " + JSON.stringify({"passed":failures.is_empty(), "kinds":shapes.size(), "checks":checks,"max_meshes":max_meshes,"failures":failures}))
	quit(0 if failures.is_empty() else 1)
