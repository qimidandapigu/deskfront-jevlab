extends RefCounted

## The source office GLB joins each material into one mesh. Its two wheeled
## chairs therefore cannot be hidden as nodes without also hiding desk parts.
## Remove only chair triangles in the two known chair footprints.
const CHAIR_A=Rect2(-1.42,.25,.76,.78)
const CHAIR_B=Rect2(1.64,2.48,.75,.76)

static func is_chair(point:Vector3)->bool:
	if point.y<-.01 or point.y>.98:return false
	return CHAIR_A.has_point(Vector2(point.x,point.z)) or CHAIR_B.has_point(Vector2(point.x,point.z))

static func strip_chairs(office:Node3D)->int:
	var removed:int=0
	var first:int=0
	var second:int=0
	for node in office.find_children("*","MeshInstance3D",true,false):
		if node.name not in ["charcoal","sage painted steel"]:continue
		var source:Mesh=node.mesh
		var filtered=ArrayMesh.new()
		for surface in range(source.get_surface_count()):
			var arrays:Array=source.surface_get_arrays(surface)
			var vertices:PackedVector3Array=arrays[Mesh.ARRAY_VERTEX]
			var original:PackedInt32Array=arrays[Mesh.ARRAY_INDEX]
			var indices=PackedInt32Array()
			if original.is_empty():
				for i in range(vertices.size()):indices.append(i)
			else:indices=original
			var retained=PackedInt32Array()
			for i in range(0,indices.size(),3):
				var center:Vector3=(vertices[indices[i]]+vertices[indices[i+1]]+vertices[indices[i+2]])/3.0
				var point:Vector3=office.to_local(node.to_global(center))
				if is_chair(point):
					removed+=1
					if CHAIR_A.has_point(Vector2(point.x,point.z)):first+=1
					else:second+=1
				else:
					retained.append(indices[i]);retained.append(indices[i+1]);retained.append(indices[i+2])
			arrays[Mesh.ARRAY_INDEX]=retained
			filtered.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES,arrays)
			filtered.surface_set_material(surface,source.surface_get_material(surface))
		node.mesh=filtered
	office.set_meta("chairs_removed_triangles",removed)
	office.set_meta("chair_triangle_counts",[first,second])
	return removed
