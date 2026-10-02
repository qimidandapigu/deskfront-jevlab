extends Node3D
const MortarPresentation=preload("res://scripts/mortar_presentation.gd")
## A crew-served indirect weapon in the same encounter as the tank.
const COOLDOWN:float=10.0
const SINGLE_CREW_COOLDOWN:float=14.0
const RANGE:float=3.2
const SETUP_SECONDS:float=4.0
const SINGLE_SETUP_SECONDS:float=5.5
const MODEL_SCALE:float=.68
const TURN_SPEED:float=PI/2.0
const INTEL_SECONDS:float=12.0
const CAPTURE_RADIUS:float=.24
const CAPTURE_SECONDS:float=3.0
class AimMarker:
	extends RefCounted
	var point:Vector3
	func _init(value:Vector3):point=value
	func aim_point()->Vector3:return point
var game
var id:String="battlefield-mortar-1"
var faction:String="red"
var initial_owner:String="red"
var deployment_phase:String="active"
var capture_team:String=""
var capture_progress:float=0.0
var capture_ids:Array=[]
var capture_count:int=0
var revealed_to:Array=[]
var team_material:StandardMaterial3D
var tank:bool=false
var hp:float=85.0
var phase:String="setting_up"
var crew_id:String=""
var crew_ids:Array=[]
var gunner_id:String=""
var guard_id:String=""
var handoff_until:float=0.0
var suppression:float=0.0
var next_shot_at:float=0.0
var last_target_id:String=""
var last_block_reason:String=""
var shots:int=0
var work_until:float=0.0
var known_target_id:String=""
var known_point:Vector3=Vector3.ZERO
var known_source:String="stage_intel"
var intel_until:float=0.0
var intel_used:bool=false
var next_target_check:float=0.0
var yaw:float=0.0
var desired_yaw:float=0.0
var elevation:float=-.50
var desired_elevation:float=-.50
var target_available:bool=false
var proxy:Dictionary={}
var visual:Node3D
var base_root:Node3D
var tube:MeshInstance3D
var tube_rest:Vector3
var recoil:float=0.0
const MUZZLE_LOCAL=MortarPresentation.MUZZLE_LOCAL
var muzzle_marker:Node3D
var visual_kit:Dictionary={}
var auto_capture_id:String=""
var auto_capture_goal:Vector2=Vector2.ZERO
var auto_capture_order:String=""

func part(mesh:Mesh,pos3:Vector3,color:Material,tilt:float=0.0)->MeshInstance3D:
	var item=MeshInstance3D.new();item.mesh=mesh;item.material_override=color
	item.position=pos3;item.rotation.x=tilt;visual.add_child(item);return item

func setup(g,point:Vector2,announced_tank,owner:String="red") -> void:
	game=g;faction=owner;initial_owner=owner
	# Use the same faceted mesh and faction material as the game units.
	base_root=Node3D.new();add_child(base_root);base_root.scale=Vector3.ONE*MODEL_SCALE
	team_material=game.field.mat(game.colors[faction],.32)
	# Keep the ground plate fixed and let only the traverse receive yaw. The
	# presentation kit provides a readable V bipod, light tube, hand wheel and
	# attachment points without changing any combat authority.
	visual_kit=MortarPresentation.build(game,faction,base_root)
	visual=visual_kit.traverse
	tube=visual_kit.tube;tube_rest=tube.position;muzzle_marker=visual_kit.muzzle
	var label=Label3D.new();add_child(label)
	label.text="迫击炮组";label.font_size=17;label.pixel_size=.0008
	label.position=Vector3(0,.12,0);label.billboard=BaseMaterial3D.BILLBOARD_ENABLED
	label.modulate=Color(.58,1,.68);label.name="StatusLabel"
	proxy={"id":id,"position":[point.x,point.y],"size":[.08,.08],"normal":[0,1],"height":.04,"bottom":game.field.height,"hp":hp,"max_hp":hp,"damage_stage":"intact","kind":"gun","alive":true,"node":self,"nav_block":false,"no_slots":true}
	game.field.covers.append(proxy);game.field.harness_index_covers()
	game.at_guns.append(self)
	redeploy(point,announced_tank)

