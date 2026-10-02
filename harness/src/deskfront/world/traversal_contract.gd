extends SceneTree
func _initialize():call_deferred("run")
func run():
	set_meta("infinite_world",true)
	var results=[]
	for option in ["gate_north_books_cross_tight","stagger_south_crates_depth_wide","court_north_books_depth_tight","breach_south_crates_depth_wide"]:
		var g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
		g.set_physics_process(false);g.paused=false;g.fx.set_muted(true)
		var left=float(g.config.bounds[2]);var z=(g.config.bounds[1]+g.config.bounds[3])*.5
		var c={"action":"grow_world","run_id":g.run_id,"growth_revision":0,"operation_id":option,"option":option,"hormones":{"pressure":.5,"recovery":.5,"expansion":.5,"teaching":.5,"novelty":.5}}
		var accepted=g.command(c).accepted;g.growth.tick(1.6)
		if not accepted or g.growth.mission.is_empty():
			results.append({"option":option,"accepted":accepted,"reached":false,"stayed_on_floor":false,"void_blocked":false,"reason":"construction_rejected"})
			g.queue_free();await process_frame;continue
		var u=g.living("green")[0]
		for other in g.units:
			if other!=u:other.hp=0
		var spec=g.growth.mission.spec
		u.position.x=left+.12;u.position.z=z;u.goal=u.pos();u.route.clear()
		var valid=true;var reached=true;var steps=0
		for point in spec.flank+[spec.exit]:
			var dest=Vector2(left+point[0],z+point[1]);u.move_to(dest)
			var count=0
			while u.pos().distance_to(dest)>.10 and count<2400:
				g.elapsed+=1.0/60;u.tick(1.0/60);count+=1;steps+=1
				var supported=false
				for r in spec.floors:
					if u.pos().x>=left+r[0]-.01 and u.pos().x<=left+r[2]+.01 and u.pos().y>=z+r[1]-.01 and u.pos().y<=z+r[3]+.01:supported=true
				if not supported:valid=false
			if count>=2400:reached=false;break
		var missing=Vector2(left+.25,z+.8) if option.begins_with("gate") else Vector2(left+.9,z-.7) if option.begins_with("stagger") else Vector2(left+1.1,z-.4) if option.begins_with("breach") else Vector2(left+.9,z)
		var blocked=not g.field.walkable(missing) and not g.field.walkable(missing,true)
		results.append({"option":option,"accepted":accepted,"reached":reached,"stayed_on_floor":valid,"void_blocked":blocked,"steps":steps})
		g.queue_free();await process_frame
	var passed=results.all(func(r):return r.accepted and r.reached and r.stayed_on_floor and r.void_blocked)
	print("SHAPE_TRAVERSAL "+JSON.stringify({"passed":passed,"results":results}))
	quit(0 if passed else 1)
