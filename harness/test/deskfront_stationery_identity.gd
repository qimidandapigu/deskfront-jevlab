extends SceneTree
# Real meshes at canonical catalogue dimensions, including transposed footprints.
# Position must not change their shape/scale; geometry must remain static and bounded.
func _initialize():
	var art = load("res://scripts/world_props.gd")
	var cards = JSON.parse_string(FileAccess.get_file_as_string("res://curated-cards.json"))
	var shapes:Dictionary = {}
	for card in cards:
		for part in card.parts: shapes[str(part[4])] = part
	var failures:Array = []; var checks:int = 0; var max_meshes:int = 0
	for kind in shapes:
		var part:Array = shapes[kind]
		for turn in range(2):
			var w:float = part[2 + turn]; var d:float = part[3 - turn]; var h:float = part[5]
			var first:Array = []
			for position in [Vector2.ZERO, Vector2(1.275, -.475)]:
				var parent = Node3D.new()
				art.build(null, parent, [position.x, position.y, w, d, kind, h])
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
	print("STATIONERY_IDENTITY " + JSON.stringify({"passed":failures.is_empty(), "kinds":shapes.size(), "checks":checks,"max_meshes":max_meshes,"failures":failures}))
	quit(0 if failures.is_empty() else 1)