func crew_point(index:int)->Vector2:
	# Keep the two crew members tied to the rendered anchors.  The old
	# hand-written offsets were only approximately behind the tube; after the
	# mortar traversed, the soldiers could drift into a small clump beside the
	# base.  The presentation kit is deliberately the source of this visual
	# placement, while navigation still owns the final walkable-cell snap.
	var anchor_name:String="gunner_anchor" if index==0 else "guard_anchor"
	var anchor=visual_kit.get(anchor_name,null)
	if anchor!=null and is_instance_valid(anchor):
		var anchored:=Vector2(anchor.global_position.x,anchor.global_position.z)
		return game.field.to_world(game.field.nearest(anchored))
	var forward:Vector2=Vector2(known_point.x,known_point.z)-pos()
	if forward.length_squared()<.001:forward=Vector2(0,-1)
	forward=forward.normalized();var side:Vector2=Vector2(-forward.y,forward.x)
	var wanted:Vector2=pos()-forward*(.085 if index==0 else .035)+side*(-.045 if index==0 else .105)
	return game.field.to_world(game.field.nearest(wanted))

func bind_crew(members:Array,deployment:bool=false)->void:
	crew_ids.clear()
	gunner_id="";guard_id="";handoff_until=0.0
	for i in range(members.size()):
		var u=members[i]
		var sid:String=game.human_squads.owners.get(u.id,"")
		if game.human_squads.squads.has(sid):
			var squad:Dictionary=game.human_squads.squads[sid]
			game.human_squads.intent_executor.cancel_motion(u,"equipment_claimed",game.elapsed,str(squad.order_id))
			game.human_squads.intent_executor.cancel_posture(u,"equipment_claimed",game.elapsed)
			squad.unit_ids.erase(u.id)
			for key in ["personal","assignments","destinations","rally_destinations"]:
				if squad.has(key):squad[key].erase(u.id)
			if squad.get("mover","")==u.id:squad.mover=""
			if squad.has("support_ids"):squad.support_ids.erase(u.id)
			game.human_squads.owners.erase(u.id)
		if game.tactics_ai.formations.has(u.faction):game.tactics_ai.formations[u.faction].ids.erase(u.id)
		crew_ids.append(u.id);u.gun_id=id if i==0 else "";u.route.clear();u.goal=crew_point(i)
		u.remove_meta("harness_mortar_capture_id")
		game.field.release(u.id);u.cover_id="";u.cover_slot={}
		if deployment:
			u.position=Vector3(u.goal.x,game.field.height,u.goal.y)
			u.actor.global_position=u.global_position
		else:
			# Serving a claimed team weapon uses the native facility locomotion path.
			# Existing soldiers walk the short final approach; capture never teleports them.
			u.route=game.field.path_around_units(u.pos(),u.goal,game.at_guns.filter(func(g):return g.hp>0))
			if u.route.is_empty():u.goal=u.pos()
		u.weapon_state="crew_setting_up";u.target_id=""
		if i==0:
			gunner_id=u.id;u.order_mode="operate_mortar";u.posture_order="crouch";u.posture="crouch"
			MortarPresentation.pose_gunner(u,self,visual_kit)
		else:
			guard_id=u.id;u.order_mode="mortar_guard";u.posture_order="stand";u.posture="stand"
			MortarPresentation.pose_guard(u,self,visual_kit)
	crew_id=gunner_id

func assign_enemy_crew()->void:
	var members:Array=[]
	for i in range(2):
		var u=game.spawn_unit("red-mortar-crew-%d"%game.units.size(),"red",crew_point(i))
		u.equip("rifle");members.append(u)
	bind_crew(members,true)

