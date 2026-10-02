extends SceneTree

var failures:Array=[]
var checks:int=0
func check(value:bool,message:String):
	checks+=1
	if not value:failures.append(message)

func panels(revision:int)->Array:
	var result:Array=[]
	for x in range(3):
		for y in range(3):
			var panel=Node3D.new()
			panel.set_meta("cell",Vector2i(x,y));panel.set_meta("region_index",revision);panel.set_meta("desk_top",.8)
			result.append(panel)
	return result

func build(revision:int,covers:Array)->Dictionary:
	var scenery=load("res://scripts/world_scenery.gd").new()
	var desks:Array=panels(revision)
	var receipt:Dictionary=scenery.build(null,{"covers":covers},2.4,.2,desks)
	var count:int=0
	for child in scenery.get_children():
		if child.has_meta("desk_detail"):count+=1
	check(count<=1,"one detail budget")
	check(count==int(receipt.status=="placed"),"receipt describes actual placement")
	check(scenery.find_children("*","CollisionShape3D",true,false).is_empty(),"no decorative collision")
	if receipt.status=="placed":
		var b:Array=receipt.bounds
		var bounds=Rect2(b[0],b[1],b[2],b[3])
		var cell:Array=receipt.cell
		var desk=Rect2(cell[0]*.6,(cell[1]-1)*.7-.35,.6,.7).grow(-.0119)
		check(desk.encloses(bounds),"actual rotated mesh stays on desk")
		check(scenery.clear_of_covers(bounds,covers),"actual rotated mesh avoids cover")
	for panel in desks:panel.free()
	scenery.free()
	return receipt

func _initialize():
	var kinds:Dictionary={}
	# Full independent rotation: USB is reachable; roach no longer overwrites it.
	for revision in range(20):
		var receipt:Dictionary=build(revision,[])
		check(receipt.status=="placed","all detail kinds can spawn on clear desks")
		kinds[receipt.kind]=int(kinds.get(receipt.kind,0))+1
	check(kinds.size()==10 and kinds.get("usb_drive",0)==2 and kinds.get("cartoon_roach",0)==2,"complete rotation")
	# Revision 7 is USB, prefers desk 8; fully block that desk only.
	var fallback:Dictionary=build(7,[[1.5,.7,.6,.7,"warehouse",.3]])
	check(fallback.status=="placed" and fallback.cell!=[2,2],"try another desk if preferred desk is full")
	check(fallback.checked_positions>9,"fallback actually tried the full preferred desk")
	var blocked:Dictionary=build(7,[[.9,0,1.8,2.1,"warehouse",.3]])
	check(blocked.status=="skipped" and blocked.reason=="no_clear_space","fully blocked region skips explicitly")
	check(blocked.checked_positions==81,"bounded search through all desks")
	print("SCENERY_PLACEMENT "+JSON.stringify({"passed":failures.is_empty(),"checks":checks,"kinds":kinds,"fallback":fallback,"blocked":blocked,"failures":failures}))
	quit(0 if failures.is_empty() else 1)
