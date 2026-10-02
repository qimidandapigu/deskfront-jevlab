extends SceneTree
var checks:Array=[]
func _initialize():call_deferred("run")
func check(value:bool,name:String):
	checks.append({"test":name,"passed":value})
	if not value:push_error(name)
func command_for(g,id:String,enemies=6,friends=0)->Dictionary:
	return {"action":"grow_world","run_id":g.run_id,"growth_revision":g.growth.revision,"operation_id":id,"option":"gate_north_books_cross_tight","enemy_count":enemies,"friendly_count":friends,"hormones":{"pressure":.5,"recovery":.5,"expansion":.5,"teaching":.5,"novelty":.5}}
func run():
	set_meta("infinite_world",true)
	var g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
	g.set_physics_process(false);g.paused=false;g.fx.set_muted(true)
	for value in [true,false,2.5,"3",7,1,NAN,INF]:
		check(g.command(command_for(g,"invalid-enemy",value)).message=="invalid_force_count","reject enemy count "+str(value))
	for value in [true,false,1.25,"1",3,-1,NAN,INF]:
		check(g.command(command_for(g,"invalid-friendly",3,value)).message=="invalid_force_count","reject friendly count "+str(value))
	var accepted=g.command(command_for(g,"six-defenders",6.0)).accepted
	check(accepted,"integral JSON numbers support six defenders")
	check(g.living("red").is_empty(),"preview does not activate defenders")
	var actors=g.growth.preview.get_children().filter(func(n):return n is CharacterBody3D)
	check(actors.is_empty() and g.growth.preview_desks.size()==9,"construction shows desks while defenders wait for commit")
	g.growth.tick(1.6)
	check(g.living("red").size()==6 and g.growth.mission.defenders.size()==6,"six authored defenders activate atomically")
	check(g.living("red")[2].weapon=="smg","selected defender weapon appears at commit")
	check(g.growth.mission_results.is_empty(),"construction is not mission completion")
	check(g.growth.mission.enemies_remaining==6,"first active frame reports all living defenders")
	check(g.growth.hud.text.find("队员到位")==-1,"HUD no longer claims exit arrival goal")
	g.elapsed+=14.5;g.living("green")[0].hp=30
	for u in g.living("red"):u.hp=0
	g.growth.update_mission();g.growth.update_mission()
	var result=g.growth.mission_results[-1]
	check(g.growth.mission_results.size()==1 and result.status=="completed" and result.enemies_initial==6 and result.enemies_remaining==0,"one actual clear receipt")
	check(result.duration_seconds==14.5 and result.green_start.alive==4 and result.green_start.hp_total==200 and result.green_end.hp_total==180,"clear receipt records duration and real health loss")
	var old_revision=g.growth.revision
	check(g.command(command_for(g,"late-sixth-slot")).accepted,"second preview starts")
	var row=g.growth.pending.spec.defenders[5];var u=g.living("green")[0];var before=u.position
	u.position.x=g.growth.pending.left+row[0];u.position.z=g.growth.pending.z+row[1]
	g.growth.tick(1.6);u.position=before
	check(g.growth.revision==old_revision and g.growth.construction_failures[-1].reason=="site_occupied_before_commit","commit validates occupancy at sixth defender slot")
	check(g.command(command_for(g,"late-invalid-slot")).accepted,"third preview starts")
	g.growth.pending.spec.defenders[5][0]=.01
	g.growth.tick(1.6)
	check(g.growth.revision==old_revision and g.growth.construction_failures[-1].reason.begins_with("invalid_compiled_encounter"),"commit revalidates full deployment footprint")
	var layout=g.growth.Encounter
	check(layout.floor_supports([[0,0,.5,1],[.5,0,1,1]],Vector2(.5,.5),Vector2(.2,.2)),"floor support accepts rectangle seams")
	check(not layout.floor_supports([[0,0,.4,1],[.6,0,1,1],[.4,0,.6,.4],[.4,.6,.6,1]],Vector2(.5,.5),Vector2(.4,.4)),"floor support rejects hidden center gap")
	for i in range(8):
		g.growth.mission.index=100+i;g.growth.mission.operation_id="receipt-"+str(i)
		g.growth.finish_mission("failed","contract failure")
	check(g.growth.mission_results.size()==6 and g.growth.mission_results[-1].status=="failed","terminal receipt history is bounded and keeps failure")
	check(g.growth.mission.ended_at==g.elapsed,"terminal mission exposes stable end time")
	var passed=checks.all(func(c):return c.passed)
	print("WORLD_FORCES_CONTRACT "+JSON.stringify({"passed":passed,"checks":checks}))
	g.queue_free();await process_frame;quit(0 if passed else 1)
