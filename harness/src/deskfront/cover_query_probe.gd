extends SceneTree

# Read-only integration probe against the native arena and its cover slots.
func _initialize():call_deferred("probe")

func fail(reason: String, details={}) -> void:
	push_error(reason+" "+JSON.stringify(details))
	quit(1)

func probe():
	var arena=load("res://scenes/main.tscn").instantiate()
	root.add_child(arena);current_scene=arena;arena.paused=true
	var query=load(get_script().resource_path.get_base_dir()+"/spatial_queries.gd").new()
	var unit=arena.units.filter(func(v):return v.id=="green-1")[0]
	var enemy=arena.units.filter(func(v):return v.id=="red-1")[0]
	unit.deployment_phase="active"
	enemy.deployment_phase="active"
	unit.position=Vector3(-.05,arena.field.height,3.2)
	enemy.position=Vector3(.45,arena.field.height,3.2)
	unit.actor.global_position=unit.global_position;unit.actor.update_weapon()
	enemy.actor.global_position=enemy.global_position;enemy.actor.update_weapon()
	var wall={"id":"probe_peek_wall","alive":true,"kind":"hard","position":[.2,3.2],"size":[.05,.12],"height":.3,"bottom":arena.field.height,"normal":[1,0],"hp":100}
	arena.field.covers.append(wall)
	var original_position=unit.pos()
	var original_hp=unit.hp
	var original_reservations=arena.field.reservations.duplicate(true)
	var started=Time.get_ticks_usec()
	var options=query.cover_firing_positions(arena,unit,{})
	var query_ms=(Time.get_ticks_usec()-started)/1000.0
	if unit.pos()!=original_position or unit.hp!=original_hp or arena.field.reservations!=original_reservations:
		fail("cover query changed combat or reservation state")
	var choice={}
	for option in options:
		if option.cover_id==wall.id and option.hard and option.targets_from_peek.has(enemy.id) and option.anchor_threats.is_empty() and option.risk.status=="sampled":
			choice=option;break
	if choice.is_empty():fail("no reachable protected native peek with a clear shot",{"options":options});return
	var reverse=query.cover_firing_positions(arena,enemy,{})
	var reverse_target=false
	for option in reverse:
		if option.targets_from_peek.has(unit.id):reverse_target=true
		if option.targets_from_peek.has(enemy.id):fail("same-faction unit listed as target",{"option":option});return
		for attacker in option.risk.get("attackers",[]):
			if str(attacker).begins_with("red-"):fail("same-faction unit listed as route threat",{"option":option});return
	if not reverse_target:fail("red unit has no green target in cover query",{"options":reverse});return
	# Reservation is reported as evidence. The query itself never books a slot.
	arena.field.reservations[choice.slot_key]="green-2"
	var reserved=query.cover_firing_positions(arena,unit,{})
	var occupied={}
	for option in reserved:
		if option.slot_key==choice.slot_key:occupied=option;break
	if occupied.is_empty() or occupied.available or occupied.reserved_by!="green-2":
		fail("reserved slot not represented accurately",{"occupied":occupied});return
	print("HARNESS_COVER_QUERY_PROBE_PASS native_peek_ray_path_reservation_readonly_both_factions "+JSON.stringify({"clear_slot":choice.slot_key,"targets":choice.targets_from_peek,"reverse_target":reverse_target,"anchor_threats":choice.anchor_threats,"peek_threats":choice.peek_threats,"travel_s":choice.risk.travel_s,"query_ms":query_ms}))
	quit(0)
