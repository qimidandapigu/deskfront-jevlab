extends Node3D

# Damage and destruction presentation for the Harness-owned infinite world.
# The engine unit remains the only authority for HP, collision and death.
var unit
var painted: Array=[]
var stage: String="intact"
var melt_progress: float=0.0
var turret_start_roll: float=0.0
var turret_start_yaw: float=0.0
var damaged_track_start: Vector3=Vector3.ZERO
var damaged_track_name: String="TrackMesh_R"
var scar_side: String="right"
var scar_front: bool=true

func _process(delta: float) -> void:
	# The match can end on the killing hit; keep the visible death finish running.
	if unit!=null and unit.game.winner!="" and not unit.game.paused and stage=="melting":advance(delta)

func setup(owner, hit_origin: Vector3=Vector3.INF) -> void:
	unit=owner
	if hit_origin!=Vector3.INF:
		var local_hit: Vector3=unit.model.to_local(hit_origin)
		scar_side="left" if local_hit.z>0.0 else "right"
		scar_front=local_hit.x>=0.0
	damaged_track_name="TrackMesh_L" if scar_side=="left" else "TrackMesh_R"
	for part in unit.model.find_children("*","MeshInstance3D",true,false):
		if not part.material_override is StandardMaterial3D:continue
		var original: StandardMaterial3D=part.material_override
		var material: Material
		if part.name in ["Tank_body","Tank_Turret",damaged_track_name]:
			var burn:=ShaderMaterial.new()
			burn.shader=preload("res://scripts/tank_burn.gdshader")
			burn.set_shader_parameter("base_color",original.albedo_color)
			var bounds: AABB=part.get_aabb()
			burn.set_shader_parameter("bounds_min",bounds.position)
			burn.set_shader_parameter("bounds_size",bounds.size)
			match part.name:
				"Tank_body":
					burn.set_shader_parameter("scar_center",Vector3(.94 if scar_front else .06,.40,.24 if scar_side=="right" else .76))
					burn.set_shader_parameter("scar_radius",Vector3(.28,.39,.34))
				"Tank_Turret":
					burn.set_shader_parameter("scar_center",Vector3(.28 if scar_side=="right" else .72,.72 if scar_front else .28,.83))
					burn.set_shader_parameter("scar_radius",Vector3(.43,.43,.65))
				_:
					burn.set_shader_parameter("scar_center",Vector3(.75 if scar_front else .25,.26,.10 if scar_side=="right" else .90))
					burn.set_shader_parameter("scar_radius",Vector3(.42,.55,.72))
			material=burn
		else:material=original.duplicate()
		part.material_override=material
		painted.append({"material":material,"color":original.albedo_color,"name":part.name})
	turret_start_roll=unit.turret.rotation.z
	turret_start_yaw=unit.turret.rotation.y
	var damaged_track: MeshInstance3D=unit.model.find_child(damaged_track_name,true,false)
	if damaged_track!=null:damaged_track_start=damaged_track.position

func paint_damage(lost: float, wreck: float=0.0) -> void:
	for row in painted:
		var name: String=row.name
		if row.material is ShaderMaterial:
			var burn: ShaderMaterial=row.material
			var intensity: float=clampf((lost-.12)*1.95,0.0,1.0)
			if name=="Tank_Turret":intensity*=.82
			burn.set_shader_parameter("burn_strength",intensity)
			burn.set_shader_parameter("wreck_strength",wreck)
			continue
		var charred: float=0.0
		match name:
			"TrackMesh_L":charred=clampf(wreck*.12,0.0,.12)
			"Tank_Gun":charred=clampf(wreck*.20,0.0,.20)
		var material: StandardMaterial3D=row.material
		material.albedo_color=(row.color as Color).lerp(Color(.035,.032,.028),charred)

func bend_track(severity: float, wreck: float=0.0) -> void:
	var damaged_track: MeshInstance3D=unit.model.find_child(damaged_track_name,true,false)
	if damaged_track==null:return
	var outward: float=-1.0 if scar_side=="right" else 1.0
	damaged_track.position=damaged_track_start+Vector3(0.0,-(.22+.18*wreck)*severity,outward*(.28+.22*wreck)*severity)

func show_damage() -> void:
	if unit.hp<=0:return
	var lost: float=1.0-clampf(unit.hp/unit.max_hp,0.0,1.0)
	stage="critical" if lost>=.5 else ("damaged" if lost>=.22 else "scratched")
	paint_damage(lost)
	bend_track(clampf((lost-.25)/.35,0.0,1.0))

func begin_melt() -> void:
	if stage=="melting" or stage=="wreck":return
	stage="melting";melt_progress=0.0
	paint_damage(1.0)

func advance(dt: float) -> void:
	if stage!="melting":return
	melt_progress=minf(1.0,melt_progress+dt/3.0)
	var eased: float=melt_progress*melt_progress*(3.0-2.0*melt_progress)
	# A fallen tank keeps its hull, tracks and turret raised above the ground.
	unit.model.scale=Vector3(1.0+.025*eased,1.0-.16*eased,1.0+.025*eased)
	unit.model.position.y=-.007*eased
	unit.model.rotation.z=-.19*eased
	unit.model.rotation.x=.07*eased
	unit.turret.rotation.z=turret_start_roll-.18*eased
	unit.turret.rotation.y=turret_start_yaw+.22*eased
	bend_track(1.0,eased)
	paint_damage(1.0,eased)
	if melt_progress>=1.0:stage="wreck"

func snapshot() -> Dictionary:
	return {"stage":stage,"melt_progress":snappedf(melt_progress,.01),"scar_side":scar_side,"smoke_active":false,"wreck_height":snappedf(unit.model.scale.y,.01)}
