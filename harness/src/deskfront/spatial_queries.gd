extends RefCounted
# Read-only native geometry queries. No unit state is moved to probe a point.
var next_at := 0.0
var next_wall_at := 0
var run_id := ""
var topology_key := ""
var topology_cells := {}

# Potential exposure, not a hit predictor. No probing mutates actors or navigation.
func threats_at(arena, p: Vector2, friendly_faction: String="green"):
	var eye = Vector3(p.x,arena.field.ground_height(p)+.093,p.y)
	var threats = []
	for enemy in arena.living():
		if enemy.faction==friendly_faction:continue
		var cfg = enemy.weapon_config()
		if p.distance_to(enemy.pos())>float(cfg.range):continue
		if not arena.field.trace_cover(enemy.muzzle_position(eye),eye).is_empty():continue
		var ready = maxf(enemy.cooldown,enemy.reload_timer)
		if enemy.ammo<=0 and enemy.reload_timer<=0:ready=maxf(ready,float(cfg.reload))
		threats.append({"id":enemy.id,"ready_in_s":ready,"damage_per_hit":cfg.damage})
	return threats

func path_risk(arena, u, destination: Vector2):
	var result = {"status":"unreachable","origin":[u.pos().x,u.pos().y],"destination":[destination.x,destination.y],"observed_at":arena.elapsed}
	var faction_value=u.get("faction")
	var friendly_faction: String=str(faction_value) if faction_value!=null else "green"
	var path = u.navigation_path(destination)
	if path.is_empty() or path[-1].distance_to(destination)>.06:return result
	var points = [u.pos()]
	for p in path:
		if points[-1].distance_to(p)>.001:points.append(p)
	var length = arena.field.route_length(points)
	var speed = float(arena.config.tactics.get(u.locomotion+"_speed",arena.config.tactics.run_speed))
	if u.locomotion=="crouch_run":speed=float(arena.config.tactics.crouch_speed)
	speed=maxf(.001,speed*(float(arena.config.soldier.speed)/.12)*(1-u.suppression*.18)*u.formation_speed)
	var exposed = 0;var peak = 0;var attackers = {}
	# Equal-distance midpoints, not navigation node indices (which bias sparse paths).
	for sample in range(12):
		var remaining = length*(sample+.5)/12.0
		var p = u.pos()
		for i in range(1,points.size()):
			var segment = points[i-1].distance_to(points[i])
			if remaining<=segment:
				p=points[i-1].lerp(points[i],remaining/maxf(segment,.001));break
			remaining-=segment;p=points[i]
		var threats = threats_at(arena,p,friendly_faction)
		peak=maxi(peak,threats.size())
		if not threats.is_empty():exposed+=1
		for threat in threats:attackers[threat.id]=true
	result.merge({"status":"sampled","path_length":length,"travel_s":length/speed,"exposed_s":length/speed*exposed/12.0,"peak_attackers":peak,"attackers":attackers.keys(),"endpoint_attackers":threats_at(arena,destination,friendly_faction).size()},true)
	return result

# Query exact global topology samples, not actor-offset grid positions. Region
# routing uses this same coordinate system, so Python can match a chosen short
# step without pretending that the nearest firing point has the same risk.
func navigation_steps(arena, u, cache):
	var nearest_id = "";var nearest_distance = INF
	for id in topology_cells:
		var raw = topology_cells[id]
		var distance = u.pos().distance_to(Vector2(raw[0],raw[1]))
		if distance<nearest_distance:nearest_id=id;nearest_distance=distance
	if nearest_id=="" or nearest_distance>.12:return []
	var parts = nearest_id.split(",")
	var center = Vector2i(int(parts[0]),int(parts[1]))
	var ids = [nearest_id]
	# Ordered region routing stops at a corner or .25 world units. Three .075
	# grid edges plus the nearest-grid approach cover these straight short steps.
	# Query at most thirteen positions instead of all ~49 points in a disk.
	for direction in [Vector2i.LEFT,Vector2i.RIGHT,Vector2i.UP,Vector2i.DOWN]:
		var previous = Vector2(topology_cells[nearest_id][0],topology_cells[nearest_id][1])
		for n in range(1,4):
			var index = center+direction*n
			var id = str(index.x)+","+str(index.y)
			if not topology_cells.has(id):break
			var raw = topology_cells[id];var p = Vector2(raw[0],raw[1])
			if not arena.field.segment_walkable(previous,p):break
			ids.append(id);previous=p
	var result = []
	for id in ids:
		var raw = topology_cells[id];var p = Vector2(raw[0],raw[1])
		if u.pos().distance_to(p)<.005 or u.pos().distance_to(p)>.325:continue
		if arena.living().any(func(v):return v!=u and v.pos().distance_to(p)<.06):continue
		var key = JSON.stringify(raw)
		if not cache.has(key):cache[key]=path_risk(arena,u,p)
		result.append({"cell_id":id,"position":raw,"risk":cache[key]})
	return result

