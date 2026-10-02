extends RefCounted
## Draw only the path already travelled. No predicted hit line or extra damage.
static func handles(p:Dictionary)->bool:
	return p.cfg.get("harness_mortar",false) or p.weapon in ["cannon","at_cannon"]

static func orient(node:Node3D,direction:Vector3)->void:
	if direction.length_squared()<.000001:return
	var forward:Vector3=direction.normalized()
	node.look_at(node.global_position+forward,Vector3.RIGHT if absf(forward.dot(Vector3.UP))>.98 else Vector3.UP)

static func launch_tangent(p:Dictionary)->Vector3:
	# The engine's high arc is y += sin(t*pi)*arc_height.  Its initial
	# derivative is therefore pi*arc_height; using the same tangent keeps the
	# muzzle flash, shell orientation and first trail segment on one heading.
	var flat:Vector3=p.to-p.from
	if p.cfg.get("harness_mortar",false):flat.y+=PI*float(p.cfg.get("harness_arc_height",0.0))
	return flat.normalized() if flat.length_squared()>.000001 else Vector3.FORWARD

static func setup(fx,p:Dictionary)->void:
	if not handles(p):return
	var node:MeshInstance3D=p.node
	for child in node.get_children():
		node.remove_child(child);child.queue_free()
	# A faceted, elongated shell gives the head a readable travel direction.
	var body=SphereMesh.new();body.radius=.0075;body.height=.015;body.radial_segments=8;body.rings=4
	node.mesh=body;node.scale=Vector3(1,1,2.6)
	node.material_override=fx.material(Color(.95,.79,.40),false)
	orient(node,launch_tangent(p))
	p["presentation_kind"]="mortar_shell" if p.cfg.get("harness_mortar",false) else "tank_shell"
	p["smoke_age"]=0.0;p["trail_segments"]=0

static func step(fx,p:Dictionary,previous:Vector3,current:Vector3,dt:float)->void:
	var mortar:bool=p.cfg.get("harness_mortar",false)
	orient(p.node,current-previous)
	# Every swept segment joins the last one. The pooled effects expire quickly
	# and obey the existing global visual budget even under sustained combat.
	if previous.distance_to(current)>.0001:
		fx.beam(previous,current,.006 if mortar else .009,Color(1,.91,.65) if mortar else Color(1,.72,.32),.42 if mortar else .28)
		p.trail_segments=int(p.get("trail_segments",0))+1
	p.smoke_age+=dt
	if mortar and p.smoke_age>=.12:
		p.smoke_age=0.0;fx.puff(previous,.018,.46,true)
