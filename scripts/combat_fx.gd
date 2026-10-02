extends Node3D
## Bounded visual/audio layer. Projectiles resolve damage only on arrival.
const CombatBallistics = preload("res://scripts/combat_ballistics.gd")

var game
var ballistics = CombatBallistics.new()
var projectiles: Array=[]
var visuals: Array=[]
var voices: Array=[]
var sounds: Dictionary={}
var muted: bool=false
var audio_enabled: bool=DisplayServer.get_name()!="headless"
var audio_events: int=0
var impacts: int=0
var launched: Dictionary={}
var collision_counts: Dictionary={"cover":0,"unit":0,"miss":0,"friendly_block":0}
var hit_log: Array=[]
var pools:Dictionary={}
var variant_cursor:Dictionary={}
var variant_sounds:Dictionary={}
var budget=JSON.parse_string(FileAccess.get_file_as_string("res://data/presentation.json"))
var dropped_visuals=0
var stolen_voices=0
var reused_visuals=0
var peak_visuals=0
var peak_voices=0
var random := RandomNumberGenerator.new()
var dispersion_rng := RandomNumberGenerator.new()

func setup(g) -> void:
	game=g;random.seed=2918;dispersion_rng.seed=73129;ballistics.rng=dispersion_rng
	for key in ["rifle","smg","rocket","cannon","explosion","impact","bayonet","order","reload","pistol","grenade","rocket_blast","tank_impact","grenade_blast"]:
		sounds[key]=load("res://assets/audio/"+{"rocket":"rocket_launch","cannon":"tank_cannon","grenade":"reload"}.get(key,key)+".wav")

	for key in ["rifle","smg","pistol","rocket","cannon","grenade_blast"]:
		var stem:String={"rocket":"rocket_launch","cannon":"tank_cannon"}.get(key,key)
		variant_sounds[key]=[sounds[key],load("res://assets/audio/"+stem+"_2.wav"),load("res://assets/audio/"+stem+"_3.wav")]
	for bus_name in ["Weapons","Blasts","Interface"]:
		if AudioServer.get_bus_index(bus_name)<0:
			AudioServer.add_bus();AudioServer.set_bus_name(AudioServer.bus_count-1,bus_name)
			var limiter=AudioEffectLimiter.new();limiter.ceiling_db=-1;AudioServer.add_bus_effect(AudioServer.bus_count-1,limiter)

func acquire(kind:String,priority:int)->MeshInstance3D:
	if visuals.size()>=int(budget.visuals):
		var victim={}
		for effect in visuals:
			if int(effect.get("priority",1))<priority:victim=effect;break
		if victim.is_empty():dropped_visuals+=1;return null
		recycle(victim);visuals.erase(victim);dropped_visuals+=1
	var n:MeshInstance3D
	if pools.has(kind) and not pools[kind].is_empty():n=pools[kind].pop_back();reused_visuals+=1
	else:
		n=MeshInstance3D.new();add_child(n);n.set_meta("kind",kind)
		if kind=="ball":
			var mesh=SphereMesh.new();mesh.radius=1;mesh.height=2;mesh.radial_segments=8;mesh.rings=4;n.mesh=mesh
		elif kind=="beam":n.mesh=BoxMesh.new()
		elif kind=="ring":
			var mesh=TorusMesh.new();mesh.inner_radius=.86;mesh.outer_radius=1;mesh.rings=20;mesh.ring_segments=6;n.mesh=mesh
		else:
			n.mesh=QuadMesh.new()
			var m=ShaderMaterial.new();m.shader=preload("res://assets/vfx/soft_flipbook.gdshader")
			m.set_shader_parameter("atlas",preload("res://assets/vfx/fx.png"));m.set_shader_parameter("flow",preload("res://assets/vfx/flow.png"));n.material_override=m
		if kind!="puff":n.material_override=material(Color.WHITE)
		n.cast_shadow=GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	n.visible=true;n.transform=Transform3D.IDENTITY
	peak_visuals=maxi(peak_visuals,visuals.size()+1)
	return n

func recycle(effect:Dictionary):
	var n:MeshInstance3D=effect.node;n.hide()
	var kind:String=n.get_meta("kind")
	if not pools.has(kind):pools[kind]=[]
	if pools[kind].size()<int(budget.pool_per_kind):pools[kind].append(n)
	else:n.queue_free()