# The native cover system moves a hard-cover unit between a reserved anchor and
# a separate shoulder/peek point. Query those exact snapped points instead of
# treating a standing ray from the anchor as evidence that the unit can fire.
# These are observations for the model, never an order or a guaranteed hit.
func cover_firing_positions(arena, u, cache):
	if u.tank:return []
	var nearby = []
	for cover in arena.field.covers:
		if not cover.get("alive",false):continue
		for slot in arena.field.slots(cover):
			var anchor: Vector2=arena.field.to_world(arena.field.nearest(slot.position))
			var peek: Vector2=arena.field.to_world(arena.field.nearest(slot.peek))
			var distance=u.pos().distance_to(anchor)
			# An unsampled/off-map slot may snap to a remote cell; it is not the
			# cover station the native animation would appear to occupy.
			if distance>.85 or anchor.distance_to(slot.position)>.04 or peek.distance_to(slot.peek)>.04 or not arena.field.walkable(anchor):continue
			nearby.append({"cover":cover,"slot":slot,"anchor":anchor,"peek":peek,"distance":distance})
	nearby.sort_custom(func(a,b):return a.distance<b.distance)
	var result=[]
	# Bound ray work while sampling several different covers. This is spatial
	# coverage, not a decision about whether to fire, hide, or move.
	var sampled=[]
	var sampled_per_cover={}
	for entry in nearby:
		var cover_id: String=str(entry.slot.cover_id)
		var count=int(sampled_per_cover.get(cover_id,0))
		if count>=4:continue
		sampled.append(entry)
		sampled_per_cover[cover_id]=count+1
		if sampled.size()>=20:break
	for entry in sampled:
		var slot=entry.slot
		var anchor: Vector2=entry.anchor
		var peek: Vector2=entry.peek
		var hard: bool=slot.hard
		var owner: String=str(arena.field.reservations.get(slot.key,""))
		var contested: bool=arena.field.reserved_positions.keys().any(func(id):return id!=u.id and arena.field.reserved_positions[id].distance_to(anchor)<.048)
		var body_occupied: bool=arena.living().any(func(other):return other!=u and other.pos().distance_to(anchor)<.06)
		var temporarily_unavailable: bool=float(arena.field.unavailable_until.get(u.id+":"+slot.key,0))>arena.elapsed
		var available: bool=(owner=="" or owner==u.id) and not contested and not body_occupied and not temporarily_unavailable
		var firing_at: Vector2=peek if hard else anchor
		var peek_walkable: bool=arena.field.walkable(firing_at)
		var targets=[]
		var blocked=[]
		var anchor_threats=[]
		var peek_threats=[]
		var weapon_range=float(arena.config.weapons[u.weapon].range)
		for enemy in arena.living():
			if enemy.faction==u.faction:continue
			var aim=enemy.aim_point()
			if firing_at.distance_to(enemy.pos())<=weapon_range and peek_walkable:
				# The actual actor socket depends on animation and is unavailable at
				# an unoccupied slot. Match the native fallback's crouch muzzle height.
				var start=Vector3(firing_at.x,arena.field.ground_height(firing_at)+.068,firing_at.y)
				var muzzle=start+(aim-start).normalized()*.023
				var hit=arena.field.trace_cover(muzzle,aim)
				if hit.is_empty():targets.append(enemy.id)
				else:blocked.append({"id":enemy.id,"cover_id":hit.get("cover_id","")})
			var cfg=enemy.weapon_config()
			if anchor.distance_to(enemy.pos())<=float(cfg.range):
				var anchor_body=Vector3(anchor.x,arena.field.ground_height(anchor)+(.025 if hard else .068),anchor.y)
				if arena.field.trace_cover(enemy.muzzle_position(anchor_body),anchor_body).is_empty():anchor_threats.append(enemy.id)
			if firing_at.distance_to(enemy.pos())<=float(cfg.range):
				var peek_body=Vector3(firing_at.x,arena.field.ground_height(firing_at)+.068,firing_at.y)
				if arena.field.trace_cover(enemy.muzzle_position(peek_body),peek_body).is_empty():peek_threats.append(enemy.id)
		# A hard-cover loop starts only if its nearest enemy passes the engine's
		# own range/line-of-sight gate. Other clear shots remain useful evidence,
		# but must not be advertised as guaranteed automatic peek opportunities.
		var native_peek_gate: Variant=null # Soft cover has no peek/hide loop.
		if hard:
			var nearest=arena.closest_enemy(u)
			native_peek_gate=nearest!=null and peek_walkable and peek.distance_to(nearest.pos())<weapon_range and arena.field.line_of_sight(peek,nearest.pos())
		result.append({"slot_key":slot.key,"cover_id":slot.cover_id,"hard":hard,"position":[anchor.x,anchor.y],"peek_position":[firing_at.x,firing_at.y],"firing_point_kind":"peek" if hard else "anchor","distance":entry.distance,"reserved_by":owner,"available":available,"body_occupied":body_occupied,"temporarily_unavailable":temporarily_unavailable,"native_peek_gate":native_peek_gate,"targets_from_peek":targets,"blocked_targets":blocked,"anchor_threats":anchor_threats,"peek_threats":peek_threats})
	# Spatial sampling, not a fire/retreat policy: show near stations from
	# different covers, including obstructed and occupied slots as evidence.
	result.sort_custom(func(a,b):return a.distance<b.distance)
	var selected=[]
	var per_cover={}
	for point in result:
		var count=int(per_cover.get(point.cover_id,0))
		if count>=2:continue
		selected.append(point)
		per_cover[point.cover_id]=count+1
		if selected.size()>=8:break
	for point in selected:
		var key=JSON.stringify(point.position)
		if not cache.has(key):cache[key]=path_risk(arena,u,Vector2(point.position[0],point.position[1]))
		point["risk"]=cache[key]
		point["reachable"]=cache[key].get("status")=="sampled"
	return selected

