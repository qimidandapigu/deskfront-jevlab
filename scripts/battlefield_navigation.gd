extends RefCounted

# Navigation is a controlled helper. Battlefield remains the public world and
# collision fact surface; this helper only mutates its grids and caches.
var battlefield

func setup(value) -> void:
	battlefield = value

func rebuild() -> void:
	# update() does not clear solids when region/cell size are unchanged.
	battlefield.grid.clear();battlefield.tank_grid.clear()
	battlefield.grid.region = Rect2i(0,0, int((battlefield.config.bounds[2]-battlefield.base.x)/battlefield.cell)+1,int((battlefield.config.bounds[3]-battlefield.base.y)/battlefield.cell)+1)
	battlefield.grid.cell_size = Vector2.ONE * battlefield.cell
	battlefield.grid.offset = battlefield.base
	battlefield.grid.diagonal_mode = AStarGrid2D.DIAGONAL_MODE_ONLY_IF_NO_OBSTACLES
	battlefield.grid.update()
	battlefield.tank_grid.region=battlefield.grid.region
	battlefield.tank_grid.cell_size=battlefield.grid.cell_size
	battlefield.tank_grid.offset=battlefield.base
	battlefield.tank_grid.diagonal_mode=battlefield.grid.diagonal_mode
	battlefield.tank_grid.update()
	for c in battlefield.covers + battlefield.obstacles:
		if not c.get("alive",true) or not c.get("nav_block",true): continue
		var center := Vector2(c.position[0],c.position[1])
		var half := Vector2(c.size[0],c.size[1])/2 + Vector2.ONE*.018
		for x in range(battlefield.grid.region.size.x):
			for y in range(battlefield.grid.region.size.y):
				var pos: Vector2=battlefield.to_world(Vector2i(x,y))
				if absf(pos.x-center.x)<half.x and absf(pos.y-center.y)<half.y:
					battlefield.grid.set_point_solid(Vector2i(x,y))
				if absf(pos.x-center.x)<half.x+.075 and absf(pos.y-center.y)<half.y+.075:
					battlefield.tank_grid.set_point_solid(Vector2i(x,y))
	for x in range(battlefield.grid.region.size.x):
		for y in range(battlefield.grid.region.size.y):
			var p=battlefield.to_world(Vector2i(x,y))
			for water in battlefield.config.get("water",[]):
				if battlefield.inside_object(p,water):
					var bridge=false
					for b in battlefield.config.get("bridges",[]):
						if battlefield.inside_object(p,b):bridge=true
					if not bridge:battlefield.grid.set_point_solid(Vector2i(x,y));battlefield.tank_grid.set_point_solid(Vector2i(x,y))
	battlefield.tactical_cache.clear()
	# A topology change invalidates failed cover plans as well as weighted paths.
	# Keeping the cache bounded avoids carrying old unit ids across a rebuild.
	battlefield.cover_misses.clear()
	battlefield.revision += 1

func nearest(p: Vector2, tank: bool=false) -> Vector2i:
	var nav: AStarGrid2D=battlefield.tank_grid if tank else battlefield.grid
	var id: Vector2i=battlefield.to_cell(p)
	id.x = clampi(id.x,0,battlefield.grid.region.size.x-1)
	id.y = clampi(id.y,0,battlefield.grid.region.size.y-1)
	if not nav.is_point_solid(id): return id
	for radius in range(1,16):
		for x in range(-radius,radius+1):
			for y in range(-radius,radius+1):
				var q: Vector2i=id+Vector2i(x,y)
				if nav.is_in_boundsv(q) and not nav.is_point_solid(q): return q
	return id

func path(from: Vector2, dest: Vector2, tank: bool=false) -> PackedVector2Array:
	battlefield.path_queries+=1
	var nav: AStarGrid2D=battlefield.tank_grid if tank else battlefield.grid
	return nav.get_point_path(nearest(from,tank),nearest(dest,tank))

