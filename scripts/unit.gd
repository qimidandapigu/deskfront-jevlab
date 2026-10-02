extends Node3D

const COMBAT_AWARENESS = preload("res://scripts/unit_combat_awareness.gd")
const UNIT_PRESENTATION = preload("res://scripts/unit_presentation.gd")

var game
var gun_id:String=""
var garrison_phase:String=""
var garrison_floor:int=0
var garrison_path:Array[Vector3]=[]
var garrison_history:Array[Vector3]=[]
var garrison_stall:float=0
var id: String
var faction: String
var hp: float = 100
var max_hp: float = 100
var lm_intent: String=""
var lm_reason: String=""
var emotion: String=""
var emotion_until: float=0
var suppression: float = 0
var state: String = "idle"
var goal := Vector2.ZERO
var route := PackedVector2Array()
var route_revision: int = -1
var cover_id: String = ""
var target_id: String = ""
var cooldown: float = 0
var reload_timer: float = 0
var ammo: int = 6
var tank: bool = false
var anim: AnimationPlayer
var tree: AnimationTree
var playback: AnimationNodeStateMachinePlayback
var animation_names: Dictionary = {}
var model: Node3D
var ring: MeshInstance3D
var hp_fill: MeshInstance3D
var fire_until: float = 0
var last_clip: String = ""
var bone_count: int = 0
var selected: bool = false
var weapon: String="rifle"
var cover_since: float=0
var reaction_cooldown: float=0
var melee_until: float=0
var pursuit_clock: float=0
var tactical_role: String=""
var order_mode: String="hold"
var cover_slot: Dictionary={}
var cqb_stance: String="open"
var peek_until: float=0
var hide_until: float=0
var peeking: bool=false
var focus_id: String=""
var formation_speed: float=1
var aim_time: float=0
var turret: Node3D
var muzzle: Node3D
var reversing: bool=false
var actor
var actor_advanced: bool=false
var grenade_count: int=2
var grenade_time: float=-1
var grenade_target
var grenade_released: bool=false
var tank_skeleton: Skeleton3D
var weapon_attachment: BoneAttachment3D
var posture: String="stand"
var locomotion: String="idle"
var weapon_state: String="ready"
var posture_order: String="auto"
var posture_since: float=-10
var explosive_until: float=0
var explosive_notice_at: float=-100
var safety_until: float=0
var safety_reason: String=""
var last_shot_at: float=-10
var last_shot_target: String=""
var last_threat_at: float=-10
var last_threat_position := Vector2.ZERO
var reaction_at: float=0
var action_counts: Dictionary={}
var last_action_key: String=""
var progress_position:=Vector2.INF
var no_progress_seconds: float=0
var path_repairs: int=0
var path_failure: String=""
var previous_hull_yaw: float=0
var deployment_phase: String="active"
var deployment_goal:=Vector2.ZERO
var track_clip: String="TankArmature|Tank_Forward"

func weapon_config() -> Dictionary:
	var cfg: Dictionary=game.config.weapons[weapon].duplicate()
	# Existing designer sliders act as shared multipliers; defaults preserve balance.
	cfg.damage*=game.config.soldier.damage/9.0
	cfg.cooldown*=game.config.soldier.cooldown/1.3
	cfg.accuracy=clampf(cfg.accuracy*game.config.soldier.accuracy/.72,0,1)
	return cfg

func install_weapon() -> void:
	pass # Weapon assets are attached to the imported hand anchors by toy_actor.gd.

func pos() -> Vector2:
	return Vector2(position.x,position.z)

func setup(owner_game, unit_id: String, team: String, p: Vector2, is_tank: bool=false) -> void:
	game=owner_game;id=unit_id;faction=team;tank=is_tank
	var cfg: Dictionary = game.config.tank if tank else game.config.soldier
	max_hp=cfg.hp;hp=max_hp
	weapon="cannon" if tank else game.config.loadout[(int(unit_id.get_slice("-",1))-1)%3]
	tactical_role={"rifle":"overwatch","smg":"assault","rocket":"anti_armor"}.get(weapon,"armor")
	ammo=int(game.config.weapons[weapon].magazine)
	position=Vector3(p.x,game.field.ground_height(p),p.y);goal=p
	if not tank:
		actor=preload("res://scripts/toy_actor.gd").new();add_child(actor);actor.top_level=true
		actor.global_position=global_position;actor.rotation.y=rotation.y+PI
		actor.navigation_guard=func(p:Vector3):return garrison_phase!="" or game.field.walkable(Vector2(p.x,p.z))
		actor.ground_sampler=func(at:Vector3):return actor.global_position.y if garrison_phase!="" else game.field.ground_height(Vector2(at.x,at.z))
		actor.setup(game.colors[faction],"rocket" if weapon=="rocket" else "rifle")
		model=actor.model;anim=actor.anim;tree=actor.tree;playback=actor.playback;bone_count=actor.skeleton.get_bone_count()
		for clip_name in anim.get_animation_list():animation_names[clip_name]=clip_name
	else:
		model=preload("res://scripts/tank_visual.gd").new();add_child(model)
		model.setup(game.field.mat(game.colors[faction],.32));turret=model.turret;muzzle=model.muzzle
		var body=StaticBody3D.new();add_child(body);body.collision_layer=1;body.collision_mask=0
		var col=CollisionShape3D.new();body.add_child(col);var shape=BoxShape3D.new();shape.size=Vector3(.18,.08,.25);col.shape=shape;col.position.y=.04
	var torus := TorusMesh.new();torus.inner_radius=.027 if not tank else .10;torus.outer_radius=.031 if not tank else .105
	ring=MeshInstance3D.new();ring.mesh=torus;add_child(ring);ring.position.y=.003;ring.scale.y=.10
	var rm := StandardMaterial3D.new();rm.albedo_color=Color(.93,.81,.47);rm.shading_mode=BaseMaterial3D.SHADING_MODE_UNSHADED
	ring.material_override=rm;ring.visible=false
	hp_fill=game.field.cube(self,Vector3(0,.145 if not tank else .18,0),Vector3(.05,.003,.005),game.field.mat(game.colors[faction].lightened(.25)))

