extends RefCounted
## Shared low-poly satchel charge presentation for flight and attachment.
## This is visual-only; damage, collision, fuse and cooldown remain authoritative
## in human_combat_fx.gd and guarded_unit.gd.

static func _part(parent: Node3D, mesh: Mesh, at: Vector3, mat: Material, name: String) -> MeshInstance3D:
	var node:=MeshInstance3D.new()
	node.name=name
	node.mesh=mesh
	node.material_override=mat
	node.position=at
	parent.add_child(node)
	return node

static func _capsule(height: float, radial_segments: int=8) -> CapsuleMesh:
	var mesh:=CapsuleMesh.new()
	mesh.radius=.5
	mesh.height=height
	mesh.radial_segments=radial_segments
	mesh.rings=3
	return mesh

static func _box(size: Vector3) -> BoxMesh:
	var mesh:=BoxMesh.new()
	mesh.size=size
	return mesh

static func _cylinder(radius: float, height: float, segments: int=8) -> CylinderMesh:
	var mesh:=CylinderMesh.new()
	mesh.top_radius=radius
	mesh.bottom_radius=radius
	mesh.height=height
	mesh.radial_segments=segments
	return mesh

static func _sphere(radius: float, segments: int=8) -> SphereMesh:
	var mesh:=SphereMesh.new()
	mesh.radius=radius
	mesh.height=radius*2.0
	mesh.radial_segments=segments
	mesh.rings=3
	return mesh

static func build(parent: MeshInstance3D, fx, _faction_color: Color=Color(.34,.28,.18)) -> void:
	# The same parent is used for the airborne projectile and the attached charge.
	# Clear the old single-mesh grenade shell if this is a pooled node.
	for child in parent.get_children():
		parent.remove_child(child)
		child.queue_free()
	parent.mesh=null
	parent.set_meta("satchel_presentation","satchel_charge")

	var body_mat: Material=fx.material(Color(.30,.24,.15),false)
	var flap_mat: Material=fx.material(Color(.39,.29,.16),false)
	var strap_mat: Material=fx.material(Color(.105,.12,.095),false)
	var metal_mat: Material=fx.material(Color(.55,.48,.30),false)
	var fuse_mat: Material=fx.material(Color(.14,.10,.065),false)
	var light_mat: Material=fx.material(Color(1.0,.18,.045),true)

	# A flattened faceted capsule gives the canvas pack rounded shoulders without
	# leaving the low-poly language used by soldiers, tanks and stationery props.
	var body:=_part(parent,_capsule(2.2),Vector3.ZERO,body_mat,"SatchelBody")
	body.scale=Vector3(.052,.014,.036)

	# Top flap and two raised straps make the object read as a charge pack instead
	# of an unmarked cube at the default battle camera distance.
	var flap:=_part(parent,_capsule(2.0),Vector3(0,.015,.001),flap_mat,"SatchelFlap")
	flap.scale=Vector3(.041,.0024,.029)
	for x in [-.014,.014]:
		var strap:=_part(parent,_box(Vector3(.005,.004,.040)),Vector3(x,.019,0),strap_mat,"SatchelStrap")
		strap.rotation.y=.035 if x<0 else -.035
	var buckle:=_part(parent,_box(Vector3(.009,.004,.006)),Vector3(0,.022,.015),metal_mat,"SatchelBuckle")
	buckle.rotation.x=-.10

	# Short fuse stem and an emissive red indicator provide a readable countdown.
	_part(parent,_cylinder(.0027,.012,6),Vector3(.015,.027,-.008),fuse_mat,"SatchelFuse")
	var indicator:=_part(parent,_sphere(.0034,8),Vector3(.015,.035,-.008),light_mat,"SatchelIndicator")
	parent.set_meta("satchel_indicator",indicator)
	parent.set_meta("satchel_visual_parts",["SatchelBody","SatchelFlap","SatchelStrap","SatchelBuckle","SatchelFuse","SatchelIndicator"])

static func orient(parent: Node3D, direction: Vector3) -> void:
	if direction.length_squared()<.000001:return
	# The pack's local +Y is its face. Build an orthonormal frame explicitly so
	# a top-armour normal parallel to world up never asks look_at for a bad up.
	var normal:=direction.normalized()
	var reference:=Vector3.FORWARD if absf(normal.dot(Vector3.UP))>.97 else Vector3.UP
	var tangent:=reference.cross(normal).normalized()
	var bitangent:=normal.cross(tangent).normalized()
	parent.global_basis=Basis(tangent,normal,bitangent)

static func pulse(parent: Node3D, phase: float) -> void:
	var indicator=parent.get_meta("satchel_indicator",null)
	if not is_instance_valid(indicator):return
	var hot: bool=sin(phase*TAU*4.0)>0.15
	var mat=indicator.material_override
	if mat is StandardMaterial3D:
		mat.albedo_color=Color(1.0,.18,.045) if hot else Color(.22,.045,.018)
	indicator.scale=Vector3.ONE*(1.0 if hot else .72)
