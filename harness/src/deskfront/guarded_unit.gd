extends "human_unit.gd"
# Harness extension: blocked direct fire is feedback, never a hidden move order.
var harness_fire_check: Dictionary = {}
var harness_blocks: int = 0
var harness_last_block: Dictionary = {}
var harness_last_damage: float = -100.0
var harness_last_hit_at: float = -1.0
var harness_regen: Dictionary = {"active":false,"rate":2.0,"delay":6.0,"healed":0.0}
const SATCHEL_RANGE: float = .60
const SATCHEL_COOLDOWN: float = 14.0
var harness_satchel_ready_at: float = 0.0
var harness_engine_damaged: bool = false
var harness_crew_shock_until: float = 0.0
var harness_tank_damage_visual

# Harness balance pass: the tank's cannon is the heavy weapon and its
# authoritative hit damage is doubled here, at the same point the base unit
# applies the shared weapon sliders.
func weapon_config() -> Dictionary:
	var cfg: Dictionary=super.weapon_config()
	if tank and weapon=="cannon":
		cfg.damage*=2.0
	return cfg

func harness_satchel_config() -> Dictionary:
	var cfg: Dictionary=game.config.weapons.grenade.duplicate(true)
	cfg.damage=110.0
	cfg.armor_multiplier=1.2
	cfg.splash=.13
	cfg.cover_damage=65.0
	cfg.harness_satchel=true
	cfg.harness_satchel_fuse=1.5
	return cfg
func apply_satchel_critical() -> void:
	if not tank or hp<=0:return
	harness_crew_shock_until=maxf(harness_crew_shock_until,game.elapsed+3.0)
	set_meta("harness_crew_shock_until",harness_crew_shock_until)
	if hp/max_hp<=.5 and not harness_engine_damaged:
		harness_engine_damaged=true
		set_meta("harness_engine_damaged",true)
		game.add_event(id+" 引擎受损 · 机动速度下降")
func satchel_block_reason(target) -> String:
	if not game.growth or tank or hp<=0 or deployment_phase!="active" or game.paused or game.winner!="":return "unit_unavailable"
	if target==null or not is_instance_valid(target) or not target.tank or target.hp<=0 or target.faction==faction:return "invalid_target"
	if game.elapsed<harness_satchel_ready_at:return "cooldown"
	if grenade_time>=0:return "throw_in_progress"
	if suppression>=.8:return "heavy_suppression"
	if game.elapsed<safety_until:return "urgent_safety"
	if actor and actor.stepping:return "cover_step"
	if pos().distance_to(target.pos())>SATCHEL_RANGE:return "out_of_range"
	var endpoint: Vector3=target.aim_point()
	var origin: Vector3=muzzle_position(endpoint)
	return game.fx.explosive_fire_block(self,origin,endpoint,harness_satchel_config(),"grenade")
func can_satchel(target) -> bool:
	return satchel_block_reason(target)==""
func satchel_lane_at(target,site: Vector2) -> String:
	if target==null or not is_instance_valid(target) or not target.tank or target.hp<=0 or target.faction==faction:return "invalid_target"
	if site.distance_to(target.pos())>SATCHEL_RANGE:return "out_of_range"
	var endpoint: Vector3=target.aim_point()
	var start:=Vector3(site.x,game.field.ground_height(site)+.093,site.y)
	var origin: Vector3=start+(endpoint-start).normalized()*.023
	return game.fx.explosive_fire_block(self,origin,endpoint,harness_satchel_config(),"grenade")
func request_satchel(target) -> bool:
	if not can_satchel(target):return false
	posture="stand";posture_since=game.elapsed
	grenade_time=0;grenade_released=false;grenade_target=target
	route.clear();goal=pos();state="satchel"
	var delta: Vector2=target.pos()-pos();rotation.y=atan2(-delta.x,-delta.y)
	actor.play("grenade_throw");cooldown=1.3
	harness_satchel_ready_at=game.elapsed+SATCHEL_COOLDOWN
	set_meta("harness_satchel_active",true)
	set_meta("harness_satchel_config",harness_satchel_config())
	set_meta("harness_satchel_result",{"status":"windup","time":game.elapsed,"target_id":target.id})
	return true
func hit(amount: float, pressure: float, origin:Vector3=Vector3.INF, impulse:float=.25) -> void:
	var before = hp
	super.hit(amount,pressure,origin,impulse)
	if hp < before:
		if tank:
			if harness_tank_damage_visual==null:
				harness_tank_damage_visual=preload("res://scripts/tank_damage_visual.gd").new()
				add_child(harness_tank_damage_visual)
				harness_tank_damage_visual.setup(self,origin)
			harness_tank_damage_visual.show_damage()
			if hp<=0:harness_tank_damage_visual.begin_melt()
		# A single hit starts posture recovery (at least three seconds prone);
		# a second hit within two seconds can also activate a cover escape.
		if game.elapsed-harness_last_damage<=2.0:set_meta("harness_sustained_until",game.elapsed+1.5)
		harness_last_damage=game.elapsed;harness_regen.active=false
		if hp>0 and not tank:
			last_threat_at=game.elapsed
			if origin!=Vector3.INF:last_threat_position=Vector2(origin.x,origin.z)
			harness_note_prone_hit()
