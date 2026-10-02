extends RefCounted
var seen := ""
var candidate_seen: Dictionary={}
var candidate_results: Dictionary={}
var candidate_pending: Dictionary={}
var next_poll_usec: int=0
var poll_base: String=""
func tick(arena, output: String):
	if output=="":return
	var base=output.get_base_dir()
	var now: int=Time.get_ticks_usec()
	if base!=poll_base:poll_base=base;next_poll_usec=0
	if now<next_poll_usec:return
	next_poll_usec=now+50000
	for team in ["green","red"]:candidate_tick(arena,base,team)
	var path=base+"/move-check-request.json"
	var marker=base+"/move-check-request.id"
	var marker_token: String=""
	if FileAccess.file_exists(marker):
		marker_token=FileAccess.get_file_as_string(marker).strip_edges()
		if marker_token.is_empty() or marker_token==seen:return
	if not FileAccess.file_exists(path):return
	var request=JSON.parse_string(FileAccess.get_file_as_string(path))
	if marker_token!="" and request is Dictionary and str(request.get("id",""))!=marker_token:return
	if not request is Dictionary or str(request.get("id",""))==seen:return
	seen=str(request.get("id",""))
	var result={"id":seen,"run_id":arena.run_id,"valid":false,"reason":"stale_run","time":arena.elapsed}
	if request.get("run_id")==arena.run_id:
		var members=arena.living().filter(func(u):return u.id==request.get("unit_id"))
		result.reason="unit_unavailable"
		if not members.is_empty():
			var u=members[0];var p=Vector2(request.position[0],request.position[1])
			result.reason="destination_blocked"
			if arena.field.walkable(p) and not arena.living().any(func(v):return v!=u and v.pos().distance_to(p)<.06):
				var route_started: int=Time.get_ticks_usec()
				var route=u.navigation_path(p)
				arena.record_cost("validation/move_check_route",route_started)
				result.valid=not route.is_empty() and route[-1].distance_to(p)<.06
				result.reason="reachable" if result.valid else "no_route"
				result["path_length"]=arena.field.route_length(route)
	var file=FileAccess.open(base+"/move-check-response.json",FileAccess.WRITE)
	if file:file.store_string(JSON.stringify(result));file.close()

func candidate_tick(arena,base: String,team: String) -> void:
	var stem: String="soldier-candidates-"+team
	if candidate_pending.has(team):
		_candidate_shard(arena,base,team,stem)
		return
	var path: String=base+"/"+stem+"-request.json"
	var marker: String=base+"/"+stem+"-request.id"
	var marker_token: String=""
	if FileAccess.file_exists(marker):
		marker_token=FileAccess.get_file_as_string(marker).strip_edges()
		if marker_token.is_empty() or marker_token==candidate_seen.get(team,""):return
	if not FileAccess.file_exists(path):return
	# The Python writer replaces this file atomically, but a Windows read can
	# still observe a transient empty/invalid snapshot during replacement.
	# Retry on the next physics tick without reporting a game error.
	var request_raw: String=FileAccess.get_file_as_string(path)
	if request_raw.is_empty():return
	var request=JSON.parse_string(request_raw)
	if not request is Dictionary:return
	var token: String=str(request.get("id",""))
	if marker_token!="" and token!=marker_token:return
	if token.is_empty() or token==candidate_seen.get(team,""):return
	candidate_seen[team]=token
	var result: Dictionary={"id":token,"run_id":arena.run_id,"unit_id":str(request.get("unit_id","")),"status":"stale_run","options":[],"sampled_at":arena.elapsed,"navigation_revision":arena.field.revision}
	if request.get("run_id")==arena.run_id and request.get("navigation_revision")==arena.field.revision:
		var matches: Array=arena.living(team).filter(func(v):return v.id==request.get("unit_id"))
		result.status="unit_unavailable"
		if not matches.is_empty():
			var u=matches[0]
			result.status="fresh"
			result["unit_position"]=[u.pos().x,u.pos().y]
			var contacts: Dictionary=arena.human_squads.perception.get(team,{}) if arena.human_squads else {}
			var enemies: Array=[]
			for contact in contacts.values():
				if not bool(contact.get("visible",false)):continue
				for enemy in arena.living():
					if enemy.id==contact.get("id") and enemy.faction!=team:enemies.append(enemy)
			var cover_slots: Array=[]
			var cover_started: int=Time.get_ticks_usec()
			for cover in arena.field.covers:
				if cover.get("alive",false):
					for slot in arena.field.slots(cover):
						if slot.get("position") is Vector2:cover_slots.append(slot)
			arena.record_cost("validation/cover_slots",cover_started)
			var proposals: Array=request.get("proposals",[])
			if proposals.size()>12:proposals.resize(12)
			candidate_pending[team]={"request":request,"result":result,"proposals":proposals,"index":0,"u":u,"enemies":enemies,"cover_slots":cover_slots}
			_candidate_shard(arena,base,team,stem)
			return
	_candidate_finish(arena,base,team,stem,result)

