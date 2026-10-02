extends Node3D
## One autonomous crew member; a swept carriage footprint and root-driven hauling.
var game
var tank:bool=true
var collider:StaticBody3D
var id:String
var faction:String
var hp:float=180
var crew_id:String=""
var phase:String="parked"
var reason:String=""
var target_id:String=""
var destination:=Vector2.ZERO
var yaw:float=0
var cooldown:float=0
var deploy_time:float=0
var distance_pushed:float=0
var shots:int=0
var crew
var visual:Node3D
var proxy:Dictionary
var retry_at:float=0
var stalled:float=0
var last_crew_pos:=Vector2.INF
const AIM_DOT_THRESHOLD:float=.97

func setup(g,s:Dictionary):
	set_meta("nav_radius",.095)
	game=g;id=s.id;faction=s.faction;hp=game.config.equipment.gun_health
	position=Vector3(s.position[0],game.field.height,s.position[1]);destination=pos()
	visual=load("res://assets/models/antitank-gun.glb").instantiate();add_child(visual);visual.scale=Vector3.ONE*game.config.equipment.gun_scale
	for mesh in visual.find_children("*","MeshInstance3D",true,false):mesh.material_override=game.field.mat(game.colors[faction],.32)
	proxy={"id":id,"position":[position.x,position.z],"size":[.14,.14],"normal":[0,1],"height":.085,"bottom":position.y,"hp":hp,"max_hp":hp,"damage_stage":"intact","kind":"gun","alive":true,"node":visual,"nav_block":false,"no_slots":true}
	collider=StaticBody3D.new();add_child(collider);collider.collision_layer=1
	var shape=BoxShape3D.new();shape.size=Vector3(.13,.07,.13)
	var col=CollisionShape3D.new();col.shape=shape;col.position.y=.035;collider.add_child(col)
	game.field.covers.append(proxy)

func pos()->Vector2:return Vector2(position.x,position.z)
func forward()->Vector2:return Vector2(-sin(yaw),-cos(yaw))
func handle()->Vector2:return pos()-forward()*.115
func muzzle_position(_target:Vector3)->Vector3:return global_position+Vector3(forward().x*.13,.07,forward().y*.13)
func enemy_tank():
	var result=null;var nearest:float=INF
	for u in game.living():
		if u.faction==faction or not u.tank:continue
		var d:float=u.pos().distance_to(pos())
		if d<nearest:result=u;nearest=d
	return result
func eligible(u)->bool:
	return hp>0 and proxy.alive and crew_id=="" and not u.tank and u.faction==faction and u.weapon!="rocket" and u.hp/u.max_hp>=.65 and u.suppression<.35 and game.elapsed>=u.safety_until and u.garrison_phase=="" and game.elapsed>=retry_at and u.pos().distance_to(pos())<1.2
func safe_route(u,route:PackedVector2Array)->bool:
	if route.is_empty() or game.field.route_length(route)>1.3:return false
	for enemy in game.living():
		if enemy.faction==faction:continue
		for p in route:
			if p.distance_to(enemy.pos())<(.48 if enemy.tank else .23) and game.field.line_of_sight(enemy.pos(),p):return false
	return true
func claim(u)->bool:
	if crew_id==u.id:return true
	if not eligible(u):return false
	var enemy=enemy_tank()
	if enemy==null:return false
	var delta:Vector2=enemy.pos()-pos();yaw=atan2(-delta.x,-delta.y);rotation.y=yaw
	var path:PackedVector2Array=game.field.path_around_units(u.pos(),handle(),game.at_guns.filter(func(g):return g.hp>0))
	if not game.field.walkable(handle()) or not safe_route(u,path):return false
	# Choose a reachable short bound; later decisions can move the gun again.
	destination=pos()
	for step in [.32,.22,.12]:
		var p:Vector2=pos()+forward()*step
		if p.distance_to(enemy.pos())<game.config.equipment.gun_min_range:continue
		if not game.field.segment_walkable(pos(),p,true) or not game.field.segment_walkable(handle(),p-forward()*.115):continue
		if not safe_route(u,PackedVector2Array([pos(),p])):continue
		destination=p;break
	stalled=0;last_crew_pos=u.pos();crew=u;crew_id=u.id;u.gun_id=id;u.route=path;u.goal=handle();u.cover_id="";u.cover_slot={};game.field.release(u.id);u.target_id="";u.order_mode="man_at_gun"
	phase="approaching";reason="接近炮尾，先就位再推炮";return true
func release(why:String):
	if is_instance_valid(crew):
		crew.gun_id="";crew.actor.weapon.show();crew.route.clear();crew.goal=crew.pos();crew.order_mode="hold"
	crew_id="";crew=null;phase="abandoned" if hp>0 else "destroyed";reason=why;retry_at=game.elapsed+12
