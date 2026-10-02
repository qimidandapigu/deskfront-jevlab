extends SceneTree
var failures: Array=[]
var checks: Array=[]
func _initialize():call_deferred("run")
func check(ok: bool,label: String):
	checks.append({"test":label,"passed":ok})
	if not ok:failures.append(label)
func run():
	var g=load("res://scenes/main.tscn").instantiate();g.use_legacy_fixture=true;root.add_child(g);g.set_physics_process(false);g.fx.set_muted(true);g.human_squad=true
	for u in g.units:u.hp=0
	g.field.covers.clear();g.field.obstacles.clear();g.field.slot_cache.clear();g.field.rebuild();g.elapsed=20
	var a=g.units[0];var other=g.units[1]
	for u in [a,other]:u.hp=30;u.safety_until=0;u.suppression=0;u.route.clear();u.cover_id="";u.cover_slot={};u.explosive_notice_at=-100
	a.position=Vector3(.3,g.field.height,0);other.position=Vector3(.3,g.field.height,.5)
	var node=Node3D.new();g.add_child(node);node.position=Vector3(.7,g.field.height+.04,0)
	var p={"weapon":"rocket","age":.2,"duration":1.,"node":node,"from":Vector3(1.1,g.field.height+.04,0),"to":a.aim_point(),"team":"red","cfg":{"splash":.105}}
	var queries: int=g.field.path_queries
	g.fx.warn_explosive(p)
	check(a.safety_reason=="incoming_explosive" and a.hp==30,"visible incoming rocket triggers before damage")
	check(other.safety_until==0,"outside danger corridor receives no warning")
	check(g.field.path_queries==queries,"immediate evasion uses no global path query")
	check(not a.route.is_empty() and g.field.segment_walkable(a.pos(),a.goal),"evasion destination is directly navigable")
	var count: int=g.human_squads.events.size();p.age+=.15;g.fx.warn_explosive(p)
	check(g.human_squads.events.size()==count,"same shell warns a member only once")
	check(g.human_squads.events[-1].kind=="incoming_explosive","warning reaches harness event stream")
	g.elapsed=a.explosive_until+.1
	check(g.elapsed>=a.safety_until,"warning has bounded expiry")
	a.explosive_notice_at=-100;a.safety_until=0;a.route.clear();p.erase("warned");p.erase("warning_at")
	g.field.covers.append({"id":"warning-wall","position":[.5,0],"size":[.04,.3],"normal":[1,0],"height":.2,"hp":100,"kind":"hard","alive":true,"node":null})
	g.fx.warn_explosive(p)
	check(a.safety_until==0,"opaque obstruction prevents omniscient projectile sight")
	g.field.covers.clear();g.field.rebuild();g.field.simulation_time=1
	var threats: Array=[Vector2(.8,.2)]
	g.field.tactical_path(Vector2(.2,0),Vector2(.6,0),threats,"probe")
	var rebuilds: int=g.field.tactical_profile.rebuilds
	g.field.simulation_time=3;g.field.tactical_path(Vector2(.2,0),Vector2(.6,0),threats,"probe")
	check(g.field.tactical_profile.rebuilds==rebuilds,"unchanged threats do not rebuild expired cache")
	g.field.simulation_time=4.1;g.field.tactical_path(Vector2(.2,0),Vector2(.6,0),[Vector2(1.,.2)],"probe")
	g.field.simulation_time=4.2;g.field.tactical_path(Vector2(.2,0),Vector2(.6,0),[Vector2(1.2,.2)],"probe")
	check(g.field.tactical_profile.rebuilds==rebuilds+1,"moving threats respect rebuild interval")
	var original_nav=g.field.tactical_cache["probe"].nav
	g.field.simulation_time=8;g.field.tactical_path(Vector2(.2,0),Vector2(.6,0),[Vector2(1.4,.2)],"probe")
	check(g.field.tactical_cache["probe"].nav==original_nav,"threat updates reuse navigation allocation")
	var opts={"tactical_path":true,"max_travel":.2}
	g.field.choose_cover("miss-test",Vector2(.2,0),Vector2(.8,0),Vector2(.3,0),opts)
	var cover_calls: int=g.field.tactical_profile.cover_calls
	g.field.choose_cover("miss-test",Vector2(.2,0),Vector2(.8,0),Vector2(.3,0),opts)
	check(g.field.tactical_profile.cover_calls==cover_calls,"unchanged failed cover query is reused")
	g.field.simulation_time+=2
	g.field.choose_cover("miss-test",Vector2(.2,0),Vector2(.8,0),Vector2(.3,0),opts)
	check(g.field.tactical_profile.cover_calls==cover_calls+1,"failed cover query retries after bounded delay")
	print("EXPLOSIVE_WARNING "+JSON.stringify({"passed":failures.is_empty(),"checks":checks,"failures":failures,"profile":g.field.tactical_profile}))
	g.queue_free();await process_frame;quit(0 if failures.is_empty() else 1)