# One representative walkable native cell per coarse spatial bucket. The
# bucket size grows with map size, so procedural maps keep a bounded ray budget
# without assuming a named lane or a fixed map coordinate.
func remote_topology_samples():
	if topology_cells.is_empty():return []
	var bucket_size=maxi(2,ceili(sqrt(float(topology_cells.size())/110.0)))
	var buckets={}
	while true:
		buckets={}
		for id in topology_cells:
			var parts=id.split(",")
			var x=int(parts[0]);var z=int(parts[1])
			var bx=floori(float(x)/bucket_size);var bz=floori(float(z)/bucket_size)
			var key=str(bx)+","+str(bz)
			var offset=absf(x-(bx+.5)*bucket_size)+absf(z-(bz+.5)*bucket_size)
			if not buckets.has(key) or offset<buckets[key].offset:
				buckets[key]={"cell_id":id,"position":topology_cells[id],"offset":offset}
		if buckets.size()<=128:break
		bucket_size=maxi(bucket_size+1,ceili(bucket_size*sqrt(float(buckets.size())/128.0)))
	return buckets.values()

# Remote firing points are reconnaissance only. A clear predicted standing
# muzzle ray is not a hit guarantee, and a walkable endpoint is not a safe
# route. Pathfinding is performed only after a bounded full-map ray pass.
func remote_firing_positions(arena, u, cache):
	var started=Time.get_ticks_usec()
	if u.tank or u.garrison_phase!="":
		return {"positions":[],"search":{"status":"unsupported_muzzle_pose","sampled_cells":0,"path_queries":0,"assumptions":"remote standing infantry muzzle only"},"query_ms":0.0}
	var samples=remote_topology_samples()
	if samples.is_empty():return {"positions":[],"search":{"status":"unknown_no_topology","sampled_cells":0,"path_queries":0},"query_ms":0.0}
	var weapon_range=float(arena.config.weapons[u.weapon].range)
	var enemies=arena.living().filter(func(other):return other.faction!=u.faction)
	var lanes={}
	var clear_cells=0
	for sample in samples:
		var raw=sample.position
		var p=Vector2(raw[0],raw[1])
		if u.pos().distance_to(p)<.40:continue
		if arena.living().any(func(other):return other!=u and other.pos().distance_to(p)<.06):continue
		var targets=[];var blocked=[]
		for enemy in enemies:
			var distance=p.distance_to(enemy.pos())
			if distance>weapon_range:continue
			var aim=enemy.aim_point()
			var origin=Vector3(p.x,arena.field.ground_height(p)+.093,p.y)
			var muzzle=origin+(aim-origin).normalized()*.023
			var first_hit=arena.field.trace_cover(muzzle,aim)
			if first_hit.is_empty():targets.append(enemy.id)
			else:blocked.append({"id":enemy.id,"cover_id":first_hit.get("cover_id","")})
		if targets.is_empty():continue
		clear_cells+=1
		var direction=p-u.pos()
		var sector=(floori((direction.angle()+PI)/(TAU/8.0))+8)%8
		for target_id in targets:
			var lane_key=str(sector)+":"+str(target_id)
			if not lanes.has(lane_key):lanes[lane_key]=[]
			lanes[lane_key].append({"cell_id":sample.cell_id,"position":[p.x,p.y],"sector":sector,"focus_target_id":target_id,"targets":targets,"blocked_targets":blocked,"direct_distance":direction.length(),"weapon_range":weapon_range,"observed_at":arena.elapsed,"basis":"walkable topology sample; approximate standing muzzle ray; stationary targets; no hit or safety guarantee"})
	var lane_keys=lanes.keys()
	lane_keys.sort()
	for key in lane_keys:lanes[key].sort_custom(func(a,b):return a.direct_distance<b.direct_distance)
	var path_candidates=[]
	for depth in range(2):
		for key in lane_keys:
			if lanes[key].size()<=depth:continue
			path_candidates.append(lanes[key][depth])
			if path_candidates.size()>=18:break
		if path_candidates.size()>=18:break
	var tested=[]
	for point in path_candidates:
		var key=JSON.stringify(point.position)
		if not cache.has(key):cache[key]=path_risk(arena,u,Vector2(point.position[0],point.position[1]))
		point["risk"]=cache[key]
		point["reachable"]=cache[key].get("status")=="sampled"
		tested.append(point)
	var selected=[]
	var lane_counts={}
	# Round one covers distinct direction/target pairs; round two fills unused
	# capacity. Reachable points are shown first, but unreachable samples remain
	# evidence instead of being silently described as safe or impossible.
	for phase in range(2):
		for point in tested:
			if phase==0 and not point.reachable:continue
			var lane_key=str(point.sector)+":"+str(point.focus_target_id)
			var count=int(lane_counts.get(lane_key,0))
			if phase==0 and count>0:continue
			if phase==1 and count>=2:continue
			if selected.any(func(other):return Vector2(other.position[0],other.position[1]).distance_to(Vector2(point.position[0],point.position[1]))<.15):continue
			selected.append(point)
			lane_counts[lane_key]=count+1
			if selected.size()>=6:break
		if selected.size()>=6:break
	return {"positions":selected,"search":{"status":"sampled" if clear_cells>0 else "no_clear_ray_in_sample","sampled_cells":samples.size(),"clear_ray_cells":clear_cells,"path_queries":path_candidates.size(),"returned":selected.size(),"assumptions":"coarse full-map walkable samples; enemy positions fixed; standing fallback muzzle and cover first hit; native path sampled, no hit or safety guarantee"},"query_ms":(Time.get_ticks_usec()-started)/1000.0}