func material(color: Color, glow: bool=true) -> StandardMaterial3D:
	var m := StandardMaterial3D.new();m.albedo_color=color
	m.shading_mode=BaseMaterial3D.SHADING_MODE_UNSHADED if glow else BaseMaterial3D.SHADING_MODE_PER_PIXEL
	m.transparency=BaseMaterial3D.TRANSPARENCY_ALPHA;m.no_depth_test=false
	return m

func ball(p:Vector3,radius:float,color:Color,ttl:float,velocity:Vector3=Vector3.ZERO)->void:
	var n=acquire("ball",1)
	if n==null:return
	n.scale=Vector3.ONE*radius;n.position=p;n.material_override.albedo_color=color
	visuals.append({"node":n,"ttl":ttl,"life":ttl,"velocity":velocity,"grow":1.4,"priority":1})

func beam(a:Vector3,b:Vector3,width:float,color:Color,ttl:float)->void:
	if a.distance_to(b)<.0001:return
	var n=acquire("beam",2)
	if n==null:return
	n.position=(a+b)*.5;n.look_at(b);n.scale=Vector3(width,width,a.distance_to(b));n.material_override.albedo_color=color
	visuals.append({"node":n,"ttl":ttl,"life":ttl,"velocity":Vector3.ZERO,"grow":0.0,"priority":2})

func ring(p:Vector2,color:Color,radius:float=.04,ttl:float=.75)->void:
	var n=acquire("ring",3)
	if n==null:return
	n.scale=Vector3(radius,.12*radius,radius);n.position=Vector3(p.x,game.field.height+.006,p.y);n.material_override.albedo_color=color
	visuals.append({"node":n,"ttl":ttl,"life":ttl,"velocity":Vector3.ZERO,"grow":.7,"priority":3})

func sound(key: String, p: Vector3, quiet: float=0) -> void:
	if muted or not audio_enabled or not sounds.has(key):return
	var priority:int=3 if key in ["explosion","cannon","rocket_blast","tank_impact","grenade_blast"] else (2 if key in ["rifle","smg","pistol","rocket"] else 1)
	var player:AudioStreamPlayer3D
	for voice in voices:
		if not voice.playing:player=voice;break
	if player==null and voices.size()<int(budget.voices):
		player=AudioStreamPlayer3D.new();add_child(player);voices.append(player)
	if player==null:
		for voice in voices:
			if int(voice.get_meta("priority",1))<priority:player=voice;stolen_voices+=1;break
	if player==null:return
	player.stop();player.set_meta("priority",priority);player.position=p
	var variants:Array=variant_sounds.get(key,[sounds[key]])
	var cursor:int=int(variant_cursor.get(key,0));player.stream=variants[cursor%variants.size()];variant_cursor[key]=cursor+1
	player.unit_size=1.2;player.max_distance=8
	player.bus="Blasts" if priority==3 else ("Weapons" if priority==2 else "Interface")
	player.volume_db=float(budget.weapon_gain_db.get(key,-9))+quiet;player.pitch_scale=random.randf_range(.98,1.02)
	player.play();audio_events+=1;peak_voices=maxi(peak_voices,voices.filter(func(v):return v.playing).size())

func set_muted(value: bool) -> void:
	muted=value
	if muted:
		for v in voices:
			if is_instance_valid(v):v.stop();v.stream=null;v.queue_free()
		voices.clear()

func dispersed_endpoint(origin: Vector3, aim: Vector3, accuracy: float, pressure: float, weapon: String="rifle") -> Vector3:
	return ballistics.dispersed_endpoint(origin,aim,accuracy,pressure,weapon)

# 用实际将发射的散射轨迹检查首个碰撞，拒绝枪口前障碍和友军附近爆炸。
func firing_solution(shooter, origin: Vector3, target: Vector3, cfg: Dictionary, weapon: String) -> Dictionary:
	var hit: Dictionary=trace(origin,target,shooter.id)
	var reason: String=""
	if hit.get("kind","")=="cover":reason="muzzle_cover" if origin.distance_to(hit.point)<.20 else "target_occluded"
	elif hit.get("kind","")=="unit" and hit.unit.faction==shooter.faction:reason="friendly_in_firing_lane"
	if reason=="":reason=explosive_fire_block(shooter,origin,target,cfg,weapon)
	return {"clear":reason=="","reason":reason,"blocker_id":hit.get("cover_id",hit.unit.id if hit.has("unit") else ""),"distance":origin.distance_to(hit.point) if hit.has("point") else -1.0}

