extends RefCounted
## Geometry-only support placement helpers for the infinite encounter builder.
## They receive the growth owner explicitly and never mutate mission state.
const MORTAR=preload("res://scripts/world_mortar.gd")

static func tank_staging_point(growth, left:float,z:float,spec:Dictionary)->Dictionary:
	# The cannon is a vehicle, not an anti-tank emplacement. Search only the
	# newly committed enemy side and use the actual tank navigation grid.
	var exit_point:Vector2=Vector2(left+float(spec.exit[0]),z+float(spec.exit[1]))
	var best:Vector2=Vector2.ZERO;var best_score:float=INF
	# Leave the outer rear socket free for the mortar.  The old upper bound
	# allowed the tank to occupy the last column, forcing the gun into a nearly
	# lateral position even when the snapshot called it rear support.
	for xi in range(6,14):
		for zi in range(-9,10):
			var point:Vector2=Vector2(left+float(xi)*.1,z+float(zi)*.1)
			if not growth.game.field.walkable(point,true):continue
			if growth.game.living().any(func(u):return u.pos().distance_to(point)<.28):continue
			var score:float=point.distance_to(exit_point)+absf(point.y-z)*.08
			if score<best_score:best=point;best_score=score
	if best_score<INF:return {"ok":true,"point":best}
	return {"ok":false,"reason":"no_clear_tank_staging_point"}

static func mortar_staging_point(growth, left:float,z:float,tank_unit)->Dictionary:
	# The tank is the front-line vehicle.  The old rule picked the low-x side
	# because it was called the "rear band", but low x is actually the approach
	# side for the green squad.  Place the indirect weapon on the tank's actual
	# back side: away from the region entry, with a lateral offset so it still
	# has a clear crew footprint on the tabletop.
	var entry:Vector2=Vector2(left+.18,z)
	var front:Vector2=(entry-tank_unit.pos()).normalized()
	if front.length_squared()<.001:front=Vector2(-1,0)
	var rear:Vector2=-front
	var side:Vector2=Vector2(-rear.y,rear.x)
	var best:Vector2=Vector2.ZERO;var best_score:float=-INF
	for depth in [.14,.24,.34,.44]:
		for lateral in [-.98,-.84,-.70,.70,.84,.98]:
			var desired:Vector2=tank_unit.pos()+rear*depth+side*lateral
			var xoff:float=desired.x-left
			var zoff:float=desired.y-z
			# Keep the rear support socket on this region's tabletop.  A point
			# behind the tank must also remain visibly behind it in map space.
			if xoff<.65 or xoff>1.80:continue
			var point:Vector2=growth.game.field.to_world(growth.game.field.nearest(Vector2(left+xoff,z+zoff)))
			if point.x<=tank_unit.pos().x+.25:continue
			if not growth.game.field.walkable(point):continue
			if not growth.game.field.walkable(point+Vector2(-.07,.11)) or not growth.game.field.walkable(point+Vector2(.07,.11)):continue
			if point.distance_to(tank_unit.pos())<.90 or point.distance_to(tank_unit.pos())>3.2:continue
			var rear_alignment:float=(point-tank_unit.pos()).normalized().dot(rear)
			if rear_alignment<.05:continue
			var nearest_enemy:float=INF
			var enemy_los:int=0
			for enemy in growth.game.living("red"):
				nearest_enemy=minf(nearest_enemy,point.distance_to(enemy.pos()))
				if growth.game.field.line_of_sight(enemy.pos(),point):enemy_los+=1
			if nearest_enemy<.55:continue
			if growth.game.living("green").any(func(u):return u.pos().distance_to(point)<.16):continue
			if not mortar_arc_clear(growth,point,tank_unit):continue
			# Prefer the farthest clear socket behind the tank, then protection.
			var rear_depth:float=(point-tank_unit.pos()).dot(rear)
			var protection:float=growth.game.field.protection(point,tank_unit.pos())
			var score:float=rear_depth*1.35+nearest_enemy-.13*float(enemy_los)-.05*absf(zoff)+protection*.38
			if score>best_score:best=point;best_score=score
	if best_score>-INF:return {"ok":true,"point":best}
	return {"ok":false,"reason":"no_safe_mortar_staging_point"}

static func mortar_arc_clear(growth, point:Vector2,tank_unit)->bool:
	var end:Vector3=tank_unit.aim_point()
	var direction:Vector2=(tank_unit.pos()-point).normalized()
	var mortar_script=MORTAR
	var scale:float=mortar_script.MODEL_SCALE
	var local_muzzle:Vector3=mortar_script.MUZZLE_LOCAL
	var origin:Vector3=Vector3(point.x+direction.x*absf(local_muzzle.z)*scale,growth.game.field.height+local_muzzle.y*scale,point.y+direction.y*absf(local_muzzle.z)*scale)
	var previous:Vector3=origin
	for i in range(1,17):
		var t:float=float(i)/16.0
		var next:Vector3=origin.lerp(end,t)
		next.y+=sin(t*PI)*.72
		var hit:Dictionary=growth.game.fx.trace(previous,next,"battlefield-mortar-1")
		if not hit.is_empty():
			if hit.get("kind","")=="unit" and hit.unit==tank_unit:return true
			return Vector2(hit.point.x,hit.point.z).distance_to(tank_unit.pos())<.20
		previous=next
	return true

static func tank_counter_available(growth, planned_friendlies:int)->bool:
	if growth.game.living("green").any(func(u):return u.weapon=="rocket"):return true
	return OS.get_environment("HARNESS_SECOND_STAGE_TANK_RULE")=="1" and growth.revision==1 and planned_friendlies>0


