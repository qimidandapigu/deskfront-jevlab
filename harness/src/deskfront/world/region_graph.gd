extends RefCounted
const ENTRY="c0r1"
const EXIT="c2r1"
const NAV_STEP=.025
const NAV_CLEARANCE=.0401
const NAV_DIRECTIONS=[Vector2i(1,0),Vector2i(-1,0),Vector2i(0,1),Vector2i(0,-1)]

static func nav_point(node:Vector2i)->Array:
	return [snappedf(node.x*NAV_STEP,.001),snappedf(node.y*NAV_STEP-1.15,.001)]

static func nav_index(point:Array)->Vector2i:
	return Vector2i(floori(float(point[0])/NAV_STEP+.5),floori((float(point[1])+1.15)/NAV_STEP+.5))

static func clear_grid(covers:Array)->Dictionary:
	var nodes:Dictionary={}
	for i in range(2,71):
		for j in range(6,87):nodes[Vector2i(i,j)]=true
	for row in covers:
		var lo_x:int=floori((float(row[0])-float(row[2])*.5-NAV_CLEARANCE)/NAV_STEP+.0000001)+1
		var hi_x:int=ceili((float(row[0])+float(row[2])*.5+NAV_CLEARANCE)/NAV_STEP-.0000001)
		var lo_z:int=floori((float(row[1])-float(row[3])*.5-NAV_CLEARANCE+1.15)/NAV_STEP+.0000001)+1
		var hi_z:int=ceili((float(row[1])+float(row[3])*.5+NAV_CLEARANCE+1.15)/NAV_STEP-.0000001)
		for i in range(lo_x,hi_x):
			for j in range(lo_z,hi_z):nodes.erase(Vector2i(i,j))
	return nodes

static func cell_nodes(nodes:Dictionary,cell:String,boundary:bool=false)->Dictionary:
	var x:int=int(cell.substr(1,1));var z:int=int(cell.substr(3,1));var margin:int=0 if boundary else 1
	var result:Dictionary={}
	for point in nodes:
		if point.x>=x*24+margin and point.x<=(x+1)*24-margin and point.y>=4+z*28+margin and point.y<=4+(z+1)*28-margin:result[point]=true
	return result

static func grid_path(nodes:Dictionary,start:Vector2i,finish:Vector2i)->Array:
	if not nodes.has(start) or not nodes.has(finish):return []
	var queue:Array=[start];var previous:Dictionary={start:null};var cursor:int=0
	while cursor<queue.size():
		var node:Vector2i=queue[cursor];cursor+=1
		if node==finish:
			var result:Array=[];var back:Variant=node
			while back!=null:result.append(back);back=previous[back]
			result.reverse();return result
		for direction in NAV_DIRECTIONS:
			var other:Vector2i=node+direction
			if nodes.has(other) and not previous.has(other):previous[other]=node;queue.append(other)
	return []

static func largest_component(nodes:Dictionary)->Dictionary:
	var remaining:Dictionary=nodes.duplicate();var largest:Dictionary={}
	while not remaining.is_empty():
		var first:Vector2i=remaining.keys()[0]
		for candidate in remaining:
			if candidate.x<first.x or (candidate.x==first.x and candidate.y<first.y):first=candidate
		var queue:Array=[first];var component:Dictionary={first:true};var cursor:int=0;remaining.erase(first)
		while cursor<queue.size():
			var node:Vector2i=queue[cursor];cursor+=1
			for direction in NAV_DIRECTIONS:
				var other:Vector2i=node+direction
				if remaining.has(other):remaining.erase(other);component[other]=true;queue.append(other)
		if component.size()>largest.size():largest=component
	return largest

static func grid_reachable(nodes:Dictionary,start:Vector2i)->Dictionary:
	if not nodes.has(start):return {}
	var queue:Array=[start];var seen:Dictionary={start:true};var cursor:int=0
	while cursor<queue.size():
		var node:Vector2i=queue[cursor];cursor+=1
		for direction in NAV_DIRECTIONS:
			var other:Vector2i=node+direction
			if nodes.has(other) and not seen.has(other):seen[other]=true;queue.append(other)
	return seen

