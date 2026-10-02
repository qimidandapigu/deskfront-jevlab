
# The Soldier Agent selects only a native candidate ID and a short action.
# The engine rechecks the chosen point and retains immediate survival authority.
func personal_site_arrived(row: Dictionary,u) -> bool:
	var raw: Variant=row.get("position",[])
	return raw is Array and raw.size()==2 and u.pos().distance_to(Vector2(float(raw[0]),float(raw[1])))<=.085

func finish_selected_personal(row: Dictionary,u,reason: String) -> void:
	if row.get("intent","")=="rush_to_site":
		u.remove_meta("harness_antiarmor_charge_until")
		u.remove_meta("harness_antiarmor_target_id")
	if row.get("intent","") in ["rush_to_site","prone_approach"]:
		intent_executor.cancel_posture(u,reason,game.elapsed)
	if row.get("intent","")=="rush_to_site":u.formation_speed=1.0
	if row.get("intent","")=="focus_fire" and u.focus_id==row.get("target_id",""):
		u.focus_id=""

# A model-approved anti-armor rush carries its target through the short charge.
# The engine releases the pack on the first safe throwing frame instead of
# waiting for another model round trip while the tank can leave range.
func try_auto_satchel_on_charge(row: Dictionary,u) -> bool:
	if row.get("intent","")!="rush_to_site" or row.get("status","")!="active" or not u.harness_antiarmor_commit_active():return false
	var target_id: String=str(u.get_meta("harness_antiarmor_target_id",""))
	for enemy in game.living():
		if enemy.id!=target_id or not enemy.tank or enemy.faction==u.faction or not visible_to(u.faction,enemy):continue
		if not u.can_satchel(enemy) or not u.request_satchel(enemy):return false
		personal_transition(row,"completed","satchel_throw_on_charge")
		finish_selected_personal(row,u,"satchel_throw_on_charge")
		intent_executor.cancel_motion(u,"satchel_throw_on_charge",game.elapsed)
		game.add_event(u.id+" 冲锋后向 "+enemy.id+" 投出炸药包")
		return true
	return false

