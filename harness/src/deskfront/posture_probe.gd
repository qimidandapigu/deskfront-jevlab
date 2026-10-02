extends SceneTree
func _initialize():call_deferred("probe")
func probe():
	var arena=load("res://scenes/main.tscn").instantiate()
	root.add_child(arena);current_scene=arena;arena.paused=true;arena.elapsed=30
	var u=arena.units.filter(func(v):return v.id=="green-1")[0]
	var enemy=arena.units.filter(func(v):return v.id=="red-1")[0]
	u.position=Vector3(-10,arena.field.height,0);enemy.position=Vector3(-9.5,arena.field.height,0)
	u.deployment_phase="active";enemy.deployment_phase="active"
	u.cover_id="";u.cover_slot={};u.cqb_stance="open";u.garrison_phase="";u.posture_order="auto";u.posture_since=0;u.last_threat_at=-10;u.safety_until=0;u.suppression=0;u.posture="stand"
	u.update_posture(false)
	if u.posture!="stand":push_error("contact alone forced prone");quit(1);return
	u.suppression=1;u.last_threat_at=30;u.update_posture(true)
	if u.posture!="crouch":push_error("automatic escape should crouch-run");quit(1);return
	u.update_posture(false)
	if u.posture!="prone":push_error("stationary suppression protection lost");quit(1);return
	arena.elapsed=40;u.suppression=0;u.posture_since=30;u.update_posture(true)
	if u.posture=="prone":push_error("safe movement still crawling");quit(1);return
	u.posture_order="prone";u.update_posture(true)
	if u.posture!="prone":push_error("explicit prone ignored");quit(1);return
	print("HARNESS_POSTURE_PROBE_PASS contact_pressure_recovery_explicit")
	quit(0)
