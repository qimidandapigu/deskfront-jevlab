extends Node
## 持续小队执行器：参考 Jurney 的 virtual leader / destination reservation。
## DeepSeek 给目标区，JEV 拥有意图，本模块只维护动作与可观察反馈。
const PerceptionLogic=preload("res://scripts/human_squad_perception.gd")
const SnapshotWriter=preload("res://scripts/human_squad_snapshot.gd")
var game
var squads: Dictionary={}
var owners: Dictionary={}
var perception: Dictionary={}
var event_seq: int=0
var events: Array=[]
var clock: float=0
var _perception_logic
var _snapshot_writer

func setup(g) -> void:
	game=g
	_perception_logic=PerceptionLogic.new(self)
	_snapshot_writer=SnapshotWriter.new(self)

# Shared locomotion gate for managed soldiers. Sources propose destinations;
# the accepted owner alone may replace the route until completion or expiry.
func request_motion(u, s: Dictionary, source: String, destination: Vector2, slot: Dictionary={}) -> bool:
	if u.hp<=0 or game.elapsed<u.safety_until or u.grenade_time>=0:return false
	if source!="personal" and personal_owned(u,s):return false
	if source in ["formation","fire_position"] and s.get("mover","")!="" and s.get("support_ids",[]).has(u.id):return false
	var priorities: Dictionary={"formation":10,"station":20,"fire_position":30,"bound":40,"personal":50}
	var current: Dictionary=u.get_meta("motion_owner",{})
	var valid: bool=current.get("order_id")==s.get("order_id") and game.elapsed<float(current.get("until",0)) and not u.route.is_empty()
	if valid and current.get("source")!=source and int(current.get("priority",0))>=int(priorities.get(source,0)):return false
	if slot.is_empty():u.move_to(destination,source=="fire_position")
	else:u.occupy(slot)
	u.set_meta("motion_owner",{"source":source,"priority":priorities.get(source,0),"order_id":s.get("order_id"),"until":game.elapsed+6,"destination":[destination.x,destination.y]})
	return true

func request_fire_adjustment(u, destination: Vector2) -> bool:
	var sid: String=owners.get(u.id,"")
	if not squads.has(sid):return false
	return request_motion(u,squads[sid],"fire_position",destination)

func emit(kind: String, team: String, squad_id: String="", unit_id: String="", detail: Dictionary={}) -> void:
	event_seq+=1
	var item: Dictionary={"seq":event_seq,"kind":kind,"faction":team,"squad_id":squad_id,"unit_id":unit_id,"time":game.elapsed}
	item.merge(detail,true);events.append(item)
	if events.size()>64:events.pop_front()

func visible_to(team: String, enemy) -> bool:
	return _perception_logic.visible_to(team,enemy)

func update_perception() -> void:
	_perception_logic.update()

func visible_enemy(u):
	return _perception_logic.visible_enemy(u)

func threat_points(team: String) -> Array:
	return _perception_logic.threat_points(team)

func cancel(team: String, ids: Array=[]) -> void:
	for sid in squads.keys():
		var s: Dictionary=squads[sid]
		if s.faction!=team:continue
		if ids.is_empty() or s.unit_ids.any(func(id):return ids.has(id)):
			for uid in s.unit_ids:owners.erase(uid)
			squads.erase(sid)

func accept(c: Dictionary) -> String:
	var sid: String=str(c.get("squad_id",""))
	var order: String=str(c.get("order_id",""))
	var ids: Array=c.get("unit_ids",[])
	var team: String=str(c.faction)
	if sid.is_empty() or sid.length()>100 or order.is_empty() or order.length()>160:return "invalid_squad_identity"
	if ids.is_empty() or ids.size()>10 or ids.any(func(id):return ids.count(id)>1):return "invalid_squad_members"
	if c.get("intent","") not in ["advance","cover","bound","flank","hold","regroup"]:return "invalid_squad_intent"
	if not c.has("position") or not (c.get("radius") is float or c.get("radius") is int):return "invalid_squad_region"
	var radius: float=float(c.radius)
	if not is_finite(radius) or radius<.06 or radius>2:return "invalid_squad_region"
	var goal := Vector2(c.position[0],c.position[1])
	if not game.field.walkable(goal):return "region_not_walkable"
	if squads.has(sid) and squads[sid].faction!=team:return "invalid_squad_authority"
	for uid in ids:
		if owners.has(uid) and owners[uid]!=sid:return "squad_member_already_owned"
	var members: Array=game.living(team).filter(func(u):return ids.has(u.id))
	if members.size()!=ids.size():return "invalid_unit_authority"
	if members.any(func(u):return u.gun_id!="" or u.garrison_phase!=""):return "leave_equipment_first"
	var assignments: Dictionary={}
	if not c.get("assignments",{}) is Dictionary:return "invalid_assignments"
	for uid in c.get("assignments",{}):
		var row=c.assignments[uid]
		if not ids.has(uid) or not row is Dictionary or row.get("role","") not in ["establish_fire","maneuver","fire_support"]:return "invalid_assignments"
		assignments[uid]=row.duplicate(true)
	var previous: Dictionary=squads.get(sid,{})
	if previous.get("order_id","")==order:return "applied"
	# Equivalent five-second review renews identity without restarting formation slots.
	if not previous.is_empty() and previous.get("phase","")!="blocked" and previous.get("assignments",{})==assignments and previous.unit_ids==ids and previous.intent==c.intent and previous.goal.distance_to(goal)<.035 and absf(previous.radius-radius)<.01:
		for u in members:
			var motion: Dictionary=u.get_meta("motion_owner",{})
			if motion.get("order_id")==previous.order_id:motion.order_id=order
		for row in previous.get("personal",{}).values():
			if row.get("order_id")==previous.order_id:row.order_id=order
			if row.get("wait_order")==previous.order_id:row.wait_order=order
		previous.order_id=order;previous.reason=str(c.get("reason",previous.reason));return "applied"
	for uid in previous.get("unit_ids",[]):owners.erase(uid)
	game.tactics_ai.cancel_selected(team,ids)
	var anchor: Vector2=game.tactics_ai.squad_center(members)
	var s: Dictionary={"squad_id":sid,"faction":team,"unit_ids":ids.duplicate(),"order_id":order,"intent":c.intent,"goal":goal,"radius":radius,"anchor":anchor,"rally":anchor,"rally_destinations":{},"regrouped":false,"path":game.field.tactical_path(anchor,goal,threat_points(team),team),"revision":game.field.revision,"phase":"assembling","reason":str(c.get("reason","执行小队意图")),"progress":0.0,"start_distance":maxf(.03,anchor.distance_to(goal)),"mover":"","turn":0,"since":game.elapsed,"arrived":false,"route_failed":false,"support_lost":false,"last":{},"destinations":{},"shape":"wedge","next_cover":0.0}
	s["duties"]=previous.get("duties",{})
	s["assignments"]=assignments
	for u in members:
		owners[u.id]=sid;u.target_id="";u.focus_id="";u.order_mode="squad_"+str(c.intent);u.formation_speed=1
		if game.elapsed>=u.safety_until and not personal_owned(u,s):u.route.clear();u.goal=u.pos()
		s.last[u.id]={"alive":true,"cover":u.cover_id,"cover_position":u.cover_slot.get("position",u.pos()),"failure":u.path_failure}
	squads[sid]=s
	emit("order_started",team,sid,"",{"order_id":order,"intent":c.intent})
	return "applied"