func animate(clip: String) -> void:
	UNIT_PRESENTATION.animate(self,clip)

func hit_box() -> Dictionary:
	var size:=Vector3(.13,.085,.21) if tank else (Vector3(.035,.035,.085) if posture=="prone" else Vector3(.035,.077 if posture=="crouch" else .118,.035))
	return {"center":global_position+Vector3.UP*size.y*.5,"size":size}

func aim_point() -> Vector3:
	var box:=hit_box()
	# Exposed upper torso, not a guessed tabletop-level point.
	return box.center+Vector3.UP*box.size.y*.22

var firing_awareness: Dictionary={}
var firing_review_at: float=0
var firing_posture: String=""
var firing_posture_until: float=0

func firing_solution_at(enemy, point: Vector2, stance: String) -> Dictionary:
	return COMBAT_AWARENESS.firing_solution_at(self,enemy,point,stance)

func update_firing_awareness() -> void:
	COMBAT_AWARENESS.update_firing_awareness(self)

func can_engage(enemy) -> bool:
	return COMBAT_AWARENESS.can_engage(self,enemy)

func receive_pressure(amount: float, origin: Vector3) -> void:
	suppression=clampf(suppression+amount,0,1)
	last_threat_at=game.elapsed;last_threat_position=Vector2(origin.x,origin.z)

# 紧急动作不等待模型，也不调用全场 A*；只采用已验证可直达的短距离落点。
func evade_explosive(estimate: Vector2, origin: Vector2, eta: float, radius: float) -> void:
	if game.elapsed-explosive_notice_at<.8:return
	explosive_notice_at=game.elapsed;explosive_until=game.elapsed+minf(1.4,eta+.35)
	safety_until=maxf(safety_until,explosive_until);safety_reason="incoming_explosive"
	last_threat_at=game.elapsed;last_threat_position=origin;target_id="";focus_id=""
	if game.human_squads:game.human_squads.emit("incoming_explosive",faction,game.human_squads.owners.get(id,""),id,{"reason":"visible_projectile_approaching","estimated_position":[estimate.x,estimate.y],"eta":eta,"expires_at":explosive_until})
	# 已有坚实遮挡时缩回，不为躲弹反而跑出保护。
	if in_cover() and game.field.protection(pos(),estimate)>=.6:
		route.clear();goal=pos();hide_until=explosive_until;cqb_stance="hide";posture="prone";return
	var away: Vector2=(pos()-estimate).normalized()
	if away.length()<.1:away=(pos()-origin).orthogonal().normalized()
	var side: Vector2=(estimate-origin).normalized().orthogonal()
	var best: Vector2=pos();var score: float=pos().distance_to(estimate)
	var distance: float=clampf(eta*.12,.04,.14)
	for direction in [away,side,-side,(away+side).normalized(),(away-side).normalized()]:
		var candidate: Vector2=pos()+direction*distance
		if not game.field.segment_walkable(pos(),candidate):continue
		if game.living().any(func(v):return v!=self and v.pos().distance_to(candidate)<.04):continue
		var separation: float=candidate.distance_to(estimate)
		if separation>score+.015:best=candidate;score=separation
	route.clear();goal=pos();posture="prone"
	if best!=pos():
		game.field.release(id);cover_id="";cover_slot={};peeking=false;cqb_stance="open"
		goal=best;route=PackedVector2Array([best]);route_revision=game.field.revision;order_mode="evade_explosive"
	else:order_mode="pinned"

