extends RefCounted
## The same bounded recipe used by the Python builder and the Godot engine.

static func recipe()->Dictionary:
	return JSON.parse_string(FileAccess.get_file_as_string("res://data/world-fortress.json"))

static func outside_slots(covers:Array,row_z:float,original:Array,reachable:Variant=null)->Array:
	var separation:float=.1501 if reachable!=null else .15
	var xs:Array=[1.32,1.38,1.26,1.44,1.50,1.56,1.62,1.68,1.18,1.12,1.06,1.22,1.0,.94,.88]
	var dzs:Array=[0.0,-.1,.1,-.2,.2,-.3,.3,-.4,.4,-.5,.5,-.6,.6,
		-.05,.05,-.15,.15,-.25,.25,-.35,.35,-.45,.45,-.55,.55]
	var toward_center:float=1.0 if row_z<0.0 else -1.0
	var desired:Array=[[1.32,0.0],[1.33,-.205],[1.33,.205],[1.45,toward_center*.42],[1.55,toward_center*.20],[1.65,-toward_center*.20]]
	if row_z==0.0:
		desired=[]
		for source in original:desired.append([source[0],source[1]])
	var chosen:Array=[]
	for i in range(desired.size()):
		var best:Array=[];var best_score:float=INF
		for x in xs:
			for dz in dzs:
				var z:float=snappedf(row_z+float(dz),.001)
				if float(x)<.08 or float(x)>1.72 or z<-.98 or z>.98:continue
				if reachable!=null and not reachable.has(preload("res://scripts/world_region_graph.gd").nav_index([x,z])):continue
				if float(x)>1.42 and absf(float(dz))<.35:continue
				var blocked:bool=false
				for cover in covers:
					if absf(float(x)-float(cover[0]))<float(cover[2])*.5+.053 and absf(z-float(cover[1]))<float(cover[3])*.5+.053:
						blocked=true;break
				if blocked:continue
				for placed in chosen:
					if Vector2(float(x)-float(placed[0]),z-float(placed[1])).length()<separation:
						blocked=true;break
				if blocked:continue
				var score:float=pow(float(x)-float(desired[i][0]),2)+pow(float(dz)-float(desired[i][1]),2)
				if score<best_score-.000000001:
					best=[x,z,original[i][2],original[i][3]];best_score=score
		if best.is_empty():return []
		chosen.append(best)
	return chosen

static func apply(spec:Dictionary,enemy_count:int)->Dictionary:
	var row:Dictionary=recipe()
	if enemy_count<1 or enemy_count>row.defender_slots.size():return {}
	if spec.get("assembly_kind","")=="region_graph_v1":
		var anchors:Array=[]
		for operation in spec.get("build_operations",[]):
			if operation.get("op","")=="place_region" and operation.get("module","")=="fortress_base":anchors.append(operation.get("cell",""))
		if anchors!=[spec.design_card.exit_cell]:return {}
	var built:Dictionary=spec.duplicate(true)
	var row_z:float=float(spec.exit[1])
	built.name=row.name;built.intent=row.intent
	var covers:Array=row.covers.duplicate(true)
	for cover in covers:cover[1]=snappedf(float(cover[1])+row_z,.001)
	built.covers.append_array(covers)
	var reachable:Variant=null
	if built.design_card.get("navigation","")=="geometry_grid_v1":
		var builder=preload("res://scripts/world_region_graph.gd")
		reachable=builder.grid_reachable(builder.clear_grid(built.covers),builder.nav_index(built.entry))
	built.defender_slots=outside_slots(built.covers,row_z,row.defender_slots,reachable)
	if built.defender_slots.is_empty():return {}
	built.defenders=built.defender_slots.slice(0,enemy_count)
	built.exit=[row.exit[0],row_z]
	built["rescue"]={"captive":[row.captive[0],row_z],"status":"waiting"}
	built.design_card["mission_kind"]="rescue"
	if built.design_card.get("navigation","")=="geometry_grid_v1":
		if not preload("res://scripts/world_region_graph.gd").refresh_geometry_navigation(built,built.exit):return {}
	return built