static func nearest_node(nodes:Dictionary,target:Vector2i)->Vector2i:
	var best:Vector2i=nodes.keys()[0];var best_distance:int=(best-target).length_squared()
	for node in nodes:
		var distance:int=(node-target).length_squared()
		if distance<best_distance or (distance==best_distance and (node.x<best.x or (node.x==best.x and node.y<best.y))):best=node;best_distance=distance
	return best

static func port_component(nodes:Dictionary,cell:String,neighbours:Array)->Dictionary:
	var remaining:Dictionary=nodes.duplicate();var required:Array=[]
	var x:int=int(cell.substr(1,1));var z:int=int(cell.substr(3,1))
	for other in neighbours:
		var ox:int=int(other.substr(1,1));var oz:int=int(other.substr(3,1))
		required.append([0,(x+1)*24 if ox>x else x*24] if ox!=x else [1,4+(z+1)*28 if oz>z else 4+z*28])
	while not remaining.is_empty():
		var component:Dictionary=largest_component(remaining)
		for node in component:remaining.erase(node)
		var eligible:bool=true
		for edge in required:
			var touches:bool=false
			for node in component:
				if (node.x if edge[0]==0 else node.y)==edge[1]:touches=true;break
			if not touches:eligible=false;break
		if eligible:return component
	return {}

static func compact_path(nodes:Array)->Array:
	var result:Array=[]
	for i in range(nodes.size()):
		if i==0 or i==nodes.size()-1 or nodes[i]-nodes[i-1]!=nodes[i+1]-nodes[i]:result.append(nav_point(nodes[i]))
	return result

static func stitched_route(regions:Array,components:Dictionary,anchors:Dictionary,crossings:Dictionary,endpoint_ids:Array)->Array:
	var points:Array=grid_path(components[regions[0]],endpoint_ids[0],anchors[regions[0]])
	for i in range(regions.size()-1):points.append_array(crossings[regions[i]+"__"+regions[i+1]].slice(1))
	var tail:Array=grid_path(components[regions[-1]],anchors[regions[-1]],endpoint_ids[1])
	if points.is_empty() or tail.is_empty():return []
	points.append_array(tail.slice(1));return compact_path(points)

