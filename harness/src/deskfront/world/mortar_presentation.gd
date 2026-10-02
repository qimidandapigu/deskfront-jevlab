extends RefCounted
class_name MortarPresentation

## Presentation-only kit for the light mortar.
##
## The game owns the fixed base and the TubeTraverse yaw.  This module owns
## only meshes, attachment points, and the small arm IK pose used after a
## unit's normal idle tick.  It deliberately does not decide targets, fire,
## capture, or crew ownership.

## The tube's local +Y axis is the bore direction.  A -0.68 rad rotation puts
## it at roughly 52 degrees above the tabletop from the isometric camera.
const BARREL_TILT: float = -0.68
## Tip of the .150m tube after BARREL_TILT. The marker, bore and muzzle ring
## all use this point so the rendered muzzle and shell origin stay aligned.
const MUZZLE_LOCAL: Vector3 = Vector3(0.0, 0.151, -0.071)
const GUNNER_HAND_LEFT: Vector3 = Vector3(-0.033, 0.094, -0.005)
const GUNNER_HAND_RIGHT: Vector3 = Vector3(0.033, 0.094, -0.005)

static func _mesh(parent: Node3D, mesh: Mesh, at: Vector3, material: Material,
		rot: Vector3 = Vector3.ZERO, name: String = "") -> MeshInstance3D:
	var item := MeshInstance3D.new()
	item.mesh = mesh
	item.material_override = material
	item.position = at
	item.rotation = rot
	if not name.is_empty():
		item.name = name
	parent.add_child(item)
	return item

static func _beam(parent: Node3D, from: Vector3, to: Vector3, width: float,
		material: Material, name: String = "") -> MeshInstance3D:
	# BoxMesh is vertical in local space. Align its long Y axis with the
	# measured support vector so the two legs form a real V in plan view.
	var beam := BoxMesh.new()
	beam.size = Vector3(width, from.distance_to(to), width)
	var item := MeshInstance3D.new()
	item.mesh = beam
	item.material_override = material
	item.position = (from + to) * 0.5
	var direction := to - from
	if direction.length_squared() > 0.000001:
		item.basis = Basis(Quaternion(Vector3.UP, direction.normalized()))
	if not name.is_empty():
		item.name = name
	parent.add_child(item)
	return item

static func _marker(parent: Node3D, at: Vector3, name: String) -> Node3D:
	var marker := Node3D.new()
	marker.name = name
	marker.position = at
	parent.add_child(marker)
	return marker

