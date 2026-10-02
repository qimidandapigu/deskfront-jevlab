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
	enemy.position=Vector3(-9.6,arena.field.height,0);enemy.actor.global_position=enemy.global_position
	u.actor.update_weapon();enemy.actor.update_weapon()
	var results=[]
	for weapon in ["rifle","smg","rocket"]:
		u.weapon=weapon;u.ammo=8;u.cooldown=0
		u.position=Vector3(-10,arena.field.height,0);u.actor.global_position=u.global_position;u.actor.update_weapon()
		var wall={"id":"probe-wall","alive":true,"position":[-9.75,0],"size":[.05,.2],"height":.3,"bottom":arena.field.height,"normal":[1,0],"hp":100}
		arena.field.covers.append(wall)
		var shots_before=arena.shots;var ammo_before=u.ammo
		u.fire(enemy)
		if u.harness_fire_check.get("status")!="blocked" or u.ammo!=ammo_before or arena.shots!=shots_before:
			push_error("blocked fire failed: "+weapon);quit(1);return
		u.position.z=.4;u.actor.global_position=u.global_position;u.actor.update_weapon()
		u.fire(enemy)
		if u.harness_fire_check.get("status")!="clear" or u.ammo!=ammo_before-1 or arena.shots!=shots_before+1:
			push_error("reposition fire failed: "+weapon);quit(1);return
		results.append({"weapon":weapon,"blocked_ammo_used":0,"clear_ammo_used":1,"native_shots":arena.shots-shots_before})
		arena.field.covers.erase(wall)
	print("HARNESS_WEAPON_MATRIX "+JSON.stringify(results))
	quit(0)