# HumanSquad consumes shared topology only. Legacy callers explicitly retain full reports.
func tick(arena, output: String, profile: String="full"):
	if output == "":return
	if profile == "topology":
		export_topology(arena,output+".topology.json")
		return
	if profile != "full":
		push_error("Unknown spatial query profile: "+profile)
		return
	if run_id != arena.run_id:run_id = arena.run_id;next_at = 0.0;next_wall_at = 0
	# Deployment changes positions while the opening countdown pauses game time.
	# Wall time refresh prevents the commander receiving only pre-deployment data.
	if output == "" or arena.demo.phase != "battle" or (arena.elapsed < next_at and Time.get_ticks_msec() < next_wall_at):return
	var query_started = Time.get_ticks_usec()
	next_at = arena.elapsed + 1.0
	next_wall_at = Time.get_ticks_msec() + 1000
	export_topology(arena,output+".topology.json")
	var report = {"run_id":arena.run_id,"time":arena.elapsed,"navigation_revision":arena.field.revision,"units":{}}
	# Each side uses its own hostile faction; geometry remains shared.
	for u in arena.living().filter(func(unit):return arena.control.get(unit.faction)=="lm"):
		var opponents = arena.living().filter(func(other):return other.faction != u.faction)
		var candidates = []
		var withdrawals = []
		var shelters = []
		var current_threats = []
		var blocked_shots = []
		var current_nearest = 100.0
		var weapon_range = float(arena.config.weapons[u.weapon].range)
		for enemy in opponents:
			current_nearest = minf(current_nearest,u.pos().distance_to(enemy.pos()))
			if u.pos().distance_to(enemy.pos())<=float(arena.config.weapons[enemy.weapon].range) and arena.field.trace_cover(enemy.muzzle_position(u.aim_point()),u.aim_point()).is_empty():current_threats.append(enemy.id)
			var hit = arena.field.trace_cover(u.muzzle_position(enemy.aim_point()),enemy.aim_point())
			if not hit.is_empty():blocked_shots.append(enemy.id)
		for dx in range(-4,5):
			for dz in range(-4,5):
				var p = u.pos() + Vector2(dx,dz)*.15
				if p.distance_to(u.pos()) < .08 or not arena.field.walkable(p):continue
				if arena.living().any(func(v):return v != u and v.pos().distance_to(p)<.08):continue
				var targets = [];var threats = [];var nearest = 100.0
				var eye = Vector3(p.x,arena.field.ground_height(p)+.093,p.y)
				for enemy in opponents:
					nearest = minf(nearest,p.distance_to(enemy.pos()))
					if p.distance_to(enemy.pos()) <= weapon_range and arena.field.trace_cover(eye,enemy.aim_point()).is_empty():targets.append(enemy.id)
					if p.distance_to(enemy.pos()) <= float(arena.config.weapons[enemy.weapon].range) and arena.field.trace_cover(enemy.muzzle_position(eye),eye).is_empty():threats.append(enemy.id)
				if targets.is_empty() and nearest <= current_nearest + .08 and threats.size()>=current_threats.size():continue
				var path = u.navigation_path(p)
				if path.is_empty():continue
				var length = arena.field.route_length(path)
				var spacing = absf(nearest-weapon_range*.78)
				var point = {"position":[p.x,p.y],"targets":targets,"threats":threats,"distance":length,"nearest_enemy":nearest,"score":-threats.size()*1.4-length-spacing*3.0}
				if not targets.is_empty():candidates.append(point)
				if threats.size()<current_threats.size():
					var shelter = point.duplicate()
					var exposed_samples = 0
					for fraction in [.25,.5,.75]:
						var step = path[mini(path.size()-1,int((path.size()-1)*fraction))]
						var body = Vector3(step.x,arena.field.ground_height(step)+.093,step.y)
						for enemy in opponents:
							if step.distance_to(enemy.pos())<=float(arena.config.weapons[enemy.weapon].range) and arena.field.trace_cover(enemy.muzzle_position(body),body).is_empty():exposed_samples+=1
					shelter["route_threat_samples"]=exposed_samples
					shelter.score=-threats.size()*10.0-length*3.0-exposed_samples*.2
					shelters.append(shelter)
				if nearest > current_nearest + .08:
					var escape = point.duplicate();escape.score = -threats.size()*2.0-length+minf(nearest,weapon_range)
					withdrawals.append(escape)
		candidates.sort_custom(func(a,b):return a.score>b.score)
		withdrawals.sort_custom(func(a,b):return a.score>b.score)
		shelters.sort_custom(func(a,b):return a.score>b.score)
		candidates=candidates.slice(0,5);withdrawals=withdrawals.slice(0,3);shelters=shelters.slice(0,3)
		var cache = {}
		for point in candidates+withdrawals+shelters:
			var key=JSON.stringify(point.position)
			if not cache.has(key):cache[key]=path_risk(arena,u,Vector2(point.position[0],point.position[1]))
			point["risk"]=cache[key]
		var route_forecasts = []
		var route_entries = {}
		var lanes: Dictionary = {}
		var raw_lanes = OS.get_environment("HARNESS_ROUTES_JSON")
		if not raw_lanes.is_empty():
			var parsed = JSON.parse_string(raw_lanes)
			if parsed is Dictionary:lanes=parsed
		if arena.get("growth") != null and not arena.growth.mission.is_empty():
			var m=arena.growth.mission
			lanes={}
			for i in range(m.spec.support.size()):
				var p=m.spec.support[i]
				lanes["front_"+str(i)]={"points":[[m.left+p[0],m.center_z+p[1]]]}
			var points:Array=[]
			for p in m.spec.flank:points.append([m.left+p[0],m.center_z+p[1]])
			lanes["flank"]={"points":points}
		if lanes is Dictionary:
			for name in lanes:
				var lane=lanes[name]
				for raw in lane.get("points",[]).slice(0,8):
					var key=JSON.stringify(raw)
					if not cache.has(key):cache[key]=path_risk(arena,u,Vector2(raw[0],raw[1]))
					route_forecasts.append({"position":raw,"risk":cache[key]})
					if not route_entries.has(name) and u.pos().distance_to(Vector2(raw[0],raw[1]))>.12:route_entries[name]={"position":raw,"risk":cache[key]}
		report.units[u.id] = {"origin":[u.pos().x,u.pos().y],"blocked_shots":blocked_shots,"current_threats":current_threats,"shelter_positions":shelters.slice(0,3),"nearest_enemy":current_nearest,"preferred_distance":[weapon_range*.6,weapon_range*.9],"withdrawal_positions":withdrawals.slice(0,3),"firing_positions":candidates.slice(0,5),"cover_firing_positions":cover_firing_positions(arena,u,cache),"cover_selection":"reference_only: native cover command chooses its own slot; move to anchor does not reserve a cover slot", "basis":"native navigation and cover-slot rays; cover query samples up to 20 nearby slots within .85 (up to 4 per cover) and returns up to 8 (up to 2 per cover); approximate crouch muzzle at snapped peek; not a guaranteed shot, hit, or safe route"}
		report.units[u.id]["route_forecasts"]=route_forecasts
		report.units[u.id]["threat_forecast"]={"standing_exposure":threats_at(arena,u.pos(),u.faction),"current_goal":path_risk(arena,u,u.goal),"assumptions":"12 distance samples; stationary enemies, standing rays, current movement speed; readiness excludes aiming/reaction; no hit probability or projectile splash prediction"}
		report.units[u.id]["route_entries"]=route_entries
		report.units[u.id]["navigation_steps"]=navigation_steps(arena,u,cache)
		var remote=remote_firing_positions(arena,u,cache)
		report.units[u.id]["remote_firing_positions"]=remote.positions
		report.units[u.id]["remote_firing_search"]=remote.search
		report.units[u.id]["remote_firing_query_ms"]=remote.query_ms
		var objective_risk=path_risk(arena,u,arena.objective)
		objective_risk["scope"]="flag_center"
		objective_risk["capture_radius"]=arena.config.rules.capture_radius
		objective_risk["assumption"]="center path only; capture may begin inside radius before center; travel and exposure are samples, not guaranteed"
		report.units[u.id]["objective_path_risk"]=objective_risk
	report["query_elapsed_ms"]=(Time.get_ticks_usec()-query_started)/1000.0
	var file = FileAccess.open(output,FileAccess.WRITE)
	if file:file.store_string(JSON.stringify(report));file.close()

func export_topology(arena, output):
	var key = output+":"+arena.run_id+":"+str(arena.field.revision)+":"+str(arena.config.bounds)
	if topology_key==key:return
	var cells = {};var edges = [];var step = .075
	var b = arena.config.bounds
	for x in range(ceili(b[0]/step),floori(b[2]/step)+1):
		for z in range(ceili(b[1]/step),floori(b[3]/step)+1):
			var p = Vector2(x*step,z*step)
			if arena.field.walkable(p):cells[str(x)+","+str(z)]=[p.x,p.y]
	for id in cells:
		var parts = id.split(",");var x = int(parts[0]);var z = int(parts[1])
		for d in [Vector2i(1,0),Vector2i(0,1)]:
			var other = str(x+d.x)+","+str(z+d.y)
			if cells.has(other) and arena.field.segment_walkable(Vector2(cells[id][0],cells[id][1]),Vector2(cells[other][0],cells[other][1])):edges.append([id,other])
	topology_cells=cells
	var f = FileAccess.open(output,FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify({"run_id":arena.run_id,"revision":arena.field.revision,"bounds":b,"step":step,"cells":cells,"edges":edges}));f.close()
		topology_key=key
