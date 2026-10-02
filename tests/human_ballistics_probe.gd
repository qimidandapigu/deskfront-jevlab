extends SceneTree
func _initialize():call_deferred("run")
func run():
	var g=load("res://scenes/main.tscn").instantiate();g.use_legacy_fixture=true;root.add_child(g);g.set_physics_process(false);g.fx.set_muted(true)
	var a=g.units[0];a.position=Vector3(.65,g.field.height,1.4);a.rotation.y=0
	var results={}
	var passed=true
	for distance in [.2875,.575,1.035]:
		var row={}
		for posture in ["stand","prone"]:
			a.posture=posture;g.fx.dispersion_rng.seed=73129
			var origin=Vector3(a.position.x,g.field.height+.093,a.position.z-distance)
			var hits=0
			for i in range(12000):
				var endpoint=g.fx.dispersed_endpoint(origin,a.aim_point(),float(g.config.weapons.rifle.accuracy),0,"rifle")
				var box=a.hit_box()
				if not g.field.ray_box(origin,endpoint,box.center,box.size,a.rotation.y).is_empty():hits+=1
			row[posture]=float(hits)/12000
		results[str(distance)]=row
	var mid=results[str(.575)]
	passed=mid.stand>=.35 and mid.stand<=.45 and mid.prone>=.17 and mid.prone<=.25
	passed=passed and results[str(.2875)].stand>mid.stand and results[str(1.035)].stand<mid.stand
	for row in results.values():passed=passed and row.prone<row.stand
	var report={"passed":passed,"samples_per_condition":12000,"rifle":results,"conditions":"stationary frontal target, standing muzzle, no cover, no suppression"}
	var file=FileAccess.open("res://output/human-ballistics-probe.json",FileAccess.WRITE)
	if file:file.store_string(JSON.stringify(report,"  "))
	print("BALLISTICS "+JSON.stringify(report))
	g.queue_free();await process_frame;quit(0 if passed else 1)
