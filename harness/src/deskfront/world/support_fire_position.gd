extends RefCounted

# Local execution aid for direct-fire support soldiers. The squad Agent still
# chooses the region and role; this only maintains a short, verified firing
# position inside the current engagement.
var evaluator=preload("res://scripts/engagement_position.gd").new()
const MAX_LOCAL_TRAVEL: float=0.42

func eligible(controller,u,s: Dictionary) -> bool:
	return not u.tank and float(u.weapon_config().get("splash",0.0))>0.0 and \
		str(s.get("assignments",{}).get(u.id,{}).get("role","fire_support"))=="fire_support" and \
		str(s.get("intent","")) in ["advance","bound","flank","hold","cover"]

func hold_if_firing(controller,u,s: Dictionary,status: Dictionary) -> bool:
	if not eligible(controller,u,s):return false
	var target=controller.game.find_target(u)
	if target==null:target=controller.visible_enemy(u)
	if target==null or u.pos().distance_to(target.pos())>float(u.weapon_config().range):return false
	var distance: float=u.pos().distance_to(target.pos())
	var band: Dictionary=evaluator.envelope(u,"fire_support")
	if distance<float(band.preferred_min) or distance>float(band.maximum):return false
	if not u.firing_solution_at(target,u.pos(),u.posture).clear:return false
	if controller.request_motion(u,s,"fire_position",u.pos(),u.cover_slot if u.in_cover() else {}):
		u.set_meta("engagement_position",{"status":"ready","position":u.pos(),"distance":distance,
			"role":"fire_support","firing_line":"clear","target_id":target.id,"mode":"holding_valid_fire"})
		status.state="holding_fire_position";return true
	return false

func recover(controller,u,s: Dictionary,status: Dictionary) -> bool:
	if not eligible(controller,u,s):return false
	var targets: Array=controller.game.living().filter(func(enemy):return enemy.faction!=u.faction and controller.visible_to(u.faction,enemy) and u.pos().distance_to(enemy.pos())<=float(u.weapon_config().range))
	targets.sort_custom(func(a,b):return (a.tank and not b.tank) or (a.tank==b.tank and u.pos().distance_to(a.pos())<u.pos().distance_to(b.pos())))
	var failed: Dictionary={"status":"no_visible_target"}
	for target in targets.slice(0,4):
		var choice: Dictionary=evaluator.choose(controller.game,u,target,"fire_support",MAX_LOCAL_TRAVEL)
		choice["target_id"]=target.id
		if choice.status!="ready":failed=choice;continue
		var site: Vector2=choice.position
		if not controller.destination_free(u,site,s):failed={"status":"site_occupied","target_id":target.id};continue
		u.set_meta("engagement_position",choice)
		if u.pos().distance_to(site)<.035:
			status.state="holding_fire_position";status.since=controller.game.elapsed
			return true
		if controller.request_motion(u,s,"fire_position",site):
			u.order_mode="squad_firing_position"
			status.state="relocating";status.since=controller.game.elapsed
			return true
		status.state="deferred_to_intent_executor"
		return true
	u.set_meta("engagement_position",failed)
	return false
