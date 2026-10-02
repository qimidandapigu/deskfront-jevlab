extends "res://scripts/combat_fx.gd"
# Shot geometry owns hits; the upstream landed roll never guarantees a hit.
const SatchelPresentation=preload("res://scripts/satchel_presentation.gd")
var legacy_dispersion_rng := RandomNumberGenerator.new()
var pending_satchels: Array=[]

func setup(g) -> void:
	super.setup(g)
	legacy_dispersion_rng.seed=73129

func dispersed_endpoint(origin: Vector3, aim: Vector3, accuracy: float, pressure: float, weapon: String="rifle") -> Vector3:
	if game.human_squad:return super.dispersed_endpoint(origin,aim,accuracy,pressure,weapon)
	var distance: float=origin.distance_to(aim)
	var forward: Vector3=(aim-origin).normalized()
	var right: Vector3=forward.cross(Vector3.UP).normalized()
	if right.length_squared()<.01:right=Vector3.RIGHT
	var up: Vector3=right.cross(forward).normalized()
	# Uniform area on a disk perpendicular to aim: no world-axis bias.
	var angle: float=legacy_dispersion_rng.randf()*TAU
	# Indirect fire gets its own, wider cone.  A mortar is aimed at the
	# observed point, then lands around it; it must not inherit rifle spread.
	var base: float={"mortar":.032,"cannon":.020,"at_cannon":.016}.get(weapon,.012)
	var cone: float=(base+.055*(1-clampf(accuracy,0,1)))*(1+clampf(pressure,0,1)*.8)
	var radius: float=sqrt(legacy_dispersion_rng.randf())*distance*tan(cone)
	return aim+(right*cos(angle)+up*sin(angle))*radius

func launch(shooter, target, weapon: String, _landed: bool, override_cfg: Dictionary={}) -> bool:
	if game.human_squad:
		var accepted:bool=super.launch(shooter,target,weapon,_landed,override_cfg)
		if accepted and not projectiles.is_empty() and override_cfg.get("harness_mortar",false):
			# The native branch deliberately defers mortar dispersion; apply the
			# team-weapon cone here with the same payload used for safety checks.
			var mortar:Dictionary=projectiles[-1]
			var pressure:float=float(shooter.get("suppression")) if shooter.get("suppression")!=null else 0.0
			mortar.to=dispersed_endpoint(mortar.from,target.aim_point(),float(override_cfg.accuracy),pressure,"mortar")
			mortar.duration=maxf(.09,mortar.from.distance_to(mortar.to)/float(override_cfg.projectile_speed))
			mortar["dispersion_model"]="angular_disk_v1"
			mortar["nominal_target"]=target.aim_point()
			mortar["dispersion_weapon"]="mortar"
			# The mortar uses the same high arc as its rendered shell.  Passing the
			# semantic weapon here keeps the safety gate from checking a flat hand
			# grenade path and rejecting a valid indirect shot at the first cover.
			var mortar_block:String=explosive_fire_block(shooter,mortar.from,mortar.to,override_cfg,"mortar")
			if mortar_block!="":
				mortar.node.queue_free();projectiles.erase(mortar);launched[weapon]-=1;shooter.set_meta("fire_block_reason",mortar_block);return false
		# A satchel is a deliberate close-range anti-armour action. Keep the
		# authored target point after the native safety gate; ordinary grenades
		# retain their normal dispersion and can still miss.
		if accepted and weapon=="grenade" and override_cfg.get("harness_satchel",false) and not projectiles.is_empty():
			var satchel:Dictionary=projectiles[-1]
			satchel.to=target.aim_point()
			satchel.duration=maxf(.09,satchel.from.distance_to(satchel.to)/float(satchel.cfg.projectile_speed))
			satchel["dispersion_model"]="direct_close_charge_v1"
		return accepted
	var count: int=projectiles.size()
	if not super.launch(shooter,target,weapon,true,override_cfg):return false
	if weapon=="bayonet" or projectiles.size()==count:return true
	var p: Dictionary=projectiles[-1]
	# Team weapons pass a purpose-built payload (mortar arc, crew penalty,
	# splash). Preserve it instead of replacing it with the crew member's
	# grenade defaults just because the weapon has no infantry `weapon` field.
	var cfg: Dictionary=override_cfg.duplicate(true) if not override_cfg.is_empty() else (shooter.weapon_config() if shooter.has_method("weapon_config") else game.config.weapons[weapon].duplicate(true))
	var pressure: float=float(shooter.get("suppression")) if shooter.get("suppression")!=null else 0.0
	var dispersion_weapon: String="mortar" if cfg.get("harness_mortar",false) else weapon
	p.to=dispersed_endpoint(p.from,target.aim_point(),float(cfg.accuracy),pressure,dispersion_weapon)
	p.duration=maxf(.09,p.from.distance_to(p.to)/float(cfg.projectile_speed))
	p["dispersion_model"]="angular_disk_v1"
	p["nominal_target"]=target.aim_point()
	p["dispersion_weapon"]=dispersion_weapon

	var blocked: String=explosive_fire_block(shooter,p.from,p.to,cfg,weapon)
	shooter.set_meta("fire_block_reason",blocked)
	if blocked!="":
		p.node.queue_free();projectiles.erase(p);launched[weapon]-=1;return false
	return true

