# Execute the accepted establish_fire assignment toward its accepted region.
func harness_establish_fire(u,s: Dictionary) -> bool:
	if s.intent!="cover" or s.get("assignments",{}).get(u.id,{}).get("role","")!="establish_fire":return false
	if personal_owned(u,s) or game.elapsed<u.safety_until or u.suppression>=.35 or u.reload_timer>0:return true
	if not u.route.is_empty():return true
	if game.elapsed-u.last_shot_at<2:return true
	for enemy in game.living():
		if enemy.faction==u.faction or not visible_to(u.faction,enemy):continue
		if u.pos().distance_to(enemy.pos())>u.weapon_config().range:continue
		if u.firing_solution_at(enemy,u.pos(),u.posture).clear:return true
		if u.firing_solution_at(enemy,u.pos(),"stand").clear:
			if intent_executor.request_posture(u,"stand",str(s.order_id),game.elapsed):return true
	if game.elapsed<float(u.get_meta("harness_fire_retry",0)):return true
	u.set_meta("harness_fire_retry",game.elapsed+1.5)
	# Prefer a reachable local firing position; otherwise approach the commanded region.
	for radius in [.10,.20,.30]:
		for i in range(8):
			var p: Vector2=u.pos()+Vector2.from_angle(i*TAU/8)*radius
			if not game.field.walkable(p) or not destination_free(u,p,s) or not has_firing_lane(u,p):continue
			var route: PackedVector2Array=game.field.path(u.pos(),p)
			if route.is_empty() or game.field.route_length(route)>.65:continue
			if game.field.route_exposure(route,threat_points(s.faction))>.12:continue
			if request_motion(u,s,"fire_position",p):u.order_mode="squad_firing_position";return true
	if u.pos().distance_to(s.goal)>s.radius:
		for i in range(9):
			var p: Vector2=s.goal if i==0 else s.goal+Vector2.from_angle((i-1)*TAU/8)*s.radius*.8
			if not game.field.walkable(p) or not destination_free(u,p,s):continue
			if game.field.path(u.pos(),p).is_empty():continue
			if request_motion(u,s,"fire_position",p):u.order_mode="squad_firing_position";return true
	emit("participation_gap",s.faction,s.squad_id,u.id,{"reason":"no_reachable_firing_position_in_assigned_region"})
	return true

# Local, bounded recovery for a healthy direct-fire unit. This does not choose
# a region or change a squad role: it only tries a few nearby points that pass
# native walkability, exposure and muzzle-ray checks. It prevents a blocked
# muzzle/no-effective-fire report from becoming an indefinite wait.
func local_fire_recovery(u,s: Dictionary,reason: String) -> bool:
	if u.hp<=0 or personal_owned(u,s) or game.elapsed<u.safety_until or not u.route.is_empty():return false
	if game.elapsed<float(u.get_meta("harness_local_fire_retry",0.0)):return false
	var target=visible_enemy(u)
	if target==null or (target.tank and u.weapon not in ["rocket","cannon"]):return false
	var origin: Vector2=u.pos();var away: Vector2=(origin-target.pos()).normalized()
	if away.length()<.1:away=Vector2.UP
	var directions: Array=[away.orthogonal(),-away.orthogonal(),away,-away]
	var candidates: Array=[]
	for radius in [.075,.12,.18]:
		for direction in directions:
			var point: Vector2=origin+direction*radius
			if not game.field.walkable(point) or not game.field.segment_walkable(origin,point) or not destination_free(u,point,s):continue
			if point.distance_to(target.pos())>u.weapon_config().range:continue
			if not (u.firing_solution_at(target,point,"crouch").clear or u.firing_solution_at(target,point,"stand").clear):continue
			var route: PackedVector2Array=game.field.path(origin,point)
			if route.is_empty() or game.field.route_length(route)>.24 or game.field.route_exposure(route,threat_points(s.faction))>.20:continue
			candidates.append({"point":point,"length":game.field.route_length(route)})
	u.set_meta("harness_local_fire_retry",game.elapsed+2.0)
	if not candidates.is_empty():
		candidates.sort_custom(func(a,b):return a.length<b.length)
		var point: Vector2=candidates[0].point
		if request_motion(u,s,"fire_position",point):
			u.order_mode="squad_local_fire_adjustment"
			emit("local_fire_recovery",s.faction,s.squad_id,u.id,{"reason":reason,"action":"side_step","target_id":target.id})
			return true
	# If no nearby lane exists, make one short native-validated approach. The
	# next observation decides whether it helped; it never invents a long route.
	var approach: Vector2=origin.move_toward(target.pos(),.14)
	if game.field.walkable(approach) and game.field.segment_walkable(origin,approach) and destination_free(u,approach,s):
		var approach_route: PackedVector2Array=game.field.path(origin,approach)
		if not approach_route.is_empty() and game.field.route_length(approach_route)<=.22 and game.field.route_exposure(approach_route,threat_points(s.faction))<=.20 and request_motion(u,s,"fire_position",approach):
			u.order_mode="squad_local_fire_approach"
			emit("local_fire_recovery",s.faction,s.squad_id,u.id,{"reason":reason,"action":"approach","target_id":target.id})
			return true
	return false