# 个人执行权限是短时租约，始终绑定当前团队命令；不能覆盖真实自保。
func personal_owned(u,s: Dictionary) -> bool:
	var row: Dictionary=s.get("personal",{}).get(u.id,{})
	return row.get("status","") in ["active","suspended"] and game.elapsed<float(row.get("until",0)) and row.get("order_id")==s.order_id

# Bounded per-soldier execution slot. Store intent, never replay a stale movement route.
func personal_transition(row: Dictionary, status: String, reason: String="") -> void:
	if row.get("status","")==status:return
	var trace: Array=row.get("transitions",[])
	trace.append({"from":row.get("status",""),"to":status,"reason":reason,"time":game.elapsed})
	if trace.size()>8:trace.pop_front()
	row.transitions=trace;row.status=status;row.transition_reason=reason

func accept_personal(c: Dictionary) -> String:
	var sid: String=str(c.get("squad_id",""))
	if not squads.has(sid):return "missing_squad"
	var s: Dictionary=squads[sid]
	if s.faction!=c.faction or s.order_id!=c.get("order_id"):return "stale_soldier_assignment"
	var ids: Array=c.get("unit_ids",[])
	if ids.size()!=1 or not s.unit_ids.has(ids[0]):return "invalid_unit_authority"
	var matches: Array=game.living(s.faction).filter(func(u):return u.id==ids[0])
	if matches.is_empty():return "invalid_unit_authority"
	var u=matches[0]
	var intent: String=str(c.get("intent",""))
	if intent not in ["adjust_position","take_cover","wait_support","report_blocked"]:return "invalid_soldier_intent"
	if not s.has("personal"):s.personal={}
	var old: Dictionary=s.personal.get(u.id,{})
	if intent=="report_blocked":
		if game.elapsed-float(old.get("reported_at",-100))>=5:
			emit("participation_gap",s.faction,sid,u.id,{"reason":"soldier_reports_assignment_blocked"})
			old.reported_at=game.elapsed;s.personal[u.id]=old
		return "applied"
	if game.elapsed<u.safety_until or u.suppression>=.35 or game.elapsed-u.last_threat_at<2:return "survival_override"
	if not u.route.is_empty() or u.reload_timer>0:return "action_busy"
	if personal_owned(u,s):return "personal_action_active"
	# 不得让正在掩护移动同伴的士兵自行换位。
	if s.get("mover","")!="" and (s.mover==u.id or s.get("support_ids",[]).has(u.id)):return "team_handoff_active"
	if intent=="wait_support":
		if not u.in_cover():return "wait_requires_protection"
		if old.get("wait_order")==s.order_id:return "wait_already_used_report_or_act"
		s.personal[u.id]={"intent":intent,"status":"active","order_id":s.order_id,"until":game.elapsed+4,"wait_order":s.order_id,"waiting_for":"actual_support"}
		return "applied"
	var threats: Array=threat_points(s.faction)
	if threats.is_empty():return "no_known_threat"
	var opts: Dictionary={"tactical_path":true,"tactical_cache_key":s.faction,"threats":threats,"range":u.weapon_config().range,"max_travel":.25,"goal_leash":.25,"reserve":false,"allow_same":false,"max_exposure":.12}
	if intent=="adjust_position":
		opts.require_fire_arc=true;opts.fire_query=func(point):return has_firing_lane(u,point)
		opts.fire_targets=game.living().filter(func(enemy):return enemy.faction!=u.faction and visible_to(u.faction,enemy)).map(func(enemy):return enemy.aim_point())
	var slot: Dictionary=game.field.choose_cover(u.id,u.pos(),threats[0],u.pos(),opts)
	if slot.is_empty() or not destination_free(u,slot.position,s):return "no_safe_personal_position"
	if not request_motion(u,s,"personal",slot.position,slot):return "execution_owned"
	u.order_mode="soldier_"+intent
	s.personal[u.id]={"intent":intent,"status":"active","order_id":s.order_id,"until":game.elapsed+6,"wait_order":old.get("wait_order",""),"waiting_for":"arrival"}
	return "applied"