func _candidate_shard(arena,base: String,team: String,stem: String) -> void:
	var pending: Dictionary=candidate_pending.get(team,{})
	if pending.is_empty():return
	var result: Dictionary=pending["result"]
	var u=pending["u"]
	if not is_instance_valid(u) or not arena.living().has(u):
		result.status="unit_unavailable"
		result["options"]=[]
		candidate_pending.erase(team)
		_candidate_finish(arena,base,team,stem,result)
		return
	var proposals: Array=pending["proposals"]
	var index: int=pending["index"]
	var processed: int=0
	var started: int=Time.get_ticks_usec()
	while index<proposals.size():
		_candidate_proposal(arena,team,pending,proposals[index])
		index+=1
		processed+=1
		if processed>=2 and Time.get_ticks_usec()-started>=4000:break
	arena.record_cost("validation/shard",started)
	pending["index"]=index
	if index>=proposals.size():
		candidate_pending.erase(team)
		_candidate_finish(arena,base,team,stem,result)

func _candidate_proposal(arena,team: String,pending: Dictionary,proposal) -> void:
	var result: Dictionary=pending["result"]
	var u=pending["u"]
	var enemies: Array=pending["enemies"]
	var cover_slots: Array=pending["cover_slots"]
	if not proposal is Dictionary:return
	var raw: Variant=proposal.get("position",[])
	if not raw is Array or raw.size()!=2:return
	if not (raw[0] is float or raw[0] is int) or not (raw[1] is float or raw[1] is int):return
	var p:=Vector2(float(raw[0]),float(raw[1]))
	if not is_finite(p.x) or not is_finite(p.y) or not arena.field.walkable(p):return
	if arena.living().any(func(v):return v!=u and v.pos().distance_to(p)<.07):return
	var route_started: int=Time.get_ticks_usec()
	# A shortlist only needs physical reachability. The selected order is
	# revalidated with the soldier's threat-weighted route before execution.
	var route: PackedVector2Array=arena.field.path(u.pos(),p)
	arena.record_cost("validation/route",route_started)
	if route.is_empty() or route[-1].distance_to(p)>.06:return
	if proposal.get("kind","")=="anti_armor_throw_site":
		var armor=null
		for enemy in enemies:
			if enemy.id==str(proposal.get("target_id","")) and enemy.tank:armor=enemy;break
		if armor==null or not u.has_method("satchel_lane_at") or u.satchel_lane_at(armor,p)!="":return
	var fire_targets: Array=[]
	var potential_attackers: int=0
	var fire_started: int=Time.get_ticks_usec()
	for enemy in enemies:
		if enemy.tank and u.weapon not in ["rocket","cannon"]:continue
		if p.distance_to(enemy.pos())<=float(u.weapon_config().range) and u.firing_solution_at(enemy,p,"stand").get("clear",false):fire_targets.append(enemy.id)
	arena.record_cost("validation/fire_lane",fire_started)
	var threat_started: int=Time.get_ticks_usec()
	for enemy in arena.living():
		if enemy.faction==team or p.distance_to(enemy.pos())>float(enemy.weapon_config().range):continue
		if arena.field.line_of_sight(enemy.pos(),p):potential_attackers+=1
	arena.record_cost("validation/threat",threat_started)
	var cover_key: String=""
	var cover_id: String=""
	var hard: bool=false
	var cover_match_started: int=Time.get_ticks_usec()
	for slot in cover_slots:
		if slot.position.distance_to(p)>.075:continue
		if str(arena.field.reservations.get(slot.key,"")) not in ["",u.id]:continue
		cover_key=str(slot.key);cover_id=str(slot.cover_id);hard=bool(slot.hard);break
	arena.record_cost("validation/cover_match",cover_match_started)
	result.options.append({"id":str(proposal.get("id","")),"region_id":str(proposal.get("region_id","")),"position":[p.x,p.y],"path_length":arena.field.route_length(route),"fire_targets":fire_targets,"potential_attackers":potential_attackers,"cover_key":cover_key,"cover_id":cover_id,"hard_cover":hard,"kind":str(proposal.get("kind","navigation_sample")),"target_id":str(proposal.get("target_id","")),"target_distance":proposal.get("target_distance",null)})

func _candidate_finish(arena,base: String,team: String,stem: String,result: Dictionary) -> void:
	result["sampled_at"]=arena.elapsed
	var token: String=str(result.get("id",""))
	var cache: Dictionary=candidate_results.get(team,{})
	for old_id in cache.keys():
		if arena.elapsed-float(cache[old_id].get("sampled_at",-100))>12:cache.erase(old_id)
	cache[token]=result.duplicate(true)
	while cache.size()>32:cache.erase(cache.keys()[0])
	candidate_results[team]=cache
	if arena.human_squads:arena.human_squads.set_meta("candidate_results_"+team,cache.duplicate(true))
	var file=FileAccess.open(base+"/"+stem+"-response.json",FileAccess.WRITE)
	if file:file.store_string(JSON.stringify(result));file.close()

func candidate_for(team: String,token: String,unit_id: String,site_id: String) -> Dictionary:
	var result: Dictionary=candidate_results.get(team,{}).get(token,{})
	if result.get("id")!=token or result.get("status")!="fresh" or result.get("unit_id")!=unit_id:return {}
	for option in result.get("options",[]):
		if option.get("id")==site_id:return option
	return {}