func accept_selected_personal(c: Dictionary,s: Dictionary,u) -> String:
	var intent: String=str(c.get("intent",""))
	var committed_throw: bool=intent=="satchel" and u.harness_antiarmor_commit_active()
	if game.elapsed<u.safety_until or u.suppression>=(.72 if committed_throw else .35) or (game.elapsed-u.last_threat_at<2 and not committed_throw):return "survival_override"
	if not s.has("personal"):s.personal={}
	var old: Dictionary=s.personal.get(u.id,{})
	var target_id: String=str(c.get("target_id",""))
	if intent=="satchel":
		var armor=null
		for enemy in game.living():
			if enemy.id==target_id and enemy.faction!=u.faction and enemy.tank and visible_to(u.faction,enemy):armor=enemy;break
		if armor==null:return "invalid_satchel_target"
		if not u.has_method("can_satchel"):return "satchel_unavailable"
		var block_reason: String=u.satchel_block_reason(armor)
		if not block_reason.is_empty():return "satchel_blocked:"+block_reason
		if not u.request_satchel(armor):return "satchel_unavailable"
		if personal_owned(u,s):
			personal_transition(old,"completed","satchel_throw")
			finish_selected_personal(old,u,"satchel_throw")
		intent_executor.cancel_motion(u,"satchel_throw",game.elapsed)
		u.formation_speed=1.0
		return "applied"
	if personal_owned(u,s):return "personal_action_active"
	if intent=="focus_fire":
		var target=null
		for enemy in game.living():
			if enemy.id==target_id and enemy.faction!=u.faction and visible_to(u.faction,enemy):target=enemy;break
		if target==null or (target.tank and u.weapon not in ["rocket","cannon"]):return "invalid_fire_target"
		if u.pos().distance_to(target.pos())>float(u.weapon_config().range) or not u.can_engage(target):return "no_clear_firing_lane"
		# Focusing while a route is active cannot fire: infantry must stand and aim.
		# The IntentExecutor cancels that motion so its receipt reflects the interruption.
		intent_executor.cancel_motion(u,"focus_fire",game.elapsed)
		u.focus_id=target_id
		s.personal[u.id]={"intent":intent,"status":"active","order_id":s.order_id,"until":game.elapsed+3,"target_id":target_id,"wait_order":old.get("wait_order","")}
		return "applied"
	var token: String=str(c.get("candidate_query_id",""))
	var cache: Dictionary=get_meta("candidate_results_"+s.faction,{})
	var result: Dictionary=cache.get(token,{})
	if result.get("id")!=token or result.get("unit_id")!=u.id or result.get("status")!="fresh" or game.elapsed-float(result.get("sampled_at",-100))>12:return "stale_candidate_query"
	if result.get("navigation_revision")!=game.field.revision:return "navigation_changed"
	var option: Dictionary={}
	for row in result.get("options",[]):
		if row.get("id")==c.get("site_id"):option=row;break
	if option.is_empty():return "invalid_site_id"
	var assignment: Dictionary=s.get("assignments",{}).get(u.id,{})
	if not assignment.get("region_path",[]).has(option.get("region_id")):return "site_outside_assigned_route"
	var raw: Array=option.get("position",[])
	if raw.size()!=2:return "invalid_site_position"
	var p:=Vector2(float(raw[0]),float(raw[1]))
	if not game.field.walkable(p) or not destination_free(u,p,s):return "site_occupied_or_blocked"
	var route: PackedVector2Array=u.navigation_path(p)
	if route.is_empty() or route[-1].distance_to(p)>.06:return "no_route"
	var slot: Dictionary={}
	if intent in ["occupy_cover","peek_fire"]:
		var key: String=str(option.get("cover_key",""))
		if key.is_empty():return "site_has_no_cover"
		for cover in game.field.covers:
			if not cover.get("alive",false):continue
			for candidate in game.field.slots(cover):
				if str(candidate.get("key",""))==key and candidate.position.distance_to(p)<.075:
					if str(game.field.reservations.get(key,"")) not in ["",u.id]:return "cover_reserved"
					slot=candidate;break
			if not slot.is_empty():break
		if slot.is_empty():return "cover_destroyed_or_changed"
	if intent=="peek_fire":
		if target_id not in option.get("fire_targets",[]):return "no_verified_fire_lane"
	if option.get("kind","")=="anti_armor_throw_site":
		var throw_target=null
		for enemy in game.living():
			if enemy.id==str(option.get("target_id","")) and enemy.tank and enemy.faction!=u.faction and visible_to(u.faction,enemy):throw_target=enemy;break
		if throw_target==null or u.satchel_lane_at(throw_target,p)!="":return "throw_site_no_longer_clear"
	var charge_target: String=""
	if intent=="rush_to_site" and option.get("kind","") in ["anti_armor_approach","anti_armor_throw_site"] and u.hp/u.max_hp>=.35 and u.suppression<.35 and game.elapsed>=u.harness_satchel_ready_at:
		for enemy in game.living():
			if enemy.id==str(option.get("target_id","")) and enemy.tank and enemy.faction!=u.faction and visible_to(u.faction,enemy):charge_target=enemy.id;break
	if not request_motion(u,s,"personal",p,slot):return "execution_owned"
	if intent=="peek_fire":u.focus_id=target_id
	if intent=="rush_to_site":intent_executor.request_posture(u,"stand",s.order_id,game.elapsed)
	elif intent=="prone_approach":intent_executor.request_posture(u,"prone",s.order_id,game.elapsed)
	else:intent_executor.cancel_posture(u,"new_personal_action",game.elapsed)
	u.formation_speed=1.4 if intent=="rush_to_site" else 1.0
	u.order_mode="soldier_"+intent
	if not charge_target.is_empty():
		u.set_meta("harness_antiarmor_charge_until",game.elapsed+4.5)
		u.set_meta("harness_antiarmor_target_id",charge_target)
	s.personal[u.id]={"intent":intent,"status":"active","order_id":s.order_id,"until":game.elapsed+6,"position":[p.x,p.y],"site_id":str(c.get("site_id","")),"candidate_query_id":str(c.get("candidate_query_id","")),"target_id":target_id,"wait_order":old.get("wait_order","")}
	return "applied"
