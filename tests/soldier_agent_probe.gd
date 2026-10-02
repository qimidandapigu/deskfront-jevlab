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
	var u=g.units[0];u.hp=8;u.safety_until=0;u.suppression=0;u.last_threat_at=-100;u.reload_timer=0;u.route.clear();u.position=Vector3(.3,g.field.height,0)
	var s={"faction":u.faction,"squad_id":"personal-test","order_id":"v1","intent":"bound","unit_ids":[u.id],"mover":"","support_ids":[],"personal":{},"goal":Vector2(.9,0),"radius":.1}
	g.human_squads.squads[s.squad_id]=s
	var c={"squad_id":s.squad_id,"faction":u.faction,"order_id":"v1","unit_ids":[u.id],"intent":"wait_support"}
	check(g.human_squads.accept_personal(c)=="wait_requires_protection","cannot wait in exposed ground")
	u.cover_id="fixture";u.cover_slot={"position":u.pos(),"hard":true}
	check(g.human_squads.accept_personal(c)=="applied","protected wounded member can wait without waiting for health regeneration")
	var deadline: float=s.personal[u.id].until
	check(g.human_squads.accept_personal(c)=="personal_action_active" and s.personal[u.id].until==deadline,"duplicate command cannot renew wait")
	g.human_squads.station(u,s,0,[u])
	check(u.route.is_empty() and g.human_squads.personal_owned(u,s),"team station cannot overwrite personal lease")
	g.elapsed=deadline+.1;g.human_squads.update_personal(s,[u])
	check(s.personal[u.id].status=="wait_expired" and g.human_squads.events[-1].reason=="wait_expired","expired support wait reports to team")
	check(g.human_squads.accept_personal(c)=="wait_already_used_report_or_act","same assignment cannot restart expired wait")
	c.order_id="old"
	check(g.human_squads.accept_personal(c)=="stale_soldier_assignment","old model response cannot act")
	c.order_id="v1";c.intent="adjust_position";u.safety_until=g.elapsed+2
	check(g.human_squads.accept_personal(c)=="survival_override","personal move cannot override engine survival")
	u.safety_until=0;s.mover="other";s.support_ids=[u.id]
	check(g.human_squads.accept_personal(c)=="team_handoff_active","supporter cannot abandon active handoff")
	s.mover="";s.support_ids=[]
	check(g.human_squads.accept_personal(c)=="no_known_threat","no fabricated position without threat evidence")
	s.personal[u.id]={"intent":"wait_support","status":"active","order_id":"v1","until":g.elapsed+4};u.safety_until=g.elapsed+2
	g.human_squads.update_personal(s,[u])
	check(s.personal[u.id].status=="suspended" and g.human_squads.personal_owned(u,s),"incoming fire suspends intent while protecting it from team movement")
	var saved_deadline: float=s.personal[u.id].until
	u.safety_until=0;u.last_threat_at=-100
	g.human_squads.update_personal(s,[u])
	check(s.personal[u.id].status=="active" and s.personal[u.id].until==saved_deadline,"safe protected wait resumes without extending original deadline")
	u.safety_until=g.elapsed+2;g.human_squads.update_personal(s,[u]);u.safety_until=0;u.cover_id="";u.cover_slot={}
	g.human_squads.update_personal(s,[u])
	check(s.personal[u.id].status=="resume_requires_protection","lost protection prevents blind replay of suspended wait")
	s.personal[u.id]={"intent":"adjust_position","status":"suspended","order_id":"v1","until":g.elapsed+4}
	g.human_squads.update_personal(s,[u])
	check(s.personal[u.id].status=="resume_failed:no_known_threat","movement resume revalidates current world rather than replaying cached path")
	u.safety_until=0;s.personal[u.id]={"intent":"wait_support","status":"active","order_id":"v1","until":g.elapsed+4};s.order_id="v2"
	g.human_squads.update_personal(s,[u])
	check(s.personal[u.id].status=="assignment_changed","team reassignment releases personal ownership")
	g.human_squads.update_personal(s,[])
	check(not s.personal.has(u.id),"dead members removed from personal board")
	u.hp=30;u.safety_until=0;u.route.clear();u.cover_id="";u.cover_slot={};s.personal={};s.mover="";s.support_ids=[]
	check(g.human_squads.request_motion(u,s,"bound",Vector2(.6,0)),"bound obtains movement ownership")
	var owned_goal: Vector2=u.goal
	check(not g.human_squads.request_motion(u,s,"formation",Vector2(.4,.2)) and u.goal==owned_goal,"formation cannot overwrite an active bound")
	check(not g.human_squads.request_motion(u,s,"fire_position",Vector2(.4,.2)) and u.goal==owned_goal,"fire correction cannot overwrite an active bound")
	u.safety_until=g.elapsed+2
	check(not g.human_squads.request_motion(u,s,"personal",Vector2(.4,.2)) and u.goal==owned_goal,"survival blocks every ordinary movement source")
	u.safety_until=0;u.route.clear()
	check(g.human_squads.request_motion(u,s,"formation",Vector2(.4,.2)),"completed movement releases ownership to formation")
	s.mover="other";s.support_ids=[u.id];u.route.clear()
	check(not g.human_squads.request_motion(u,s,"fire_position",Vector2(.5,0)),"supporter cannot leave through firing correction")
	print("SOLDIER_AGENT "+JSON.stringify({"passed":failures.is_empty(),"checks":checks,"failures":failures}))
	g.human_squads.squads.clear();g.queue_free();await process_frame;quit(0 if failures.is_empty() else 1)
