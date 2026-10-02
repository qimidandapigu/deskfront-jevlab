extends RefCounted
## A designed encounter, mirrored by JEV; positions are local metres [x,z].
const WIDTH=1.8
static func catalog() -> Dictionary:
	return JSON.parse_string(FileAccess.get_file_as_string("res://data/world-components.json"))

static func specification(option: String) -> Dictionary:
	return catalog().get(option,{}).duplicate(true)

static func assemble(option: String, operations: Variant) -> Dictionary:
	var libraries=JSON.parse_string(FileAccess.get_file_as_string("res://data/world-build-parts.json"))
	if not libraries is Dictionary or not libraries.has(option):return {}
	var library:Dictionary=libraries[option]
	if not operations is Array or operations.size()!=library.size():return {}
	var selected:Dictionary={}
	for operation in operations:
		if not operation is Dictionary:return {}
		var slot=operation.get("slot","");var module=operation.get("module","")
		if not slot is String or not module is String:return {}
		if not library.has(slot) or selected.has(slot) or not library[slot].has(module):return {}
		var part:Dictionary=library[slot][module]
		if operation.get("op","")!=part.op:return {}
		selected[slot]=part
	var spec=specification(option)
	spec.floors=[];spec.covers=[]
	for slot in library:
		var part:Dictionary=selected[slot]
		if part.op=="place_floor":spec.floors.append(part.value.duplicate(true))
		elif part.op=="place_cover":spec.covers.append(part.value.duplicate(true))
		elif part.op=="deploy":spec.defender_slots=part.value.duplicate(true)
	spec.defenders=spec.defender_slots.slice(0,3)
	spec["build_operations"]=operations.duplicate(true)
	return spec

# A footprint must be supported by the union of floor rectangles, including seams.
# Checking only its center/corners misses holes crossing the middle of a component.
static func floor_supports(floors:Array,center:Vector2,half:Vector2)->bool:
	var xs:Array=[center.x-half.x,center.x+half.x];var zs:Array=[center.y-half.y,center.y+half.y]
	for r in floors:
		for x in [r[0],r[2]]:
			if x>xs[0] and x<xs[1]:xs.append(x)
		for z in [r[1],r[3]]:
			if z>zs[0] and z<zs[1]:zs.append(z)
	xs.sort();zs.sort()
	for i in range(xs.size()-1):
		for j in range(zs.size()-1):
			var x:float=(xs[i]+xs[i+1])*.5;var z:float=(zs[j]+zs[j+1])*.5;var supported=false
			for r in floors:
				if x>=r[0]-.00001 and x<=r[2]+.00001 and z>=r[1]-.00001 and z<=r[3]+.00001:supported=true;break
			if not supported:return false
	return true

static func validate(spec: Dictionary, half_depth: float) -> Dictionary:
	if spec.is_empty() or not spec.has("floors"):return {"ok":false,"reason":"missing_layout"}
	for row in spec.covers:
		if not floor_supports(spec.floors,Vector2(row[0],row[1]),Vector2(row[2],row[3])*.5):return {"ok":false,"reason":"unsupported_component","component":row}
	for i in range(spec.covers.size()):
		var a=spec.covers[i]
		for j in range(i):
			var b=spec.covers[j]
			if absf(a[0]-b[0])<(a[2]+b[2])*.5 and absf(a[1]-b[1])<(a[3]+b[3])*.5:return {"ok":false,"reason":"overlapping_components"}
	var grid=AStarGrid2D.new();var cell: float=.025
	grid.region=Rect2i(0,0,int(WIDTH/cell)+1,int(half_depth*2/cell)+1);grid.cell_size=Vector2.ONE*cell
	grid.diagonal_mode=AStarGrid2D.DIAGONAL_MODE_ONLY_IF_NO_OBSTACLES;grid.update()
	for x in range(grid.region.size.x):
		for y in range(grid.region.size.y):
			var p=Vector2(x*cell,y*cell-half_depth);var supported=false
			for r in spec.floors:
				if p.x>=r[0] and p.x<=r[2] and p.y>=r[1] and p.y<=r[3]:supported=true;break
			if not supported:grid.set_point_solid(Vector2i(x,y))
	for row in spec.covers:
		if row[0]-row[2]/2<0 or row[0]+row[2]/2>WIDTH or absf(row[1])+row[3]/2>half_depth:return {"ok":false,"reason":"cover_outside_region"}
		for x in range(grid.region.size.x):
			for y in range(grid.region.size.y):
				var p=Vector2(x*cell,y*cell-half_depth)
				if absf(p.x-row[0])<row[2]/2+.04 and absf(p.y-row[1])<row[3]/2+.04:grid.set_point_solid(Vector2i(x,y))
	var deployments:Array=spec.defenders+spec.get("friendlies",[])
	var slots:Array=spec.get("defender_slots",spec.defenders)
	var points: Array=[spec.entry,spec.exit]+spec.flank
	for row in slots+deployments:points.append([row[0],row[1]])
	points.append_array(spec.support)
	if spec.has("rescue"):points.append(spec.rescue.captive)
	var ids:Array=[]
	for p in points:
		if not floor_supports(spec.floors,Vector2(p[0],p[1]),Vector2.ONE*.034):return {"ok":false,"reason":"unsupported_route_or_deployment","point":p}
		var id=Vector2i(roundi(p[0]/cell),roundi((p[1]+half_depth)/cell))
		if not grid.is_in_boundsv(id) or grid.is_point_solid(id):return {"ok":false,"reason":"blocked_route_or_deployment","point":p}
		ids.append(id)
	for id in ids:
		if grid.get_id_path(ids[0],id).is_empty():return {"ok":false,"reason":"isolated_deployment_or_route"}
	var direct=grid.get_id_path(ids[0],ids[1])
	if direct.is_empty():return {"ok":false,"reason":"no_main_route"}
	var route:Array=[ids[0]]+ids.slice(2,2+spec.flank.size())+[ids[1]]
	var flank_steps:int=0
	for i in range(route.size()-1):
		var path=grid.get_id_path(route[i],route[i+1])
		if path.is_empty():return {"ok":false,"reason":"no_flank_route"}
		flank_steps+=path.size()-1
	for rows in [slots,deployments]:
		for i in range(rows.size()):
			for j in range(i):
				if Vector2(rows[i][0],rows[i][1]).distance_to(Vector2(rows[j][0],rows[j][1]))<.15:return {"ok":false,"reason":"overlapping_deployments","points":[rows[i],rows[j]]}
	return {"ok":true,"main_steps":direct.size()-1,"flank_steps":flank_steps,"defenders":spec.defenders.size()}
