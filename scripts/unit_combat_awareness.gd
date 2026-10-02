extends RefCounted

## Read-only combat awareness for Unit.
##
## This helper intentionally receives the Unit instance instead of owning any
## state.  Unit remains the authority for setup, movement, firing, damage and
## snapshots; this script only evaluates geometry and records the existing
## awareness result on the caller.

static func firing_solution_at(unit, enemy, point: Vector2, stance: String) -> Dictionary:
	var y: float=.026 if stance=="prone" else (.068 if stance=="crouch" else .093)
	var origin:=Vector3(point.x,unit.position.y+y,point.y)
	origin+=(enemy.aim_point()-origin).normalized()*.023
	return unit.game.fx.firing_solution(unit,origin,enemy.aim_point(),unit.weapon_config(),unit.weapon)

static func update_firing_awareness(unit) -> void:
	if not unit.game.human_squad or unit.tank or unit.game.elapsed<unit.firing_review_at:return
	unit.firing_review_at=unit.game.elapsed+.8+float(abs(unit.id.hash())%4)*.05
	var enemy=unit.game.human_squads.visible_enemy(unit)
	if enemy==null or unit.pos().distance_to(enemy.pos())>unit.weapon_config().range:
		unit.firing_awareness={};unit.set_meta("fire_block_reason","");return
	unit.firing_awareness=unit.game.fx.firing_solution(unit,unit.muzzle_position(enemy.aim_point()),enemy.aim_point(),unit.weapon_config(),unit.weapon)
	unit.firing_awareness["target_id"]=enemy.id;unit.firing_awareness["response"]="aim" if unit.firing_awareness.clear else "wait"
	unit.set_meta("fire_block_reason",unit.firing_awareness.reason)
	if unit.firing_awareness.clear or not unit.route.is_empty() or unit.reload_timer>0 or unit.game.elapsed<unit.safety_until or unit.suppression>=.35 or unit.game.elapsed-unit.last_threat_at<2:return
	if unit.firing_awareness.reason=="friendly_in_firing_lane" or unit.firing_awareness.reason=="friendly_near_impact":return
	if unit.posture_order=="auto" and unit.cqb_stance!="hide":
		for stance in ["crouch","stand"]:
			if stance==unit.posture:continue
			if firing_solution_at(unit,enemy,unit.pos(),stance).clear:
				unit.firing_posture=stance;unit.firing_posture_until=unit.game.elapsed+2;unit.posture=stance;unit.posture_since=unit.game.elapsed;unit.last_clip=""
				unit.firing_awareness.response="adjust_posture";return
	if unit.cover_slot.is_empty():return
	var candidates: Array=[unit.cover_slot.get("peek",unit.pos())]
	var side: Vector2=(enemy.pos()-unit.pos()).normalized().orthogonal()
	candidates.append(unit.pos()+side*.075);candidates.append(unit.pos()-side*.075)
	for point: Vector2 in candidates:
		if point.distance_to(unit.pos())<.025 or point.distance_to(unit.pos())>.16 or not unit.game.field.walkable(point):continue
		if not unit.game.field.segment_walkable(unit.pos(),point) or unit.game.field.protection(point,enemy.pos())<.2:continue
		if unit.game.living().any(func(u):return u!=unit and u.pos().distance_to(point)<.05):continue
		if not firing_solution_at(unit,enemy,point,"crouch").clear:continue
		if not unit.game.human_squads.request_fire_adjustment(unit,point):return
		unit.order_mode="adjust_firing_lane";unit.firing_awareness.response="move_to_cover_edge";return
	unit.firing_awareness.response="request_new_firing_position"

static func can_engage(unit, enemy) -> bool:
	if unit.deployment_phase!="active" or enemy.get("deployment_phase")=="entering":return false
	if enemy.tank and unit.weapon not in ["rocket","cannon"]:return false
	if unit.game.human_squad:return unit.game.fx.firing_solution(unit,unit.muzzle_position(enemy.aim_point()),enemy.aim_point(),unit.weapon_config(),unit.weapon).clear
	var hit: Dictionary=unit.game.field.trace_cover(unit.muzzle_position(enemy.aim_point()),enemy.aim_point())
	if hit.is_empty():return true
	# Heavy weapons may deliberately breach blocking cover, but still hit its near face.
	return unit.weapon in ["rocket","cannon"] and unit.cqb_stance!="hide" and unit.pos().distance_to(enemy.pos())>.16

static func snapshot_engagement(unit, enemy, queries: Dictionary) -> bool:
	# Directed pair: A firing at B is not interchangeable with B firing at A.
	var key: String=unit.id+":"+enemy.id
	if not queries.has(key):queries[key]=can_engage(unit,enemy)
	return queries[key]