func survival_tick() -> void:
	if game.human_squad and game.elapsed<explosive_until:return
	# During imminent flag defeat, honor LM counterattack orders even at low health.
	# Damage, suppression, navigation and animation constraints still apply.
	if not game.human_squad and game.control[faction]=="lm" and game.flag_emergency(faction):
		safety_until=0;safety_reason="";return
	if tank:
		if game.control[faction]=="lm" and game.elapsed>=reaction_at:
			reaction_at=game.elapsed+.4
			var danger: bool=hp/max_hp<.35 or game.living().any(func(u):return u.faction!=faction and u.weapon=="rocket" and u.pos().distance_to(pos())<game.config.tactics.tank_danger_range and game.field.line_of_sight(u.pos(),pos()))
			danger=danger or game.at_guns.any(func(g):return g.faction!=faction and g.phase=="ready" and g.pos().distance_to(pos())<1.1 and game.field.line_of_sight(g.pos(),pos()))
			if danger:
				safety_until=game.elapsed+3;target_id="";game.tactics_ai.plan_tank(self)
		return
	if game.elapsed<reaction_at:return
	reaction_at=game.elapsed+game.config.tactics.safe_reaction_seconds
	var enemy=game.closest_enemy(self)
	if enemy==null:return
	var under_fire: bool=game.elapsed-last_threat_at<3.0 or (not game.human_squad and enemy.pos().distance_to(pos())<.8 and game.field.line_of_sight(enemy.pos(),pos()))
	var armor_threat=enemy if enemy.tank else null
	for candidate in game.living():
		if candidate.tank and candidate.faction!=faction and candidate.pos().distance_to(pos())<.85 and game.field.line_of_sight(candidate.pos(),pos()):armor_threat=candidate;break
	var outmatched:bool=armor_threat!=null and weapon not in ["rocket","cannon"] and game.field.line_of_sight(armor_threat.pos(),pos()) and armor_threat.pos().distance_to(pos())<.85
	# A tank must not erase a nearer flank threat: cover is safe only if both
	# directions are protected. Escape the exposed flank before hiding from armor.
	var compromised: bool=in_cover() and enemy.pos().distance_to(pos())<game.config.weapons[enemy.weapon].range and enemy.can_engage(self) and game.field.protection(pos(),enemy.pos())<.2
	if outmatched and not compromised:enemy=armor_threat
	compromised=compromised or (in_cover() and enemy.pos().distance_to(pos())<game.config.weapons[enemy.weapon].range and enemy.can_engage(self) and game.field.protection(pos(),enemy.pos())<.2)
	# 拟人模式下真实近失弹/受击即可触发自保，不等待残血；单纯看见敌人不等于受火。
	var incoming_fire: bool=game.human_squad and game.elapsed-last_threat_at<1.5
	var danger: bool=incoming_fire or outmatched or compromised or (under_fire and (hp/max_hp<game.config.tactics.survival_hp or suppression>.72))
	if not danger:return
	safety_until=game.elapsed+3.0
	target_id="" # Pursuit must never overwrite an emergency escape route.
	safety_reason="armor_outmatched" if outmatched else "low_health" if hp/max_hp<game.config.tactics.survival_hp else ("flanked" if compromised else ("incoming_fire" if incoming_fire else "suppressed"))
	if in_cover() and not compromised:
		if peeking:peeking=false;move_to(cover_slot.position,true)
		hide_until=game.elapsed+2.2;cqb_stance="hide";return
	if compromised:game.field.release(id);cover_id="";cover_slot={};peeking=false;cqb_stance="open"
	if order_mode=="self_preserve" and not route.is_empty() and not compromised:return
	var away: Vector2=pos()+(pos()-enemy.pos()).normalized()*.25
	if game.human_squad and game.elapsed<float(get_meta("survival_cover_retry",0)):return
	set_meta("survival_cover_retry",game.elapsed+.8)
	if seek_cover(enemy.pos(),away,{"threats":game.tactics_ai.threat_points(faction),"max_travel":.38,"survival":true,"range":weapon_config().range}):
		order_mode="self_preserve";return
	# 没有验证可用的掩体时，先就地压低姿态，不在火力下盲目穿越空地。
	if game.human_squad:
		# 无掩体时仍可脱离射线，但只接受可直达且确实获得遮挡的短路。
		var escape: Vector2=pos()
		var backward: Vector2=(pos()-enemy.pos()).normalized()
		for direction in [backward,backward.orthogonal(),-backward.orthogonal()]:
			var candidate: Vector2=pos()+direction*.12
			if not game.field.segment_walkable(pos(),candidate) or game.field.line_of_sight(candidate,enemy.pos()):continue
			if game.living().any(func(v):return v!=self and v.pos().distance_to(candidate)<.04):continue
			escape=candidate;break
		route.clear();goal=escape
		if escape!=pos():route=PackedVector2Array([escape]);route_revision=game.field.revision;order_mode="self_preserve"
		else:order_mode="pinned"
		return
	# No useful cover is a legitimate query failure. Crawl away, never force a bad slot.
	var destination: Vector2=game.field.soft_offset(pos(),away,.32)
	if destination.distance_to(enemy.pos())>pos().distance_to(enemy.pos())+.025:
		move_to(destination);order_mode="self_preserve"
	else:route.clear();goal=pos();order_mode="pinned"