func redeploy(point:Vector2,announced_tank) -> void:
	if not crew_ids.is_empty():release("关卡交接")
	position=Vector3(point.x,game.field.height,point.y)
	faction=initial_owner;capture_team="";capture_progress=0.0;capture_ids.clear();revealed_to.clear()
	known_target_id=announced_tank.id if announced_tank.faction!=faction else ""
	known_point=announced_tank.aim_point();known_source="stage_intel" if known_target_id!="" else "none"
	intel_until=game.elapsed+INTEL_SECONDS;intel_used=false;target_available=known_target_id!=""
	next_target_check=0.0;next_shot_at=game.elapsed+SETUP_SECONDS
	set_elevation(-.50)
	var direction:Vector2=Vector2(known_point.x,known_point.z)-pos()
	yaw=atan2(-direction.x,-direction.y);desired_yaw=yaw;visual.rotation.y=yaw;recoil=0.0
	last_target_id="";last_block_reason="";phase="setting_up"
	work_until=game.elapsed+SETUP_SECONDS
	if not proxy.is_empty():
		proxy.position=[point.x,point.y];proxy.hp=85.0;proxy.alive=true
		hp=85.0;game.field.harness_index_covers()
	if faction=="red":assign_enemy_crew()
	else:
		# Explicit green fixtures may use existing soldiers; live deployment is red.
		bind_crew(game.living(faction).filter(func(u):return not u.tank and u.weapon!="rocket" and u.gun_id=="").slice(0,2),true)
	update_color()
	update_label()

func update_color()->void:
	team_material.albedo_color=game.colors[faction] if game.colors.has(faction) else Color(.43,.45,.40)
	get_node("StatusLabel").modulate=Color(.58,1,.68) if faction=="green" else Color(1,.55,.42) if faction=="red" else Color(.95,.86,.55)

func capture_eligible(u)->bool:
	return hp>0 and u.hp>0 and not u.tank and u.gun_id=="" and u.weapon!="rocket" and u.deployment_phase=="active" and u.suppression<.5 and game.elapsed>=u.safety_until and u.grenade_time<0 and u.garrison_phase=="" and u.pos().distance_to(pos())<=CAPTURE_RADIUS

func capture_tick(dt:float)->void:
	var nearby:Array=game.living().filter(func(u):return capture_eligible(u))
	var team:String=""
	for candidate in ["green","red"]:
		if nearby.filter(func(u):return u.faction==candidate).size()>=1:
			if game.living().any(func(u):return u.faction!=candidate and u.pos().distance_to(pos())<.40):continue
			team=candidate;break
	if team=="":capture_team="";capture_ids.clear();capture_progress=0.0;phase="abandoned";update_label();return
	var members:Array=nearby.filter(func(u):return u.faction==team)
	members.sort_custom(func(a,b):return a.id<b.id);members=members.slice(0,1)
	var ids:Array=members.map(func(u):return u.id)
	if capture_team!=team or ids!=capture_ids:capture_team=team;capture_ids=ids;capture_progress=0.0
	capture_progress+=dt;phase="capturing";update_label()
	if capture_progress<CAPTURE_SECONDS:return
	faction=team;capture_count+=1;bind_crew(members)
	known_target_id="";known_source="none";target_available=false;next_target_check=0.0
	next_shot_at=game.elapsed+SETUP_SECONDS;work_until=next_shot_at;phase="setting_up"
	capture_team="";capture_ids.clear();capture_progress=0.0;update_color();update_label()
	game.control_epochs[team]+=1
	game.add_event(("我方" if team=="green" else "敌方")+"夺取迫击炮：一名现有士兵即可接管，炮架损伤保留")

func pos() -> Vector2:return Vector2(position.x,position.z)
func muzzle_position(_target:Vector3) -> Vector3:return muzzle_marker.global_position if muzzle_marker else visual.to_global(MUZZLE_LOCAL)