func update_personal(s: Dictionary,members: Array) -> void:
	for uid in s.get("personal",{}).keys():
		var row: Dictionary=s.personal[uid]
		var matches: Array=members.filter(func(u):return u.id==uid)
		if matches.is_empty():s.personal.erase(uid);continue
		if row.get("status","") not in ["active","suspended"]:continue
		var u=matches[0]
		var reason: String=""
		if row.order_id!=s.order_id:reason="assignment_changed"
		elif game.elapsed>=float(row.until):reason="wait_expired" if row.intent=="wait_support" else "movement_timeout"
		elif game.elapsed<u.safety_until or u.suppression>=.35:
			personal_transition(row,"suspended","survival_override")
			continue
		elif row.status=="suspended":
			# Let the safety route finish; do not overwrite it on the first safe tick.
			if not u.route.is_empty() or game.elapsed-u.last_threat_at<2:continue
			if row.intent=="wait_support":
				if not u.in_cover():reason="resume_requires_protection"
				else:personal_transition(row,"active","protection_revalidated")
			else:
				personal_transition(row,"revalidating","danger_cleared")
				var result: String=accept_personal({"squad_id":s.squad_id,"faction":s.faction,"order_id":s.order_id,"unit_ids":[uid],"intent":row.intent})
				if result=="applied":
					var resumed: Dictionary=s.personal[uid]
					resumed.until=row.until;resumed.transitions=row.get("transitions",[]);resumed.status="revalidating"
					personal_transition(resumed,"active","position_revalidated")
				else:reason="resume_failed:"+result
			if reason.is_empty():continue
		elif row.intent=="wait_support" and not supporting_members(u,members).is_empty():reason="support_available"
		elif row.intent!="wait_support" and u.route.is_empty():reason="arrived" if u.in_cover() else "position_unresolved"
		elif game.elapsed>=float(row.until):reason="wait_expired" if row.intent=="wait_support" else "movement_timeout"
		if reason!="":
			personal_transition(row,reason,reason)
			if reason in ["movement_timeout","assignment_changed"] and game.elapsed>=u.safety_until:u.route.clear();u.goal=u.pos()
			if reason in ["wait_expired","position_unresolved","movement_timeout","resume_requires_protection"] or reason.begins_with("resume_failed:"):emit("participation_gap",s.faction,s.squad_id,uid,{"reason":reason})

func tick(dt: float) -> void:
	if not game.human_squad:return
	clock-=dt
	if clock>0:return
	clock=.2
	update_perception()
	for sid in squads.keys():
		var s: Dictionary=squads[sid]
		if game.control[s.faction] not in ["lm","agent"]:cancel(s.faction);continue
		update_squad(sid,s)

func note_members(sid: String,s: Dictionary) -> Array:
	var members: Array=[]
	for uid in s.unit_ids:
		var matches: Array=game.units.filter(func(u):return u.id==uid)
		if matches.is_empty():continue
		var u=matches[0]
		var prev: Dictionary=s.last.get(uid,{"alive":true,"cover":"","failure":""})
		if u.hp<=0:
			if prev.alive:emit("ally_down",s.faction,sid,uid)
			prev.alive=false;s.last[uid]=prev
			for key in ["duties","personal","fire_positions"]:
				if s.has(key):s[key].erase(uid)
			continue
		if prev.cover!="" and u.cover_id!=prev.cover:
			var intact: bool=game.field.covers.any(func(c):return c.id==prev.cover and c.alive)
			var former_position: Vector2=prev.get("cover_position",u.pos())
			var flanked: bool=threat_points(s.faction).any(func(p):return game.field.line_of_sight(former_position,p) and game.field.protection(former_position,p)<.2)
			if not intact or flanked:emit("cover_invalidated",s.faction,sid,uid,{"cover_id":prev.cover,"reason":"destroyed" if not intact else "flanked"})
		if u.path_failure=="no_safe_route" and prev.failure!=u.path_failure:emit("route_failed",s.faction,sid,uid)
		s.last[uid]={"alive":true,"cover":u.cover_id,"cover_position":u.cover_slot.get("position",u.pos()),"failure":u.path_failure}
		members.append(u)
	return members

func has_firing_lane(u, point: Vector2) -> bool:
	return game.living().any(func(enemy):return enemy.faction!=u.faction and visible_to(u.faction,enemy) and (not enemy.tank or u.weapon in ["rocket","cannon"]) and point.distance_to(enemy.pos())<=u.weapon_config().range and u.firing_solution_at(enemy,point,"crouch").clear)

