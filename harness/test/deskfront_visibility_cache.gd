extends SceneTree

var failures: Array=[]

func _initialize() -> void:call_deferred("run")

func check(value: bool, label: String) -> void:
	if not value:
		failures.append(label)
		push_error(label)

func old_visible_enemy(g, u):
	var best=null
	var distance: float=INF
	for enemy in g.living():
		if enemy.faction==u.faction or not g.human_squads.visible_to(u.faction,enemy):continue
		var d: float=u.pos().distance_to(enemy.pos())
		if d<distance:best=enemy;distance=d
	return best

func run() -> void:
	set_meta("infinite_world",true)
	var g=load("res://scenes/main.tscn").instantiate()
	root.add_child(g)
	g.set_physics_process(false)
	g.paused=false
	check(g.human_squad,"Harness mode enabled")
	var friends: Array=g.living("green")
	var u=friends[0]
	var enemy=g.spawn_unit("visibility-probe-enemy","red",u.pos()+Vector2(.15,0))
	check(enemy!=null,"test enemy spawned")
	if enemy==null:
		g.queue_free()
		await process_frame
		quit(1)
		return
	enemy.deployment_phase="active"
	var found: bool=false
	for offset in [Vector2(.15,0),Vector2(-.15,0),Vector2(0,.15),Vector2(0,-.15),Vector2(.10,.10)]:
		var p: Vector2=u.pos()+offset
		if not g.field.walkable(p):continue
		enemy.position.x=p.x;enemy.position.z=p.y
		if g.human_squads.visible_to("green",enemy):found=true;break
	check(found,"visible test enemy placed")
	if found:
		g.human_squads.update_perception()
		check(g.human_squads.visible_enemy(u)==old_visible_enemy(g,u),"cached selection matches live selection")
		var start_old: int=Time.get_ticks_usec()
		for i in range(250):old_visible_enemy(g,u)
		var old_us: int=Time.get_ticks_usec()-start_old
		var start_new: int=Time.get_ticks_usec()
		for i in range(250):g.human_squads.visible_enemy(u)
		var cached_us: int=Time.get_ticks_usec()-start_new
		check(cached_us<old_us,"cached selection faster than repeated team LOS")
		enemy.hp=0
		check(g.human_squads.visible_enemy(u)==null,"dead enemy not returned before cache refresh")
		var second=g.spawn_unit("visibility-probe-second","red",u.pos()+Vector2(.15,0))
		second.deployment_phase="active"
		check(g.human_squads.visible_enemy(u)==null,"new enemy waits for perception refresh")
		g.human_squads.update_perception()
		check(g.human_squads.visible_enemy(u)==second,"new enemy appears after perception refresh")
		print("VISIBILITY_CACHE "+JSON.stringify({"failures":failures,"old_us":old_us,"cached_us":cached_us}))
	g.queue_free()
	await process_frame
	quit(0 if failures.is_empty() else 1)