static func build(game, faction: String, base_root: Node3D) -> Dictionary:
	"""Build a small low-poly mortar beneath an existing scaled base root.

	`base_root` is the fixed ground plate.  The returned `traverse` is the only
	part that should receive the mortar yaw.  `tube_assembly` can receive recoil;
	`muzzle`, `gunner_anchor`, and `guard_anchor` are stable local attachment
	points for the authoritative projectile and crew presentation.
	"""
	var green: Material = game.field.mat(game.colors.get(faction, Color(.43, .45, .40)), .32)
	var dark: Material = game.field.mat(Color(.12, .16, .15), .38)
	var edge: Material = game.field.mat(Color(.67, .63, .47), .32)

	# Fixed circular ground plate and a darker inset.  Their low profile reads
	# as equipment on the tabletop instead of a second vehicle body.
	var plate := CylinderMesh.new()
	plate.top_radius = .108
	plate.bottom_radius = .132
	plate.height = .022
	plate.radial_segments = 10
	_mesh(base_root, plate, Vector3(0, .011, 0), green, Vector3.ZERO, "BasePlate")
	var inset := CylinderMesh.new()
	inset.top_radius = .086
	inset.bottom_radius = .099
	inset.height = .010
	inset.radial_segments = 8
	_mesh(base_root, inset, Vector3(0, .027, 0), dark, Vector3.ZERO, "BaseInset")
	# A thin rim separates the plate from the tabletop at the isometric camera
	# distance.  It also makes the fixed ground contact obvious when the tube
	# traverses, instead of reading as a floating red cylinder.
	var rim := TorusMesh.new()
	rim.inner_radius = .105
	rim.outer_radius = .118
	rim.rings = 8
	rim.ring_segments = 8
	_mesh(base_root, rim, Vector3(0, .030, 0), edge, Vector3.ZERO, "BaseRim")

	var traverse := Node3D.new()
	traverse.name = "TubeTraverse"
	base_root.add_child(traverse)

	# A pivot, crossbar, and angled V legs give the silhouette of a light
	# infantry mortar.  The feet are offset in both X and Z, so they are not two
	# parallel skis when viewed from the isometric camera.
	var pivot := CylinderMesh.new()
	pivot.top_radius = .035
	pivot.bottom_radius = .040
	pivot.height = .018
	pivot.radial_segments = 8
	_mesh(traverse, pivot, Vector3(0, .041, .012), dark, Vector3.ZERO, "TraversePivot")
	var crossbar := BoxMesh.new()
	crossbar.size = Vector3(.125, .018, .030)
	_mesh(traverse, crossbar, Vector3(0, .061, .015), dark, Vector3.ZERO, "BipodCrossbar")
	_beam(traverse, Vector3(-.043, .061, .011), Vector3(-.090, .021, .077), .018, green, "BipodLeft")
	_beam(traverse, Vector3(.043, .061, .011), Vector3(.090, .021, .077), .018, green, "BipodRight")
	# A short rear spade stabilises the toy silhouette without turning it into a
	# three-legged chair; it also gives the barrel a visible ground contact.
	_beam(traverse, Vector3(0, .052, .030), Vector3(0, .020, .102), .016, dark, "RearSpade")
	for side in [-1.0, 1.0]:
		var foot := BoxMesh.new()
		foot.size = Vector3(.040, .010, .026)
		_mesh(traverse, foot, Vector3(side * .090, .010, .077), dark, Vector3.ZERO,
				"Foot" + str(side))

	# The tube is intentionally a light-mortar length: after the caller's .68
	# root scale, its muzzle is about .10 above the tabletop, around a standing
	# toy soldier's chest rather than above its head.
	var tube_assembly := Node3D.new()
	tube_assembly.name = "TubeAssembly"
	tube_assembly.position = Vector3.ZERO
	traverse.add_child(tube_assembly)
	var tube := CylinderMesh.new()
	tube.top_radius = .021
	tube.bottom_radius = .025
	tube.height = .150
	tube.radial_segments = 10
	_mesh(tube_assembly, tube, Vector3(0, .093, -.024), green,
			Vector3(BARREL_TILT, 0, 0), "Tube")
	var collar := CylinderMesh.new()
	collar.top_radius = .030
	collar.bottom_radius = .032
	collar.height = .015
	collar.radial_segments = 10
	_mesh(tube_assembly, collar, Vector3(0, .041, -.006), dark, Vector3.ZERO, "TubeCollar")
	var collar_band := TorusMesh.new()
	collar_band.inner_radius = .024
	collar_band.outer_radius = .030
	collar_band.rings = 8
	collar_band.ring_segments = 6
	_mesh(tube_assembly, collar_band, Vector3(0, .041, -.006), edge,
			Vector3(BARREL_TILT, 0, 0), "TubeCollarBand")
	var bore := CylinderMesh.new()
	bore.top_radius = .014
	bore.bottom_radius = .014
	bore.height = .005
	bore.radial_segments = 10
	_mesh(tube_assembly, bore, MUZZLE_LOCAL, dark, Vector3(BARREL_TILT, 0, 0), "MuzzleBore")
	var muzzle_ring := TorusMesh.new()
	muzzle_ring.inner_radius = .020
	muzzle_ring.outer_radius = .026
	muzzle_ring.rings = 8
	muzzle_ring.ring_segments = 6
	_mesh(tube_assembly, muzzle_ring, MUZZLE_LOCAL, edge,
			Vector3(BARREL_TILT, 0, 0), "MuzzleRing")
	var sight := BoxMesh.new()
	sight.size = Vector3(.012, .014, .100)
	_mesh(tube_assembly, sight, Vector3(.038, .060, -.020), green,
			Vector3(BARREL_TILT, 0, 0), "TubeSight")

	# A small hand wheel makes the traverse readable when the tube turns.
	var wheel := TorusMesh.new()
	wheel.inner_radius = .019
	wheel.outer_radius = .026
	wheel.rings = 8
	wheel.ring_segments = 6
	_mesh(traverse, wheel, Vector3(.067, .073, .020), dark,
			Vector3(PI / 2.0, 0, 0), "TraverseHandwheel")
	var hub := CylinderMesh.new()
	hub.top_radius = .009
	hub.bottom_radius = .009
	hub.height = .012
	hub.radial_segments = 8
	_mesh(traverse, hub, Vector3(.067, .073, .020), edge,
			Vector3(0, 0, PI / 2.0), "TraverseHub")
	# A compact ammunition case sits by the guard.  It is intentionally flat and
	# separate from the bipod so the weapon reads as a crew-served emplacement,
	# not a single oversized prop.
	var ammo_case := BoxMesh.new()
	ammo_case.size = Vector3(.070, .030, .050)
	_mesh(base_root, ammo_case, Vector3(.145, .020, .065), dark, Vector3.ZERO, "AmmoCase")
	var ammo_lid := BoxMesh.new()
	ammo_lid.size = Vector3(.076, .006, .054)
	_mesh(base_root, ammo_lid, Vector3(.145, .038, .065), edge, Vector3.ZERO, "AmmoCaseLid")

	return {
		"root": base_root,
		"traverse": traverse,
		"tube_assembly": tube_assembly,
		"tube": tube_assembly.get_node("Tube"),
		"tube_rest": tube_assembly.position,
		"muzzle": _marker(tube_assembly, MUZZLE_LOCAL, "MuzzlePoint"),
		"gunner_anchor": _marker(traverse, Vector3(-.090, .040, .096), "GunnerAnchor"),
		"guard_anchor": _marker(traverse, Vector3(.125, .030, .070), "GuardAnchor")
	}

