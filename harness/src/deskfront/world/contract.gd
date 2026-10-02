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
	check(g.living("blue").is_empty(),"infinite battle has only two teams")
	check(g.living("green").all(func(u):return u.hp==50 and u.max_hp==50),"initial squad has 50 health")
	g.set_control_mode("green","player")
	check(g.control.green=="game_ai","selection cannot disable local bot")
	check(not g.command({"action":"control","faction":"red","mode":"lm"}).accepted,"model soldier control forbidden")
	check(not g.command({"action":"move","faction":"green","position":[0,0]}).accepted,"spectator cannot overwrite bot orders")
	var run_id:String=g.run_id;var old_right:float=g.config.bounds[2];var old_units:int=g.units.size()
	var hp:float=g.units[0].hp;var old_cover=g.field.covers[0]
	old_cover.hp-=12
	var cmd={"action":"grow_world","run_id":run_id,"growth_revision":0,"operation_id":"test-one","option":"gate_north_books_cross_tight","hormones":{"pressure":.6,"recovery":.2,"expansion":.7,"teaching":.3,"novelty":.5}}
	check(g.command(dict_with(cmd,{"source":"agent","faction":"green"})).accepted==false,"battle agent cannot edit world")
	check(g.command(dict_with(cmd,{"run_id":"old"})).message=="stale_run","reject stale run")
	check(g.command(cmd).accepted,"valid growth starts during battle")
	check(g.config.bounds[2]==old_right,"preview does not expand navigation early")
	check(not g.field.walkable(Vector2(old_right+.2,0)),"unfinished terrain not walkable")
	check(not g.command(cmd).accepted,"duplicate is not executed twice")
	g.growth.tick(.4)
	check(g.growth.snapshot().phase=="building","visible construction has duration")
	g.growth.tick(2.1)
	check(g.config.bounds[2]>old_right and g.growth.revision==1,"commit expands existing world")
	check(g.run_id==run_id and g.units[0].hp==hp,"no reload or healing")
	check(g.field.covers.has(old_cover) and old_cover.hp==old_cover.max_hp-12,"existing destruction state retained")
	check(g.units.size()==old_units+3,"three defenders activate with scene commit")
	check(g.living("red").all(func(u):return u.hp==50 and u.max_hp==50),"generated defenders have 50 health")
	check(g.growth.reinforcements.orders.is_empty(),"no delayed spawn wave in encounter")
	check(g.growth.unit_roles.size()==3,"defenders receive separate prepared roles")
	OS.set_environment("HARNESS_ROUTES_JSON","")
	g.growth.spatial.tick(g,"res://output/world/route-probe.json")
	var spatial_report=JSON.parse_string(FileAccess.get_file_as_string("res://output/world/route-probe.json"))
	check(spatial_report.units.values().all(func(r):return r.route_forecasts.size()==6 and r.route_entries.has("flank")),"generated routes provide native risk forecasts without fixed map environment")
	var design=g.growth.Encounter.specification("gate_north_books_cross_tight")
	var report=g.growth.Encounter.validate(design,(g.config.bounds[3]-g.config.bounds[1])*.5)
	check(report.ok and report.flank_steps>report.main_steps,"reachable flank costs more travel than frontal route")
	check(g.growth.Encounter.validate(g.growth.Encounter.specification("gate_south_books_cross_tight"),(g.config.bounds[3]-g.config.bounds[1])*.5).ok,"mirrored layout also validated")
	check(not g.growth.Encounter.validate(design,.3).ok,"reject cramped map without viable routes")
	check(g.growth.snapshot().completed[0].design.defenders.size()==3,"receipt contains complete encounter specification")
	check(g.field.walkable(g.objective),"new rally point walkable")
	check(not g.field.path(Vector2(old_right-.1,g.objective.y),g.objective).is_empty(),"old and new navigation connected")
	check(g.growth.snapshot().completed[0].spawned.size()==3,"completed snapshot reports actual new unit")
	check(g.command(dict_with(cmd,{"operation_id":"old-version"})).message=="growth_revision_changed","reject stale region version")
	check(g.growth.snapshot().phase=="encounter","building does not equal mission completion")
	check(g.growth.snapshot().options.is_empty(),"unfinished encounter blocks expansion")
	check(not g.flag_banner.visible,"flag banner removed")
	g.growth.plan("green")
	check(g.living("green").any(func(u):return not u.route.is_empty()),"mission supplies real movement routes")
	for i in range(1,3):
		for u in g.living("red"):u.hp=0
		g.growth.mission.status="completed" # Separate geometry test from task progression.
		var next=dict_with(cmd,{"operation_id":"next-"+str(i),"growth_revision":i,"option":"gate_south_books_cross_tight"})
		check(g.command(next).accepted,"continuous region "+str(i));g.growth.tick(3.1)
	check(g.growth.revision==3,"scene construction continues without battle reset")
	var greens: Array=g.living("green")
	for u in greens:u.position.x=g.objective.x;u.position.z=g.objective.y
	g.growth.update_mission()
	check(g.growth.mission.status!="completed","arrival cannot skip living defenders")
	for u in greens:u.position.x=g.config.bounds[0]+.1
	for u in g.living("red"):u.hp=0
	g.growth.update_mission()
	check(g.growth.mission.arrived==0 and g.growth.mission.status=="completed","clearing defenders completes task without exit arrival")
	for u in greens:u.position.x=g.objective.x;u.route.clear();u.goal=u.pos()
	g.growth.retire_old_regions()
	check(not g.growth.snapshot().options.is_empty(),"completed task unlocks next construction")
	g.update_flag(100);check(g.winner=="","flag does not terminate infinite mode")
	# Site collision is checked again at commit, even if occupancy changes after preview.
	var occupied=dict_with(cmd,{"operation_id":"occupied","growth_revision":3,"option":"gate_south_books_cross_tight"})
	check(g.command(occupied).accepted,"safe frontier preview starts")
	var oldpos=greens[0].position;var left:float=g.config.bounds[2]
	greens[0].position.x=left+.59;greens[0].position.z=g.objective.y-.17
	g.growth.tick(3.1)
	check(g.growth.revision==3 and g.growth.construction_failures.size()==1,"occupied commit cancels without map expansion")
	greens[0].position=oldpos
	# Recovery never claims an unfinished task was completed.
	var remaining=g.spawn_unit("red-stall","red",Vector2(g.objective.x-.2,g.objective.y))
	g.growth.mission.defenders=[remaining.id]
	g.growth.mission.status="active";g.growth.mission.best_distance=0;g.growth.mission.least_enemy_hp=0
	g.growth.mission.last_progress=g.elapsed-26
	for u in greens:u.position.x=g.objective.x-.7
	g.growth.update_mission()
	check(g.growth.mission.status=="regrouping" and g.growth.snapshot().options.is_empty(),"stalled task regroups without unlocking expansion")
	g.growth.mission.status="active";g.growth.mission.recovery_count=2;g.growth.mission.last_progress=g.elapsed-26
	g.growth.update_mission()
	check(g.growth.mission.status=="failed","repeated stall is explicit failure")
	g.paused=true
	check(g.command(dict_with(cmd,{"operation_id":"paused","growth_revision":3})).message=="growth_game_not_running","pause blocks construction commands")
	g.paused=false
	for u in g.living("red"):u.hp=0
	g.growth.mission.status="completed"
	var friendly_before=g.living("green").size()
	check(g.command(dict_with(cmd,{"operation_id":"forces","growth_revision":3,"friendly_count":1,"enemy_count":2})).accepted,"chosen friendly and enemy counts accepted")
	check(g.living("green").size()==friendly_before,"friendly preview does not spawn early")
	g.growth.tick(1.6)
	check(g.living("green").size()==friendly_before+1 and g.living("red").size()==2,"forces activate atomically with chosen counts")
	check(g.living("green").all(func(u):return u.max_hp==50),"reinforcements retain 50 health")
	var result={"passed":checks.all(func(c):return c.passed),"checks":checks}
	DirAccess.make_dir_recursive_absolute("res://output/world")
	FileAccess.open("res://output/world/engine-contract.json",FileAccess.WRITE).store_string(JSON.stringify(result,"  "))
	print("WORLD_GROWTH_CONTRACT ",JSON.stringify(result));g.queue_free();await process_frame;quit(0 if result.passed else 1)
func dict_with(a:Dictionary,b:Dictionary)->Dictionary:
	var result=a.duplicate(true);result.merge(b,true);return result
