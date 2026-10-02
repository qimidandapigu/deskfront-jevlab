extends SceneTree
var checks:Array=[]
func _initialize():call_deferred("run")
func check(ok:bool,label:String):
	checks.append({"test":label,"passed":ok})
	if not ok:push_error(label)
func run():
	var encounter=load("res://scripts/world_choke.gd")
	var library=JSON.parse_string(FileAccess.get_file_as_string("res://data/world-build-parts.json"))
	var option="gate_north_books_cross_tight"
	var ops:Array=[]
	for slot in library[option]:
		ops.append({"slot":slot,"module":"wide" if slot=="floor_0" else ("replace" if slot=="cover_2" else "original"),"op":library[option][slot].original.op})
	var spec=encounter.assemble(option,ops)
	check(spec.floors!=encounter.specification(option).floors,"builder changes floor geometry")
	check(spec.covers!=encounter.specification(option).covers,"builder replaces actual cover")
	check(encounter.validate(spec,1.15).ok,"native navigation validates assembled map")
	var bad=ops.duplicate(true);bad[0].module="invented"
	check(encounter.assemble(option,bad).is_empty(),"unknown module rejected")
	set_meta("infinite_world",true)
	var g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
	g.set_physics_process(false);g.paused=false;g.fx.set_muted(true)
	var c={"action":"grow_world","run_id":g.run_id,"growth_revision":0,"operation_id":"assembly-test","option":option,"build_operations":ops,"friendly_count":0,"enemy_count":3,"hormones":{"pressure":.3,"recovery":.4,"expansion":.6,"teaching":.3,"novelty":.5}}
	check(g.command(c).accepted,"engine accepts builder operations")
	g.growth.tick(1.6)
	check(g.growth.revision==1,"engine completes assembly")
	if g.growth.completed.size():
		var actual=g.growth.completed[0].design
		check(actual.covers==spec.covers and actual.floors==spec.floors,"receipt geometry equals chosen assembly")
		check(actual.build_operations==ops,"operation evidence retained")
	check(g.living("red").size()==3,"defenders deployed with assembly")
	var passed=checks.all(func(row):return row.passed)
	print("ASSEMBLY_CONTRACT "+JSON.stringify({"passed":passed,"checks":checks}))
	quit(0 if passed else 1)
