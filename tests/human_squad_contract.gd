extends SceneTree
var failures: Array=[]
var checks: Array=[]
func _initialize():call_deferred("run")
func check(ok: bool, name: String):
	checks.append({"test":name,"passed":ok})
	if not ok:failures.append(name);push_error(name)
func run():
	var g=load("res://scenes/main.tscn").instantiate();g.use_legacy_fixture=true;root.add_child(g);g.set_physics_process(false);g.fx.set_muted(true)
	g.human_squad=true;g.elapsed=30
	for c in g.field.covers:c.alive=false
	g.field.obstacles.clear();g.field.rebuild()
	for u in g.units:u.hp=0;u.actor.collision_layer=0
	var a=g.units[0];var b=g.units[1];var enemy=g.units[6]
	a.hp=100;b.hp=100
	a.position=Vector3(.3,g.field.height,.2);b.position=Vector3(.3,g.field.height,.28)
	g.set_control_mode("green","lm")
	var c={"action":"squad_order","source":"lm","faction":"green","unit_ids":[a.id,b.id],"squad_id":"green-squad","order_id":"one","intent":"advance","position":[.65,.2],"radius":.10,"run_id":g.run_id,"seen_tick":g.tick_id,"control_epoch":g.control_epochs.green}
	check(g.command(c).accepted,"authorized squad accepted")
	var s=g.human_squads.squads["green-squad"]
	g.human_squads.tick(.2)
	check(a.goal.distance_to(b.goal)>.025,"stable separated formation destinations")
	var anchor: Vector2=s.anchor
	c.order_id="two";check(g.command(c).accepted and s.anchor==anchor,"equivalent review keeps virtual leader progress")
	var conflict=c.duplicate(true);conflict.squad_id="other"
	check(g.command(conflict).message=="squad_member_already_owned","one intent owner per soldier")
	conflict=c.duplicate(true);conflict.unit_ids=[a.id,enemy.id]
	check(not g.command(conflict).accepted,"cross faction squad rejected")
	a.last_threat_at=30;a.suppression=1;a.safety_until=33;a.posture_order="auto";a.cover_id="";a.cover_slot={};a.cqb_stance="open";a.update_posture(true)
	check(a.posture=="prone" and a.locomotion=="crawl","real automatic suppressed crawl")
	g.flag_objective.holder="red"
	check(not g.flag_emergency("green"),"flag countdown cannot disable human self preservation")
	a.safety_until=0;a.suppression=0
	enemy.hp=100;enemy.position=Vector3(.9,g.field.height,.2)
	enemy.deployment_phase="parked"
	check(not g.human_squads.visible_to("green",enemy) and g.find_target(a)!=enemy,"parked nonparticipant cannot be perceived or targeted")
	var previous_shots: int=g.shots
	a.fire(enemy)
	check(g.shots==previous_shots,"final firing guard rejects parked targets")
	enemy.deployment_phase="active"
	g.human_squads.update_perception()
	check(g.human_squads.perception.green.has(enemy.id),"visible contact acquired")
	var observed: Array=g.human_squads.perception.green[enemy.id].position.duplicate()
	enemy.position=Vector3(3,g.field.height,3);g.elapsed+=1;g.human_squads.update_perception()
	check(not g.human_squads.perception.green[enemy.id].visible and g.human_squads.perception.green[enemy.id].position==observed,"hidden contact keeps last observed position")
	g.elapsed+=7;g.human_squads.update_perception()
	check(not g.human_squads.perception.green.has(enemy.id),"old contact expires")
	enemy.position=Vector3(1.35,g.field.height,.2);a.route.clear();b.route.clear();a.goal=a.pos();b.goal=b.pos()
	g.human_squads.tick(.2)
	check(s.phase=="advancing","visible but distant enemy does not deadlock support")
	enemy.position=Vector3(.7,g.field.height,.2);a.last_threat_at=-100;b.last_threat_at=-100;a.safety_until=0;b.safety_until=0
	g.human_squads.tick(.2)
	check(s.phase=="advancing","in-range contact alone keeps ordinary advance moving")
	s.cover_detours={a.id:{"until":g.elapsed-1}};s.cover_cooldowns={}
	check(not g.human_squads.moving_cover(a,s,s.goal) and s.cover_detours.is_empty() and s.cover_cooldowns[a.id]>g.elapsed,"expired cover deviation resumes formation with cooldown")
	a.last_threat_at=g.elapsed
	a.ammo=0;b.ammo=0;a.route.clear();b.route.clear();s.phase="establishing_support";s.since=g.elapsed-6
	g.human_squads.tick(.2)
	check(g.human_squads.events.any(func(e):return e.kind=="route_failed" and e.get("reason","")=="support_unavailable"),"missing support emits replanning event")
	check(s.phase=="blocked","unsupported movement timeout is not a successful standing order")
	a.last_threat_at=-100
	a.ammo=10;b.ammo=10;enemy.position=Vector3(1.12,g.field.height,.2);a.route.clear();b.route.clear();s.since=g.elapsed-2;s.phase="establishing_support";s.mover=""
	g.human_squads.bound("green-squad",s,[a,b])
	check(s.get("probing",false) and s.mover!="","no sustained support permits only a short firing-position approach")
	var probe=g.units.filter(func(u):return u.id==s.mover)[0];probe.suppression=.5
	g.human_squads.bound("green-squad",s,[a,b])
	check(s.mover=="" and probe.route.is_empty(),"firing-position approach aborts under pressure")
	probe.suppression=0;enemy.hp=0
	a.position=Vector3(.48,g.field.height,.2);b.position=Vector3(.48,g.field.height,.28);s.anchor=Vector2(.1,.2);s.phase="bounding"
	g.human_squads.tick(.2)
	check(s.anchor.x>.45 and a.goal.x>.40,"lost contact resumes from current squad position")
	var old_goal: Vector2=s.goal
	c.order_id="regroup";c.intent="regroup";g.command(c)
	g.human_squads.tick(.2);s=g.human_squads.squads["green-squad"]
	check(s.phase in ["regrouping","regrouped"] and s.goal==old_goal and s.rally.distance_to(old_goal)>.15,"regroup is local and preserves planner goal")
	c.order_id="resume";c.intent="advance";g.command(c);s=g.human_squads.squads["green-squad"]
	b.hp=0;g.human_squads.tick(.2)
	check(g.human_squads.events.any(func(e):return e.kind=="ally_down" and e.unit_id==b.id),"ally loss semantic event")
	a.position=Vector3(.65,g.field.height,.2);a.route.clear();g.human_squads.tick(.2)
	check(g.human_squads.events.any(func(e):return e.kind=="arrived"),"arrival semantic event")
	# The same sampled angular cone hits the actual low hit box less often from the front.
	var origin=Vector3(.65,g.field.height+.085,-.6);a.rotation.y=0
	var counts={}
	for posture in ["stand","prone"]:
		a.posture=posture;g.fx.dispersion_rng.seed=73129
		var hits: int=0
		for i in range(4000):
			var endpoint: Vector3=g.fx.dispersed_endpoint(origin,a.aim_point(),.72,0,"rifle")
			var box: Dictionary=a.hit_box()
			if not g.field.ray_box(origin,endpoint,box.center,box.size,a.rotation.y).is_empty():hits+=1
		counts[posture]=hits
	check(counts.prone<counts.stand,"frontal prone silhouette reduces physical hits")
	for weapon in ["rifle","smg","rocket","cannon","grenade"]:
		g.fx.launch(a,enemy,weapon,true)
		check(g.fx.projectiles[-1].to.distance_to(enemy.aim_point())>.000001,"every projectile scatters: "+weapon)
	var emotion_command={"action":"unit_emotion","source":"lm","faction":"green","unit_ids":[a.id],"emotion":"afraid","run_id":g.run_id,"seen_tick":g.tick_id,"control_epoch":g.control_epochs.green}
	var before_goal: Vector2=a.goal
	var before_safety: float=a.safety_until
	check(g.command(emotion_command).accepted and a.snapshot().emotion=="afraid","model emotion accepted per living owned unit")
	check(a.goal==before_goal and a.safety_until==before_safety and g.human_squads.squads.has("green-squad"),"emotion never cancels squad or survival")
	emotion_command.emotion="invincible"
	check(not g.command(emotion_command).accepted,"invalid emotion rejected")
	g.elapsed+=13
	check(a.snapshot().emotion=="","stale emotion expires")
	enemy.hp=100;enemy.deployment_phase="active";enemy.position=a.position+Vector3(.4,0,0)
	g.human_squads.update_perception()
	var protect: Dictionary={"faction":"green","squad_id":"green-squad","goal":a.pos(),"radius":.1,"phase":"taking_cover","reason":""}
	a.route.clear();a.cover_id="";a.cover_slot={}
	g.human_squads.protection_status(a,protect,false);g.elapsed+=2.1
	g.human_squads.protection_status(a,protect,false)
	check(protect.phase=="blocked" and g.human_squads.events[-1].reason=="no_reachable_protection","unprotected wait reports blocked instead of success")
	c.unit_ids=[a.id];c.intent="regroup";c.order_id="regroup-cover-failure"
	g.command(c);s=g.human_squads.squads["green-squad"]
	a.route.clear();a.safety_until=0
	g.human_squads.update_squad("green-squad",s);g.elapsed+=2.2
	g.human_squads.update_squad("green-squad",s)
	check(s.phase=="blocked" and s.protection[a.id].state=="unavailable" and not s.regrouped,"regroup preserves cover failure and cannot falsely complete")
	# 健康士兵被实际火力威胁时也应自保；只看见敌人不应自动恐慌。
	a.hp=100;a.suppression=0;a.safety_until=0;a.reaction_at=0;a.last_threat_at=-100
	a.route.clear();a.cover_id="";a.cover_slot={};a.cqb_stance="open"
	a.survival_tick()
	check(a.safety_until<=g.elapsed,"mere visible contact does not trigger panic")
	a.reaction_at=0;a.last_threat_at=g.elapsed;a.move_to(a.pos()+Vector2(.12,0))
	a.survival_tick();a.posture_since=-100;a.update_posture(false)
	check(a.safety_until>g.elapsed and a.safety_reason=="incoming_fire" and a.posture=="prone","healthy soldier immediately protects against real incoming fire")
	check(a.route.is_empty() and a.order_mode=="pinned","no verified cover means pin down rather than blind exposed retreat")
	g.elapsed+=4;a.reaction_at=0;a.suppression=0;a.posture_since=-100;a.update_posture(false)
	check(a.posture!="prone","safe interval allows posture recovery")
	c.intent="cover";c.order_id="cover-after-arrival";g.command(c);s=g.human_squads.squads["green-squad"];s.arrived=true
	a.safety_until=0;a.route.clear();g.human_squads.update_squad("green-squad",s)
	check(s.phase=="taking_cover","cover intent is honored even after strategic arrival")
	# 无射界的健康成员应报告缺席，不能把在掩体里当成已经提供支援。
	a.weapon="smg";a.hp=100;a.suppression=0;a.safety_until=0;a.last_threat_at=-100;a.last_shot_at=-100;a.reload_timer=0;a.route.clear()
	enemy.position=a.position+Vector3(1.05,0,0);s.fire_positions={}
	g.human_squads.maintain_fire_position(a,s);g.elapsed+=4.1
	g.human_squads.maintain_fire_position(a,s)
	check(s.fire_positions[a.id].state=="unavailable" and g.human_squads.events[-1].kind=="participation_gap","healthy covered-order member without firing lane requests replanning")
	var seq: int=g.human_squads.event_seq
	g.human_squads.maintain_fire_position(a,s)
	check(g.human_squads.event_seq==seq,"missing firing lane event is rate limited")
	a.safety_until=g.elapsed+3;g.elapsed+=1
	g.human_squads.maintain_fire_position(a,s)
	check(s.fire_positions[a.id].state=="recovering" and a.route.is_empty(),"participation repair respects immediate self preservation")
	a.safety_until=0;enemy.position=a.position+Vector3(3,0,0);g.elapsed+=8
	g.human_squads.maintain_fire_position(a,s)
	check(s.fire_positions[a.id].state=="observing" and g.human_squads.event_seq==seq,"hidden enemies do not force firing-position repair")
	enemy.position=a.position+Vector3(.3,0,0);a.last_shot_at=g.elapsed
	g.human_squads.maintain_fire_position(a,s)
	check(s.fire_positions[a.id].state=="engaging","active shooter keeps its position")
	# 一处确有射界的低掩体：修复应真的下达可达换位，而不仅发送事件。
	a.position=Vector3(.65,g.field.height,-.50);enemy.position=Vector3(.65,g.field.height,.55)
	a.last_shot_at=-100;a.last_threat_at=-100;a.safety_until=0;a.route.clear();a.cover_id="";a.cover_slot={};a.cqb_stance="open"
	g.config.weapons.smg.range=.9;g.field.reservations.clear();g.field.reserved_positions.clear()
	g.field.covers.append({"id":"fire-position-test","position":[.65,-.25],"size":[.18,.06],"normal":[0,1],"height":.043,"hp":100,"kind":"sandbags","alive":true,"node":null})
	g.field.rebuild();s.intent="cover";s.fire_positions={}
	g.human_squads.maintain_fire_position(a,s);g.elapsed+=4.1;g.human_squads.maintain_fire_position(a,s)
	check(a.order_mode=="squad_firing_position" and not a.route.is_empty() and a.cover_slot.get("fire_arc",false),"idle short-range shooter relocates to reachable covered firing lane")
	# 短时掩护结束后应交回意图选择；仍受压时不能谎报恢复。
	a.route.clear();a.safety_until=0;a.suppression=0;a.reload_timer=0;a.last_threat_at=-100
	s.intent="cover";s.since=g.elapsed-7;s.cover_ready_notified=false;s.unit_ids=[a.id]
	g.human_squads.update_squad("green-squad",s)
	check(s.phase=="cover_ready" and s.cover_ready_notified,"temporary cover emits completion for next maneuver")
	a.safety_until=g.elapsed+3;s.since=g.elapsed-13;s.cover_blocked_notified=false
	g.human_squads.update_squad("green-squad",s)
	check(s.phase=="blocked" and s.cover_blocked_notified,"ongoing danger reports recovery timeout without forcing movement")
	a.position=Vector3(.65,g.field.height,-.43);a.hp=100;a.ammo=10;a.reload_timer=0;a.suppression=0;a.safety_until=0;a.last_threat_at=-100;a.last_shot_at=-100
	a.route.clear();g.field.release(a.id);a.cover_id="";a.cover_slot={};a.cqb_stance="open"
	s.goal=Vector2(.65,.05);s.radius=.1;s.mover="";s.probing=false;s.since=g.elapsed-2
	g.human_squads.update_perception();g.human_squads.bound("green-squad",s,[a])
	check(a.order_mode=="squad_covered_approach" and not a.route.is_empty(),"unsupported healthy member can short-step to verified forward cover")
	a.route.clear();a.safety_until=0;a.last_shot_at=-100;s.mover=a.id;s.probing=false;s.handoff_at=g.elapsed-5;s.route_failed=false
	g.human_squads.bound("green-squad",s,[a])
	check(s.mover=="" and float(s.get("retry_after",{}).get(a.id,0))>g.elapsed,"failed handoff rotates mover and applies retry cooldown")
	a.hp=30;b.hp=30;a.safety_until=0;b.safety_until=0
	c.unit_ids=[a.id,b.id];c.order_id="roles-v1";c.seen_tick=g.tick_id;c.assignments={a.id:{"role":"establish_fire","source":"jev"},b.id:{"role":"maneuver","source":"jev"}}
	check(g.command(c).accepted,"team role contract accepted by engine")
	var assigned: Dictionary=g.human_squads.squads["green-squad"]
	check(g.human_squads.snapshot().squads["green-squad"].assignments[b.id].role=="maneuver","assigned maneuver role reaches observation")
	assigned.personal={a.id:{"intent":"wait_support","status":"suspended","order_id":assigned.order_id,"wait_order":assigned.order_id,"until":g.elapsed+4}}
	c.order_id="roles-equivalent"
	check(g.command(c).accepted and assigned.personal[a.id].order_id==c.order_id and assigned.personal[a.id].wait_order==c.order_id and assigned.personal[a.id].until==g.elapsed+4,"equivalent team review preserves suspended execution and original deadline")
	assigned.phase="blocked";assigned.since=g.elapsed-20;c.order_id="roles-v2"
	check(g.command(c).accepted and g.human_squads.squads["green-squad"].phase=="assembling" and g.human_squads.squads["green-squad"].since==g.elapsed,"equivalent blocked order restarts execution clock")
	# Verify actual threat-specific support, recovery after timeout, and cheap repeated reviews.
	for cover in g.field.covers:cover.alive=false
	g.field.obstacles.clear();g.field.rebuild()
	a.position=Vector3(.3,g.field.height,.2);b.position=Vector3(.3,g.field.height,.28);enemy.position=Vector3(.7,g.field.height,.2);enemy.hp=100
	for u in [a,b]:
		u.hp=30;u.weapon="rifle";u.ammo=8;u.reload_timer=0;u.route.clear();u.safety_until=0;u.suppression=0;u.last_threat_at=-100;u.cover_slot={};u.cover_id="";u.cqb_stance="open";u.set_meta("fire_block_reason","")
	g.human_squads.update_perception();a.last_shot_at=g.elapsed;a.last_shot_target="unrelated";b.last_shot_at=-100
	check(g.human_squads.supporting_members(b,[a,b]).is_empty(),"fire at unrelated enemy is not support for mover")
	a.last_shot_target=enemy.id
	check(g.human_squads.supporting_members(b,[a,b]).size()==1,"recent fire with clear lane toward mover threat counts as support")
	a.safety_until=g.elapsed+1
	check(g.human_squads.supporting_members(b,[a,b]).is_empty(),"evading soldier cannot count as support")
	a.safety_until=0
	s=g.human_squads.squads["green-squad"];s.goal=Vector2(.9,.28);s.mover="";s.since=g.elapsed-20;s.phase="blocked";s.probing=false;s.support_ready=false;s.route_failed=true;s.next_bound_search=g.elapsed+10
	s.assignments={a.id:{"role":"establish_fire"},b.id:{"role":"maneuver"}};s.retry_after={}
	g.human_squads.bound("green-squad",s,[a,b])
	check(s.since>=g.elapsed-1.2 and not s.route_failed and g.human_squads.events[-1].kind=="support_restored","actual support clears expired wait and notifies harness")
	check(s.mover==b.id and not b.route.is_empty(),"restored support releases assigned maneuver soldier")
	b.safety_until=g.elapsed+1
	g.human_squads.bound("green-squad",s,[a,b])
	check(s.mover=="" and s.support_lost,"immediate danger interrupts maneuver even during search cooldown")
	b.safety_until=0;b.route.clear();a.last_shot_at=-100;s.since=g.elapsed-2;s.next_bound_search=g.elapsed+.8;s.bound_revision=g.field.revision;s.support_ready=false
	var calls: int=g.field.tactical_profile.calls
	g.human_squads.bound("green-squad",s,[a,b]);g.human_squads.bound("green-squad",s,[a,b])
	check(g.field.tactical_profile.calls==calls,"repeated review inside cooldown does not repeat tactical search")
	a.last_shot_at=g.elapsed;s.support_ready=false;s.next_bound_search=0;s.mover="";s.since=g.elapsed-2;b.weapon="rocket";s.assignments[b.id].role="fire_support"
	g.human_squads.bound("green-squad",s,[a,b])
	check(s.mover!=b.id and b.route.is_empty(),"rear fire support is not selected as assault mover")
	var result={"passed":failures.is_empty(),"checks":checks,"failures":failures,"frontal_hits":counts}
	var file=FileAccess.open("res://output/human-squad-contract.json",FileAccess.WRITE)
	if file:file.store_string(JSON.stringify(result,"  "))
	print("HUMAN_SQUAD_CONTRACT "+JSON.stringify(result))
	g.queue_free();await process_frame;await process_frame
	quit(0 if failures.is_empty() else 1)