func is_mortar_target()->bool:return true
func aim_point()->Vector3:return global_position+Vector3.UP*.06
func hit(amount:float, pressure:float, origin:Vector3=Vector3.INF, impulse:float=.12)->void:
	if hp<=0:return
	hp=maxf(0.0,hp-amount)
	suppression=minf(1.0,suppression+pressure)
	if not proxy.is_empty():proxy.hp=hp
	if hp<=0:
		if not proxy.is_empty():proxy.alive=false
		phase="destroyed"
		update_label()
		game.add_event("迫击炮架被摧毁：炮组失去火力")
	else:update_label()

func guide_capture()->void:
	if faction!="neutral" or hp<=0:return
	var candidate=null
	if auto_capture_id!="":
		for u in game.living("green"):
			if u.id==auto_capture_id and u.weapon!="rocket" and not u.tank:
				candidate=u;break
	if candidate==null or candidate.pos().distance_to(pos())>.42:
		var options:Array=game.living("green").filter(func(u):return not u.tank and u.weapon!="rocket" and u.gun_id=="" and u.suppression<.65 and game.elapsed>=u.safety_until and u.grenade_time<0)
		options.sort_custom(func(a,b):return a.pos().distance_to(pos())<b.pos().distance_to(pos()))
		candidate=options[0] if not options.is_empty() else null
		if candidate==null:
			auto_capture_id=""
			auto_capture_goal=Vector2.ZERO
			return
		if candidate!=null:
			auto_capture_id=candidate.id
			auto_capture_order="mortar_capture_%s_%d"%[id,int(game.elapsed*10)]
			if game.human_squads:
				game.human_squads.intent_executor.cancel_motion(candidate,"mortar_capture",game.elapsed)
				game.human_squads.intent_executor.cancel_posture(candidate,"mortar_capture",game.elapsed)
		var approach:Vector2=pos()
		var away:Vector2=(candidate.pos()-pos()).normalized()
		if away.length_squared()<.001:away=Vector2(-1,0)
		approach=pos()+away*.13
		approach=game.field.to_world(game.field.nearest(approach))
		auto_capture_goal=approach
		candidate.set_meta("harness_mortar_capture_id",id)
		candidate.order_mode="mortar_capture"
		candidate.target_id="";candidate.focus_id=""
		candidate.posture_order="crouch"
		candidate.goal=approach
		candidate.route=game.field.path_around_units(candidate.pos(),approach,game.living().filter(func(v):return v!=candidate and v.tank))
		candidate.route_revision=game.field.revision
		if candidate.route.is_empty() and candidate.pos().distance_to(approach)>.04:candidate.move_to(approach)
	if candidate!=null and candidate.pos().distance_to(pos())<=CAPTURE_RADIUS:
		candidate.goal=candidate.pos();candidate.route.clear()

func set_elevation(angle:float)->void:
	desired_elevation=clampf(angle,-1.25,-.25)
	elevation=desired_elevation
	var assembly:Node3D=visual_kit.get("tube_assembly",null)
	if assembly!=null:
		# Meshes in the presentation kit carry the neutral BARREL_TILT;
		# the assembly supplies only the per-shot elevation correction.
		assembly.rotation.x=desired_elevation-MortarPresentation.BARREL_TILT
func enemy_tank():
	for u in game.living():
		if u.id==known_target_id and u.tank:return u
	return null

# Use the shared perception snapshot for selection; recheck sight at launch.
# Initial deployment intelligence authorizes only one shell within 12 seconds.
func update_target()->void:
	target_available=false
	var contacts:Dictionary=game.human_squads.perception.get(faction,{})
	var selected=null;var score:float=-INF
	for enemy in game.living():
		if enemy.faction==faction or enemy.deployment_phase!="active":continue
		if not bool(contacts.get(enemy.id,{}).get("visible",false)):continue
		var distance:float=pos().distance_to(enemy.pos())
		if distance<.90 or distance>RANGE:continue
		if game.living(faction).any(func(ally):return ally.pos().distance_to(enemy.pos())<.31):continue
		var priority:float=(1.0 if enemy.tank else 0.0)-distance*.1
		if enemy.id==known_target_id:priority+=.2
		if priority>score:selected=enemy;score=priority
	if selected!=null:
		known_target_id=selected.id;known_point=selected.aim_point();known_source="spotted"
		target_available=true
	elif known_source=="stage_intel" and not intel_used and game.elapsed<=intel_until and enemy_tank()!=null:
		target_available=true
	if target_available:
		var direction:Vector2=Vector2(known_point.x,known_point.z)-pos()
		desired_yaw=atan2(-direction.x,-direction.y)

