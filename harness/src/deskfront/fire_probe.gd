extends SceneTree
func _initialize():call_deferred("probe")
func probe():
	var arena = load("res://scenes/main.tscn").instantiate()
	root.add_child(arena);current_scene=arena;arena.paused=true
	var u = arena.units.filter(func(v):return v.id=="green-3")[0]
	var enemy = arena.units.filter(func(v):return v.id=="red-1")[0]
	var values = {}
	for property in u.get_property_list():
		if property.usage & PROPERTY_USAGE_SCRIPT_VARIABLE:values[property.name]=u.get(property.name)
	u.set_script(load(get_script().resource_path.get_base_dir()+"/guarded_unit.gd"))
	for key in values:u.set(key,values[key])
	u.deployment_phase="active";enemy.deployment_phase="active"
	u.position=Vector3(-10,arena.field.height,0);u.actor.global_position=u.global_position
	enemy.position=Vector3(-9.5,arena.field.height,0);enemy.actor.global_position=enemy.global_position
	u.actor.update_weapon();enemy.actor.update_weapon()
	var wall={"id":"probe-wall","alive":true,"position":[-9.75,0],"size":[.05,.2],"height":.3,"bottom":arena.field.height,"normal":[1,0],"hp":100}
	arena.field.covers.append(wall)
	var ammo_before=u.ammo;var shots_before=arena.shots
	u.fire(enemy)
	if u.harness_fire_check.get("status")!="blocked" or u.ammo!=ammo_before or arena.shots!=shots_before:
		push_error("blocked shot consumed ammo or failed to block");quit(1);return
	# Test post-reposition firing with the same wall still present.
	u.position.z=.5;u.actor.global_position=u.global_position;u.actor.update_weapon()
	u.fire(enemy)
	if u.harness_fire_check.get("status")!="clear" or u.ammo!=ammo_before-1 or arena.shots!=shots_before+1:
		push_error("clear reposition did not resume native firing");quit(1);return
	print("HARNESS_FIRE_PROBE_PASS blocked_no_ammo_then_reposition_fire")
	# Recovery checks use the same live native unit, away from all enemy ranges.
	arena.paused=false;arena.elapsed=20;u.last_shot_at=0;u.suppression=0
	u.position=Vector3(-20,arena.field.height,0);u.actor.global_position=u.global_position
	u.hp=50;u.harness_last_damage=15
	u.harness_regenerate(1)
	if u.hp!=50:push_error("healed during delay");quit(1);return
	arena.elapsed=21;u.harness_regenerate(1)
	if u.hp!=52:push_error("safe recovery failed");quit(1);return
	u.last_shot_at=21;u.harness_regenerate(1)
	if u.hp!=52:push_error("healed while firing");quit(1);return
	u.last_shot_at=0;u.hp=99.5;u.harness_regenerate(1)
	if u.hp!=100:push_error("healing exceeded max");quit(1);return
	u.hp=0;u.harness_regenerate(1)
	if u.hp!=0:push_error("healing revived dead unit");quit(1);return
	print("HARNESS_REGEN_PROBE_PASS delay_rate_fire_cap_death")
	quit(0)
