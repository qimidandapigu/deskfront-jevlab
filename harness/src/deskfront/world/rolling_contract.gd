extends SceneTree
func _initialize():call_deferred("run")
func run():
	set_meta("infinite_world",true)
	var g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
	g.set_physics_process(false);g.paused=false;g.fx.set_muted(true)
	var u=g.living("green")[0]
	for other in g.living("green"):
		if other!=u:other.hp=0
	var checks=[]
	for i in range(9):
		for enemy in g.living("red"):enemy.hp=0
		if not g.growth.mission.is_empty():g.growth.mission.status="completed"
		if i==2:u.position.x=g.growth.active_regions[0].left+.2;u.route.clear();u.goal=u.pos()
		var command={"action":"grow_world","run_id":g.run_id,"growth_revision":g.growth.revision,"operation_id":"roll-"+str(i),"option":"gate_north_books_cross_tight","hormones":{"pressure":.5,"recovery":.5,"expansion":.5,"teaching":.5,"novelty":.5}}
		checks.append(g.command(command).accepted);g.growth.tick(1.6)
		if i==2:
			var original=u.position;var old_left=g.config.bounds[0]
			g.growth.retire_old_regions()
			checks.append(g.growth.retirement_blocked and u.position==original and g.config.bounds[0]==old_left)
			checks.append(g.growth.snapshot().options.is_empty())
		u.position.x=g.config.bounds[2]-.14;u.position.z=g.objective.y;u.route.clear();u.goal=u.pos()
		var before=u.position;g.growth.retire_old_regions()
		checks.append(u.position==before and g.growth.active_regions.size()<=2)
		checks.append(g.field.grid.region.size.x<=int(3.7/g.field.cell)+1 or i<2)
		if i>=2:checks.append(not g.field.walkable(Vector2(g.config.bounds[0]-.3,g.objective.y)))
		await process_frame
	checks.append(g.growth.retired_regions==7 and g.growth.completed.size()<=6 and g.config.world_floor_regions.size()==2)
	checks.append(g.growth.desk_panels.size()==g.growth.active_regions.size()*9)
	checks.append(absf(g.growth.desk_panels[0].get_meta("desk_top")-g.growth.desk_panels[1].get_meta("desk_top"))>=.002)
	var expected_covers=load("res://scripts/world_choke.gd").specification("gate_north_books_cross_tight").covers.size()*g.growth.active_regions.size()
	checks.append(g.units.size()<10 and g.field.covers.size()==expected_covers)
	var passed=checks.all(func(c):return c)
	print("ROLLING_REGIONS "+JSON.stringify({"passed":passed,"checks":checks,"retired":g.growth.retired_regions,"active":g.growth.active_regions.size(),"units":g.units.size(),"grid_width":g.field.grid.region.size.x}))
	g.queue_free();await process_frame;quit(0 if passed else 1)