func face_crew(u)->void:
	var direction:Vector2=pos()-u.pos()
	u.rotation.y=atan2(-direction.x,-direction.y);u.actor.rotation.y=u.rotation.y+PI

func face_guard(u)->void:
	var direction:Vector2=Vector2(known_point.x,known_point.z)-u.pos()
	if direction.length_squared()<.001:direction=pos()-u.pos()
	u.rotation.y=atan2(-direction.x,-direction.y);u.actor.rotation.y=u.rotation.y+PI

func promote_guard(u)->void:
	gunner_id=u.id;guard_id="";crew_id=gunner_id;handoff_until=game.elapsed+SINGLE_SETUP_SECONDS
	u.gun_id=id;u.order_mode="operate_mortar";u.posture_order="crouch";u.posture="crouch"
	u.route.clear();u.goal=crew_point(0);MortarPresentation.pose_gunner(u,self,visual_kit)
	next_shot_at=maxf(next_shot_at,handoff_until);work_until=handoff_until
	game.add_event("迫击炮操作手倒下：警戒兵接替炮位，单人操作精度下降")

func update_label()->void:
	if not has_node("StatusLabel"):return
	var status:String={"setting_up":"架设","single_operator":"单人操作 · 精度下降","suppressed":"受压制","decrewed":"缺炮手","destroyed":"损毁","abandoned":"可夺取 · 需一人","waiting_target":"待目标","aiming":"转向","capturing":"接管 %d%%"%int(100*capture_progress/CAPTURE_SECONDS)}.get(phase,"装填" if game.elapsed<next_shot_at else "就绪")
	get_node("StatusLabel").text=("敌方" if faction=="red" else "我方" if faction=="green" else "无人")+"迫击炮 · "+status
func eligible(_u)->bool:return false
func claim(_u)->bool:return false
func release(_reason:String)->void:
	for u in game.living(faction):
		if u.id in crew_ids:
			u.gun_id="";u.order_mode="hold";u.posture_order="auto"
			u.route.clear();u.goal=u.pos();u.actor.weapon.show()
	crew_ids.clear();crew_id="";gunner_id="";guard_id="";handoff_until=0.0;phase="abandoned"
	faction="neutral";known_target_id="";known_source="none";target_available=false
	auto_capture_id="";auto_capture_goal=Vector2.ZERO;auto_capture_order=""
	update_color()
	update_label()
func drive(u,dt:float)->void:
	if u.id!=gunner_id:return
	u.order_mode="operate_mortar"
	if not u.route.is_empty():
		var point:Vector2=u.route[0]
		if u.pos().distance_to(point)<.025:u.route.remove_at(0)
		else:
			var direction:Vector2=point-u.pos();u.rotation.y=atan2(-direction.x,-direction.y);u.actor.rotation.y=u.rotation.y+PI
			u.actor.advance_drive(Vector3(point.x,u.position.y,point.y),game.config.tactics.run_speed,dt,false,"crouch_run")
			u.global_position=u.actor.global_position;u.actor_advanced=true;u.locomotion="crouch_run";u.posture="crouch";return
	u.goal=u.pos()
	u.posture="crouch";u.locomotion="idle";u.weapon_state="crew_reload" if game.elapsed<next_shot_at else "crew_ready"
	face_crew(u);u.target_id=""
	MortarPresentation.pose_gunner(u,self,visual_kit)
func pose_crew(u)->void:
	if u.id==gunner_id:
		MortarPresentation.pose_gunner(u,self,visual_kit)
	else: MortarPresentation.pose_guard(u,self,visual_kit)

