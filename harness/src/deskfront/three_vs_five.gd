extends SceneTree

# Harness test launcher. The game project and its rules remain unchanged.
var arena
var added_run := ""
var prepared_run := ""
var spatial
var guarded_script
var execution_validator
var opening_run := ""
var opening_released := false
var opening_overlay

func _initialize():
	call_deferred("launch")

func launch():
	opening_overlay=load(get_script().resource_path.get_base_dir()+"/opening_overlay.gd").new()
	execution_validator=load(get_script().resource_path.get_base_dir()+"/execution_validation.gd").new()
	guarded_script = load(get_script().resource_path.get_base_dir() + ("/guarded_unit.gd" if OS.get_environment("HARNESS_TACTICAL_MAP")=="1" else "/human_unit.gd"))
	spatial = load(get_script().resource_path.get_base_dir() + "/spatial_queries.gd").new()
	arena = load("res://scenes/main.tscn").instantiate()
	root.add_child(arena)
	current_scene = arena
	root.add_child(load(get_script().resource_path.get_base_dir()+"/commentary_overlay.gd").new())
	# Preserve initialized presentation resources while replacing shot dispersion.
	var fx_values = {}
	for property in arena.fx.get_property_list():
		if property.usage & PROPERTY_USAGE_SCRIPT_VARIABLE:fx_values[property.name]=arena.fx.get(property.name)
	arena.fx.set_script(load(get_script().resource_path.get_base_dir()+"/human_combat_fx.gd"))
	for key in fx_values:arena.fx.set(key,fx_values[key])
	arena.fx.legacy_dispersion_rng.seed=73129

func _process(_delta):
	arena = current_scene
	if not is_instance_valid(arena) or arena.demo == null:
		return false
	var gate=OS.get_environment("HARNESS_OPENING_GATE")
	if gate!="" and arena.demo.phase=="battle":
		if opening_run!=arena.run_id:opening_run=arena.run_id;opening_released=false
		if not opening_released:
			arena.paused=true
			if FileAccess.file_exists(gate+".status"):
				var status=JSON.parse_string(FileAccess.get_file_as_string(gate+".status"))
				if status is Dictionary and status.get("run_id")==arena.run_id:
					var remaining=int(status.get("remaining",-1))
					if remaining>0:opening_overlay.show(self,str(remaining))
					elif remaining<0:opening_overlay.show(self,str(status.get("reason","准备开战")))
			if FileAccess.file_exists(gate):
				var permission=JSON.parse_string(FileAccess.get_file_as_string(gate))
				if permission is Dictionary and permission.get("run_id")==arena.run_id:
					opening_released=true;arena.paused=false
					opening_overlay.show(self,"开战")
	if OS.get_environment("HARNESS_TACTICAL_MAP") == "1":arena.config.soldier.hp = 50
	for u in arena.units:
		if u.get_script() == guarded_script:continue
		# Preserve the native instance, actor references and navigation closures.
		var values = {}
		for property in u.get_property_list():
			if property.usage & PROPERTY_USAGE_SCRIPT_VARIABLE:values[property.name] = u.get(property.name)
		u.set_script(guarded_script)
		for key in values:u.set(key,values[key])
		if not u.tank and OS.get_environment("HARNESS_TACTICAL_MAP") == "1":
			var health_ratio = u.hp / maxf(1.0,u.max_hp)
			u.max_hp=50.0;u.hp=health_ratio*u.max_hp
	execution_validator.tick(arena, OS.get_environment("HARNESS_SPATIAL_OUTPUT"))
	spatial.tick(arena, OS.get_environment("HARNESS_SPATIAL_OUTPUT"))
	if OS.get_environment("HARNESS_TACTICAL_MAP") == "1" and arena.demo.phase == "deploying" and prepared_run != arena.run_id:
		prepared_run = arena.run_id
		# This infantry scenario does not use artillery. Its original parked gun
		# overlaps the green spawn and encloses two starts in dynamic nav cells.
		for gun in arena.at_guns:
			arena.field.covers.erase(gun.proxy)
			gun.queue_free()
		arena.at_guns.clear()
		# Parked blue actors are still eligible targets in native find_target.
		# A two-faction scenario must remove them from the simulation entirely.
		for parked in arena.units.duplicate():
			if parked.faction != "blue":continue
			arena.field.release(parked.id)
			if is_instance_valid(parked.actor):parked.actor.queue_free()
			arena.units.erase(parked)
			parked.queue_free()
		for u in arena.units:
			if u.faction == "blue":continue
			u.position = arena.demo.targets[u.id]
			u.goal = u.pos()
			u.route.clear()
			u.deployment_phase = "active"
			u.order_mode = "hold"
			if u.actor:u.actor.global_position = u.global_position
		arena.demo.phase = "ready"
	if arena.demo.phase != "battle" or added_run == arena.run_id:
		return false
	added_run = arena.run_id
	var team = OS.get_environment("HARNESS_EXTRA_TEAM")
	var data = arena.faction_data(team)
	for i in range(4, 6):
		var position = Vector2(data.spawn[0] + (i - 4.5) * .12, data.spawn[1] - .09 if team == "red" else data.spawn[1] + .09)
		arena.spawn_unit(team + "-" + str(i), team, position)
	if OS.get_environment("HARNESS_TACTICAL_MAP") == "1":
		var lanes = JSON.parse_string(OS.get_environment("HARNESS_ROUTES_JSON"))
		for key in lanes:
			var previous = Vector2(.54, 3.22)
			for point in lanes[key].points:
				var target = Vector2(point[0], point[1])
				if not arena.field.walkable(target) or arena.field.path(previous, target).is_empty():
					push_error("Harness route unreachable: " + key + " " + str(target))
					quit(2)
					return false
				previous = target
		print("HARNESS_ROUTES_VALIDATED " + JSON.stringify(lanes.keys()))
		for u in arena.units:
			if u.faction != "green":continue
			for key in lanes:
				var point = lanes[key].points[0]
				if u.navigation_path(Vector2(point[0], point[1])).is_empty():
					push_error("Harness unit route unreachable: " + u.id + " " + key)
					quit(2)
					return false
		print("HARNESS_UNIT_ROUTES_VALIDATED green-1 green-2 green-3")
		var positions = [Vector2(.3, 1.63), Vector2(.72, 1.6), Vector2(.56, 1.02), Vector2(.28, 1.08), Vector2(1.15, 1.38)]
		for i in range(5):
			var u = arena.units.filter(func(v):return v.id == "red-" + str(i + 1))[0]
			var p = arena.field.to_world(arena.field.nearest(positions[i], true))
			u.position = Vector3(p.x, arena.field.ground_height(p), p.y)
			u.goal = p
			u.route.clear()
			if u.actor:u.actor.global_position = u.global_position
		arena.add_event("三路前哨：敌方2名前哨、2名后卫、1名侧翼兵；后续自由行动")
	arena.add_event("Harness test: 3 vs 5 infantry")
	return false