func tick(dt:float):
	hp=float(proxy.hp)
	if not proxy.alive:
		collider.collision_layer=0
		if crew_id!="":release("炮架被摧毁")
		phase="destroyed";return
	cooldown=maxf(0,cooldown-dt)
	if crew_id=="":return
	if not is_instance_valid(crew) or crew.hp<=0:release("炮手失去战斗力");return
	var danger=game.closest_enemy(crew)
	if crew.hp/crew.max_hp<game.config.equipment.crew_abort_hp or crew.suppression>game.config.equipment.crew_abort_pressure or (danger!=null and danger.pos().distance_to(crew.pos())<.23):
		var survivor=crew;release("炮组受威胁，放弃火炮保命");survivor.reaction_at=0;survivor.safety_until=game.elapsed+3;survivor.safety_reason="crew_evacuate";survivor.seek_cover(danger.pos() if danger!=null else game.objective,survivor.pos(),{"survival":true,"max_travel":.4});survivor.order_mode="self_preserve";return
	if phase=="ready":
		var target=enemy_tank()
		if target==null:return
		target_id=target.id
		var delta:Vector2=target.pos()-pos();var distance:float=delta.length()
		# Carriage is fixed after deployment; reposition/recrew for another firing arc.
		# A team weapon cannot fire through a sideways carriage.  The old .8
		# gate allowed roughly 37 degrees of visual/ballistic mismatch.
		if forward().dot(delta.normalized())<AIM_DOT_THRESHOLD or distance>game.config.weapons.at_cannon.range:
			release("目标离开射界，需要重新牵引部署");return
		if cooldown<=0 and distance>=game.config.equipment.gun_min_range and distance<=game.config.weapons.at_cannon.range:
			var obstruction:Dictionary=game.field.trace_cover(muzzle_position(target.aim_point()),target.aim_point())
			if not obstruction.is_empty() and obstruction.get("cover_id","")==id:return
			if game.fx.launch(self,target,"at_cannon",true):game.shots+=1;shots+=1;cooldown=game.config.weapons.at_cannon.cooldown;crew.fire_until=game.elapsed+.2
func drive(u,dt:float):
	if phase in ["approaching","towing"]:
		if u.pos().distance_to(last_crew_pos)<.00005:stalled+=dt
		else:stalled=0
		last_crew_pos=u.pos()
		if stalled>1.0:release("路径被占用，停止牵引并重新找掩体");u.path_failure="gun_route_blocked";return
	u.posture="stand" if phase=="approaching" else "crouch";u.actor.weapon.hide();u.target_id="";u.cqb_stance="open"
	var target:Vector2=u.pos();var moving=false
	if phase=="approaching":
		if not u.route.is_empty():
			target=u.route[0]
			if u.pos().distance_to(target)<.012:u.route.remove_at(0)
			else:moving=true
		elif u.pos().distance_to(handle())<.045:phase="towing";reason="牵引中，禁止射击";u.route.clear()
		else:release("炮位无法到达");return
	elif phase=="towing":
		if pos().distance_to(destination)<.014:phase="deploying";deploy_time=game.config.equipment.deploy_seconds;reason="驻锄、展开炮架";return
		target=destination-forward()*.115;moving=true
	elif phase=="deploying":
		deploy_time-=dt
		if deploy_time<=0:phase="ready";reason="反装甲火力位就绪"
	if moving:
		var old:Vector3=u.actor.global_position
		var delta:Vector2=target-u.pos();u.rotation.y=atan2(-delta.x,-delta.y);u.actor.rotation.y=u.rotation.y+PI
		u.actor.advance_drive(Vector3(target.x,u.position.y,target.y),game.config.equipment.tow_speed if phase=="towing" else game.config.tactics.run_speed,dt,false,"crouch_run" if phase=="towing" else "run")
		u.global_position=u.actor.global_position;u.actor_advanced=true;u.locomotion="push_gun" if phase=="towing" else "run"
		if phase=="towing":
			var candidate:Vector2=u.pos()+forward()*.115
			if not game.field.segment_walkable(pos(),candidate,true):
				u.actor.global_position=old;u.global_position=old;phase="deploying";deploy_time=game.config.equipment.deploy_seconds;reason="前方障碍，停止牵引并部署"
			else:
				distance_pushed+=pos().distance_to(candidate);position.x=candidate.x;position.z=candidate.y;proxy.position=[position.x,position.z]
	else:
		u.rotation.y=yaw;u.locomotion="idle";u.animate("crouch")
	u.state=phase;u.order_mode="operate_at_gun";u.weapon_state="crew_fire" if cooldown>game.config.weapons.at_cannon.cooldown-.25 else "crew_reload" if cooldown>0 else "crew_ready"
func snapshot()->Dictionary:
	return {"id":id,"faction":faction,"position":[position.x,position.z],"hp":hp,"crew_id":crew_id,"phase":phase,"reason":reason,"target_id":target_id,"destination":[destination.x,destination.y],"distance_pushed":distance_pushed,"shots":shots,"cooldown":cooldown,"range":game.config.weapons.at_cannon.range}

func pose_crew(u):
	if phase not in ["towing","deploying","ready"]:return
	var center:Vector3=global_position+Vector3(-forward().x*.086,.0496,-forward().y*.086)
	var side:=Vector3(cos(yaw),0,-sin(yaw))*.055
	u.actor.grip_handle("Left",center-side);u.actor.grip_handle("Right",center+side)
