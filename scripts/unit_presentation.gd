extends RefCounted

## Presentation-only helpers for Unit.
##
## Unit remains the authority for combat, movement and state transitions.  This
## helper only maps logical clips to imported actor clips and advances the
## already-selected presentation state.  It intentionally receives the Unit
## instance so existing public fields and call sites remain unchanged.

static func animate(unit, clip: String) -> void:
	var mapped: String=clip
	if unit.actor:
		mapped={"idle":"rifle_idle","run":"rifle_jog_rm","aim":"rocket_aim" if unit.weapon=="rocket" else "rifle_idle","crouch":"cover_idle","prone":"prone_idle","reload":"reload","fire":"rocket_aim" if unit.weapon=="rocket" else ("pistol_fire" if unit.weapon=="pistol" else "rifle_fire"),"death":"death","melee":"bayonet"}.get(clip,clip)
		if unit.posture=="prone" and clip in ["idle","aim","prone","reload","fire"]:
			mapped={"reload":"prone_reload","fire":"prone_fire"}.get(clip,"prone_idle")
		elif unit.posture=="crouch" and clip in ["idle","aim","crouch","reload","fire"]:
			mapped="crouch_reload" if clip=="reload" else "cover_idle"
		if unit.cqb_stance=="peek" and unit.posture!="prone" and clip in ["aim","fire","crouch"]:
			mapped="cover_peek_left" if unit.cover_slot.get("key","").ends_with("0") else "cover_peek_right"
		if unit.actor.anim.has_animation(mapped):unit.actor.play(mapped)
	unit.last_clip=clip

static func tick(unit, dt: float) -> void:
	if unit.actor and not unit.actor.stepping and unit.posture=="prone" and unit.actor.clip=="cover_idle":unit.animate("reload" if unit.reload_timer>0 else "aim")
	unit.record_action()
	if unit.tank:
		if unit.anim:
			var turn: float=angle_difference(unit.previous_hull_yaw,unit.rotation.y)
			unit.track_clip="TankArmature|Tank_Backwards" if unit.reversing else ("TankArmature|Tank_TurningLeft" if turn>.005 else ("TankArmature|Tank_TurningRight" if turn<-.005 else "TankArmature|Tank_Forward"))
			if unit.anim.current_animation!=unit.track_clip:unit.anim.play(unit.track_clip)
			unit.anim.speed_scale=(.5 if unit.hp>0 and (not unit.route.is_empty() or absf(turn)>.005) else 0.0)*unit.game.speed
			unit.previous_hull_yaw=unit.rotation.y
		return
	if not unit.actor_advanced:
		if not unit.actor.stepping and not unit.actor.dead:unit.actor.rotation.y=unit.rotation.y+PI
		unit.actor.advance_idle(dt)
		unit.global_position=unit.actor.global_position
	if not unit.actor.stepping and unit.posture=="prone" and unit.actor.clip=="cover_idle":unit.animate("reload" if unit.reload_timer>0 else "aim")
	if unit.gun_id!="":
		unit.actor.weapon.hide()
		for gun in unit.game.at_guns:
			if gun.id==unit.gun_id:gun.pose_crew(unit)
	unit.actor_advanced=false

static func pause(unit, value: bool) -> void:
	if unit.tank:
		if unit.anim:unit.anim.speed_scale=0 if value else ((.5 if unit.state=="move" and unit.hp>0 else 0.0)*unit.game.speed)
	elif unit.actor.dead:
		for row in unit.actor.bodies:row.body.freeze=value
