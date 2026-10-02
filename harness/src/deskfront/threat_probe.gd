extends SceneTree
class Walker:
	extends RefCounted
	var locomotion="run"
	var suppression=0.0
	var formation_speed=1.0
	func pos():return Vector2(-10,0)
	func navigation_path(p):return [pos(),p]
func _initialize():call_deferred("probe")
func probe():
	var arena=load("res://scenes/main.tscn").instantiate()
	root.add_child(arena);current_scene=arena;arena.paused=true
	var query=load(get_script().resource_path.get_base_dir()+"/spatial_queries.gd").new()
	var enemy=arena.units.filter(func(v):return v.id=="red-1")[0]
	enemy.deployment_phase="active"
	enemy.position=Vector3(-9.5,arena.field.height,0)
	enemy.actor.global_position=enemy.global_position;enemy.actor.update_weapon()
	enemy.cooldown=1.5;enemy.reload_timer=0;enemy.ammo=8
	var hp=enemy.hp
	var exposed=query.threats_at(arena,Vector2(-10,0))
	if exposed.size()!=1 or exposed[0].ready_in_s!=1.5:
		push_error("pre-damage threat/readiness missing");quit(1);return
	var walker=Walker.new()
	var route=query.path_risk(arena,walker,Vector2(-10,.3))
	if route.exposed_s<=0 or route.peak_attackers!=1:
		push_error("route exposure missing");quit(1);return
	var wall={"id":"risk-probe-wall","alive":true,"position":[-9.75,0],"size":[.05,1.0],"height":.3,"bottom":arena.field.height,"normal":[1,0],"hp":100}
	arena.field.covers.append(wall)
	var protected=query.path_risk(arena,walker,Vector2(-10,.3))
	if not query.threats_at(arena,Vector2(-10,0)).is_empty() or protected.exposed_s!=0 or enemy.hp!=hp:
		push_error("cover prediction or read-only invariant failed");quit(1);return
	print("HARNESS_THREAT_PROBE_PASS pre_damage_readiness_exposure_wall_readonly "+JSON.stringify({"open":route,"covered":protected}))
	quit(0)