func monitor_progress(dt: float) -> void:
	if tank:return
	if route.is_empty() or progress_position==Vector2.INF or pos().distance_to(progress_position)>.004:
		progress_position=pos();no_progress_seconds=0;return
	no_progress_seconds+=dt
	if no_progress_seconds<1.5 or actor.stepping:return
	path_repairs+=1;no_progress_seconds=0;progress_position=pos()
	var alternative: PackedVector2Array=game.field.path_around_units(pos(),goal,game.living().filter(func(u):return u!=self)+game.at_guns.filter(func(g):return g.hp>0))
	if alternative.size()>1:
		route=alternative;path_failure="replanned_around_occupant"
		if alternative[-1].distance_to(goal)>.025:
			game.field.release(id);cover_id="";cover_slot={};peeking=false;goal=alternative[-1]
	else:
		if not cover_slot.is_empty():game.field.unavailable_until[id+":"+cover_slot.key]=game.elapsed+6
		game.field.release(id);cover_id="";cover_slot={};peeking=false
		route.clear();goal=pos();state="blocked";path_failure="no_safe_route"
		game.add_event(id+" 通路受阻，停止空跑并重新寻找保护")

func update_posture(moving: bool) -> void:
	if tank:posture="armored";locomotion="reverse" if reversing else ("tracks" if moving else "idle");return
	var desired: String="stand"
	var threat=game.closest_enemy(self)
	var contact: bool=threat!=null and threat.pos().distance_to(pos())<.9 and (game.field.line_of_sight(pos(),threat.pos()) or game.elapsed-last_threat_at<3)
	# 接敌不等于正在受火。自动卧倒需有近期受威胁证据，避免远处敌人让士兵永久趴伏。
	var under_fire: bool=(game.human_squad and game.elapsed-last_threat_at<1.5) or (contact and (game.elapsed-last_threat_at<1.5 or suppression>=game.config.tactics.prone_pressure))
	if garrison_phase=="stationed":desired="prone" if cqb_stance=="hide" else "crouch"
	elif in_cover() or cqb_stance in ["hide","peek"]:
		desired="prone" if cqb_stance=="hide" and not cover_slot.get("hard",false) else "crouch"
	elif suppression>=game.config.tactics.prone_pressure or (game.elapsed<safety_until and under_fire):desired="prone"
	elif not moving and under_fire and weapon in ["rifle","smg","pistol"] and not (threat!=null and pos().distance_to(threat.pos())<.14):desired="prone"
	if posture=="prone" and suppression>game.config.tactics.recover_pressure and not in_cover() and (not moving or under_fire):desired="prone"
	# 自动避险移动用蹲跑；不能让紧急撤离路径变成长时间爬行。
	# 玩家/模型显式选择卧姿时仍允许匍匐推进。
	if moving and posture_order=="auto" and desired=="prone" and not game.human_squad:desired="crouch"
	if posture_order!="auto" and not (game.control[faction]=="lm" and (game.elapsed<safety_until or suppression>.72)):desired=posture_order
	if game.human_squad and posture_order=="auto" and game.elapsed<firing_posture_until and game.elapsed>=safety_until and not under_fire and suppression<.35 and cqb_stance!="hide":desired=firing_posture
	if desired!=posture and (game.elapsed-posture_since>=game.config.tactics.posture_dwell or desired=="prone" or cqb_stance=="hide"):
		posture=desired;posture_since=game.elapsed;last_clip=""
	var was_sprinting:bool=locomotion=="sprint"
	locomotion=("crawl" if posture=="prone" else ("crouch_run" if posture=="crouch" else "run")) if moving else "idle"

	if moving and posture=="stand" and garrison_phase=="" and suppression<game.config.tactics.prone_pressure:
		var threshold:float=game.config.tactics.sprint_exit_distance if was_sprinting else game.config.tactics.sprint_enter_distance
		if pos().distance_to(goal)>threshold:locomotion="sprint"

func record_action() -> void:
	if hp<=0:weapon_state="disabled";locomotion="disabled";return
	if gun_id!="":return
	weapon_state="throw" if grenade_time>=0 else ("melee" if game.elapsed<melee_until else ("reload" if reload_timer>0 else ("fire" if game.elapsed<fire_until else ("cooldown" if cooldown>0 else "ready"))))
	var key: String=posture+"/"+locomotion+"/"+weapon_state
	if key!=last_action_key:action_counts[key]=int(action_counts.get(key,0))+1;last_action_key=key

func in_cover() -> bool:
	return cover_id!="" and not cover_slot.is_empty() and pos().distance_to(cover_slot.position)<(.028 if cover_slot.hard else .030)

func armor_multiplier(from: Vector2) -> float:
	if not tank:return 1.0
	var forward := Vector2(-sin(rotation.y),-cos(rotation.y))
	var facing: float=forward.dot((from-pos()).normalized())
	return game.config.tactics.tank_front_armor if facing>.45 else (game.config.tactics.tank_rear_armor if facing<-.45 else game.config.tactics.tank_side_armor)