func explosive_fire_block(shooter, origin: Vector3, end: Vector3, cfg: Dictionary, weapon: String) -> String:
	if weapon not in ["rocket","cannon","at_cannon","grenade"]:return ""
	var collision: Dictionary={}
	var previous: Vector3=origin
	for i in range(1,17):
		var t: float=float(i)/16
		var point: Vector3=origin.lerp(end,t)
		if weapon=="grenade":point.y+=sin(t*PI)*.20
		collision=trace(previous,point,shooter.id)
		if not collision.is_empty():break
		previous=point
	var impact: Vector3=collision.get("point",end)
	if collision.get("kind","")=="unit" and collision.unit.faction==shooter.faction:return "friendly_in_firing_lane"
	var margin: float=float(cfg.get("splash",0))+.04
	if origin.distance_to(impact)<margin:return "muzzle_obstructed_or_blast_too_close"
	for ally in game.living(shooter.faction):
		if ally.aim_point().distance_to(impact)<margin:return "friendly_near_impact"
	return ""

func launch(shooter, target, weapon: String, landed: bool, override_cfg: Dictionary={}) -> bool:
	var cfg: Dictionary=game.config.weapons[weapon] if override_cfg.is_empty() else override_cfg
	var end: Vector3=target.aim_point()
	var from: Vector3=shooter.muzzle_position(end)
	var dir: Vector3=(end-from).normalized()
	if weapon=="bayonet":
		launched[weapon]=int(launched.get(weapon,0))+1
		sound(weapon,from)
		beam(from,end,.007,Color(.84,.91,.95),.14)
		target.hit(float(cfg.damage),float(cfg.pressure),from,.10);impacts+=1
		return true
	if game.human_squad:
		var pressure: float=float(shooter.get("suppression")) if shooter.get("suppression")!=null else 0.0
		end=dispersed_endpoint(from,end,float(cfg.accuracy),pressure,weapon)
		dir=(end-from).normalized()
	elif weapon in ["cannon","at_cannon"]:
		# Direct-fire guns retain a finite, distance-scaled cone even in the
		# native controller.  `landed` remains the damage roll; it no longer
		# makes the rendered shell perfectly exact.
		end=dispersed_endpoint(from,end,float(cfg.accuracy),0.0,weapon)
		dir=(end-from).normalized()
	elif not landed:end+=Vector3(random.randf_range(.026,.065),random.randf_range(-.025,.04),random.randf_range(-.06,.06))
	var blocked: String=explosive_fire_block(shooter,from,end,cfg,weapon)
	shooter.set_meta("fire_block_reason",blocked)
	if blocked!="":return false
	launched[weapon]=int(launched.get(weapon,0))+1
	sound("cannon" if weapon=="at_cannon" else weapon,from)
	var explosive: bool=weapon in ["rocket","cannon","at_cannon","grenade"]
	puff(from,.048 if explosive else .027,.20,false)
	beam(from,from+dir*.045,.009 if explosive else .006,Color(1,.91,.53),.10)
	var n := MeshInstance3D.new();var mesh := SphereMesh.new();mesh.radius=.009 if explosive else .0035;mesh.height=mesh.radius*2;mesh.radial_segments=8;mesh.rings=4;n.mesh=mesh
	n.material_override=material(Color(1,.54,.13) if explosive else Color(1,.91,.48));add_child(n);n.position=from
	if weapon=="grenade":
		var shell=load("res://assets/models/grenade.glb").instantiate();n.add_child(shell);shell.scale=Vector3.ONE*.075;n.mesh=null
		for part in shell.find_children("*","MeshInstance3D",true,false):part.material_override=game.field.mat(game.colors[shooter.faction],.32)
	projectiles.append({"node":n,"from":from,"to":end,"age":0.0,"duration":maxf(.09,from.distance_to(end)/float(cfg.projectile_speed)),"cfg":cfg.duplicate(),"weapon":weapon,"team":shooter.faction,"target":target,"shooter":shooter.id,"suppressed":[],"landed":landed,"trail":0.0})

	return true

func trace(a: Vector3,b: Vector3,shooter_id: String) -> Dictionary:
	var best: Dictionary=game.field.trace_cover(a,b)
	for unit in game.living():
		if unit.id==shooter_id:continue
		var box: Dictionary=unit.hit_box()
		var hit: Dictionary=game.field.ray_box(a,b,box.center,box.size,unit.rotation.y)
		if not hit.is_empty() and (best.is_empty() or hit.fraction<best.fraction):
			best=hit;best["unit"]=unit;best["kind"]="unit"
	return best

