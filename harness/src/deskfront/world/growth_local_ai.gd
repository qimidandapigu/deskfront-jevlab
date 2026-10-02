extends RefCounted
## Local game-AI combat planning for non-Harness teams in infinite growth.
## Harness-controlled teams bypass this helper; it only proposes engine moves.

func plan(growth,team: String):
	var game=growth.game
	var mission: Dictionary=growth.mission
	if mission.is_empty() or mission.get("status", "")!="active":return
	if ((growth.harness_green and team=="green") or (growth.harness_red and team=="red")):return
	var squad: Array=game.living(team).filter(func(u):return not u.tank)
	for u in squad:
		if game.elapsed<u.safety_until:continue
		var row: Dictionary=growth.unit_roles.get(u.id,{} )
		if game.elapsed<float(row.get("next_local_plan",0)):continue
		row["next_local_plan"]=game.elapsed+.8+float(abs(u.id.hash())%5)*.07
		growth.unit_roles[u.id]=row
		var enemy=game.closest_enemy(u)
		if enemy==null:continue
		var flanking:bool=team=="green" and squad.find(u)>=maxi(1,squad.size()/2) and mission.spec.design_card.get("alternate_route",false)
		row["role"]="侧翼组" if flanking else ("正面组" if team=="green" else "阵地守军")
		if not flanking and game.find_target(u)!=null and game.elapsed-u.last_shot_at<3.0:
			row["phase"]="有效交火";continue
		var previous: Vector2=row.get("last_local_position",u.pos())
		if u.pos().distance_to(previous)>.035:row["last_local_progress"]=game.elapsed
		row["last_local_position"]=u.pos()
		var idle: float=game.elapsed-float(row.get("last_local_progress",game.elapsed))
		if not row.has("last_local_progress"):row["last_local_progress"]=game.elapsed
		if not u.route.is_empty() and idle<3.2:continue
		if team=="green" and u.suppression<.65:
			var route_points:Array=mission.spec.flank if flanking else mission.spec.get("main_route",[])
			var waypoint:int=int(row.get("tactical_waypoint",0))
			while waypoint<route_points.size()-1:
				var reached=Vector2(mission.left+route_points[waypoint][0],mission.center_z+route_points[waypoint][1])
				if u.pos().distance_to(reached)>=.13:break
				waypoint+=1
			row["tactical_waypoint"]=waypoint
			if waypoint<route_points.size()-1:
				var point=Vector2(mission.left+route_points[waypoint][0],mission.center_z+route_points[waypoint][1])
				var usable=game.field.path(u.pos(),point)
				if not usable.is_empty():
					u.move_to(point);row["phase"]="侧路绕行" if flanking else "分段推进";continue
		var options: Dictionary={"require_fire_arc":true,"allow_same":false,"range":game.config.weapons[u.weapon].range,"max_travel":.85,"detour":3.0}
		var anchor:Vector2=enemy.pos()
		if team=="red" and row.has("anchor"):
			anchor=Vector2(row.anchor[0],row.anchor[1]);options["goal_leash"]=.4
		if u.suppression>.72:
			options["require_fire_arc"]=false;options["survival"]=true
		if u.seek_cover(enemy.pos(),anchor,options):
			row["phase"]="换到有效射位";u.order_mode="local_firing_position";continue
		var best: Vector2=u.pos();var best_cost: float=INF
		var approaches: Array=[]
		var distance: float=clampf(float(game.config.weapons[u.weapon].range)*.7,.25,.65)
		for j in range(12):
			var angle: float=TAU*j/12.0
			var point=enemy.pos()+Vector2(cos(angle),sin(angle))*distance
			if team=="red" and point.distance_to(anchor)>.4:continue
			if not game.field.walkable(point):continue
			if game.living().any(func(other):return other.id!=u.id and other.pos().distance_to(point)<.12):continue
			if not game.field.line_of_sight(point,enemy.pos()):continue
			approaches.append(point)
		approaches.sort_custom(func(a,b):return u.pos().distance_to(a)<u.pos().distance_to(b))
		for point in approaches.slice(0,3):
			var route=game.field.path(u.pos(),point)
			if route.is_empty():continue
			var cost: float=game.field.route_length(route)
			if point.distance_to(u.pos())<.08:continue
			if cost<best_cost:best_cost=cost;best=point
		if best_cost<INF:
			u.move_to(best);u.order_mode="local_reposition";row["phase"]="绕障接敌"