func muzzle_position(target: Vector3) -> Vector3:
	if tank and muzzle:return muzzle.global_position
	# Teleports can precede presentation synchronization; never fire from a stale socket.
	if actor and actor.global_position.distance_to(global_position)<=.001:return actor.muzzle_world
	var y: float=.026 if posture=="prone" else (.068 if posture=="crouch" else .093)
	if cqb_stance=="hide":y=.025
	var start := global_position+Vector3.UP*y
	return start+(target-start).normalized()*(.13 if tank else .023)

func navigation_path(destination:Vector2)->PackedVector2Array:
	if game.human_squad and not tank and deployment_phase=="active":
		return game.field.tactical_path(pos(),destination,game.human_squads.threat_points(faction),faction,game.living(faction).filter(func(u):return u!=self),game.at_guns.filter(func(g):return g.hp>0))
	if not tank and not game.at_guns.is_empty():
		return game.field.path_around_units(pos(),destination,game.at_guns.filter(func(g):return g.hp>0))
	return game.field.path(pos(),destination,tank)

func move_to(p: Vector2, keep_cover: bool=false) -> void:
	if hp<=0:return
	if not keep_cover:game.field.release(id);cover_id="";cover_slot={};peeking=false;cqb_stance="open"
	var destination: Vector2=game.field.to_world(game.field.nearest(p,tank))
	if route_revision==game.field.revision and destination.distance_to(goal)<game.config.tactics.repath_delta and (not route.is_empty() or pos().distance_to(destination)<(.002 if keep_cover else .025)):return
	goal=destination
	route=navigation_path(goal)
	route_revision=game.field.revision
	state="move"

func occupy(slot: Dictionary) -> void:
	if cover_slot.get("key","")!=slot.key:cover_since=game.elapsed
	game.field.reserve_slot(id,slot)
	cover_id=slot.cover_id;cover_slot=slot;peeking=false
	hide_until=game.elapsed+.25
	move_to(slot.position,true)

func seek_cover(threat: Vector2, near_goal: Vector2, options: Dictionary={}) -> bool:
	var slot: Dictionary=game.field.choose_cover(id,pos(),threat,near_goal,options)
	if slot.is_empty():return false
	occupy(slot);return true

func cover_behavior() -> void:
	if garrison_phase=="stationed":
		cqb_stance="hide" if suppression>.5 or reload_timer>0 or fmod(game.elapsed,2.5)>1.0 else "peek"
		return
	if tank or cover_slot.is_empty() or cover_id=="":cqb_stance="open";return
	var hidden: bool=reload_timer>0 or suppression>=game.config.tactics.pinned_threshold or game.elapsed<safety_until
	if not cover_slot.hard:
		cqb_stance="hide" if hidden and in_cover() else ("crouch" if in_cover() else "open")
		return
	var anchor: Vector2=cover_slot.position
	var peek: Vector2=cover_slot.peek
	if peeking:
		cqb_stance="peek"
		# Exposure dwell begins at the shoulder, not while travelling to it.
		if peek_until<0 and route.is_empty():peek_until=game.elapsed+game.config.tactics.peek_seconds
		if hidden or (peek_until>=0 and game.elapsed>peek_until):
			peeking=false;hide_until=game.elapsed+game.config.tactics.hide_seconds;cqb_stance="hide";move_to(anchor,true)
	elif pos().distance_to(anchor)<.04:
		cqb_stance="hide"
		var enemy=game.human_squads.visible_enemy(self) if game.human_squad else game.closest_enemy(self)
		if not hidden and game.elapsed>=hide_until and enemy!=null and peek.distance_to(enemy.pos())<game.config.weapons[weapon].range and game.field.walkable(peek) and (firing_solution_at(enemy,peek,"crouch").clear if game.human_squad else game.field.line_of_sight(peek,enemy.pos())):
			peeking=true;peek_until=-1;cqb_stance="peek";move_to(peek,true)

func turn_weapon(enemy, moving: bool, dt: float) -> bool:
	if enemy==null:return false
	var direction: Vector2=enemy.pos()-pos()
	var desired: float=atan2(-direction.x,-direction.y)
	if tank:
		if turret:
			turret.rotation.y=rotate_toward(turret.rotation.y,wrapf(desired-rotation.y,-PI,PI),game.config.tactics.turret_turn_speed*dt)
			if not moving:rotation.y=rotate_toward(rotation.y,desired,game.config.tactics.tank_turn_speed*dt)
			# Let the rendered barrel settle before creating a shell.  A wider
			# gate makes the muzzle visibly disagree with the projectile path.
			return absf(angle_difference(rotation.y+turret.rotation.y,desired))<.08
		rotation.y=rotate_toward(rotation.y,desired,game.config.tactics.tank_turn_speed*dt)
		return absf(angle_difference(rotation.y,desired))<.08
	if not moving and not (actor and actor.stepping):rotation.y=lerp_angle(rotation.y,desired,minf(1,dt*10))
	return true

