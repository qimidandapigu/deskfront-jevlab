extends SceneTree
func _initialize():call_deferred("run")
func run():
	var layout=load("res://scripts/world_choke.gd")
	var results=[]
	for key in layout.catalog():
		var spec=layout.specification(key)
		var result=layout.validate(spec,1.15)
		results.append({"key":key,"validation":result})
		if not result.ok:push_error(key+" "+JSON.stringify(result))
	var valid=results.all(func(row):return row.validation.ok)
	print("COMPONENT_CATALOG "+JSON.stringify({"passed":valid,"count":results.size(),"results":results}))
	quit(0 if valid else 1)