func local_cover(u,s: Dictionary,near: Vector2,max_travel: float=.45,progressing: bool=false,max_exposure: float=INF,require_fire: bool=false) -> bool:
	if personal_owned(u,s):return true
	var threats: Array=threat_points(s.faction)
	if threats.is_empty():return false
	var near_flag: bool=s.goal.distance_to(game.objective)+s.radius<=game.config.rules.capture_radius
	var options: Dictionary={"tactical_path":true,"tactical_cache_key":s.faction,"threats":threats,"range":u.weapon_config().range,"max_travel":max_travel,"max_exposure":max_exposure,"reserve":false,"allow_same":not progressing,"goal_leash":(s.radius if near_flag else maxf(s.radius,.35)) if near.distance_to(s.goal)<=s.radius else max_travel}
	if require_fire:
		options.require_fire_arc=true
		options.fire_query=func(point):return has_firing_lane(u,point)
		options.fire_targets=game.living().filter(func(enemy):return enemy.faction!=u.faction and visible_to(u.faction,enemy) and (not enemy.tank or u.weapon in ["rocket","cannon"])).map(func(enemy):return enemy.aim_point())
	var slot: Dictionary=game.field.choose_cover(u.id,u.pos(),threats[0],near,options)
	if slot.is_empty():return false
	if progressing and slot.position.distance_to(s.goal)>=u.pos().distance_to(s.goal)-.025:return false
	# 目标区域允许有限的掩体偏移；实际候选在 choose_cover 内逐个检查。
	if u.cover_slot.get("key","")==slot.key:
		if not u.in_cover() and u.route.is_empty():return request_motion(u,s,"station",slot.position,slot)
		return true
	return request_motion(u,s,"bound" if progressing else "station",slot.position,slot)

# 行进中的局部掩体偏移有期限，结束后恢复原战略路线；不把看见敌人当作受火。
func under_pressure(members: Array) -> bool:
	return members.any(func(u):return game.elapsed-u.last_threat_at<2 or u.suppression>=.55 or game.elapsed<u.safety_until)

func moving_cover(u,s: Dictionary,near: Vector2) -> bool:
	if not s.has("cover_detours"):s.cover_detours={}
	if not s.has("cover_cooldowns"):s.cover_cooldowns={}
	for uid in s.cover_detours.keys():
		if uid!=u.id and (game.elapsed>=float(s.cover_detours[uid].until) or not game.living(s.faction).any(func(v):return v.id==uid)):
			s.cover_detours.erase(uid);s.cover_cooldowns[uid]=game.elapsed+4
			emit("cover_detour_complete",s.faction,s.squad_id,uid)
	var detour: Dictionary=s.cover_detours.get(u.id,{})
	if not detour.is_empty():
		if game.elapsed<float(detour.until) and not u.route.is_empty():return true
		s.cover_detours.erase(u.id);s.cover_cooldowns[u.id]=game.elapsed+4
		emit("cover_detour_complete",s.faction,s.squad_id,u.id)
		return false
	if game.elapsed<float(s.cover_cooldowns.get(u.id,0)) or not s.cover_detours.is_empty():return false
	# 只偏向前方近处的真实掩体；没有掩体则继续走，不制造等待。
	s.cover_cooldowns[u.id]=game.elapsed+1
	if not local_cover(u,s,near,.18,true):return false
	if u.route.is_empty():return false
	s.cover_detours[u.id]={"until":game.elapsed+2.5}
	u.order_mode="squad_cover_detour"
	emit("cover_detour_started",s.faction,s.squad_id,u.id)
	return true

func destination_free(u,p: Vector2,s: Dictionary) -> bool:
	for other in squads.values():
		for table in [other.destinations,other.rally_destinations]:
			for uid in table:
				if uid!=u.id and table[uid].distance_to(p)<.05:return false
	for uid in game.field.reserved_positions:
		if uid!=u.id and game.field.reserved_positions[uid].distance_to(p)<.05:return false
	return not game.living().any(func(v):return v!=u and v.route.is_empty() and v.pos().distance_to(p)<.045)

func protection_status(u,s: Dictionary,found: bool) -> void:
	if not s.has("protection"):s.protection={}
	var prior: Dictionary=s.protection.get(u.id,{})
	var state: String="protected" if u.in_cover() else ("seeking" if found or not u.route.is_empty() else ("unavailable" if not threat_points(s.faction).is_empty() else "no_known_threat"))
	var since: float=float(prior.get("since",game.elapsed)) if prior.get("state","")==state else game.elapsed
	s.protection[u.id]={"state":state,"since":since}
	if state=="unavailable" and game.elapsed-since>=2:
		s.phase="blocked";s.reason="附近没有可达且有效的保护位置，需要调整区域或重整"
		if game.elapsed-float(prior.get("notified_at",-100))>=10:
			emit("route_failed",s.faction,s.squad_id,u.id,{"reason":"no_reachable_protection"})
			s.protection[u.id].notified_at=game.elapsed
		else:s.protection[u.id].notified_at=prior.notified_at

func station(u,s: Dictionary,index: int,members: Array) -> void:
	if personal_owned(u,s):return
	if game.elapsed<u.safety_until or u.grenade_time>=0:return
	if not u.route.is_empty():return
	if u.in_cover():protection_status(u,s,true);return
	if local_cover(u,s,s.goal):protection_status(u,s,true);return
	protection_status(u,s,false)
	if not threat_points(s.faction).is_empty() and s.goal.distance_to(game.objective)+s.radius>game.config.rules.capture_radius:return
	if not s.destinations.has(u.id):
		var found: bool=false
		for sample in range(25):
			var angle: float=TAU*(float(index)/maxi(1,members.size())+float(sample%8)/8)
			var ring: float=minf(s.radius*.85,.06+.045*int(sample/8))
			var dest: Vector2=s.goal+Vector2(cos(angle),sin(angle))*ring if sample<24 else u.pos()
			if dest.distance_to(s.goal)>s.radius or not game.field.walkable(dest) or not destination_free(u,dest,s):continue
			if u.pos().distance_to(dest)>.025 and game.field.path(u.pos(),dest).is_empty():continue
			s.destinations[u.id]=dest;found=true;break
		if not found:
			if not s.route_failed:emit("route_failed",s.faction,s.squad_id,u.id,{"reason":"no_separated_destination"});s.route_failed=true
			return
	var destination: Vector2=s.destinations[u.id]
	if u.pos().distance_to(destination)>.035 and not request_motion(u,s,"station",destination):return
	u.order_mode="squad_overwatch";u.formation_speed=1