func hit(amount: float, pressure: float, origin:Vector3=Vector3.INF, impulse:float=.25) -> void:
	if hp<=0:return
	hp=maxf(0,hp-amount);suppression=minf(1,suppression+pressure)
	if hp<=0:
		state="dead";route.clear();game.field.release(id);animate("death");hp_fill.visible=false;ring.visible=false
		if actor:actor.ragdoll(global_position+Vector3(.07,0,0) if origin==Vector3.INF else origin,impulse)
		else:
			for body in find_children("*","StaticBody3D",true,false):body.collision_layer=0
		game.add_event(faction+" · "+id+" 失去战斗力")

func deployment_tick(dt: float) -> void:
	if deployment_phase!="entering":return
	var direction: Vector2=deployment_goal-pos()
	rotation.y=rotate_toward(rotation.y,atan2(-direction.x,-direction.y),1.2*dt)
	var next: Vector2=pos().move_toward(deployment_goal,float(game.config.tank.get("deployment_speed",.06))*dt)
	position=Vector3(next.x,game.field.ground_height(next),next.y);state="move";locomotion="tracks"
	if next.distance_to(deployment_goal)<.004:
		deployment_phase="active";goal=pos();state="idle";cooldown=1.0
		game.add_event("红方坦克驶入阵地 · 可以参战")

func tick(dt: float) -> void:
	if deployment_phase!="active":
		if tank:deployment_tick(dt)
		return
	actor_advanced=false
	if hp<=0:return
	if actor and actor.global_position.distance_to(global_position)>.001 and not actor.stepping:actor.global_position=global_position
	if grenade_time>=0:
		grenade_time+=dt
		if grenade_time>=.62 and not grenade_released:
			grenade_released=true
			if is_instance_valid(grenade_target) and game.fx.launch(self,grenade_target,"grenade",true):game.shots+=1
			else:grenade_count+=1
		if grenade_time>=1.267:grenade_time=-1;last_clip=""
		return
	ring.visible=selected
	hp_fill.scale.x=maxf(.01,hp/max_hp)
	cooldown=maxf(0,cooldown-dt)
	reaction_cooldown=maxf(0,reaction_cooldown-dt)
	suppression=maxf(0,suppression-dt*game.config.soldier.suppression_decay)
	if cover_id!="":
		var valid: bool=false
		for c in game.field.covers:
			if c.id==cover_id and c.alive:valid=true
		if not valid:game.field.release(id);cover_id="";cover_slot={};peeking=false;cqb_stance="open"
	if route_revision!=game.field.revision and not route.is_empty():route=navigation_path(goal);route_revision=game.field.revision
	if gun_id!="":
		actor.weapon.hide()
		for gun in game.at_guns:
			if gun.id==gun_id:gun.drive(self,dt);return
	if garrison_phase!="" and game.building:
		if game.building.drive(self,dt):return
	else:survival_tick()
	# A locally steered unit may leave the grid-centre corridor. Re-anchor the route
	# rather than continuing to push a diagonal across a blocked neighbouring cell.
	if actor and actor.last_blocker=="navigation" and not route.is_empty() and not game.field.segment_walkable(pos(),route[0]):
		route=game.field.path(pos(),goal);route_revision=game.field.revision
	cover_behavior()
	update_firing_awareness()
	monitor_progress(dt)
	var enemy=game.find_target(self,target_id if target_id!="" else focus_id)
	# Explicit attack closes only to weapon range, never walks onto the target.
	if target_id!="":
		if enemy!=null and enemy.id==target_id:route.clear();goal=pos()
		elif pursuit_clock<=0:
			for candidate in game.living():
				if candidate.id==target_id:move_to(candidate.pos())
			pursuit_clock=.7
	pursuit_clock-=dt
	# Consume reached nodes before selecting this tick's animation and velocity.
	# Intermediate nodes are steering targets, never an implicit stop/idle order.
	while not route.is_empty():
		var can_skip: bool=route.size()>1 and game.field.segment_walkable(pos(),route[1],tank)
		var arrival: float=.008 if tank else .002
		if route.size()==1 and not tank:
			var threat=game.closest_enemy(self)
			if cover_id=="" or threat==null or game.field.protection(pos(),threat.pos())>.2:arrival=.012
		if pos().distance_to(route[0])>=(.024 if can_skip else arrival):break
		route.remove_at(0)
	var moving: bool=not route.is_empty()
	update_posture(moving)
	if not moving:reversing=false
	aim_time=0 if moving else aim_time+dt
	if moving:
		var target: Vector2=route[0]
		var base_speed: float=game.config.tank.speed if tank else float(game.config.tactics.get(locomotion+"_speed",game.config.tactics.run_speed))
		if locomotion=="crouch_run":base_speed=game.config.tactics.crouch_speed
		var speed: float=base_speed*(game.config.soldier.speed/.12 if not tank else 1.0)*(1-suppression*.18)*formation_speed
		var direction: Vector2=target-pos()
		var facing: float=atan2(-direction.x,-direction.y)
		reversing=tank and order_mode=="reverse"
		if reversing:facing=wrapf(facing+PI,-PI,PI)
		if tank:
			rotation.y=rotate_toward(rotation.y,facing,game.config.tactics.tank_turn_speed*dt)
			# Pivot the hull before translating; a tank cannot strafe towards a waypoint.
			var aligned_hull: bool=absf(angle_difference(rotation.y,facing))<.35
			var step=pos().move_toward(target,speed*dt if aligned_hull else 0.0);position.x=step.x;position.z=step.y;position.y=game.field.ground_height(step)
		else:
			var lateral=false
			if posture!="prone" and not cover_slot.is_empty() and pos().distance_to(cover_slot.position)<.07 and direction.length()<.055:
				var normal:Vector2=cover_slot.normal
				lateral=absf(direction.normalized().dot(normal))<.20
				if lateral:facing=atan2(-normal.x,-normal.y)
			if not lateral and not actor.stepping:
				# Steer the root-motion direction; never translate a planted cover foot externally.
				for other in game.units:
					if other==self or other.hp<=0:continue
					if not other.tank and route.size()>1 and pos().distance_to(target)<.015:continue
					var apart=pos()-other.pos();var space=.13 if other.tank else .030
					if apart.length()>.001 and apart.length()<space:
						var steered=target+apart.normalized()*(space-apart.length())*.8
						if game.field.segment_walkable(pos(),steered) and game.field.segment_walkable(steered,target):target=steered;direction=target-pos();facing=atan2(-direction.x,-direction.y)
			if not actor.stepping:
				rotation.y=facing;actor.rotation.y=facing+PI
				actor.position.y=game.field.ground_height(pos())
			actor.drive_limit=pos().distance_to(goal)
			actor.acceleration=game.config.tactics.move_acceleration;actor.braking=game.config.tactics.move_braking
			actor.advance_drive(Vector3(target.x,actor.position.y,target.y),speed,dt,lateral,locomotion)
			if lateral:locomotion="cover_step"
			global_position=actor.global_position;actor_advanced=true
		state="move";last_clip="run"
	var close_enemy=game.closest_enemy(self)
	if not tank and close_enemy!=null and not close_enemy.tank and pos().distance_to(close_enemy.pos())<=game.config.weapons.bayonet.range and cooldown<=0 and not (actor and actor.stepping) and game.field.melee_clear(pos(),close_enemy.pos()):
		cooldown=game.config.weapons.bayonet.cooldown;state="melee";melee_until=game.elapsed+.24
		rotation.y=atan2(-(close_enemy.pos()-pos()).x,-(close_enemy.pos()-pos()).y)
		posture="stand";animate("melee");game.fx.launch(self,close_enemy,"bayonet",true);return
	if reload_timer>0:
		reload_timer-=dt;state="reload"
		if not moving:animate("reload")
		if reload_timer<=0:ammo=int(game.config.weapons[weapon].magazine)
		return
	enemy=game.find_target(self,target_id if target_id!="" else focus_id)
	var aligned: bool=turn_weapon(enemy,moving,dt)
	if enemy!=null:
		if cooldown<=0 and aligned and (tank or (not moving and not actor.stepping and aim_time>=.16 and cqb_stance!="hide" and suppression<.95)):
			fire(enemy)
			return
	if not moving:
		state="suppressed" if suppression>.7 else ("cover" if cover_id!="" else ("aim" if enemy!=null else "idle"))
		if game.elapsed<melee_until:animate("melee")
		elif game.elapsed<fire_until:animate("fire")
		else:animate("aim" if enemy!=null else "idle")

