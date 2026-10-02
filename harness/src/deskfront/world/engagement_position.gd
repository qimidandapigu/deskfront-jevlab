extends RefCounted

# One position evaluator for direct-fire units. Weapon range and splash come
# from the live weapon configuration; the squad role supplies the range band.
var profiles: Dictionary={}

func _init() -> void:
	profiles=JSON.parse_string(FileAccess.get_file_as_string("res://data/engagement-profiles.json"))

func envelope(unit,role: String="fire_support") -> Dictionary:
	var profile: Dictionary=profiles.get(role,profiles.fire_support)
	var weapon: Dictionary=unit.weapon_config()
	var maximum: float=float(weapon.range)
	var minimum: float=maxf(maximum*float(profile.minimum_fraction),float(weapon.get("splash",0.0))*2.0+.04)
	return {"minimum":minimum,"preferred_min":maximum*float(profile.preferred_min),
		"preferred_max":maximum*float(profile.preferred_max),"maximum":maximum*.98,
		"screen_gap":float(profile.screen_gap)}

func choose(game,unit,target,role: String="fire_support",max_travel: float=INF) -> Dictionary:
	var band: Dictionary=envelope(unit,role)
	var target_pos: Vector2=target.pos()
	var allies: Array=game.living(unit.faction).filter(func(other):return other!=unit and not other.tank and other.hp>0)
	var rear_edge: float=-1.0
	for ally in allies:rear_edge=maxf(rear_edge,ally.pos().distance_to(target_pos))
	var samples: Array=[unit.pos()]
	# Target rings find a useful range; local rings find a lateral escape when
	# the desk layout leaves only a narrow reachable lane near the actor.
	for fraction in [0.5,0.65,0.8,0.9,0.96]:
		var radius: float=float(unit.weapon_config().range)*fraction
		for i in range(24):samples.append(target_pos+Vector2.from_angle(TAU*float(i)/24.0)*radius)
	for radius in [0.16,0.3,0.45]:
		for i in range(16):samples.append(unit.pos()+Vector2.from_angle(TAU*float(i)/16.0)*radius)
	var coarse: Array=[]
	for point: Vector2 in samples:
		var distance: float=point.distance_to(target_pos)
		if distance<float(band.minimum) or distance>float(band.maximum):continue
		if point.distance_to(unit.pos())>max_travel:continue
		if point.distance_to(unit.pos())>.015 and not game.field.walkable(point,unit.tank):continue
		if not game.field.line_of_sight(point,target_pos):continue
		if allies.any(func(other):return other.pos().distance_to(point)<(.14 if unit.tank else .055)):continue
		var center: float=(float(band.preferred_min)+float(band.preferred_max))*.5
		var gap: float=distance-rear_edge if rear_edge>=0 else 0.0
		var screen: float=clampf((gap-float(band.screen_gap))/.12,-1.0,1.0) if rear_edge>=0 and float(band.screen_gap)>0 else 0.0
		var rank: float=1.0-absf(distance-center)/float(band.maximum)+screen*.28-point.distance_to(unit.pos())*.5
		coarse.append({"point":point,"distance":distance,"gap":gap,"rank":rank})
	coarse.sort_custom(func(a,b):return a.rank>b.rank)
	var best: Dictionary={}
	var checked: int=0
	var rejected: Dictionary={}
	for row in coarse:
		if checked>=24:break
		checked+=1
		var point: Vector2=row.point
		var moving: bool=point.distance_to(unit.pos())>.015
		var route: PackedVector2Array=PackedVector2Array()
		if moving:
			route=game.field.path(unit.pos(),point,unit.tank)
			if route.is_empty():rejected["unreachable"]=int(rejected.get("unreachable",0))+1;continue
			if game.field.route_length(route)>max_travel:rejected["route_too_long"]=int(rejected.get("route_too_long",0))+1;continue
		var origin: Vector3=Vector3(point.x,unit.position.y+(.13 if unit.tank else .093),point.y)
		if unit.tank and unit.muzzle:
			var socket: Vector3=unit.muzzle.global_position-unit.global_position
			var forward: Vector2=(target_pos-point).normalized()
			var barrel: float=Vector2(socket.x,socket.z).length()
			origin=Vector3(point.x+forward.x*barrel,unit.position.y+socket.y,point.y+forward.y*barrel)
		if not moving:origin=unit.muzzle_position(target.aim_point())
		var fire: Dictionary=game.fx.firing_solution(unit,origin,target.aim_point(),unit.weapon_config(),unit.weapon) if unit.tank else unit.firing_solution_at(target,point,"crouch")
		if not fire.clear and not unit.tank:fire=unit.firing_solution_at(target,point,"stand")
		if not fire.clear:
			var reason: String=str(fire.get("reason","blocked"))
			rejected[reason]=int(rejected.get(reason,0))+1
			continue
		var travel: float=game.field.route_length(route) if moving else 0.0
		var score: float=float(row.rank)-travel*.6+(0.12 if not moving else 0.0)
		if role=="fire_support" and rear_edge>=0 and float(row.gap)<float(band.screen_gap):score-=.28
		if best.is_empty() or score>float(best.score):
			best={"status":"ready","position":point,"distance":row.distance,"screen_gap":row.gap,
				"score":score,"route_length":travel,"role":role,"firing_line":"clear"}
	if best.is_empty():return {"status":"no_valid_fire_position","role":role,"checked":checked,
		"coarse_candidates":coarse.size(),"rejected":rejected,"firing_line":"blocked_or_unreachable"}
	best.checked=checked
	return best
