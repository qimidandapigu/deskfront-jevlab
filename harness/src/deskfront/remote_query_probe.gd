extends SceneTree

# Bounded full-map firing reconnaissance against the native Godot map.
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
	unit.deployment_phase="active";enemy.deployment_phase="active"
	unit.position=Vector3(-.05,arena.field.height,3.2)
	enemy.position=Vector3(.7,arena.field.height,3.2)
	unit.actor.global_position=unit.global_position;unit.actor.update_weapon()
	enemy.actor.global_position=enemy.global_position;enemy.actor.update_weapon()
	var before_position=unit.pos();var before_hp=unit.hp
	var before_reservations=arena.field.reservations.duplicate(true)
	query.export_topology(arena,"user://remote-query-probe.topology.json")
	var native_topology=query.topology_cells
	query.topology_cells={}
	for i in range(400):query.topology_cells[str(i*40)+","+str(i*40)]=[float(i),float(i)]
	if query.remote_topology_samples().size()>128:fail("large-map sample bound failed");return
	query.topology_cells=native_topology
	var remote=query.remote_firing_positions(arena,unit,{})
	if remote.search.sampled_cells>128 or remote.search.path_queries>18 or remote.positions.size()>6:
		fail("remote query exceeded sample/path/output bound",remote.search);return
	if remote.positions.is_empty():fail("no remote firing evidence in open fixture",remote.search);return
	var seen={}
	for point in remote.positions:
		if point.direct_distance<.40 or point.targets.is_empty() or point.observed_at!=arena.elapsed:
			fail("remote candidate lacks distance, target, or time evidence",point);return
		if not point.risk.has("status") or not point.risk.has("observed_at"):
			fail("remote candidate lacks native path result",point);return
		if point.reachable!=(point.risk.status=="sampled"):
			fail("remote reachability disagrees with native path",point);return
		var firing=Vector2(point.position[0],point.position[1])
		var target=arena.living().filter(func(other):return other.id==point.focus_target_id)[0]
		if firing.distance_to(target.pos())>point.weapon_range:
			fail("remote candidate outside weapon range",point);return
		var aim=target.aim_point()
		var origin=Vector3(firing.x,arena.field.ground_height(firing)+.093,firing.y)
		if not arena.field.trace_cover(origin+(aim-origin).normalized()*.023,aim).is_empty():
			fail("remote candidate has a native first-hit blocker",point);return
		var lane=str(point.sector)+":"+str(point.focus_target_id)
		seen[lane]=int(seen.get(lane,0))+1
		if seen[lane]>2:fail("remote query overrepresented a direction/target lane",point);return
	if unit.pos()!=before_position or unit.hp!=before_hp or arena.field.reservations!=before_reservations:
		fail("remote query mutated battle state");return
	arena.demo={"phase":"battle"}
	query.tick(arena,"user://remote-query-probe.json")
	var report=JSON.parse_string(FileAccess.get_file_as_string("user://remote-query-probe.json"))
	if not report is Dictionary or not report.has("query_elapsed_ms") or not report.units[unit.id].has("objective_path_risk"):
		fail("tick omitted total query timing or objective path forecast",report);return
	if report.units[unit.id].objective_path_risk.scope!="flag_center" or report.units[unit.id].objective_path_risk.capture_radius<=0:
		fail("objective forecast omitted center/radius scope",report.units[unit.id].objective_path_risk);return
	print("HARNESS_REMOTE_QUERY_PROBE_PASS full_map_bounded_readonly "+JSON.stringify({"search":remote.search,"remote_query_ms":remote.query_ms,"total_query_elapsed_ms":report.query_elapsed_ms,"objective_path_risk":report.units[unit.id].objective_path_risk.status,"first":remote.positions[0]}))
	quit(0)