static func derive_navigation(graph:Dictionary,centers:Dictionary,covers:Array,main:Array,alternate:Array,entry_cell:String,exit_cell:String,exit_target:Array=[],strict_cells:Variant=null)->Dictionary:
	var nodes:Dictionary=clear_grid(covers);var components:Dictionary={};var anchors:Dictionary={}
	if strict_cells==null:strict_cells=graph
	var legacy_reachable:Dictionary=largest_component(nodes) if strict_cells.size()<graph.size() else nodes
	for cell in graph:
		var component:Dictionary=port_component(cell_nodes(nodes,cell,true),cell,graph[cell]) if strict_cells.has(cell) else largest_component(cell_nodes(legacy_reachable,cell,true))
		if component.is_empty():return {}
		components[cell]=component;anchors[cell]=nearest_node(component,nav_index(centers[cell]))
	var crossings:Dictionary={}
	for cell in graph:
		for other in graph[cell]:
			var key:String=cell+"__"+other;var reverse:String=other+"__"+cell
			if crossings.has(reverse):
				var reversed:Array=crossings[reverse].duplicate();reversed.reverse();crossings[key]=reversed;continue
			var corridor:Dictionary=cell_nodes(nodes,cell,true);corridor.merge(cell_nodes(nodes,other,true))
			var points:Array=grid_path(corridor,anchors[cell],anchors[other])
			if points.is_empty() and (not strict_cells.has(cell) or not strict_cells.has(other)):points=grid_path(nodes,anchors[cell],anchors[other])
			if points.is_empty():return {}
			crossings[key]=points
	var endpoints:Array=[];var endpoint_ids:Array=[]
	for pair in [[entry_cell,[.06,centers[entry_cell][1]]],[exit_cell,exit_target if not exit_target.is_empty() else [1.72,centers[exit_cell][1]]]]:
		var preferred:Vector2i=nav_index(pair[1]);var node:Vector2i=nearest_node(components[pair[0]],preferred)
		endpoints.append(pair[1] if node==preferred else nav_point(node));endpoint_ids.append(node)
	var main_points:Array=stitched_route(main,components,anchors,crossings,endpoint_ids)
	var flank:Array=stitched_route(alternate if not alternate.is_empty() else main,components,anchors,crossings,endpoint_ids)
	if main_points.is_empty() or flank.is_empty():return {}
	var positions:Dictionary={}
	for cell in anchors:positions[cell]=nav_point(anchors[cell])
	var friendly_slots:Array=[]
	for offset in [-.28,.28]:
		var target:Vector2i=nav_index([.12,float(endpoints[0][1])+offset]);var candidates:Dictionary={}
		for node in components[entry_cell]:
			var point:Array=nav_point(node);var free:bool=true
			for previous in friendly_slots:
				if Vector2(float(point[0])-float(previous[0]),float(point[1])-float(previous[1])).length()<.15:free=false;break
			if free:candidates[node]=true
		if candidates.is_empty():return {}
		friendly_slots.append(nav_point(nearest_node(candidates,target)))
	var walkable_slots:Dictionary={}
	for component in components.values():walkable_slots.merge(component)
	return {"anchors":positions,"entry":endpoints[0],"exit":endpoints[1],"main_route":main_points,"flank":flank,"friendly_slots":friendly_slots,"walkable_slots":walkable_slots}

static func refresh_geometry_navigation(spec:Dictionary,exit_target:Array=[])->bool:
	var library=JSON.parse_string(FileAccess.get_file_as_string("res://data/world-regions.json"))
	var graph:Dictionary={};var centers:Dictionary={};var strict_cells:Dictionary={}
	for op in spec.build_operations:
		if op.op=="place_region" and op.module!="empty":
			graph[op.cell]=[];centers[op.cell]=library.cells[op.cell][op.module].center
			if library.cells[op.cell][op.module].has("layout") or op.module=="fortress_base":strict_cells[op.cell]=true
	for op in spec.build_operations:
		if op.op=="connect_regions":
			var edge:Dictionary=library.edges[op.edge];graph[edge.a].append(edge.b);graph[edge.b].append(edge.a)
	var card:Dictionary=spec.design_card
	var navigation:Dictionary=derive_navigation(graph,centers,spec.covers,card.main_regions,card.flank_regions,card.entry_cell,card.exit_cell,exit_target,strict_cells)
	if navigation.is_empty():return false
	for key in ["entry","exit","main_route","flank","friendly_slots"]:spec[key]=navigation[key]
	spec.support=[]
	for cell in card.main_regions.slice(1,-1):
		if spec.support.size()<2:spec.support.append(navigation.anchors[cell])
	if spec.support.is_empty():spec.support=[navigation.anchors[card.entry_cell]]
	spec.design_card.region_anchors=navigation.anchors
	return true

static func rotated_cover(row:Array,center:Array,rotation:int)->Array:
	var dx:float=float(row[0])-float(center[0]);var dz:float=float(row[1])-float(center[1])
	var width:float=float(row[2]);var depth:float=float(row[3])
	for i in range(int(rotation/90)):
		var old_dx:float=dx;dx=-dz;dz=old_dx
		var old_width:float=width;width=depth;depth=old_width
	return [snappedf(float(center[0])+dx,.001),snappedf(float(center[1])+dz,.001),width,depth,row[4],row[5]]

