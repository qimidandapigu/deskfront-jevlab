extends RefCounted
# Stabilize only repeated formation corrections, never tactical destinations.
static func retain(u, order_id, destination: Vector2, now: float) -> bool:
	var previous: Dictionary=u.get_meta("harness_formation_motion",{})
	var same: bool=previous.get("order_id")==order_id
	var current_revision: int=u.game.field.revision
	var stable: bool=same and previous.get("navigation_revision",-1)==current_revision and u.route_revision==current_revision and now>=u.safety_until and u.order_mode=="squad_formation" and u.path_failure=="" and u.no_progress_seconds<.8
	var close_goal: bool=destination.distance_to(u.goal)<.12
	var arrival_radius: float=.075 if same and previous.get("settled",false) else .055
	var settled: bool=stable and u.route.is_empty() and u.pos().distance_to(destination)<arrival_radius
	# Stagger ordinary follower repaths; never hold a stale navigation revision.
	var interval: float=.5+float(abs(str(u.id).hash())%251)/1000.0
	var keep: bool=stable and close_goal and ((not u.route.is_empty() and now-float(previous.get("time",-100))<interval) or settled)
	if keep:
		previous["settled"]=settled
		u.set_meta("harness_formation_motion",previous)
		u.set_meta("harness_formation_retained",int(u.get_meta("harness_formation_retained",0))+1)
		return true
	u.set_meta("harness_formation_motion",{"order_id":order_id,"time":now,"navigation_revision":current_revision})
	return false

# Filter the squad frame, not a soldier's tactical target or aim direction.
static func heading(s: Dictionary, desired: Vector2, now: float) -> Vector2:
	var old: Dictionary=s.get("harness_frame",{})
	var result: Vector2=desired.normalized()
	if not old.is_empty():
		var previous: Vector2=old.heading
		var dt: float=clampf(now-float(old.time),0,.25)
		result=previous.rotated(clampf(previous.angle_to(result),-2.0*dt,2.0*dt))
	s["harness_frame"]={"heading":result,"time":now}
	return result

static func narrow(s: Dictionary, detected: bool, now: float) -> bool:
	# Enter a narrow formation immediately; require sustained clearance to widen.
	if detected:
		s["harness_narrow_until"]=now+.8
		return true
	return now<float(s.get("harness_narrow_until",-1))

static func separation(u, other, target: Vector2, space: float, now: float) -> Vector2:
	var apart: Vector2=u.pos()-other.pos()
	var push: Vector2=apart.normalized()*(space-apart.length())*.8
	# Safety maneuvers and tanks retain the original collision steering.
	if other.tank or now<u.safety_until:return target+push
	# Bound correction by remaining distance: an avoidance offset must never
	# put the steering target behind the actor as it approaches a waypoint.
	var delta: Vector2=target-u.pos()
	var distance: float=delta.length()
	if distance<.0005:return target
	var desired: Vector2=delta/distance
	var side: Vector2=Vector2(-desired.y,desired.x)
	var correction: Vector2=push+side*maxf(0,space-apart.length())*.5
	return target+correction.limit_length(distance*.35)