# 掩体有效不等于能支援；空闲射手有限换位，受火/恢复期间保持自保。
func maintain_fire_position(u,s: Dictionary) -> void:
	if personal_owned(u,s):return
	if not s.has("fire_positions"):s.fire_positions={}
	var status: Dictionary=s.fire_positions.get(u.id,{"since":game.elapsed,"next_check":0.0,"state":"observing"})
	s.fire_positions[u.id]=status
	if game.elapsed<u.safety_until or u.suppression>=.35 or game.elapsed-u.last_threat_at<2:
		status.since=game.elapsed;status.state="recovering";return
	if not u.route.is_empty() or u.reload_timer>0:
		status.since=game.elapsed
		if status.state!="relocating":status.state="moving_or_reloading"
		return
	if (game.find_target(u)!=null and str(u.get_meta("fire_block_reason","")).is_empty()) or game.elapsed-u.last_shot_at<4:
		status.since=game.elapsed;status.state="engaging";return
	var targets: Array=[]
	var threats: Array=[]
	for enemy in game.living():
		if enemy.faction==u.faction or not visible_to(u.faction,enemy) or (enemy.tank and u.weapon not in ["rocket","cannon"]):continue
		targets.append(enemy.aim_point());threats.append(enemy.pos())
	if targets.is_empty():status.since=game.elapsed;status.state="observing";return
	status.state="no_fire_lane"
	if game.elapsed-float(status.since)<4 or game.elapsed<float(status.next_check):return
	status.next_check=game.elapsed+8
	# hold 只报告；cover 允许换到附近掩体，但不自行变成冲锋命令。
	if s.intent=="cover" and not game.living(s.faction).any(func(v):return v!=u and not v.route.is_empty() and v.order_mode=="squad_firing_position"):
		var slot: Dictionary=game.field.choose_cover(u.id,u.pos(),threats[0],u.pos(),{"tactical_path":true,"tactical_cache_key":s.faction,"threats":threats,"range":u.weapon_config().range,"max_travel":.35,"goal_leash":.35,"reserve":false,"allow_same":false,"require_fire_arc":true,"fire_query":func(point):return has_firing_lane(u,point),"fire_targets":targets,"max_exposure":.20})
		if not slot.is_empty() and destination_free(u,slot.position,s):
			if not request_motion(u,s,"fire_position",slot.position,slot):return
			u.order_mode="squad_firing_position";status.state="relocating";status.since=game.elapsed;return
		# A usable firing point need not be a pre-authored cover slot. Try only short
		# side/back steps; never turn a blocked rocket into a forward assault.
		var away: Vector2=(u.pos()-threats[0]).normalized()
		for direction: Vector2 in [away.orthogonal(),-away.orthogonal(),away]:
			var point: Vector2=u.pos()+direction*.075
			if not game.field.walkable(point) or not game.field.segment_walkable(u.pos(),point) or not destination_free(u,point,s) or not has_firing_lane(u,point):continue
			var short_route: PackedVector2Array=game.field.path(u.pos(),point)
			if short_route.is_empty() or game.field.route_length(short_route)>.13 or game.field.route_exposure(short_route,threats)>.06:continue
			if not request_motion(u,s,"fire_position",point):return
			u.order_mode="squad_firing_position";status.state="relocating";status.since=game.elapsed;return
	status.state="unavailable"
	emit("participation_gap",s.faction,s.squad_id,u.id,{"reason":"no_safe_firing_position","weapon":u.weapon})

# 职责来自可观测执行，不把静止、路线存在或掩体存在冒充有效支援。
func update_duties(s: Dictionary,members: Array) -> void:
	if not s.has("duties"):s.duties={}
	for u in members:
		var row: Dictionary=s.duties.get(u.id,{"position":u.pos(),"progress_at":game.elapsed,"last_shot":u.last_shot_at,"notified_at":-100.0,"failures":0})
		if u.pos().distance_to(row.position)>.04 or u.last_shot_at>float(row.last_shot):
			row.progress_at=game.elapsed;row.position=u.pos();row.last_shot=u.last_shot_at;row.failures=0
		var role: String="observe";var reason: String="暂无可见威胁"
		if game.elapsed<u.safety_until or u.suppression>=.55:
			role="recover";reason="受火或压制中，优先自保"
		elif u.reload_timer>0:
			role="reload";reason="装填期间不计作有效火力"
		elif not str(u.get_meta("fire_block_reason","")).is_empty():
			role="blocked";reason=str(u.get_meta("fire_block_reason"))
		elif not u.route.is_empty():
			role="approach";reason="前往分配位置"
			if game.elapsed-float(row.progress_at)>6:role="blocked";reason="route_without_progress"
		elif game.tactics_ai.can_support(u):role="support";reason="当前具备射界并有实际开火记录"
		elif visible_enemy(u)!=null:
			role="acquire_fire";reason="尚未建立有效火力"
			if game.elapsed-float(row.progress_at)>6:role="blocked";reason="no_effective_fire"
		if role=="blocked" and game.elapsed-float(row.notified_at)>=8:
			row.notified_at=game.elapsed;row.failures+=1
			emit("participation_gap",s.faction,s.squad_id,u.id,{"reason":reason,"unresolved_for_s":game.elapsed-float(row.progress_at),"attempts":row.failures})
		row.role=role;row.reason=reason;s.duties[u.id]=row