static func rear_slots(centers:Dictionary,covers:Array,exit_z:float,walkable_slots:Variant=null)->Array:
	var offsets:Array=[[0,0],[-.18,-.27],[.18,.27],[-.18,.27],[.18,-.27],
		[0,-.28],[0,.28],[-.18,0],[.18,0],[-.08,-.16],[.08,.16],[-.08,.16],[.08,-.16]]
	var ordered:Array=centers.values()
	ordered.sort_custom(func(a,b):
		if float(a[0])!=float(b[0]):return float(a[0])>float(b[0])
		if absf(float(a[1])-exit_z)!=absf(float(b[1])-exit_z):return absf(float(a[1])-exit_z)<absf(float(b[1])-exit_z)
		return float(a[1])<float(b[1]))
	var slots:Array=[]
	for center in ordered:
		for offset in offsets:
			var x:float=snappedf(float(center[0])+float(offset[0]),.001)
			var z:float=snappedf(float(center[1])+float(offset[1]),.001)
			if walkable_slots!=null:
				var node:Vector2i=nav_index([x,z])
				if not walkable_slots.has(node):continue
				var point:Array=nav_point(node);x=point[0];z=point[1]
			if x<.08 or x>1.72 or z<-.98 or z>.98:continue
			var occupied:bool=false
			for cover in covers:
				if absf(x-float(cover[0]))<float(cover[2])*.5+.045 and absf(z-float(cover[1]))<float(cover[3])*.5+.045:
					occupied=true;break
			if occupied:continue
			for row in slots:
				if Vector2(x-float(row[0]),z-float(row[1])).length()<.149:
					occupied=true;break
			if occupied:continue
			var weapons:Array=["rifle","rifle","smg","rocket","pistol","rifle"]
			slots.append([x,z,weapons[slots.size()],"后场守备"])
			if slots.size()==6:return slots
	return []

static func route(graph:Dictionary,start:String,finish:String,excluded:String="") -> Array:
	if not graph.has(start) or not graph.has(finish):return []
	var queue:Array=[[start]];var seen:Dictionary={start:true}
	while not queue.is_empty():
		var path:Array=queue.pop_front();var node:String=path[-1]
		if node==finish:return path
		for other in graph[node]:
			if not seen.has(other) and other!=excluded:
				seen[other]=true;queue.append(path+[other])
	return []

