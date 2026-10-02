extends SceneTree
func _initialize():call_deferred("run")
func run():
	set_meta("infinite_world",true)
	var fixtures=JSON.parse_string(FileAccess.get_file_as_string("res://data/geometry-unit-fixtures.json"))
	var results:Array=[]
	for fixture in fixtures:
		var game=load("res://scenes/main.tscn").instantiate();root.add_child(game)
		game.set_physics_process(false);game.paused=false;game.fx.set_muted(true)
		var left:float=float(game.config.bounds[2]);var center_z:float=(float(game.config.bounds[1])+float(game.config.bounds[3]))*.5
		var command:Dictionary={"action":"grow_world","run_id":game.run_id,"growth_revision":0,"operation_id":fixture.name,"option":"court_north_books_cross_tight","assembly_kind":"region_graph_v1","build_operations":fixture.operations,"friendly_count":0,"enemy_count":2,"hormones":{"pressure":.3,"recovery":.3,"expansion":.5,"teaching":.3,"novelty":.5}}
		if fixture.get("rescue",false):command["mission_kind"]="rescue"
		var response:Dictionary=game.command(command)
		if not response.get("accepted",false):
			results.append({"name":fixture.name,"passed":false,"reason":response});game.queue_free();await process_frame;continue
		game.growth.tick(1.6)
		if game.growth.mission.is_empty():
			results.append({"name":fixture.name,"passed":false,"reason":"no_committed_mission"});game.queue_free();await process_frame;continue
		var spec:Dictionary=game.growth.mission.spec;var unit=game.living("green")[0]
		unit.position.x=left+float(spec.entry[0]);unit.position.z=center_z+float(spec.entry[1]);unit.goal=unit.pos();unit.route.clear();unit.suppression=0
		# Several already-arrived short waypoints should advance in one local
		# planning pass, rather than consuming one .8-second cycle per point.
		var original_main:Array=spec.main_route.duplicate(true);var far_point:Array=original_main[-1]
		for point in original_main:
			if Vector2(float(point[0])-float(spec.entry[0]),float(point[1])-float(spec.entry[1])).length()>.2:far_point=point;break
		spec.main_route=[spec.entry,spec.entry,spec.entry,far_point,original_main[-1]]
		game.elapsed=10.0;game.growth.plan("green")
		var cursor_ok:bool=int(game.growth.unit_roles.get(unit.id,{}).get("tactical_waypoint",0))==3 and not unit.route.is_empty() and game.growth.unit_roles.get(unit.id,{}).get("phase","")=="分段推进"
		spec.main_route=original_main;unit.route.clear();unit.goal=unit.pos()
		for other in game.units:
			if other!=unit:other.hp=0
		var reached:bool=true;var collision_free:bool=true;var on_floor:bool=true;var steps:int=0
		var points:Array=spec.flank if fixture.get("flank",false) else spec.main_route
		for point in points+[spec.exit]:
			var destination:Vector2=Vector2(left+float(point[0]),center_z+float(point[1]));unit.move_to(destination)
			var count:int=0
			while unit.pos().distance_to(destination)>.065 and count<1200:
				game.elapsed+=1.0/60;unit.tick(1.0/60);count+=1;steps+=1
				var position:Vector2=unit.pos()-Vector2(left,center_z)
				if position.x<0 or position.x>1.8 or position.y<-1.05 or position.y>1.05:on_floor=false
				for cover in spec.covers:
					if absf(position.x-float(cover[0]))<float(cover[2])*.5+.005 and absf(position.y-float(cover[1]))<float(cover[3])*.5+.005:collision_free=false
			if count>=1200:reached=false;break
		results.append({"name":fixture.name,"passed":reached and collision_free and on_floor and cursor_ok,"reached":reached,"collision_free":collision_free,"on_floor":on_floor,"short_waypoints_consumed_together":cursor_ok,"waypoints":points.size(),"steps":steps})
		game.queue_free();await process_frame
	var passed:bool=results.all(func(result):return result.passed)
	print("GEOMETRY_UNIT_TRAVERSAL "+JSON.stringify({"passed":passed,"results":results}))
	quit(0 if passed else 1)