func fire(enemy) -> void:
	if deployment_phase!="active" or not is_instance_valid(enemy) or enemy.hp<=0 or enemy.deployment_phase!="active" or enemy.faction==faction:return
	var cfg: Dictionary=weapon_config()
	var chance: float=cfg.accuracy*(1-suppression*.32)
	var landed: bool=game.rng.randf()<chance
	if not game.fx.launch(self,enemy,weapon,landed,cfg):
		cooldown=.35;return
	cooldown=cfg.cooldown
	last_shot_at=game.elapsed;last_shot_target=enemy.id
	game.shots+=1
	if actor:actor.recoil=1.0
	# The projectile retains this shot's current designer-adjusted values.
	if not game.fx.projectiles.is_empty():game.fx.projectiles[-1].cfg=cfg
	state="fire";animate("fire");fire_until=game.elapsed+.22
	if not tank:
		ammo-=1
		if ammo<=0:
			reload_timer=cfg.reload;game.fx.sound("reload",position,-7)

func snapshot_engagement(enemy, queries: Dictionary) -> bool:
	return COMBAT_AWARENESS.snapshot_engagement(self,enemy,queries)

func snapshot(queries: Dictionary={}) -> Dictionary:
	var combat: Dictionary={"firing_awareness":firing_awareness,"fire_block_reason":get_meta("fire_block_reason",""),"flag_hint":game.tactics_ai.flag_hint(self) if game.control[faction]=="lm" and game.tactics_ai and deployment_phase=="active" else {},"engageable_targets":[],"incoming_threats":[],"path_active":not route.is_empty()}
	if game.control[faction]=="lm" and hp>0:
		for enemy in game.living():
			if enemy.faction==faction:continue
			var distance: float=pos().distance_to(enemy.pos())
			if distance<weapon_config().range and snapshot_engagement(enemy,queries):combat.engageable_targets.append(enemy.id)
			if distance<enemy.weapon_config().range and enemy.snapshot_engagement(self,queries):combat.incoming_threats.append(enemy.id)
	return {"emotion":emotion if hp>0 and game.elapsed<emotion_until else "","emotion_until":emotion_until,"deployment_phase":deployment_phase,"combat_ready":deployment_phase=="active","combat":combat,"gun_id":gun_id,"building_phase":garrison_phase,"building_floor":garrison_floor,"elevation":position.y-game.field.height,"lm_intent":lm_intent,"lm_reason":lm_reason,"path_repairs":path_repairs,"path_failure":path_failure,"posture":posture,"locomotion":locomotion,"weapon_state":weapon_state,"posture_order":posture_order,"survival_reason":safety_reason if game.elapsed<safety_until else "","last_shot_at":last_shot_at,"last_shot_target":last_shot_target,"action_counts":action_counts,"id":id,"faction":faction,"kind":"tank" if tank else "infantry","position":[position.x,position.z],"hp":snappedf(hp,.1),"max_hp":max_hp,"state":state,"cover_id":cover_id,"suppression":snappedf(suppression,.01),"ammo":ammo,"selected":selected,"goal":[goal.x,goal.y],"animation":last_clip,"bone_count":bone_count,"weapon":weapon,"weapon_name":game.config.weapons[weapon].name,"reload_remaining":snappedf(reload_timer,.1),"weapon_range":game.config.weapons[weapon].range,"melee_ready":not tank and cooldown<=0,"tactical_role":tactical_role,"order_mode":order_mode,"cqb_stance":cqb_stance,"in_cover":in_cover(),"cover_slot":cover_slot.get("key",""),"cover_risk":cover_slot.get("risk",0),"focus_id":focus_id,"reversing":reversing,"turret_yaw":turret.rotation.y if turret else 0.0,"formation_speed":formation_speed,"grenades":grenade_count,"available_actions":available_actions(),"asset_animation":actor.clip if actor else track_clip,"root_distance":actor.roots_travelled if actor else 0,"movement_speed":actor.actual_speed if actor else 0,"animation_rate":actor.root_speed if actor else 0,"ground_correction":actor.ground_correction if actor else 0,"cover_step":actor.stepping if actor else false,"contact_slip_max":actor.contact_slip_max if actor else 0}

