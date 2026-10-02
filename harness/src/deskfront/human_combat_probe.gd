extends SceneTree
var failures: int=0
func _initialize():call_deferred("probe")
func check(ok: bool, message: String):
	if not ok:push_error(message);failures+=1
func probe():
	var arena=load("res://scenes/main.tscn").instantiate()
	root.add_child(arena);current_scene=arena;arena.paused=true;arena.elapsed=30
	var u=arena.units[0]
	var values={}
	for property in u.get_property_list():
		if property.usage & PROPERTY_USAGE_SCRIPT_VARIABLE:values[property.name]=u.get(property.name)
	u.set_script(load(get_script().resource_path.get_base_dir()+"/guarded_unit.gd"))
	for key in values:u.set(key,values[key])
	u.tank=false;u.position=Vector3(-10,arena.field.height,0);u.rotation.y=0
	u.cover_id="";u.cover_slot={};u.cqb_stance="open";u.garrison_phase="";u.posture_order="auto";u.suppression=1;u.last_threat_at=30;u.posture_since=0
	u.update_posture(true)
	check(u.posture=="prone" and u.locomotion=="crawl","pressure must allow crawl")
	arena.elapsed=40;u.suppression=0;u.safety_until=0;u.update_posture(true)
	check(u.posture=="stand","safe travel must recover")
	arena.elapsed=45;u.posture_order="crouch";u.update_posture(true)
	check(u.posture=="crouch","explicit posture must survive")
	var fx=load(get_script().resource_path.get_base_dir()+"/human_combat_fx.gd").new()
	arena.add_child(fx);fx.setup(arena)
	var origin=Vector3(-10,arena.field.height+.085,-.8)
	var counts={};var mean=Vector3.ZERO
	for stance in ["stand","crouch","prone"]:
		u.posture=stance;fx.dispersion_rng.seed=73129
		var hits=0
		for i in range(4000):
			var aim=u.aim_point();var endpoint=fx.dispersed_endpoint(origin,aim,.72,0)
			var box=u.hit_box()
			if not arena.field.ray_box(origin,endpoint,box.center,box.size,u.rotation.y).is_empty():hits+=1
			if stance=="stand":mean+=endpoint-aim
		counts[stance]=hits
	check(counts.prone<counts.stand,"frontal prone silhouette must reduce sampled hits")
	check(absf(mean.x/4000)<.002 and absf(mean.y/4000)<.002,"dispersion must be centered")
	var enemy=arena.units.filter(func(v):return v.faction!=u.faction)[0]
	for weapon in ["rifle","rocket","cannon","grenade"]:
		fx.launch(u,enemy,weapon,true)
		var shot=fx.projectiles[-1]
		check(shot.get("dispersion_model")=="angular_disk_v1" and shot.to.distance_to(enemy.aim_point())>.000001,"every projectile needs scatter: "+weapon)
	print(("HUMAN_COMBAT_PASS " if failures==0 else "HUMAN_COMBAT_FAIL ")+JSON.stringify({"samples_per_pose":4000,"frontal_hits":counts,"mean_offset":str(mean/4000)}))
	quit(0 if failures==0 else 1)