static func assemble(operations:Variant) -> Dictionary:
	var library=JSON.parse_string(FileAccess.get_file_as_string("res://data/world-regions.json"))
	if not operations is Array or operations.size()>80:return {}
	var selected:Dictionary={};var rotations:Dictionary={};var connections:Array=[];var formation:String="";var props:Array=[];var component_edits:Dictionary={}
	var entry_cell:String=ENTRY;var exit_cell:String=EXIT;var ports_set:bool=false
	for op in operations:
		if not op is Dictionary:return {}
		match op.get("op",""):
			"place_region":
				var cell=op.get("cell","");var module=op.get("module","")
				var rotation=op.get("rotation",0)
				if not cell is String or not module is String:return {}
				if not library.cells.has(cell) or selected.has(cell) or not library.cells[cell].has(module):return {}
				if not (rotation is int or rotation is float) or not float(rotation) in [0.0,90.0,180.0,270.0]:return {}
				selected[cell]=module;rotations[cell]=int(rotation)
			"connect_regions":
				var edge=op.get("edge","")
				if not edge is String or not library.edges.has(edge) or connections.has(edge):return {}
				connections.append(edge)
			"set_ports":
				if ports_set:return {}
				entry_cell=str(op.get("entry",""));exit_cell=str(op.get("exit",""))
				if not entry_cell in ["c0r0","c0r1","c0r2"] or not exit_cell in ["c2r0","c2r1","c2r2"]:return {}
				ports_set=true
			"deploy":
				if formation!="" or not op.get("module","") in ["rear","distributed","forward","layered"]:return {}
				formation=op.module
			"place_prop":
				if props.size()>=12:return {}
				props.append(op)
			"edit_component":
				var cell=str(op.get("cell",""));var index=op.get("index",-1)
				if not (index is int or index is float) or float(index)!=float(int(index)):return {}
				var edit_key:String=cell+"#"+str(int(index))
				if component_edits.has(edit_key):return {}
				component_edits[edit_key]=op
			_:return {}
	if selected.size()!=9 or formation=="":return {}
	var graph:Dictionary={};var centers:Dictionary={};var floors:Array=[];var covers:Array=[]
	# Use the same canonical cell order as the host, not model response order.
	for cell in library.cells:
		var part:Dictionary=library.cells[cell][selected[cell]]
		if selected[cell]!="empty":graph[cell]=[];centers[cell]=part.center
		floors.append_array(part.floors.duplicate(true))
		for i in range(part.covers.size()):
			var row:Array=rotated_cover(part.covers[i],part.center,rotations[cell])
			var edit_key:String=cell+"#"+str(i)
			if component_edits.has(edit_key):
				var edit:Dictionary=component_edits[edit_key]
				var action:String=str(edit.get("action",""))
				if action=="remove":continue
				if not action in ["move","replace"]:return {}
				var x=edit.get("x");var z=edit.get("z");var turn=edit.get("rotation",0)
				if not (x is int or x is float) or not (z is int or z is float):return {}
				if not is_finite(float(x)) or not is_finite(float(z)):return {}
				if not (turn is int or turn is float) or not float(turn) in [0.0,90.0]:return {}
				if action=="replace":
					var asset:String=str(edit.get("asset",""))
					if not library.props.has(asset):return {}
					var dimensions:Dictionary=library.props[asset]
					row=[float(x),float(z),float(dimensions.width),float(dimensions.depth),asset,float(dimensions.height)]
				else:row[0]=float(x);row[1]=float(z)
				if float(turn)==90.0:
					var old_width:float=float(row[2]);row[2]=row[3];row[3]=old_width
				if absf(float(x)-float(part.center[0]))+float(row[2])*.5>.3 or absf(float(z)-float(part.center[1]))+float(row[3])*.5>.35:return {}
				row[0]=snappedf(float(x),.001);row[1]=snappedf(float(z),.001)
			covers.append(row)
	for name in connections:
		var edge:Dictionary=library.edges[name]
		if not graph.has(edge.a) or not graph.has(edge.b):return {}
		graph[edge.a].append(edge.b);graph[edge.b].append(edge.a);floors.append(edge.floor.duplicate())
	for edit_key in component_edits:
		var edit:Dictionary=component_edits[edit_key]
		var cell:String=str(edit.get("cell",""));var index:int=int(edit.get("index",-1))
		if not selected.has(cell) or selected[cell]=="empty" or index<0 or index>=library.cells[cell][selected[cell]].covers.size():return {}
	floors=[[0.0,-1.05,1.8,1.05]]
	for name in library.edges:
		var edge:Dictionary=library.edges[name]
		if not connections.has(name) and graph.has(edge.a) and graph.has(edge.b):covers.append(edge.barrier.duplicate())
	var per_cell:Dictionary={}
	for op in props:
		var cell=op.get("cell","");var asset=op.get("asset","");var rotation=op.get("rotation",-1)
		var x=op.get("x");var z=op.get("z")
		if not cell is String or not graph.has(cell):return {}
		if not asset is String or not library.props.has(asset):return {}
		# JSON.parse_string turns protocol numbers into floats, including 0 and 90.
		if not (rotation is int or rotation is float) or not float(rotation) in [0.0,90.0]:return {}
		if not (x is int or x is float) or not (z is int or z is float):return {}
		if not is_finite(float(x)) or not is_finite(float(z)):return {}
		var dimensions:Dictionary=library.props[asset]
		var w:float=float(dimensions.width);var d:float=float(dimensions.depth)
		if float(rotation)==90.0:
			var old_w:float=w
			w=d
			d=old_w
		var center:Array=library.cells[cell].open.center
		if absf(float(x)-float(center[0]))+w*.5>.27 or absf(float(z)-float(center[1]))+d*.5>.32:return {}
		per_cell[cell]=int(per_cell.get(cell,0))+1
		if per_cell[cell]>3:return {}
		covers.append([snappedf(float(x),.001),snappedf(float(z),.001),w,d,asset,float(dimensions.height)])
	var main=route(graph,entry_cell,exit_cell)
	if main.is_empty():return {}
	for cell in graph:
		if route(graph,entry_cell,cell).is_empty():return {}
	var alternate:Array=[]
	for cell in main.slice(1,-1):
		alternate=route(graph,entry_cell,exit_cell,cell)
		if not alternate.is_empty():break
	var geometric_routes:bool=false
	for cell in selected:
		if library.cells[cell][selected[cell]].has("layout"):geometric_routes=true
	for point in centers.values():
		for row in covers:
			if absf(float(point[0])-float(row[0]))<float(row[2])*.5+NAV_CLEARANCE and absf(float(point[1])-float(row[1]))<float(row[3])*.5+NAV_CLEARANCE:geometric_routes=true
	var strict_cells:Dictionary={}
	for cell in graph:
		if library.cells[cell][selected[cell]].has("layout") or selected[cell]=="fortress_base":strict_cells[cell]=true
	var navigation:Dictionary=derive_navigation(graph,centers,covers,main,alternate,entry_cell,exit_cell,[],strict_cells) if geometric_routes else {}
	if geometric_routes and navigation.is_empty():return {}
	var anchors:Dictionary=navigation.anchors if geometric_routes else centers
	var rear:Array=rear_slots(centers,covers,float(centers[exit_cell][1]),navigation.walkable_slots if geometric_routes else null)
	if rear.is_empty():return {}
	var extra:Array=[]
	for cell in graph:
		if cell!=entry_cell and cell!=exit_cell:extra.append([anchors[cell][0],anchors[cell][1],"rifle","分区守备"])
	extra.sort_custom(func(a,b):return (a[0]<b[0] if formation=="forward" else a[0]>b[0]) if a[0]!=b[0] else a[1]<b[1])
	var slots:Array=rear if formation=="rear" else (extra+rear).slice(0,6)
	if formation=="layered" and not extra.is_empty():
		var front=extra[0]
		for point in extra:
			if point[0]<front[0]:front=point
		var ordered:Array=[front,rear[0]]
		for point in extra:
			if point!=front:ordered.append(point)
		ordered.append_array(rear.slice(1));slots=ordered.slice(0,6)
	var main_points:Array=[]
	for cell in main:main_points.append(centers[cell])
	var support:Array=[];var flank:Array=[]
	for cell in main.slice(1,-1):
		if support.size()<2:support.append(anchors[cell])
	if support.is_empty():support=[anchors[entry_cell]]
	for cell in (alternate if not alternate.is_empty() else main):flank.append(centers[cell])
	var spec:Dictionary={"name":"模块拼接 / "+("双路连接" if not alternate.is_empty() else "连续推进"),"intent":"清除守军", "floors":floors,"covers":covers,"defender_slots":slots,"defenders":slots.slice(0,3),"entry":[.06,centers[entry_cell][1]],"exit":[1.72,centers[exit_cell][1]],"main_route":main_points,"support":support,"flank":flank,"side":-1,"design_card":{"signature":"region_graph","regions":graph.size(),"connections":connections.size(),"alternate_route":not alternate.is_empty(),"main_regions":main,"flank_regions":alternate,"placed_props":props.size(),"entry_cell":entry_cell,"exit_cell":exit_cell},"build_operations":operations.duplicate(true),"assembly_kind":"region_graph_v1"}
	if geometric_routes:
		for key in ["entry","exit","main_route","flank","friendly_slots"]:spec[key]=navigation[key]
		spec.design_card["navigation"]="geometry_grid_v1";spec.design_card["region_anchors"]=anchors
	return spec