# 每发爆炸物以 10Hz 做局部预警；只通知能看到来袭物且位于预测危险走廊的人。
func warn_explosive(p: Dictionary) -> void:
	if not game.human_squad or p.weapon not in ["rocket","cannon","at_cannon","grenade"]:return
	if float(p.age)<float(p.get("warning_at",0)):return
	p.warning_at=float(p.age)+.10
	var remaining: float=ballistics.warning_remaining(float(p.duration),float(p.age))
	if remaining<=.08 or remaining>1.0:return
	if not p.has("warned"):p.warned=[]
	var current: Vector3=p.node.position
	var estimate: Vector2=ballistics.warning_estimate(p.to)
	var radius: float=ballistics.warning_radius(float(p.cfg.get("splash",0)))
	for u in game.living():
		if u.tank or u.faction==p.team or p.warned.has(u.id):continue
		if current.distance_to(u.aim_point())>.9 or not game.field.trace_cover(u.aim_point(),current).is_empty():continue
		if not ballistics.warning_corridor_contains(u.aim_point(),u.pos(),current,p.to,radius):continue
		p.warned.append(u.id)
		u.evade_explosive(estimate,Vector2(p.from.x,p.from.z),remaining,radius)

func physics_tick(dt: float) -> void:
	if dt>.034:
		var substeps: int=ceili(dt/.03333333)
		for i in range(substeps):physics_tick(dt/substeps)
		return
	for p in projectiles.duplicate():
		p.age+=dt
		warn_explosive(p)
		var previous: Vector3=p.node.position
		var next: Vector3=p.from.lerp(p.to,clampf(p.age/p.duration,0,1))
		if p.weapon=="grenade":next.y+=sin(clampf(p.age/p.duration,0,1)*PI)*.20
		# Continuous swept segment, not proximity to a preselected victim.
		var collision: Dictionary=trace(previous,next,p.shooter)
		if not collision.is_empty():next=collision.point
		p.node.position=next
		for unit in game.living():
			if unit.faction==p.team or p.suppressed.has(unit.id):continue
			var close: Vector3=Geometry3D.get_closest_point_to_segment(unit.aim_point(),previous,next)
			if close.distance_to(unit.aim_point())<.07 and game.field.trace_cover(close,unit.aim_point()).is_empty():
				unit.receive_pressure(float(p.cfg.pressure)*.55,p.from);p.suppressed.append(unit.id)
		p.trail-=dt
		if p.trail<=0:
			p.trail=.045
			beam(previous,next,.006 if p.weapon in ["rocket","cannon","at_cannon"] else .003,Color(1,.80,.36),.22)
			if p.weapon in ["rocket","cannon","at_cannon"]:puff(previous,.035,.7,true)
		if not collision.is_empty() or p.age>=p.duration:
			p.to=next;p["collision"]=collision
			impact(p);p.node.queue_free();projectiles.erase(p)