func payload() -> Dictionary:
	var cfg:Dictionary=game.config.weapons.grenade.duplicate(true)
	# Heavy indirect fire pass: keep the mortar's existing armor and splash
	# rules, but double the authoritative projectile payload.
	cfg.damage=72.0;cfg.accuracy=.84;cfg.projectile_speed=.75
	cfg.armor_multiplier=.55;cfg.splash=.25;cfg.pressure=.8;cfg.cover_damage=60.0
	cfg.harness_mortar=true;cfg.harness_arc_height=.72
	if guard_id=="":
		cfg.accuracy=.64;cfg.projectile_speed=.66;cfg.harness_single_crew=true
	return cfg

func tick(dt:float) -> void:
	if game.paused or game.winner!="":return
	if not proxy.is_empty():hp=float(proxy.hp)
	if hp<=0 or not bool(proxy.get("alive",true)):
		if phase!="destroyed":release("炮架被摧毁");phase="destroyed";update_label()
		return
	var crew:Array=game.living(faction).filter(func(u):return u.id in crew_ids)
	if crew.is_empty():
		if faction!="neutral":release("炮手全部失去战斗力");game.add_event("敌我炮手离场：迫击炮留在原地，可由一名士兵夺取")
		guide_capture()
		capture_tick(dt);return
	var gunner=null
	for candidate in game.units:
		if candidate.id==gunner_id and candidate.hp>0:gunner=candidate;break
	var guard=null
	for candidate in game.units:
		if candidate.id==guard_id and candidate.hp>0:guard=candidate;break
	if gunner==null and guard!=null:promote_guard(guard);gunner=guard;guard=null
	if gunner==null:
		if crew.size()>0:promote_guard(crew[0]);gunner=crew[0]
		else:
			release("炮手全部失去战斗力");game.add_event("敌我炮手离场：迫击炮留在原地，可由一名士兵夺取");capture_tick(dt);return
	if guard==null:guard_id=""
	var single_crew:bool=guard==null
	phase="single_operator" if single_crew else "setting_up"
	if guard!=null and not guard.route.is_empty():guard.order_mode="mortar_guard"
	if not gunner.route.is_empty():phase="setting_up"
	if crew.any(func(u):return u.suppression>=.7 or u.hp/u.max_hp<.3 or game.elapsed<u.safety_until):
		phase="suppressed";update_label();return
	if game.elapsed>=next_target_check:
		update_target();next_target_check=game.elapsed+.25
	var turn:float=wrapf(desired_yaw-yaw,-PI,PI)
	yaw=wrapf(yaw+clampf(turn,-TURN_SPEED*dt,TURN_SPEED*dt),-PI,PI)
	visual.rotation.y=yaw
	recoil=move_toward(recoil,0.0,dt*5.0)
	tube.position=tube_rest+Vector3(0,-.008,.005)*recoil
	if not target_available:phase="waiting_target";update_label();return
	if absf(wrapf(desired_yaw-yaw,-PI,PI))>.06:phase="aiming";update_label();return
	if game.elapsed<next_shot_at:
		phase="setting_up" if last_target_id=="" and game.elapsed<work_until else "ready"
		update_label();return
	phase="ready"
	# The contact may have moved or disappeared during traverse / reload.
	var target=null
	for enemy in game.living():
		if enemy.id==known_target_id:target=enemy;break
	if target==null:target_available=false;next_target_check=0.0;return
	if known_source=="spotted":
		if not game.human_squads.visible_to(faction,target):
			target_available=false;phase="waiting_target";next_target_check=0.0;update_label();return
		known_point=target.aim_point()
		var direction:Vector2=Vector2(known_point.x,known_point.z)-pos()
		desired_yaw=atan2(-direction.x,-direction.y)
		if absf(wrapf(desired_yaw-yaw,-PI,PI))>.06:phase="aiming";update_label();return
	elif intel_used or game.elapsed>intel_until:
		target_available=false;phase="waiting_target";update_label();return
	var aim:Vector2=Vector2(known_point.x,known_point.z)
	var distance:float=pos().distance_to(aim)
	if distance<.90 or distance>RANGE:return
	if game.living(faction).any(func(ally):return ally.pos().distance_to(aim)<.31):return
	# Match the rendered tube axis to the first derivative of the same high
	# arc used by CombatFX.  Scatter changes the impact point, so this uses
	# the nominal observed point and the round's bounded accuracy cone.
	var shot_payload:Dictionary=payload()
	var muzzle_flat:Vector2=Vector2(muzzle_position(known_point).x,muzzle_position(known_point).z)
	# The tube's local +Y axis is pitched around X, so its rotation is the
	# complement of the world elevation angle used by the projectile tangent.
	set_elevation(-atan2(maxf(muzzle_flat.distance_to(aim),.05),PI*float(shot_payload.get("harness_arc_height",.72))))
	# Physical admission still checks cover and friendly blast risk.
	if not game.fx.launch(self,AimMarker.new(known_point),"grenade",true,shot_payload):
		last_block_reason=str(get_meta("fire_block_reason",""))
		next_shot_at=game.elapsed+1.0
		return
	shots+=1;last_target_id=target.id;last_block_reason=""
	recoil=1.0
	if target.faction not in revealed_to:
		revealed_to.append(target.faction)
		game.add_event("迫击炮开火暴露炮位：%s 可以组织消灭炮手并夺取装备"%target.faction)
	if known_source=="stage_intel":intel_used=true;target_available=false
	next_shot_at=game.elapsed+(SINGLE_CREW_COOLDOWN if single_crew else COOLDOWN)
	work_until=game.elapsed+1.2
	update_label()
	for u in crew:u.fire_until=game.elapsed+.35
	game.add_event("迫击炮%s向%s的%s位置开火，装填 %d 秒"%["单人操作" if single_crew else "组" ,target.id,"已目视" if known_source=="spotted" else "部署情报",int(SINGLE_CREW_COOLDOWN if single_crew else COOLDOWN)])