func update_squad(sid: String,s: Dictionary) -> void:
	var members: Array=note_members(sid,s)
	if members.is_empty():s.phase="lost";s.reason="小队已失去战斗力";return
	update_personal(s,members)
	update_duties(s,members)
	var center: Vector2=game.tactics_ai.squad_center(members)
	s.progress=clampf(1-center.distance_to(s.goal)/float(s.start_distance),0,1)
	if s.intent=="regroup":
		s.phase="regrouping";s.reason="就地寻找保护，等待同伴重新收拢"
		if not s.has("protection"):s.protection={}
		var local: Dictionary=s.duplicate(false)
		local.goal=s.rally;local.radius=.16;local.destinations=s.rally_destinations
		for i in range(members.size()):station(members[i],local,i,members)
		s.protection=local.get("protection",{})
		if local.phase=="blocked":s.phase="blocked";s.reason=local.reason
		if not s.regrouped and s.phase!="blocked" and members.all(func(u):return u.pos().distance_to(s.rally)<.18 and u.route.is_empty() and (u.in_cover() or threat_points(s.faction).is_empty())):
			s.regrouped=true;emit("regrouped",s.faction,sid)
		if s.regrouped:s.phase="regrouped";s.reason="重整完成，等待下一阶段意图"
		elif game.elapsed-s.since>8 and members.all(func(u):return u.route.is_empty()):
			s.phase="blocked";s.reason="重整无法完成，需要重新选择集结位置"
			if not s.route_failed:emit("route_failed",s.faction,sid,"",{"reason":"regroup_unresolved"});s.route_failed=true
		return
	if s.intent in ["hold","cover"]:
		s.phase="taking_cover";s.reason="维持当前位置的保护与射界"
		for u in members:
			if game.elapsed>=u.safety_until:
				var found: bool=u.in_cover() or not u.route.is_empty() or local_cover(u,s,u.pos())
				protection_status(u,s,found)
			maintain_fire_position(u,s)
		# cover 是一个可完成的保护动作，不是无限驻守命令。hold 才是驻守。
		if s.intent=="cover":
			var ready: Array=members.filter(func(u):return game.elapsed>=u.safety_until and u.suppression<.35 and u.reload_timer<=0 and u.route.is_empty())
			if game.elapsed-s.since>=6 and not ready.is_empty():
				s.phase="cover_ready";s.reason="短时保护已完成，可用成员等待下一段行动"
				if not s.get("cover_ready_notified",false):
					emit("cover_ready",s.faction,sid,"",{"ready_ids":ready.map(func(u):return u.id)});s.cover_ready_notified=true
			elif game.elapsed-s.since>=12:
				s.phase="blocked";s.reason="保护阶段长期未恢复行动条件，需要重新选择路线或区域"
				if not s.get("cover_blocked_notified",false):
					emit("route_failed",s.faction,sid,"",{"reason":"cover_recovery_timeout"});s.cover_blocked_notified=true
		return
	if s.arrived or members.all(func(u):return u.pos().distance_to(s.goal)<=s.radius):
		s.phase="securing_position";s.reason="已接近目标，正在建立保护位置";s.progress=1.0
		for i in range(members.size()):station(members[i],s,i,members)
		if s.phase!="blocked" and members.all(func(u):return u.route.is_empty() and (u.in_cover() or threat_points(s.faction).is_empty())):
			s.phase="holding";s.reason="站位建立，保持观察"
		if not s.arrived:s.arrived=true;emit("arrived",s.faction,sid,"",{"order_id":s.order_id})
		return
	# Seeing an out-of-range enemy must not freeze the entire squad before firing range.
	var contact: bool=under_pressure(members) or (s.intent=="bound" and members.any(func(u):return game.find_target(u)!=null))
	if contact and s.intent in ["advance","bound","flank"]:
		if s.phase in ["advancing","assembling"]:
			for u in members:
				if game.elapsed>=u.safety_until and not personal_owned(u,s):u.route.clear();u.goal=u.pos()
			s.since=game.elapsed
		bound(sid,s,members);return
	if s.phase in ["bounding","establishing_support","blocked"]:
		# A completed bound moved the real squad; never send it back to an old virtual leader.
		s.anchor=center;s.path=game.field.tactical_path(center,s.goal,threat_points(s.faction),s.faction);s.revision=game.field.revision;s.mover="";s.route_failed=false
	advance(sid,s,members,center)

func supporting_members(candidate, members: Array) -> Array:
	var threat=visible_enemy(candidate)
	if threat==null:return []
	return members.filter(func(u):
		if u==candidate or game.elapsed<u.safety_until or not game.tactics_ai.can_support(u):return false
		# Recent fire must concern this mover's threat, not a newly selected unrelated target.
		return u.last_shot_target==threat.id and u.firing_solution_at(threat,u.pos(),u.posture).clear)

