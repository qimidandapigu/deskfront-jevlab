extends SceneTree
var failures: Array=[]
var checks: Array=[]
func _initialize():call_deferred("run")
func check(ok: bool,label: String):
	checks.append({"test":label,"passed":ok})
	if not ok:failures.append(label)
func run():
	var g=load("res://scenes/main.tscn").instantiate();g.use_legacy_fixture=true;root.add_child(g);g.set_physics_process(false);g.fx.set_muted(true);g.human_squad=true
	check(g.units.filter(func(u):return not u.tank).all(func(u):return u.max_hp==30 and u.hp==30),"all infantry start with 30 hp")
	for u in g.units:u.hp=0
	g.field.covers.clear();g.field.obstacles.clear();g.field.slot_cache.clear();g.field.rebuild()
	var a=g.units[0];var ally=g.units[1];var enemy=g.units[6]
	for u in [a,ally,enemy]:u.hp=u.max_hp;u.deployment_phase="active";u.posture="stand";u.cqb_stance="open"
	a.position=Vector3(.3,g.field.height,0);ally.position=Vector3(.3,g.field.height,.4);enemy.position=Vector3(.95,g.field.height,0)
	a.weapon="rocket";a.ammo=1
	g.field.covers.append({"id":"muzzle-wall","position":[.36,0],"size":[.04,.2],"normal":[1,0],"height":.18,"hp":100,"kind":"hard","alive":true,"node":null})
	var shots: int=g.shots;var projectiles: int=g.fx.projectiles.size()
	a.fire(enemy)
	check(g.shots==shots and a.ammo==1 and g.fx.projectiles.size()==projectiles and a.get_meta("fire_block_reason","")!="","muzzle wall rejects explosive without ammo or shot count")
	g.field.covers.clear();ally.position=Vector3(.6,g.field.height,0)
	check(g.fx.explosive_fire_block(a,a.muzzle_position(enemy.aim_point()),enemy.aim_point(),a.weapon_config(),"rocket")=="friendly_in_firing_lane","friendly crossing blocks explosive")
	ally.position=Vector3(.95,g.field.height,.07)
	check(g.fx.explosive_fire_block(a,a.muzzle_position(enemy.aim_point()),enemy.aim_point(),a.weapon_config(),"rocket")=="friendly_near_impact","ally beside target blocks blast")
	ally.position=Vector3(.3,g.field.height,.4)
	check(g.fx.launch(a,enemy,"rocket",true),"clear distant rocket shot is allowed")
	g.field.covers.append({"id":"route-wall","position":[.65,-.12],"size":[.40,.42],"normal":[1,0],"height":.18,"hp":100,"kind":"hard","alive":true,"node":null})
	g.field.rebuild()
	var start:=Vector2(.2,0);var goal:=Vector2(1.1,0);var threats: Array=[Vector2(.65,.45)]
	var direct: PackedVector2Array=g.field.path(start,goal)
	var safe: PackedVector2Array=g.field.tactical_path(start,goal,threats,"test")
	var direct_exposure: float=g.field.route_exposure(direct,threats)
	var safe_exposure: float=g.field.route_exposure(safe,threats)
	check(not safe.is_empty() and safe_exposure<direct_exposure,"weighted navigation finds less exposed route around wall")
	check(Array(safe).all(func(p):return g.field.walkable(p)),"tactical route stays on navigable cells")
	g.field.covers.clear();g.field.rebuild();a.weapon="smg";a.set_meta("fire_block_reason","");a.last_shot_at=-100;a.route.clear();a.safety_until=0;a.suppression=0;a.reload_timer=0
	a.position=Vector3(.2,g.field.height,0);enemy.position=Vector3(1.2,g.field.height,0);g.elapsed=20
	var squad={"faction":a.faction,"squad_id":"test","duties":{}}
	g.human_squads.update_duties(squad,[a]);g.elapsed+=7;g.human_squads.update_duties(squad,[a])
	check(squad.duties[a.id].role=="blocked" and squad.duties[a.id].failures==1,"unproductive member remains explicitly blocked")
	ally.weapon="rifle";ally.position=Vector3(.65,g.field.height,0);ally.route.clear();ally.reload_timer=0;ally.ammo=8;ally.suppression=0;ally.cqb_stance="open";ally.last_shot_at=g.elapsed
	var handoff={"faction":a.faction,"squad_id":"handoff","mover":a.id,"probing":false,"support_lost":false,"route_failed":false,"since":g.elapsed,"turn":0,"goal":Vector2(1,0),"radius":.1,"unit_ids":[a.id,ally.id]}
	g.human_squads.bound("handoff",handoff,[a,ally])
	check(handoff.mover==a.id and handoff.phase=="establishing_support","arrival alone cannot release original supporter")
	g.elapsed+=4.1;ally.last_shot_at=g.elapsed;g.human_squads.bound("handoff",handoff,[a,ally])
	check(handoff.phase=="blocked" and g.human_squads.events[-1].reason=="handoff_no_fire","failed fire handoff requests replanning")
	# 观察高度越过沙袋，但卧姿枪口仍被挡：必须在开火前知道并调整。
	g.field.covers.clear();g.field.slot_cache.clear();g.field.rebuild()
	a.position=Vector3(.3,g.field.height,0);enemy.position=Vector3(.95,g.field.height,0);ally.position=Vector3(.3,g.field.height,.4)
	a.weapon="rocket";a.posture="prone";a.posture_order="auto";a.cqb_stance="open";a.route.clear();a.safety_until=0;a.suppression=0;a.last_threat_at=-100;a.reload_timer=0;a.firing_review_at=0
	g.field.covers.append({"id":"low-muzzle-cover","position":[.36,0],"size":[.04,.2],"normal":[1,0],"height":.043,"hp":100,"kind":"sandbags","alive":true,"node":null})
	check(g.field.line_of_sight(a.pos(),enemy.pos()) and not a.can_engage(enemy),"visible target does not imply prone rocket muzzle is clear")
	var before_shots: int=g.shots
	a.update_firing_awareness()
	check(a.firing_awareness.get("blocker_id","")=="low-muzzle-cover" and a.firing_awareness.response=="adjust_posture" and a.posture=="crouch" and g.shots==before_shots,"obstruction known before shooting and safe posture corrected")
	check(a.can_engage(enemy),"adjusted posture has actual clear firing lane")
	a.posture="prone";a.safety_until=g.elapsed+3;a.last_threat_at=g.elapsed;a.firing_review_at=0
	a.update_firing_awareness()
	check(a.posture=="prone" and a.firing_awareness.response=="wait","incoming fire prevents standing up to clear muzzle")
	a.safety_until=0;a.last_threat_at=-100;a.posture_order="prone";a.firing_review_at=0
	a.update_firing_awareness()
	check(a.posture=="prone","explicit posture order is preserved")
	# 永久伤势不能成为无限恢复计时器；安静时允许重新检查，受火时仍自保。
	g.field.covers.clear();g.field.slot_cache.clear();g.field.rebuild()
	a.hp=8;a.weapon="smg";a.position=Vector3(.2,g.field.height,0);enemy.position=Vector3(.95,g.field.height,0)
	a.route.clear();a.safety_until=0;a.suppression=0;a.last_threat_at=-100;a.last_shot_at=-100;a.reload_timer=0;a.reaction_at=0
	a.cover_slot={};a.cover_id="";a.cqb_stance="open"
	a.survival_tick()
	check(a.safety_until<=g.elapsed,"wounded soldier seeing enemy is not permanently under fire")
	var wounded={"faction":a.faction,"squad_id":"wounded","intent":"hold","fire_positions":{a.id:{"since":g.elapsed-10,"next_check":0.0,"state":"observing"}}}
	g.human_squads.maintain_fire_position(a,wounded)
	check(wounded.fire_positions[a.id].state=="unavailable" and g.human_squads.events[-1].reason=="no_safe_firing_position","wounded idle soldier reports unresolved firing position instead of infinite recovery")
	a.last_threat_at=g.elapsed;a.reaction_at=0;a.survival_tick()
	g.human_squads.maintain_fire_position(a,wounded)
	check(a.safety_until>g.elapsed and wounded.fire_positions[a.id].state=="recovering","wounded soldier still takes protection during actual incoming fire")
	var report={"passed":failures.is_empty(),"checks":checks,"failures":failures,"route_exposure":{"shortest":direct_exposure,"tactical":safe_exposure}}
	var f=FileAccess.open("res://output/tactical-safety-probe.json",FileAccess.WRITE);f.store_string(JSON.stringify(report,"  "))
	print("TACTICAL_SAFETY "+JSON.stringify(report));g.queue_free();await process_frame;quit(0 if failures.is_empty() else 1)
