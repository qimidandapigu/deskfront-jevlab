extends SceneTree
var checks:Array=[]
func _initialize():call_deferred("run")
func check(ok:bool,name:String):
	checks.append({"passed":ok,"test":name})
	if not ok:push_error(name)
func run():
	set_meta("infinite_world",true)
	var g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
	g.set_physics_process(false);g.paused=false
	check(g.control.green=="lm" and g.control.red=="game_ai","green Harness and red local")
	g.set_control_mode("green","game_ai")
	check(g.control.green=="lm","local selection cannot replace Harness")
	var u=g.living("green")[0]
	var c={"action":"move","source":"lm","faction":"green","unit_ids":[u.id],"position":[u.pos().x-.1,u.pos().y],"run_id":g.run_id,"seen_tick":g.tick_id,"control_epoch":g.control_epochs.green}
	check(g.command(c).accepted,"green Harness command accepted")
	var goal=u.goal
	g.growth.plan("green")
	check(u.goal==goal,"local plan does not overwrite Harness goal")
	var console=c.duplicate();console.source="console"
	check(not g.command(console).accepted,"spectator cannot issue tactical orders")
	var red=c.duplicate();red.faction="red"
	check(not g.command(red).accepted,"Harness cannot command red")
	g.control_epochs.green+=1
	check(not g.command(c).accepted,"old encounter epoch rejected")
	print("WORLD_HARNESS_CONTRACT "+JSON.stringify(checks))
	var ok=checks.all(func(row):return row.passed)
	g.queue_free();await process_frame;quit(0 if ok else 1)