func impact(p: Dictionary) -> void:
	impacts+=1
	var collision: Dictionary=p.get("collision",{})
	var kind: String=collision.get("kind","miss")
	collision_counts[kind]+=1
	var at := Vector2(p.to.x,p.to.z)
	var explosive: bool=p.weapon in ["rocket","cannon","at_cannon","grenade"]
	if hit_log.size()<2000:hit_log.append({"time":game.elapsed,"weapon":p.weapon,"kind":kind,"id":collision.cover_id if kind=="cover" else (collision.unit.id if kind=="unit" else ""),"position":[p.to.x,p.to.y,p.to.z]})
	if explosive:
		sound({"rocket":"rocket_blast","cannon":"tank_impact","at_cannon":"tank_impact","grenade":"grenade_blast"}[p.weapon],p.to)
		var size=float(p.cfg.splash)*1.8
		puff(p.to+Vector3.UP*.025,size,1.0,false)
		for i in range(5):puff(p.to+Vector3(random.randf_range(-.025,.025),.03,random.randf_range(-.025,.025)),size,2.0+i*.35,true)
		for i in range(7):ball(p.to,.004,Color(.4,.34,.22),.65,Vector3(random.randf_range(-.15,.15),.15,random.randf_range(-.15,.15)))
		# Evaluate blast occlusion BEFORE destruction: the wall absorbs this blast,
		# then the next shot may pass through its newly opened hole.
		var blast: Vector3=p.to+(collision.get("normal",Vector3.ZERO) as Vector3)*.001
		for enemy in game.living():
			if enemy.faction==p.team:continue
			var distance: float=enemy.aim_point().distance_to(blast)
			if distance>float(p.cfg.splash):continue
			var direct: bool=kind=="unit" and collision.unit==enemy
			var shield: bool=not game.field.trace_cover(blast,enemy.aim_point()).is_empty()
			var damage: float=float(p.cfg.damage)*(1.0 if direct else .65*(1-distance/float(p.cfg.splash)))
			if shield:damage=0
			if enemy.tank:damage*=float(p.cfg.armor_multiplier)*enemy.armor_multiplier(Vector2(p.from.x,p.from.z))
			enemy.hit(damage,float(p.cfg.pressure)*(.12 if shield else 1.0),blast,.55*(1-distance/float(p.cfg.splash)))
			enemy.receive_pressure(0,p.from)
		for c in game.field.covers:
			if not c.alive:continue
			var center=Vector3(c.position[0],float(c.get("bottom",game.field.height))+c.height*.5,c.position[1])
			var basis=Basis(Vector3.UP,float(c.get("yaw",0)))
			var sz=c.get("ray_size",[c.size[0],c.height,c.size[1]])
			var half=Vector3(sz[0],sz[1],sz[2])*.5
			var local=basis.inverse()*(p.to-center)
			var distance: float=local.distance_to(local.clamp(-half,half))
			if distance>float(p.cfg.splash):continue
			var amount: float=float(p.cfg.get("cover_damage",35))*(1-.65*distance/float(p.cfg.splash))
			if game.field.damage_cover(c.id,amount):game.add_event("爆炸摧毁 "+c.id+"，射界与通路已更新")
	else:
		sound("impact",p.to,-11)
		for i in range(3):ball(p.to,.004,Color(1,.88,.46),.17,Vector3(random.randf_range(-.1,.1),.06,random.randf_range(-.1,.1)))
		if kind=="cover":game.field.damage_cover(collision.cover_id,float(p.cfg.get("cover_damage",.3)))
		if kind=="unit":
			var target=collision.unit
			if target.faction==p.team:collision_counts.friendly_block+=1;return
			var damage: float=float(p.cfg.damage)*(float(p.cfg.armor_multiplier)*target.armor_multiplier(Vector2(p.from.x,p.from.z)) if target.tank else 1.0)
			target.hit(damage,float(p.cfg.pressure),p.from,.12);target.receive_pressure(0,p.from)

func _process(dt: float) -> void:
	if game==null:return
	if game.paused or game.winner!="":return
	for effect in visuals.duplicate():
		effect.ttl-=dt*game.speed
		if effect.ttl<=0:recycle(effect);visuals.erase(effect);continue
		effect.node.position+=effect.velocity*dt*game.speed
		effect.node.scale*=1+effect.grow*dt*game.speed
		if effect.has("smoke"):
			var t=1-effect.ttl/effect.life
			effect.node.material_override.set_shader_parameter("progress",lerpf(.38,.99,t) if effect.smoke else t)
		else:effect.node.material_override.albedo_color.a=minf(1,effect.ttl/effect.life*1.6)

func _exit_tree() -> void:
	set_muted(true)
	sounds.clear()

func puff(p:Vector3,size:float,life:float,smoke:bool) -> void:
	var n=acquire("puff",1 if smoke else 3)
	if n==null:return
	n.scale=Vector3.ONE*size;n.position=p
	var m:ShaderMaterial=n.material_override
	m.set_shader_parameter("progress",.38 if smoke else 0.0)
	m.set_shader_parameter("smoke_only",smoke);m.set_shader_parameter("opacity",.36 if smoke else .88)
	visuals.append({"node":n,"ttl":life,"life":life,"velocity":Vector3(.008,.035 if smoke else .006,.005),"grow":.15,"smoke":smoke,"priority":1 if smoke else 3})

func metrics()->Dictionary:
	return {"visual_budget":budget.visuals,"voice_budget":budget.voices,"peak_visuals":peak_visuals,"peak_voices":peak_voices,"dropped_visuals":dropped_visuals,"stolen_voices":stolen_voices,"reused_visuals":reused_visuals}