# Weighted tactical navigation shares the short-lived threat snapshot used by
# cover selection. The base grid remains authoritative for collision checks.
func tactical_path(from: Vector2, dest: Vector2, threats: Array, cache_key: String="cover", occupants: Array=[], blockers: Array=[]) -> PackedVector2Array:
	if threats.is_empty() and occupants.is_empty() and blockers.is_empty():return path(from,dest)
	battlefield.tactical_profile.calls+=1
	var signature: String=str(threats.map(func(p):return Vector2(snappedf(p.x,.2),snappedf(p.y,.2))))
	var cached: Dictionary=battlefield.tactical_cache.get(cache_key,{})
	if cached.is_empty() or cached.revision!=battlefield.revision or (battlefield.simulation_time-float(cached.time)>3.0 and cached.signature!=signature):
		var rebuild_started: int=Time.get_ticks_usec()
		var fresh: bool=cached.is_empty() or cached.revision!=battlefield.revision
		var nav: AStarGrid2D=AStarGrid2D.new() if fresh else cached.nav
		if fresh:
			nav.region=battlefield.grid.region;nav.cell_size=battlefield.grid.cell_size;nav.offset=battlefield.grid.offset;nav.diagonal_mode=battlefield.grid.diagonal_mode;nav.update()
			for x in range(battlefield.grid.region.size.x):
				for y in range(battlefield.grid.region.size.y):
					var id: Vector2i=Vector2i(x,y)
					if battlefield.grid.is_point_solid(id):nav.set_point_solid(id)
		# Risk is scored in coarse buckets; final collision/path checks use the fine grid.
		var coarse: Dictionary={}
		var previous: Dictionary=cached.get("coarse",{}) if not fresh else {}
		for x in range(0,battlefield.grid.region.size.x,8):
			for y in range(0,battlefield.grid.region.size.y,8):
				var bucket:=Vector2i(x,y)
				var point: Vector2=battlefield.to_world(bucket);var risk: float=0
				for threat in threats:
					if point.distance_to(threat)<=1.6 and battlefield.line_of_sight(point,threat):risk+=1-battlefield.protection(point,threat)
				var weight: float=1+minf(16,risk*8)
				coarse[bucket]=weight
				if previous.get(bucket,1.0)==weight:continue
				for dx in range(x,mini(x+8,battlefield.grid.region.size.x)):
					for dy in range(y,mini(y+8,battlefield.grid.region.size.y)):
						var id: Vector2i=Vector2i(dx,dy)
						if not nav.is_point_solid(id):nav.set_point_weight_scale(id,weight)
		var rebuild_us: int=Time.get_ticks_usec()-rebuild_started
		battlefield.tactical_profile.rebuilds+=1;battlefield.tactical_profile.rebuild_us+=rebuild_us;battlefield.tactical_profile.max_rebuild_us=maxi(battlefield.tactical_profile.max_rebuild_us,rebuild_us)
		cached={"nav":nav,"revision":battlefield.revision,"time":battlefield.simulation_time,"signature":signature,"coarse":coarse};battlefield.tactical_cache[cache_key]=cached
	var nav: AStarGrid2D=cached.nav
	var restored: Dictionary={}
	for occupant in occupants:
		var center: Vector2i=battlefield.to_cell(occupant.pos())
		for dx in range(-2,3):
			for dy in range(-2,3):
				var id:=center+Vector2i(dx,dy)
				if not nav.is_in_boundsv(id) or nav.is_point_solid(id):continue
				if not restored.has(id):restored[id]=nav.get_point_weight_scale(id)
				nav.set_point_weight_scale(id,restored[id]+12)
	var blocked_cells: Array=[]
	var start: Vector2i=nearest(from)
	for blocker in blockers:
		var radius: float=float(blocker.get_meta("nav_radius",.14))
		var center: Vector2i=battlefield.to_cell(blocker.pos());var cells: int=ceili(radius/battlefield.cell)
		for dx in range(-cells,cells+1):
			for dy in range(-cells,cells+1):
				var id:=center+Vector2i(dx,dy)
				if id==start or not nav.is_in_boundsv(id) or nav.is_point_solid(id):continue
				if battlefield.to_world(id).distance_to(blocker.pos())<radius:nav.set_point_solid(id);blocked_cells.append(id)
	battlefield.path_queries+=1
	var result: PackedVector2Array=nav.get_point_path(start,nearest(dest))
	for id in blocked_cells:nav.set_point_solid(id,false)
	for id in restored:nav.set_point_weight_scale(id,restored[id])
	return result

func walkable(p: Vector2, tank: bool=false) -> bool:
	var id: Vector2i=battlefield.to_cell(p)
	var nav: AStarGrid2D=battlefield.tank_grid if tank else battlefield.grid
	return nav.is_in_boundsv(id) and not nav.is_point_solid(id)

func segment_walkable(a: Vector2,b: Vector2,tank: bool=false) -> bool:
	if not walkable(a,tank) or not walkable(b,tank):return false
	var nav: AStarGrid2D=battlefield.tank_grid if tank else battlefield.grid
	var first: Vector2i=battlefield.to_cell(a);var last: Vector2i=battlefield.to_cell(b)
	# Exact touched-cell test prevents a thin corner sliver from reaching the next physics step.
	for x in range(mini(first.x,last.x)-1,maxi(first.x,last.x)+2):
		for y in range(mini(first.y,last.y)-1,maxi(first.y,last.y)+2):
			var id: Vector2i=Vector2i(x,y)
			if not nav.is_in_boundsv(id) or not nav.is_point_solid(id):continue
			var center: Vector2=battlefield.to_world(id)
			if not battlefield.ray_box(Vector3(a.x,0,a.y),Vector3(b.x,0,b.y),Vector3(center.x,0,center.y),Vector3(battlefield.cell-.000001,1,battlefield.cell-.000001)).is_empty():return false
	return true

func path_around_units(from: Vector2,dest: Vector2,occupants: Array) -> PackedVector2Array:
	var saved: Array=[];var start: Vector2i=nearest(from)
	for occupant in occupants:
		var center: Vector2i=battlefield.to_cell(occupant.pos())
		var radius: float=float(occupant.get_meta("nav_radius",.14 if occupant.tank else .034))
		var cells: int=ceili(radius/battlefield.cell)
		for x in range(center.x-cells,center.x+cells+1):
			for y in range(center.y-cells,center.y+cells+1):
				var id: Vector2i=Vector2i(x,y)
				if id==start or not battlefield.grid.is_in_boundsv(id) or battlefield.grid.is_point_solid(id):continue
				if battlefield.to_world(id).distance_to(occupant.pos())<radius:saved.append(id);battlefield.grid.set_point_solid(id,true)
	battlefield.path_queries+=1
	var result: PackedVector2Array=battlefield.grid.get_point_path(start,nearest(dest))
	for id in saved:battlefield.grid.set_point_solid(id,false)
	return result

func route_length(points: PackedVector2Array) -> float:
	var length: float=0
	for i in range(1,points.size()):length+=points[i-1].distance_to(points[i])
	return length

func soft_offset(anchor: Vector2, ideal: Vector2, max_detour: float=.20) -> Vector2:
	var candidates: Array=[ideal,anchor.lerp(ideal,.66),anchor.lerp(ideal,.33),anchor]
	for candidate in candidates:
		var p: Vector2=battlefield.to_world(nearest(candidate))
		var route := path(anchor,p)
		if not route.is_empty() and route_length(route)<=max_detour:return p
	return battlefield.to_world(nearest(anchor))