func tick(dt: float) -> void:
	super.tick(dt)
	if harness_tank_damage_visual!=null:harness_tank_damage_visual.advance(dt)
	harness_regenerate(dt)
func harness_regenerate(dt: float) -> void:
	harness_regen.active=false
	harness_regen["remaining_delay"]=maxf(0,6.0-(game.elapsed-maxf(harness_last_damage,last_shot_at)))
	if tank or hp<=0 or hp>=max_hp or deployment_phase!="active" or game.paused or game.winner!="":return
	if harness_regen.remaining_delay>0 or suppression>.2:return
	for enemy in game.living():
		if enemy.faction==faction:continue
		if pos().distance_to(enemy.pos())<=float(game.config.weapons[enemy.weapon].range) and game.field.trace_cover(enemy.muzzle_position(aim_point()),aim_point()).is_empty():return
	var amount = minf(max_hp-hp,maxf(0,dt)*float(harness_regen.rate))
	hp+=amount;harness_regen.healed+=amount;harness_regen.active=amount>0
func fire(enemy) -> void:
	if actor:actor.update_weapon()
	var destination = enemy.aim_point()
	var origin = muzzle_position(destination)
	var hit: Dictionary = game.fx.trace(origin,destination,id)
	var reason = ""
	if not hit.is_empty():
		if hit.get("kind") == "cover":reason = "cover_blocks_muzzle"
		elif hit.get("kind") == "unit" and hit.unit.faction == faction:reason = "ally_blocks_muzzle"
	if reason != "":
		harness_blocks += 1
		harness_fire_check = {"status":"blocked","reason":reason,"target_id":enemy.id,"time":game.elapsed,"position":[pos().x,pos().y],"blocker":hit.get("cover_id",hit.unit.id if hit.has("unit") else ""),"distance":origin.distance_to(hit.get("point",origin)),"instruction":"换射位或换可交战目标；等待和hold不会解决射线受阻"}
		harness_last_block = harness_fire_check.duplicate()
		cooldown = .2
		return
	harness_fire_check = {"status":"clear","target_id":enemy.id,"time":game.elapsed}
	super.fire(enemy)
func snapshot(queries: Dictionary={}) -> Dictionary:
	var result = super.snapshot(queries)
	result["last_hit_at"] = harness_last_hit_at
	# Damage received is distinct from last_hit_at, which records a hit dealt.
	result["last_damage_at"] = harness_last_damage
	result.combat["fire_check"] = harness_fire_check.duplicate()
	result.combat["blocked_shots_count"] = harness_blocks
	result.combat["last_fire_block"] = harness_last_block.duplicate()
	result.combat["regeneration"] = harness_regen.duplicate()
	result.combat["posture_stability"] = harness_posture_snapshot()
	result["satchel_ready_in"] = maxf(0,harness_satchel_ready_at-game.elapsed)
	result["satchel_range"] = SATCHEL_RANGE
	result["antiarmor_charge_remaining"] = maxf(0,float(get_meta("harness_antiarmor_charge_until",0.0))-game.elapsed) if harness_antiarmor_commit_active() else 0.0
	result.combat["satchel"] = get_meta("harness_satchel_result",{})
	if game.growth and not tank and hp>0 and game.human_squads:
		var closest_tank=null
		var best_distance: float=SATCHEL_RANGE+.2
		for enemy in game.living():
			if not enemy.tank or enemy.faction==faction or not game.human_squads.visible_to(faction,enemy):continue
			var distance: float=pos().distance_to(enemy.pos())
			if distance<best_distance:closest_tank=enemy;best_distance=distance
		if closest_tank!=null:result.combat["satchel_check"]={"target_id":closest_tank.id,"reason":satchel_block_reason(closest_tank),"distance":best_distance}
	if has_meta("engagement_position"):
		var engagement: Dictionary=get_meta("engagement_position",{}).duplicate(true)
		if engagement.get("position") is Vector2:
			var site: Vector2=engagement.position
			engagement.position=[site.x,site.y]
		result.combat["engagement_position"] = engagement
	if tank:
		result.combat["engine_damaged"] = harness_engine_damaged
		result.combat["crew_shock_remaining"] = maxf(0,harness_crew_shock_until-game.elapsed)
		result.combat["damage_visual"] = harness_tank_damage_visual.snapshot() if harness_tank_damage_visual!=null else {"stage":"intact","melt_progress":0.0}
	return result
