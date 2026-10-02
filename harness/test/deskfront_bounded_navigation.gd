extends SceneTree

var failures: Array=[]
var summaries: Array=[]

class Occupant:
	extends RefCounted
	var position: Vector2
	func pos():return position

func _initialize():call_deferred("run")

func check(value: bool,label: String):
	if not value:
		failures.append(label)
		push_error(label)

func make_field(bounds: Array,covers: Array=[],obstacles: Array=[]):
	var field=load("res://scripts/battlefield.gd").new()
	root.add_child(field)
	field.config={"bounds":bounds}
	field.cell=.025;field.base=Vector2(bounds[0],bounds[1]);field.height=.82
	field.covers=covers;field.obstacles=obstacles
	field.rebuild()
	return field

func snapshot_regression():
	var path: String=get_script().resource_path.get_base_dir()+"/deskfront_navigation_fixture.json"
	var fixture: Dictionary=JSON.parse_string(FileAccess.get_file_as_string(path))
	var field=make_field(fixture.bounds,fixture.covers,fixture.obstacles)
	var threats: Array=[]
	for contact in fixture.contacts:threats.append(Vector2(contact.position[0],contact.position[1]))
	for query in fixture.queries:
		var from: Vector2
		var occupants: Array=[]
		for unit in fixture.units:
			if unit.id==query.id:from=Vector2(unit.position[0],unit.position[1])
			elif unit.faction=="green" and unit.hp>0:
				var actor=Occupant.new();actor.position=Vector2(unit.position[0],unit.position[1]);occupants.append(actor)
		var target:=Vector2(query.target[0],query.target[1])
		var shortest: PackedVector2Array=field.path(from,target)
		var route: PackedVector2Array=field.tactical_path(from,target,threats,"green",occupants)
		var length: float=field.route_length(route)
		var minimum_x: float=from.x
		for point in route:minimum_x=minf(minimum_x,point.x)
		check(not route.is_empty() and route[-1].distance_to(target)<.025,query.id+" preserves selected forward destination")
		check(length<=field.harness_navigation_limit(field.route_length(shortest))+.001,query.id+" obeys soft-detour budget")
		check(minimum_x>=from.x-.075,query.id+" no longer retreats to the spawn area")
		check(length<float(query.old_weighted_length)*.75,query.id+" removes reproduced long avoidance loop")
		var started: int=Time.get_ticks_usec()
		var rays_before: int=field.ray_queries
		for iteration in range(100):field.tactical_path(from,target,threats,"green",occupants)
		summaries.append({"id":query.id,"old_length":query.old_weighted_length,"new_length":length,"shortest_length":field.route_length(shortest),"minimum_x":minimum_x,"100_cached_risk_queries_us":Time.get_ticks_usec()-started,"extra_rays":field.ray_queries-rays_before})
		check(field.ray_queries==rays_before,"path budget reuses risk cache without extra visibility rays")
	field.queue_free()

func hard_obstacle_regression():
	var wall={"id":"wall","position":[1.0,.8],"size":[.08,1.6],"height":.2,"normal":[1,0],"kind":"hard","alive":true}
	var field=make_field([0.0,0.0,2.0,2.0],[wall])
	var from:=Vector2(.5,.5);var target:=Vector2(1.5,.5)
	var shortest: PackedVector2Array=field.path(from,target)
	var route: PackedVector2Array=field.tactical_path(from,target,[Vector2(1.4,.5)],"test")
	check(not route.is_empty(),"required terrain detour is still available")
	check(field.route_length(route)>from.distance_to(target)*2,"length budget uses physical shortest path, not straight-line distance")
	check(field.route_length(route)>=field.route_length(shortest)-.001,"fallback never cuts across terrain wall")
	for i in range(1,route.size()):check(field.segment_walkable(route[i-1],route[i]),"terrain route follows walkable cells")
	field.queue_free()

func temporary_blocker_regression():
	var field=make_field([0.0,0.0,2.0,2.0])
	var from:=Vector2(.2,.9);var target:=Vector2(1.7,.9)
	var threats: Array=[Vector2(1.6,1.0)]
	field.tactical_path(from,target,threats,"test")
	# Force an expensive soft band so this test exercises the shortest fallback,
	# while a field gun remains an independent hard obstacle inside that band.
	var nav: AStarGrid2D=field.tactical_cache.test.nav
	for x in range(nav.region.size.x):
		for y in range(nav.region.size.y):nav.set_point_weight_scale(Vector2i(x,y),17.0 if y>=20 and y<=52 else 1.0)
	var gun=Occupant.new();gun.position=Vector2(.9,.9);gun.set_meta("nav_radius",.22)
	var before: int=int(field.tactical_profile.get("detour_fallbacks",0))
	var route: PackedVector2Array=field.tactical_path(from,target,threats,"test",[],[gun])
	check(not route.is_empty() and route[-1].distance_to(target)<.025,"dynamic blocker still permits reachable destination")
	check(int(field.tactical_profile.get("detour_fallbacks",0))>before,"dynamic blocker case exercised shortest fallback")
	for point in route:check(point.distance_to(gun.pos())>=.219,"fallback respects field gun hard collision")
	check(not field.grid.is_point_solid(field.to_cell(gun.pos())),"temporary hard blockers restored in base graph")
	check(not nav.is_point_solid(field.to_cell(gun.pos())),"temporary hard blockers restored in tactical graph")
	# A blocker over the requested destination cannot be ignored by fallback.
	gun.position=target
	check(field.tactical_path(from,target,threats,"test",[],[gun]).is_empty(),"blocked destination is not made reachable by fallback")
	field.queue_free()

func run():
	snapshot_regression()
	hard_obstacle_regression()
	temporary_blocker_regression()
	print("BOUNDED_NAVIGATION "+JSON.stringify({"failures":failures,"snapshot_replay":summaries}))
	await process_frame
	quit(0 if failures.is_empty() else 1)