func snapshot() -> Dictionary:
	var seen_by:Array=[]
	for team in ["green","red"]:
		if faction==team or team in revealed_to or game.living(team).any(func(u):return u.pos().distance_to(pos())<=float(game.config.get("human_vision_range",1.2)) and game.field.line_of_sight(u.pos(),pos())):seen_by.append(team)
	return {"kind":"mortar","id":id,"faction":faction,"initial_owner":initial_owner,"seen_by":seen_by,"capture_team":capture_team,"capture_progress":minf(1.0,capture_progress/CAPTURE_SECONDS),"capture_radius":CAPTURE_RADIUS,"capture_seconds":CAPTURE_SECONDS,"required_crew":1,"crew_required_to_fire":1,"capture_required_crew":1,"capture_count":capture_count,"capturable":faction=="neutral" and hp>0,"position":[position.x,position.z],"hp":hp,"phase":phase,"crew_id":crew_id,"gunner_id":gunner_id,"guard_id":guard_id,"crew_ids":crew_ids.duplicate(),"crew_alive":game.living(faction).filter(func(u):return u.id in crew_ids).size(),"fire_mode":"single_operator" if guard_id=="" else "crew_served","single_crew_penalty":{"accuracy":.64,"cooldown":SINGLE_CREW_COOLDOWN} if guard_id=="" else {},"ammunition_policy":"unlimited_reserve","model_scale":MODEL_SCALE,"staging_role":"rear_support","yaw":yaw,"desired_yaw":desired_yaw,"elevation":elevation,"desired_elevation":desired_elevation,"target_available":target_available,"shots":shots,"known_target_id":known_target_id,"known_position":[known_point.x,known_point.z],"known_source":known_source,"last_target_id":last_target_id,"last_block_reason":last_block_reason,"next_shot_in":maxf(0.0,next_shot_at-game.elapsed)}