func impact(p: Dictionary) -> void:
	if not p.cfg.get("harness_satchel",false):
		super.impact(p)
		return
	var pack:=MeshInstance3D.new()
	SatchelPresentation.build(pack,self,game.colors.get(str(p.team),Color(.34,.28,.18)))
	add_child(pack);pack.global_position=p.to
	var payload: Dictionary=p.duplicate()
	var attached=p.target if p.get("collision",{}).get("kind","")=="unit" and p.get("collision",{}).get("unit")==p.target else null
	var world_normal:Vector3=p.get("collision",{}).get("normal",Vector3.UP)
	if world_normal.length_squared()<.001 and attached!=null:world_normal=(p.to-attached.global_position).normalized()
	if world_normal.length_squared()<.001:world_normal=Vector3.UP
	if attached!=null:SatchelPresentation.orient(pack,world_normal)
	var local_normal:Vector3=attached.global_basis.inverse()*world_normal if attached!=null else Vector3.UP
	pending_satchels.append({"payload":payload,"pack":pack,"target":attached,"local_anchor":attached.to_local(p.to) if attached!=null else Vector3.ZERO,"local_normal":local_normal,"remaining":float(p.cfg.get("harness_satchel_fuse",1.5)),"fuse":float(p.cfg.get("harness_satchel_fuse",1.5)),"position":p.to})
	if attached!=null:game.add_event(attached.id+" 被贴上炸药包")

func physics_tick(dt: float) -> void:
	if dt>.034:
		var substeps: int=ceili(dt/.03333333)
		for i in range(substeps):physics_tick(dt/substeps)
		return
	super.physics_tick(dt)
	for charge in pending_satchels.duplicate():
		charge.remaining-=dt
		var attached=charge.target
		if is_instance_valid(attached) and attached.hp>0:
			charge.position=attached.to_global(charge.local_anchor)
			charge.pack.global_position=charge.position
			SatchelPresentation.orient(charge.pack,attached.global_basis*charge.get("local_normal",Vector3.UP))
		var phase: float=1.0-charge.remaining/charge.fuse
		SatchelPresentation.pulse(charge.pack,phase)
		if charge.remaining>0:continue
		pending_satchels.erase(charge)
		charge.pack.queue_free()
		var payload: Dictionary=charge.payload
		payload.to=charge.position
		if is_instance_valid(attached) and attached.hp>0:
			payload.collision={"kind":"unit","unit":attached,"normal":Vector3.UP}
		else:payload.collision={}
		var before_hp: float=attached.hp if is_instance_valid(attached) else 0.0
		super.impact(payload)
		if is_instance_valid(attached) and attached.hp>0 and attached.hp<before_hp and attached.has_method("apply_satchel_critical"):
			attached.apply_satchel_critical()
		for shooter in game.units:
			if shooter.id!=str(payload.shooter):continue
			shooter.set_meta("harness_satchel_result",{"status":"detonated","time":game.elapsed,"target_id":attached.id if is_instance_valid(attached) else "","damage":maxf(0.0,before_hp-attached.hp) if is_instance_valid(attached) else 0.0})
			break
