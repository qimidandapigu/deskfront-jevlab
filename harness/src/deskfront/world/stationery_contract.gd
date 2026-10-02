extends SceneTree
var failures:Array=[]
func check(ok:bool,message:String):
	if not ok:failures.append(message)
func _initialize():
	var art=load("res://scripts/world_props.gd")
	var total=0
	for kind in art.IDENTITIES:
		for size in [Vector3(.2,.08,.12),Vector3(.045,.043,.2),Vector3(.56,.25,.66)]:
			var parent=Node3D.new()
			art.build(null,parent,[0,0,size.x,size.z,kind,size.y])
			check(parent.get_meta("stationery_identity")==art.IDENTITIES[kind],"Identity: "+kind)
			var meshes=parent.find_children("*","MeshInstance3D",true,false)
			check(meshes.size()>0 and meshes.size()<=12,"Draw-call budget: "+kind)
			for child in meshes:
				var t=child.transform;var ancestor=child.get_parent()
				while ancestor!=parent:t=ancestor.transform*t;ancestor=ancestor.get_parent()
				var bounds:AABB=t*child.get_aabb()
				check(bounds.position.y>=-.002 and bounds.end.y<=size.y+.002,"Height: "+kind)
				check(bounds.position.x>=-size.x*.5-.002 and bounds.end.x<=size.x*.5+.002,"Width: "+kind)
				check(bounds.position.z>=-size.z*.5-.002 and bounds.end.z<=size.z*.5+.002,"Depth: "+kind)
				check(not child.is_processing(),"Art should be static")
			total+=1;parent.free()
	print("STATIONERY_LEGACY "+JSON.stringify({"checks":total,"passed":failures.is_empty(),"failures":failures}))
	quit(0 if failures.is_empty() else 1)
