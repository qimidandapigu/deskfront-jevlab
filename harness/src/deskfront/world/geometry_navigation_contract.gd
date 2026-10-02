extends SceneTree
# Fixture runner intentionally needs only the actual assembler and native
# AStar validator. It does not invoke models or create a visible game window.
func _initialize():call_deferred("run")
func run():
	var builder=load("res://scripts/world_region_graph.gd")
	var validator=load("res://scripts/world_choke.gd")
	var fixtures=JSON.parse_string(FileAccess.get_file_as_string("res://data/geometry-navigation-fixtures.json"))
	var results:Array=[]
	for fixture in fixtures:
		var actual:Dictionary=builder.assemble(fixture.operations)
		var errors:Array=[]
		if not actual.is_empty() and fixture.get("rescue",false):actual=load("res://scripts/world_fortress.gd").apply(actual,3)
		if actual.is_empty():errors.append("assembly_rejected")
		else:
			for key in ["covers","defender_slots","entry","exit","main_route","flank","friendly_slots"]:
				if JSON.stringify(actual.get(key))!=JSON.stringify(fixture.expected.get(key)):errors.append("host_native_mismatch:"+key)
			actual["friendlies"]=actual.get("friendly_slots",[])
			var validation:Dictionary=validator.validate(actual,1.15)
			if not validation.ok:errors.append(validation)
			var nodes:Dictionary=builder.clear_grid(actual.covers)
			for points in [actual.main_route,actual.flank]:
				for i in range(points.size()-1):
					var first:Vector2i=builder.nav_index(points[i]);var last:Vector2i=builder.nav_index(points[i+1])
					if first.x!=last.x and first.y!=last.y:errors.append("non_cardinal_segment");continue
					var direction:Vector2i=Vector2i(signi(last.x-first.x),signi(last.y-first.y));var point:Vector2i=first
					while true:
						if not nodes.has(point):errors.append("route_crosses_obstacle");break
						if point==last:break
						point+=direction
		results.append({"name":fixture.name,"passed":errors.is_empty(),"errors":errors})
	var passed:bool=results.all(func(result):return result.passed)
	print("GEOMETRY_NAVIGATION "+JSON.stringify({"passed":passed,"fixtures":results.size(),"failures":results.filter(func(result):return not result.passed)}))
	quit(0 if passed else 1)
