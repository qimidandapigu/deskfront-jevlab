extends SceneTree
var checks:Array=[]
func _initialize():call_deferred("run")
func check(value:bool,name:String):
	checks.append({"test":name,"passed":value})
	if not value:push_error(name)
func run():
	set_meta("infinite_world",true)
	var g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
	g.set_physics_process(false);g.paused=false;g.fx.set_muted(true)
	var left:float=g.config.bounds[2];var center:float=(g.config.bounds[1]+g.config.bounds[3])*.5
	var before:int=g.living("green").size()
	var command={"action":"grow_world","run_id":g.run_id,"growth_revision":0,"operation_id":"rescue-contract","option":"gate_north_books_cross_tight","mission_kind":"rescue","assembly_kind":"region_graph_v1","build_operations":JSON.parse_string(FileAccess.get_file_as_string("res://data/rescue-scene.json")),"friendly_count":0,"enemy_count":3,"hormones":{"pressure":.5,"recovery":.5,"expansion":.5,"teaching":.5,"novelty":.5}}
	var receipt=g.command(command)
	check(receipt.accepted,"rescue command accepted: "+str(receipt))
	if receipt.accepted:
		check(g.units.size()==before,"preview does not recruit captive")
		g.growth.tick(1.6)
		var captives:Array=g.units.filter(func(u):return u.deployment_phase=="captive")
		check(captives.size()==1,"one trapped soldier appears inside fort")
		check(g.living("green").size()==before,"trapped soldier cannot act as active squad member")
		check(g.living("red").size()==3,"three outer defenders guard rescue")
		check(g.growth.mission.rescue_status=="trapped","mission receipt reports trapped state")
		var fort:Array=g.field.covers.filter(func(c):return str(c.id).begins_with("growth_") and c.hp==240)
		check(fort.size()==7,"seven destructible fort walls exist in engine")
		check(not g.field.trace_cover(Vector3(left+1.32,g.field.height+.10,center-.205),Vector3(left+1.57,g.field.height+.10,center-.205)).is_empty(),"fort wall physically blocks fire")
		check(not g.field.path(Vector2(left-.1,center),Vector2(left+1.6,center)).is_empty(),"infantry has a legal route to the entrance")
		var first:Dictionary=fort[0]
		check(g.field.damage_cover(first.id,240),"fort wall can be destroyed")
		check(not first.alive,"destroyed wall clears collision and line of fire")
		for u in g.living("red"):u.hp=0
		g.growth.update_mission()
		check(g.growth.mission.status=="completed" and g.growth.mission.rescue_status=="joined","clearing surrounding defenders completes rescue")
		check(g.living("green").size()==before+1 and captives[0].deployment_phase=="active","rescued soldier joins the active squad")
		check(g.growth.mission_results.back().friendly_added==1,"completion receipt counts recruited soldier")
		g.growth.update_mission()
		check(g.living("green").size()==before+1,"rescue does not recruit twice")
	var result={"passed":checks.all(func(c):return c.passed),"checks":checks}
	DirAccess.make_dir_recursive_absolute("res://output/world")
	FileAccess.open("res://output/world/rescue-contract.json",FileAccess.WRITE).store_string(JSON.stringify(result,"  "))
	print("WORLD_RESCUE_CONTRACT ",JSON.stringify(result));g.queue_free();await process_frame;quit(0 if result.passed else 1)