static func pose_gunner(u, mortar, kit: Dictionary) -> void:
	if u == null or not is_instance_valid(u) or u.actor == null:
		return
	u.actor.weapon.hide()
	u.posture = "crouch"
	u.locomotion = "idle"
	# The gunner is a crew member now, so resolve the body facing from the
	# mortar pivot every presentation tick.  This keeps the torso and hands
	# aligned with the traversing tube instead of leaving a rifleman facing
	# away while the barrel turns.
	var pivot: Vector3 = mortar.to_global(Vector3(0.0, .07, 0.0))
	var direction: Vector2 = Vector2(pivot.x-u.global_position.x, pivot.z-u.global_position.z)
	if direction.length_squared() > .000001:
		u.rotation.y = atan2(-direction.x, -direction.y)
		u.actor.rotation.y = u.rotation.y + PI
	# cover_idle supplies the crouched legs; the hand targets make this an
	# operator gripping the tube instead of a rifleman idling with a hidden gun.
	u.actor.play("cover_idle")
	var tube_assembly: Node3D = kit.get("tube_assembly", mortar)
	var anchor: Node3D = kit.get("gunner_anchor", null)
	var grip_origin: Vector3 = anchor.to_global(Vector3(0.0, .025, -.020)) if anchor != null else tube_assembly.to_global(Vector3(0.0, .073, -.008))
	# Resolve through the traversing assembly so a turn updates the hands and
	# not only the barrel/muzzle.  The grip origin comes from the gunner anchor,
	# keeping the operator attached to the same side of the bipod.
	u.actor.grip_handle("Left", grip_origin + tube_assembly.global_basis * Vector3(-.025, .015, -.006))
	u.actor.grip_handle("Right", grip_origin + tube_assembly.global_basis * Vector3(.025, .015, -.006))

static func pose_guard(u, mortar, kit: Dictionary) -> void:
	if u == null or not is_instance_valid(u) or u.actor == null:
		return
	u.actor.weapon.show()
	u.posture = "stand"
	u.locomotion = "idle"
	u.actor.play("rifle_idle")
	var anchor: Node3D = kit.get("guard_anchor", null)
	var origin: Vector3 = anchor.global_position if anchor != null else u.global_position
	var target: Vector3 = mortar.to_global(Vector3(0, .08, -.46))
	var direction: Vector2 = Vector2(target.x, target.z) - Vector2(origin.x, origin.z)
	if direction.length_squared() > .000001:
		u.rotation.y = atan2(-direction.x, -direction.y)
		u.actor.rotation.y = u.rotation.y + PI