func bound(sid: String,s: Dictionary,members: Array) -> void:
	var movers: Array=members.filter(func(u):return u.id==s.mover)
	var mover=null if movers.is_empty() else movers[0]
	var supporters: Array=supporting_members(mover,members) if mover!=null else []
	# Recovery is edge-triggered: an expired wait must not permanently latch the squad.
	var support_ready: bool=members.any(func(u):return not supporting_members(u,members).is_empty())
	if support_ready and not s.get("support_ready",false):
		s.since=game.elapsed-1.2;s.route_failed=false;s.next_bound_search=0.0
		emit("support_restored",s.faction,sid)
	s.support_ready=support_ready
	# 机动者的中间落点不是火力接替点；原掩护仍有效时可继续下一小段。
	if mover!=null and mover.route.is_empty() and game.elapsed>=mover.safety_until and not supporters.is_empty() and s.get("assignments",{}).get(mover.id,{}).get("role","")=="maneuver" and mover.pos().distance_to(s.goal)>s.radius and game.find_target(mover)==null:
		s.mover="";s.erase("handoff_at");mover=null;s.since=game.elapsed-1.2
	if mover!=null:
		var probing: bool=bool(s.get("probing",false))
		if (supporters.is_empty() and not probing and not mover.route.is_empty()) or mover.suppression>=.55 or game.elapsed<mover.safety_until or (probing and mover.suppression>=.35):
			if not s.support_lost:emit("support_lost",s.faction,sid,mover.id)
			s.support_lost=true
			if game.elapsed>=mover.safety_until:mover.route.clear();mover.goal=mover.pos();local_cover(mover,s,mover.pos(),.18)
			s.mover="";s.phase="establishing_support";s.reason="实际掩护火力中断，推进者就地保护";return
		if mover.route.is_empty() and game.elapsed>=float(mover.safety_until) and not probing:
			if not s.has("handoff_at"):s.handoff_at=game.elapsed
			if not game.tactics_ai.can_support(mover):
				s.phase="establishing_support";s.reason="推进者已到位，等待建立射界接替火力"
				if game.elapsed-float(s.handoff_at)>4:
					s.phase="blocked";s.reason="新位置未形成接替火力，原掩护者继续守位"
					if not s.route_failed:emit("participation_gap",s.faction,sid,mover.id,{"reason":"handoff_no_fire"});s.route_failed=true
					if not s.has("retry_after"):s.retry_after={}
					s.retry_after[mover.id]=game.elapsed+8
					s.mover="";s.erase("handoff_at");s.turn+=1;s.since=game.elapsed
				return
		if mover.route.is_empty() or game.elapsed<float(mover.safety_until):
			s.erase("handoff_at");s.mover="";s.probing=false;s.turn+=1;s.since=game.elapsed
		else:s.phase="bounding";s.reason="一人分段推进，其余成员提供实际掩护";return
	s.phase="establishing_support";s.reason="等待有效火力后再推进"
	if game.elapsed-float(s.since)>5:
		s.phase="blocked";s.reason="掩护条件持续不满足，需要改变路线或执行方式"
		if not s.route_failed:emit("route_failed",s.faction,sid,"",{"reason":"support_unavailable"});s.route_failed=true
		return
	for u in members:
		if game.elapsed>=u.safety_until and game.elapsed-u.last_threat_at<2 and u.route.is_empty() and not u.in_cover():local_cover(u,s,u.pos(),.22)
	if game.elapsed-float(s.since)<1.2:return
	# Only expensive route/cover selection is throttled. Active movement safety runs above.
	if game.elapsed<float(s.get("next_bound_search",0)) and s.get("bound_revision",-1)==game.field.revision:return
	s.next_bound_search=game.elapsed+.8;s.bound_revision=game.field.revision
	# Fire support must first be established. A single-shot rocket is reloading immediately
	# after every shot and cannot truthfully count as sustained covering fire. Permit only
	# one healthy light-weapon member a short, abortable approach into an actual firing lane.
	if not members.any(func(u):return game.tactics_ai.can_support(u)):
		var starters: Array=members.duplicate()
		starters.sort_custom(func(a,b):
			var ar: String=s.get("assignments",{}).get(a.id,{}).get("role","")
			var br: String=s.get("assignments",{}).get(b.id,{}).get("role","")
			if (ar=="establish_fire")!=(br=="establish_fire"):return ar=="establish_fire"
			return float(a.weapon_config().range)>float(b.weapon_config().range))
		for candidate in starters:
			if game.elapsed<float(s.get("retry_after",{}).get(candidate.id,0)):continue
			if personal_owned(candidate,s) or candidate.tank or candidate.weapon=="rocket" or candidate.ammo<=0 or candidate.reload_timer>0 or candidate.hp/candidate.max_hp<.25 or candidate.suppression>=.35 or game.elapsed<candidate.safety_until or not candidate.route.is_empty():continue
			var enemy=visible_enemy(candidate)
			if enemy==null or game.elapsed-candidate.last_threat_at<2:continue
			var next: Vector2=game.field.soft_offset(candidate.pos(),candidate.pos().move_toward(s.goal,.16),.21)
			# 已处射程内也可以在低暴露路径上短移到前方有效掩体。
			# 不把这种移动称作已有火力掩护；途中受火会立即中止。
			if local_cover(candidate,s,next,.18,true,.06) and not candidate.route.is_empty():
				candidate.order_mode="squad_covered_approach"
				s.mover=candidate.id;s.probing=true;s.since=game.elapsed;s.phase="establishing_support";s.reason="一人沿低暴露短路移向前方掩体，其余观察"
				return
			if game.find_target(candidate)!=null:continue
			if next.distance_to(s.goal)>=candidate.pos().distance_to(s.goal)-.025 or next.distance_to(enemy.pos())>=candidate.pos().distance_to(enemy.pos())-.025:continue
			var route: PackedVector2Array=game.field.tactical_path(candidate.pos(),next,threat_points(s.faction),s.faction)
			if route.is_empty() or game.field.route_length(route)>.20 or game.field.route_exposure(route,threat_points(s.faction))>.18 or not has_firing_lane(candidate,next) or not destination_free(candidate,next,s):continue
			if not request_motion(candidate,s,"bound",next):continue
			candidate.order_mode="squad_establish_fire"
			s.mover=candidate.id;s.probing=true;s.since=game.elapsed;s.phase="establishing_support";s.reason="一人谨慎短移建立有效射位，其余保持观察"
			return
	var movers_ranked: Array=members.duplicate()
	movers_ranked.sort_custom(func(a,b):return s.get("assignments",{}).get(a.id,{}).get("role","")=="maneuver" and s.get("assignments",{}).get(b.id,{}).get("role","")!="maneuver")
	for i in range(movers_ranked.size()):
		var candidate=movers_ranked[i]
		if candidate.weapon in ["rocket","cannon"] or s.get("assignments",{}).get(candidate.id,{}).get("role","")=="fire_support":continue
		if game.elapsed<float(s.get("retry_after",{}).get(candidate.id,0)):continue
		if personal_owned(candidate,s) or game.elapsed<candidate.safety_until or candidate.suppression>.55 or not candidate.route.is_empty():continue
		if supporting_members(candidate,members).is_empty():continue
		var next: Vector2=candidate.pos().move_toward(s.goal,.16)
		next=game.field.soft_offset(candidate.pos(),next,.18)
		if next.distance_to(s.goal)>=candidate.pos().distance_to(s.goal)-.02:continue
		if not local_cover(candidate,s,next,.35,true,.20,false):
			# 有实际掩护时允许一段有限暴露的接近，不要求每段落点已经具备射界。
			if s.get("assignments",{}).get(candidate.id,{}).get("role","")!="maneuver":continue
			var step_route: PackedVector2Array=game.field.tactical_path(candidate.pos(),next,threat_points(s.faction),s.faction)
			if step_route.is_empty() or game.field.route_length(step_route)>.22 or game.field.route_exposure(step_route,threat_points(s.faction))>.18 or not destination_free(candidate,next,s):continue
			if not request_motion(candidate,s,"bound",next):continue
		if candidate.route.is_empty():continue
		s["support_ids"]=supporting_members(candidate,members).map(func(u):return u.id)
		s.erase("handoff_at");s.mover=candidate.id;s.support_lost=false;s.route_failed=false;s.since=game.elapsed;s.phase="bounding";s.reason="交替推进，掩护者留在射位";candidate.order_mode="squad_bound";return

