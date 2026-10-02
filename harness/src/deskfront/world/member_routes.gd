
# Per-member area choices are emitted by the Harness squad Agent. This is a
# mechanical waypoint follower; it does not choose tactics or new areas.
func valid_member_assignment(row: Dictionary) -> bool:
	var points: Variant=row.get("route_positions",[])
	if not points is Array or points.size()>9:return false
	var previous:=Vector2.ZERO
	var has_previous: bool=false
	for raw in points:
		if not raw is Array or raw.size()!=2:return false
		if not (raw[0] is float or raw[0] is int) or not (raw[1] is float or raw[1] is int):return false
		var point:=Vector2(float(raw[0]),float(raw[1]))
		if not is_finite(point.x) or not is_finite(point.y) or not game.field.walkable(point):return false
		# A list of walkable cells is not yet a route.  Reject assignments whose
		# consecutive waypoints are disconnected, otherwise every member can be
		# sent toward the same visible cell and pile up against a cover block.
		if has_previous and previous.distance_to(point)>.02 and game.field.path(previous,point).is_empty():return false
		previous=point;has_previous=true
	var final: Variant=row.get("position",[])
	if not final is Array or (not final.is_empty() and final.size()!=2):return false
	if final.size()==2:
		if not (final[0] is float or final[0] is int) or not (final[1] is float or final[1] is int):return false
		var goal:=Vector2(float(final[0]),float(final[1]))
		if not is_finite(goal.x) or not is_finite(goal.y) or not game.field.walkable(goal):return false
		if not points.is_empty() and goal.distance_to(Vector2(float(points[-1][0]),float(points[-1][1])))>.12:return false
	return true

func member_has_route(s: Dictionary,u) -> bool:
	var row: Dictionary=s.get("assignments",{}).get(u.id,{})
	return row.get("route_positions",[]) is Array and not row.get("route_positions",[]).is_empty()

func member_final_goal(s: Dictionary,u) -> Vector2:
	var row: Dictionary=s.get("assignments",{}).get(u.id,{})
	var p: Array=row.get("position",[])
	return Vector2(float(p[0]),float(p[1])) if p.size()==2 else s.goal

func member_next_goal(s: Dictionary,u) -> Vector2:
	var row: Dictionary=s.get("assignments",{}).get(u.id,{})
	var points: Array=row.get("route_positions",[])
	if points.is_empty():return s.goal
	if not s.has("member_cursors"):s.member_cursors={}
	# The first region is the actor's origin region, not a destination to which
	# the actor should walk backwards to touch its exact center.
	var cursor: int=int(s.member_cursors.get(u.id,1 if points.size()>1 else 0))
	cursor=clampi(cursor,0,points.size()-1)
	while cursor<points.size()-1:
		var point: Array=points[cursor]
		if u.pos().distance_to(Vector2(float(point[0]),float(point[1])))>.12:break
		cursor+=1
	s.member_cursors[u.id]=cursor
	var target: Array=points[cursor]
	var candidate:=Vector2(float(target[0]),float(target[1]))
	if not game.field.path(u.pos(),candidate).is_empty():return candidate
	# The world may have changed after the assignment was accepted.  Skip a
	# blocked waypoint only when a later authored waypoint is still reachable;
	# never keep steering into the same obstacle.
	for index in range(cursor+1,points.size()):
		var alternate: Array=points[index]
		var alternate_point:=Vector2(float(alternate[0]),float(alternate[1]))
		if not game.field.path(u.pos(),alternate_point).is_empty():
			s.member_cursors[u.id]=index
			return alternate_point
	return u.pos()

func member_arrived(s: Dictionary,u) -> bool:
	return u.pos().distance_to(member_final_goal(s,u))<=s.radius