func presentation_tick(dt:float) -> void:
	UNIT_PRESENTATION.tick(self,dt)

func can_throw(enemy) -> bool:
	return not tank and hp>0 and grenade_count>0 and grenade_time<0 and enemy!=null and pos().distance_to(enemy.pos())<=game.config.weapons.grenade.range and not actor.stepping and reload_timer<=0 and suppression<.8

func available_actions() -> Array:
	if deployment_phase!="active":return []
	if hp<=0:return []
	if gun_id!="":return ["hold","leave_gun","cover","retreat"]
	if garrison_phase!="":return ["hold","leave_building","cover","retreat"]
	var actions: Array=["move","capture","cover","retreat","hold","attack"]
	if not tank:
		actions.append("flank")
		if game.at_guns.any(func(g):return g.eligible(self) and g.enemy_tank()!=null):actions.append("man_at_gun")
		if faction=="blue" and game.building and not game.building.collapsed:actions.append("garrison")
	if not tank:
		if grenade_time<0 and not actor.stepping:actions.append("posture")
		if can_throw(game.closest_enemy(self)):actions.append("grenade")
	return actions

func request_grenade(enemy) -> bool:
	if not can_throw(enemy):return false
	posture="stand";posture_since=game.elapsed
	grenade_count-=1;grenade_time=0;grenade_released=false;grenade_target=enemy
	route.clear();goal=pos();state="grenade"
	var delta=enemy.pos()-pos();rotation.y=atan2(-delta.x,-delta.y)
	actor.play("grenade_throw");cooldown=1.3
	return true

func equip(value:String) -> void:
	if tank or value not in ["rifle","smg","rocket","pistol"]:return
	weapon=value;ammo=int(game.config.weapons[value].magazine);reload_timer=0
	tactical_role={"rifle":"overwatch","smg":"assault","rocket":"anti_armor","pistol":"assault"}[value]
	actor.weapon.queue_free();actor.weapon_mode="rifle" if value=="smg" else value
	actor.weapon=load("res://assets/models/"+actor.weapon_mode+".glb").instantiate();actor.add_child(actor.weapon)
	for part in actor.weapon.find_children("*","MeshInstance3D",true,false):part.material_override=game.field.mat(game.colors[faction],.32)
	actor.update_weapon()
	last_clip=""

func presentation_pause(value:bool) -> void:
	UNIT_PRESENTATION.pause(self,value)