func advance(sid: String,s: Dictionary,members: Array,center: Vector2) -> void:
	if s.revision!=game.field.revision or game.elapsed-float(s.get("path_review_at",-100))>=4:
		s.path=game.field.tactical_path(s.anchor,s.goal,threat_points(s.faction),s.faction);s.revision=game.field.revision;s.route_failed=false;s.path_review_at=game.elapsed
	var path: PackedVector2Array=s.path
	while not path.is_empty() and s.anchor.distance_to(path[0])<.02:path.remove_at(0)
	if path.is_empty() and s.anchor.distance_to(s.goal)>s.radius:
		s.phase="blocked";s.reason="通路失效，等待重新规划"
		if not s.route_failed:emit("route_failed",s.faction,sid);s.route_failed=true
		return
	if not path.is_empty() and s.anchor.distance_to(center)<.16:s.anchor=s.anchor.move_toward(path[0],game.config.tactics.run_speed*.2)
	s.path=path
	var heading: Vector2=(s.goal-s.anchor).normalized()
	if not path.is_empty():heading=(path[mini(3,path.size()-1)]-s.anchor).normalized()
	if heading.length()<.5:heading=Vector2.UP
	var side := Vector2(-heading.y,heading.x)
	var future: Vector2=game.field.soft_offset(s.anchor,s.anchor+heading*.06,.1)
	var narrow: bool=not game.field.walkable(future+side*.065) or not game.field.walkable(future-side*.065)
	s.shape="column" if narrow else "wedge";s.phase="advancing";s.reason="窄道收成纵列" if narrow else "按稳定队形行进，落后成员可追赶"
	var used: Array=[]
	for u in members:
		var i: int=s.unit_ids.find(u.id)
		if personal_owned(u,s) or game.elapsed<u.safety_until or u.grenade_time>=0:continue
		var offset: Vector2=-heading*i*.06 if narrow else side*(i-(s.unit_ids.size()-1)*.5)*.075-heading*(.025 if i%2==0 else 0.0)
		# 火箭筒保持后侧并横向错开，避免直线隔着队友发射；前排仍受安全约束。
		if u.weapon in ["rocket","cannon","at_cannon"]:offset-=heading*.12;offset+=side*.055

		var dest: Vector2=game.field.soft_offset(future,future+offset,.15)
		for shift in [Vector2.ZERO,side*.045,-side*.045,-heading*.06]:
			var alternative: Vector2=game.field.soft_offset(future,dest+shift,.15)
			if not used.any(func(p):return p.distance_to(alternative)<.035):dest=alternative;break
		used.append(dest)
		if moving_cover(u,s,dest):continue
		u.formation_speed=clampf(1+(s.anchor+offset-u.pos()).dot(heading)*2.5,.75,1.15)
		if u.goal.distance_to(dest)>.035 or (u.route.is_empty() and u.pos().distance_to(dest)>.035):
			if not request_motion(u,s,"formation",dest):continue
		u.order_mode="squad_formation"

func snapshot() -> Dictionary:
	return _snapshot_writer.write()
