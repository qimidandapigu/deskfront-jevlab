extends Node
## Original squad coordinator. Formation ideas mapped to Jurney's PDF in docs/TACTICS.md.
var game
var flag_next: Dictionary={}
var flag_progress: Dictionary={}
var flag_hints: Dictionary={}
var hint_cursor: int=0
var hint_clock: float=0
var clock: float=0
var squads: Dictionary={}
var formations: Dictionary={}
var tank_next: Dictionary={}
var grenade_next: Dictionary={}
var counters: Dictionary={"bounds":0,"flanks":0,"cover_repositions":0,"tank_repositions":0,"formation_updates":0}

func setup(g) -> void:
	game=g

func enemies(team: String) -> Array:
	return game.living().filter(func(u):return u.faction!=team)

func threat_points(team: String) -> Array:
	if game.human_squad and game.human_squads:return game.human_squads.threat_points(team)
	var points: Array=[]
	for enemy in enemies(team):points.append(enemy.pos())
	return points

func squad_center(squad: Array) -> Vector2:
	var p := Vector2.ZERO
	for u in squad:p+=u.pos()
	return p/maxi(1,squad.size())

func tick(dt: float) -> void:
	refresh_flag_hint(dt)
	clock-=dt
	if clock>0:return
	clock=game.config.tactics.update_interval
	update_formations()
	for team in game.control:
		if game.control[team]=="game_ai":plan(team)

func cancel(team: String) -> void:
	formations.erase(team);squads.erase(team)
	for u in game.living(team).filter(func(u):return u.gun_id=="" and u.garrison_phase==""):u.formation_speed=1;u.focus_id="";u.target_id="";u.order_mode="hold"

func cancel_selected(team: String, ids: Array) -> void:
	if ids.is_empty():cancel(team);return
	if formations.has(team):
		formations[team].ids=formations[team].ids.filter(func(id):return not ids.has(id))
		if formations[team].ids.is_empty():formations.erase(team)
	if squads.has(team):squads.erase(team)
	for u in game.living(team):
		if ids.has(u.id):u.formation_speed=1;u.focus_id="";u.target_id="";u.order_mode="hold"

func set_phase(team: String, phase: String, reason: String) -> void:
	var s: Dictionary=squads[team]
	if s.phase!=phase:
		s.phase=phase;s.since=game.elapsed
		game.add_event(team+" · "+phase+" · "+reason)
	s.reason=reason

func acquire(u, goal: Vector2, max_travel: float=.6, allow_same: bool=true) -> bool:
	var enemy=game.closest_enemy(u)
	var threat: Vector2=enemy.pos() if enemy!=null else game.objective
	return u.seek_cover(threat,goal,{"threats":threat_points(u.faction),"range":game.config.weapons[u.weapon].range,"max_travel":max_travel,"allow_same":allow_same})

func publish(team: String, action: String) -> void:
	var s: Dictionary=squads[team]
	s.support_ids=game.living(team).filter(func(u):return not u.tank and u.id!=s.mover and can_support(u)).map(func(u):return u.id)
	game.decisions[team]={"action":action,"phase":s.phase,"reason":s.reason,"candidates":[],"tick":game.tick_id,"source":"squad_coordinator","confidence":0.0}

func can_support(u) -> bool:
	return str(u.get_meta("fire_block_reason","")).is_empty() and u.hp>0 and u.ammo>0 and u.route.is_empty() and u.reload_timer<=0 and u.suppression<.72 and u.cqb_stance!="hide" and game.elapsed-u.last_shot_at<game.config.tactics.support_memory and game.find_target(u)!=null

func stop_formation(team: String) -> void:
	if not formations.has(team):return
	for u in game.living(team):
		if formations[team].ids.has(u.id):u.route.clear();u.goal=u.pos();u.formation_speed=1;u.order_mode="overwatch"
	formations.erase(team)

func plan(team: String) -> void:
	if game.config.rules.get("mode","")=="center_flag":
		for gun in game.at_guns:
			if gun.faction==team and gun.crew_id!="" and gun.enemy_tank()==null and game.elapsed>30:gun.release("装甲威胁解除，返回旗点任务")
		if game.building:
			for u in game.living(team):
				if u.garrison_phase=="stationed" and game.elapsed-u.last_shot_at>15 and game.elapsed>30:game.building.leave(u)
	# Equipment users keep their own executable route. Do not overwrite it with a formation.
	for gun in game.at_guns:
		if gun.faction!=team or gun.crew_id!="" or gun.enemy_tank()==null:continue
		var candidates=game.living(team).filter(func(u):return gun.eligible(u))
		candidates.sort_custom(func(a,b):return a.pos().distance_to(gun.pos())<b.pos().distance_to(gun.pos()))
		for u in candidates:
			if gun.claim(u):
				if formations.has(team):formations[team].ids.erase(u.id)
				break
	if team=="blue" and game.building and not game.building.collapsed and (game.config.rules.get("mode","")!="center_flag" or game.elapsed<30):
		for u in game.living(team):
			if u.weapon=="rifle" and not game.living(team).any(func(v):return v.garrison_phase!="") and u.garrison_phase=="" and u.gun_id=="" and u.hp/u.max_hp>.65 and u.suppression<.35 and u.pos().distance_to(game.building.approach())<.8:
				if game.building.enter(u,2):
					if formations.has(team):formations[team].ids.erase(u.id)
	var squad: Array=game.living(team).filter(func(u):return not u.tank and u.gun_id=="" and u.garrison_phase=="")
	for armor in game.living(team).filter(func(u):return u.tank):plan_tank(armor)
	if squad.is_empty():return
	if game.config.rules.get("mode","")=="center_flag":plan_flag(team,squad);return
	if not squads.has(team):
		squads[team]={"phase":"take_cover","since":game.elapsed,"reason":"先预约掩体，再分工交火","mover":"","turn":0,"leader":squad[0].id,"anchor":squad_center(squad),"threat":""}
		for u in squad:
			if game.elapsed>=u.safety_until:u.order_mode="take_cover";acquire(u,u.pos())
		publish(team,"cover");return
	var s: Dictionary=squads[team]
	if not squad.any(func(u):return u.id==s.leader):s.leader=squad[0].id
	var center := squad_center(squad)
	s.anchor=center
	var threat=null;var nearest: float=INF;var health: float=0;var pressure: float=0
	for u in squad:
		health+=u.hp/u.max_hp;pressure+=u.suppression
		var target=game.find_target(u)
		if target!=null and u.pos().distance_to(target.pos())<nearest:nearest=u.pos().distance_to(target.pos());threat=target
	health/=squad.size();pressure/=squad.size()
	var contact: bool=threat!=null or squad.any(func(u):return game.elapsed-u.last_threat_at<3)
	if contact and s.phase=="advance":
		stop_formation(team)
		set_phase(team,"suppress","行军中接敌，停止队形推进并建立掩护")
	if threat==null:threat=game.closest_enemy(squad[0])
	s.threat=threat.id if threat!=null else ""
	for u in squad:
		# Keep anti-armor specialists free to override the infantry focus target.
		u.focus_id=s.threat if u.weapon!="rocket" else ""
	if health<.30 or pressure>.9:
		set_phase(team,"retreat","伤亡或压制过高，沿可达路线撤回")
		if not formations.has(team):
			var spawn: Array=game.faction_data(team).spawn
			begin_move(team,Vector2(spawn[0],spawn[1]),squad.map(func(u):return u.id),true)
		publish(team,"retreat");return
	if s.phase=="retreat":publish(team,"retreat");return
	# A destroyed or flanked station invalidates protection immediately. Relocate one element.
	if contact and s.phase!="take_cover" and s.phase!="bound":
		for u in squad:
			if not u.route.is_empty() or game.elapsed<u.safety_until:continue
			var own_threat=game.closest_enemy(u)
			if own_threat==null:continue
			if u.cover_id=="" or (u.in_cover() and game.field.protection(u.pos(),own_threat.pos())<.2 and game.field.line_of_sight(own_threat.pos(),u.pos())):
				if acquire(u,u.pos(),.32,false):
					counters.cover_repositions+=1;u.order_mode="reposition";s.mover=u.id
					set_phase(team,"bound","原站位失效，一人重新占掩体，其余保持火力")
					publish(team,"cover");return
	if s.phase=="take_cover":
		var arrived: int=squad.filter(func(u):return u.route.is_empty() and u.in_cover()).size()
		if arrived>=mini(2,squad.size()) or game.elapsed-s.since>5:
			set_phase(team,"suppress","步枪掩护、冲锋枪压制、火箭筒关注装甲")
		publish(team,"cover");return
	if s.phase=="bound":
		var mover=null
		for u in squad:
			if u.id==s.mover:mover=u
		if mover!=null and mover.order_mode in ["bound","cqb_flank"] and contact and not squad.any(func(u):return u!=mover and can_support(u)):
			mover.route.clear();mover.goal=mover.pos();acquire(mover,mover.pos(),.18)
			mover.order_mode="take_cover";s.mover=""
			set_phase(team,"suppress","掩护火力中断，暂停推进并寻找就近保护")
			publish(team,"cover");return
		if mover==null or mover.route.is_empty() or game.elapsed-s.since>game.config.tactics.bound_timeout:
			if mover!=null:
				if not mover.route.is_empty():mover.route.clear();mover.goal=mover.pos();acquire(mover,mover.pos(),.26)
				mover.order_mode="overwatch"
			s.mover="";s.turn+=1;set_phase(team,"suppress","推进者到位，重新建立交叉火力")
		publish(team,"flank");return
	if game.elapsed-s.since<game.config.tactics.suppress_seconds:
		publish(team,"cover");return
	# Flush an entrenched opponent while protected; do not throw during retreat/pinning.
	if threat!=null and game.elapsed>=float(grenade_next.get(team,0)):
		for u in squad:
			if game.elapsed<u.safety_until or u.suppression>.45 or not u.in_cover() or not u.route.is_empty():continue
			if threat.in_cover() and u.pos().distance_to(threat.pos())>.17 and u.request_grenade(threat):
				grenade_next[team]=game.elapsed+12;publish(team,"grenade");return
	var holders: Array=squad.filter(func(u):return can_support(u))
	var choices: Array=squad.duplicate()
	choices.sort_custom(func(a,b):return mover_priority(a,int(s.turn))<mover_priority(b,int(s.turn)))
	for mover in choices:
		if game.living().any(func(e):return e.tank and e.faction!=team and e.pos().distance_to(mover.pos())<1.0) and mover.weapon!="rocket":continue
		if game.elapsed<mover.safety_until or mover.suppression>.5 or mover.hp/mover.max_hp<.50 or not mover.route.is_empty():continue
		var protected_by: Array=holders.filter(func(u):return u!=mover)
		if contact and protected_by.is_empty():continue
		var destination: Vector2=game.objective
		if threat!=null and threat.tank and mover.weapon=="rocket":destination=threat.pos().move_toward(mover.pos(),.55)
		var slot: Dictionary=game.field.choose_cover(mover.id,mover.pos(),threat.pos() if threat!=null else game.objective,destination,{"threats":threat_points(team),"range":game.config.weapons[mover.weapon].range,"max_travel":game.config.tactics.bound_distance,"allow_same":false,"reserve":false})
		if not slot.is_empty() and slot.position.distance_to(destination)+.045<mover.pos().distance_to(destination):
			stop_formation(team)
			mover.occupy(slot);mover.order_mode="bound";s.mover=mover.id;counters.bounds+=1
			set_phase(team,"bound","一人向前沿掩体推进，其他成员掩护")
			publish(team,"flank");return
		if threat!=null and not threat.tank and (threat.suppression>.45 or threat.hp/threat.max_hp<.45) and not protected_by.is_empty():
			var flank: Dictionary=flank_goal(mover,threat)
			if not flank.is_empty():
				stop_formation(team)
				mover.move_to(flank.position);mover.order_mode="cqb_flank";s.mover=mover.id;counters.flanks+=1
				set_phase(team,"bound","敌方已受压制，从掩体端部绕侧清理")
				publish(team,"flank");return
	if not contact and not squad.any(func(u):return game.elapsed<u.safety_until):
		if not formations.has(team):begin_move(team,game.objective,squad.map(func(u):return u.id))
		set_phase(team,"advance","没有射界，按柔性队形靠向下一个交战位置")
		publish(team,"capture")
	else:
		if formations.has(team):formations.erase(team)
		set_phase(team,"suppress","维持有效掩体与射界，等待推进窗口")
		publish(team,"cover")

func mover_priority(u, turn: int) -> int:
	var order: Array=["smg","rifle","rocket"]
	return (order.find(u.weapon)-turn%3+3)%3

func flank_goal(u, enemy) -> Dictionary:
	var best: Dictionary={};var score: float=INF
	for c in game.field.covers:
		if not c.alive or enemy.pos().distance_to(Vector2(c.position[0],c.position[1]))>.21:continue
		var normal := Vector2(c.normal[0],c.normal[1]);var tangent := Vector2(-normal.y,normal.x)
		var width: float=c.size[1] if normal.x!=0 else c.size[0]
		for side in [-1,1]:
			var p: Vector2=Vector2(c.position[0],c.position[1])+tangent*(width*.5+.085)*side
			if not game.field.walkable(p) or not game.field.line_of_sight(p,enemy.pos()):continue
			if game.field.protection(enemy.pos(),p)>.25 or u.pos().distance_to(p)>.34:continue
			var path: PackedVector2Array=game.field.path(u.pos(),p)
			var distance: float=game.field.route_length(path)
			if path.is_empty() or distance>.45:continue
			if distance<score:score=distance;best={"position":p}
	return best

func begin_move(team: String, destination: Vector2, ids: Array, retreat: bool=false) -> void:
	var squad: Array=game.living(team).filter(func(u):return not u.tank and (ids.is_empty() or ids.has(u.id)))
	if squad.is_empty():return
	var anchor := squad_center(squad)
	formations[team]={"ids":squad.map(func(u):return u.id),"destination":destination,"anchor":anchor,"path":game.field.path(anchor,destination),"revision":game.field.revision,"retreat":retreat,"leader":squad[0].id,"shape":"wedge"}
	for u in squad:u.target_id="";u.order_mode="retreat" if retreat else "formation";game.field.release(u.id);u.cover_id="";u.cover_slot={}
	update_formation(team,formations[team])

func update_formations() -> void:
	for team in formations.keys():update_formation(team,formations[team])

func update_formation(team: String, f: Dictionary) -> void:
	var squad: Array=game.living(team).filter(func(u):return f.ids.has(u.id) and u.gun_id=="" and u.garrison_phase=="")
	if squad.is_empty():formations.erase(team);return
	var center := squad_center(squad)
	if f.revision!=game.field.revision:f.path=game.field.path(f.anchor,f.destination);f.revision=game.field.revision
	var path: PackedVector2Array=f.path
	while not path.is_empty() and f.anchor.distance_to(path[0])<.015:path.remove_at(0)
	if not path.is_empty() and f.anchor.distance_to(center)<game.config.tactics.leader_leash:
		var step: float=game.config.tactics.run_speed*game.config.tactics.update_interval
		while step>0 and not path.is_empty():
			var distance: float=f.anchor.distance_to(path[0])
			if distance<=step:f.anchor=path[0];path.remove_at(0);step-=distance
			else:f.anchor=f.anchor.move_toward(path[0],step);step=0
	f.path=path
	var heading: Vector2=(f.destination-f.anchor).normalized()
	if not path.is_empty():heading=(path[mini(3,path.size()-1)]-f.anchor).normalized()
	if heading.length()<.5:heading=Vector2.UP
	var side := Vector2(-heading.y,heading.x)
	var future: Vector2=f.anchor+heading*game.config.soldier.speed*game.config.tactics.formation_lookahead
	if future.distance_to(f.destination)<.15:future=f.destination
	future=game.field.soft_offset(f.anchor,future,.23)
	var width: float=game.config.tactics.formation_width
	var narrow: bool=not game.field.walkable(future+side*width) or not game.field.walkable(future-side*width)
	f.shape="column" if narrow else "wedge"
	var destinations: Array=[]
	for i in range(squad.size()):
		var u=squad[i]
		if game.elapsed<u.safety_until:continue
		var offset: Vector2=-heading*float(i)*.05 if narrow else side*(i-1)*width-heading*(.035 if i!=1 else 0.0)
		var goal: Vector2=game.field.soft_offset(future,future+offset,.15)
		if f.anchor.distance_to(f.destination)<.07:goal=game.field.soft_offset(f.destination,f.destination+offset,.15)
		if destinations.any(func(p):return p.distance_to(goal)<.024):
			for shift in [side*.035,-side*.035,-heading*.055,-heading*.09]:
				var alternative: Vector2=game.field.soft_offset(future,goal+shift,.18)
				if not destinations.any(func(p):return p.distance_to(alternative)<.024):goal=alternative;break
		destinations.append(goal)
		var ideal: Vector2=f.anchor+offset
		u.formation_speed=clampf(1+(ideal-u.pos()).dot(heading)*2.5,.75,1.2)
		# Soft cover bias during retreat: keep moving instead of hard-stopping at every sandbag.
		if f.retreat:
			var threat=game.closest_enemy(u)
			if threat!=null:
				var cover: Dictionary=game.field.choose_cover(u.id,u.pos(),threat.pos(),goal,{"reserve":false,"max_travel":.22})
				if not cover.is_empty():goal=game.field.soft_offset(future,goal.lerp(cover.position,.65),.22)
		if u.goal.distance_to(goal)>game.config.tactics.repath_delta or (u.route.is_empty() and u.pos().distance_to(goal)>.035):u.move_to(goal)
		counters.formation_updates+=1
	if f.anchor.distance_to(f.destination)<.04 and squad.all(func(u):return u.route.is_empty() and u.pos().distance_to(u.goal)<.035):
		formations.erase(team)
		for u in squad:
			u.formation_speed=1
			if not f.retreat:acquire(u,u.pos(),.18)

func plan_tank(tank) -> void:
	if tank.deployment_phase!="active":return
	if game.elapsed<float(tank_next.get(tank.id,-1)):return
	tank_next[tank.id]=game.elapsed+game.config.tactics.tank_replan_seconds
	var target=game.find_target(tank)
	if target==null:target=game.closest_enemy(tank)
	if target==null:return
	tank.focus_id=target.id
	var rocket_distance: float=INF
	for enemy in enemies(tank.faction):
		if enemy.weapon=="rocket" and game.field.line_of_sight(enemy.pos(),tank.pos()):rocket_distance=minf(rocket_distance,tank.pos().distance_to(enemy.pos()))
	for gun in game.at_guns:
		if gun.faction!=tank.faction and gun.phase=="ready" and game.field.line_of_sight(gun.pos(),tank.pos()):rocket_distance=minf(rocket_distance,tank.pos().distance_to(gun.pos())*.5)
	var retreat: bool=rocket_distance<game.config.tactics.tank_danger_range or tank.hp/tank.max_hp<.35
	var desired: float=.78 if retreat else game.config.tactics.tank_preferred_range
	tank.safety_reason="anti_armor_threat" if retreat else ""
	var distance: float=tank.pos().distance_to(target.pos())
	if not retreat and distance>.36 and distance<.82 and game.field.line_of_sight(tank.pos(),target.pos()):
		tank.route.clear();tank.goal=tank.pos();tank.order_mode="fire_support";return
	var best: Dictionary={};var best_cost: float=INF
	for i in range(16):
		var angle: float=TAU*i/16
		var candidate: Vector2=target.pos()+Vector2(cos(angle),sin(angle))*desired
		if not game.field.walkable(candidate,true):continue
		if game.living(tank.faction).any(func(u):return u!=tank and u.pos().distance_to(candidate)<.13):continue
		if not game.field.line_of_sight(candidate,target.pos()):continue
		var route: PackedVector2Array=game.field.path(tank.pos(),candidate,true)
		if route.is_empty():continue
		var cost: float=game.field.route_length(route)
		for enemy in enemies(tank.faction):
			if enemy.weapon=="rocket" and game.field.line_of_sight(enemy.pos(),candidate):cost+=.20/maxf(.15,candidate.distance_to(enemy.pos()))
		if cost<best_cost:best_cost=cost;best={"position":candidate}
	if not best.is_empty() and tank.goal.distance_to(best.position)>.035:
		tank.move_to(best.position);tank.order_mode="reverse" if retreat else "reposition";counters.tank_repositions+=1

func snapshot() -> Dictionary:
	var result: Dictionary={"squads":{},"formations":{},"counters":counters.duplicate(),"path_queries":game.field.path_queries}
	for team in squads:
		var s: Dictionary=squads[team].duplicate();s.anchor=[s.anchor.x,s.anchor.y];result.squads[team]=s
	for team in formations:
		var f: Dictionary=formations[team]
		result.formations[team]={"leader":f.leader,"anchor":[f.anchor.x,f.anchor.y],"destination":[f.destination.x,f.destination.y],"shape":f.shape,"ids":f.ids}
	return result

func flag_options(u) -> Array:
	var output: Array=[]
	var urgent: bool=game.control[u.faction]=="lm" and game.flag_emergency(u.faction)
	if u.tank or (not urgent and (u.hp/u.max_hp<.45 or u.suppression>.65 or game.elapsed<u.safety_until)):return output
	var direction: Vector2=(game.objective-u.pos()).normalized()
	var side=Vector2(-direction.y,direction.x)
	var threats: Array=[]
	for enemy in enemies(u.faction):
		if enemy.pos().distance_to(u.pos())<game.config.weapons[enemy.weapon].range+.4:threats.append(enemy.pos())
	var supporting: bool=game.living(u.faction).any(func(v):return v!=u and can_support(v))
	# A healthy unit can attempt one short exposed leg after sustained stalemate.
	# Low health, suppression and survival vetoes above remain authoritative.
	var stalled: bool=game.elapsed-float(flag_progress.get(u.faction,0))>=8.0 and u.hp/u.max_hp>=.65 and u.suppression<.35
	# Follow the navigation route around props before choosing the next short leg.
	# Straight-line steps alone can repeatedly select the same side of a sandbag.
	var goals: Array=[]
	for angle in range(0,360,45):
		var destination: Vector2=game.objective+Vector2.from_angle(deg_to_rad(angle))*.10
		if not game.field.walkable(destination):continue
		var full: PackedVector2Array=game.field.path(u.pos(),destination)
		var travelled: float=0
		for i in range(1,full.size()):
			travelled+=full[i-1].distance_to(full[i])
			if travelled>=.24 or i==full.size()-1:
				goals.append(full[i]);break
	for offset in [0.0,.18,-.18,.30,-.30]:goals.append(u.pos().move_toward(game.objective,.24)+side*offset)
	for goal: Vector2 in goals:
		if not game.field.walkable(goal) or goal.distance_to(u.pos())<.04:continue
		var path: PackedVector2Array=game.field.path(u.pos(),goal)
		if path.is_empty() or game.field.route_length(path)>.55:continue
		var exposure: float=game.field.route_exposure(path,threats)
		if not urgent and exposure>(.24 if supporting or stalled else .12):continue
		if game.living(u.faction).any(func(v):return v!=u and v.pos().distance_to(goal)<.065):continue
		var remaining: float=game.field.route_length(game.field.path(goal,game.objective))
		output.append({"position":[goal.x,goal.y],"exposure":exposure,"cost":remaining+exposure*4+game.field.route_length(path)*.2})
	output.sort_custom(func(a,b):return a.cost<b.cost)
	return output

func refresh_flag_hint(dt: float) -> void:
	# Spread advisory route searches over time; /api/sync must only read state.
	hint_clock-=dt
	if hint_clock>0 or game.units.is_empty():return
	hint_clock=.10
	for i in game.units.size():
		hint_cursor=(hint_cursor+1)%game.units.size()
		var u=game.units[hint_cursor]
		if u.hp<=0 or u.tank or game.control[u.faction]!="lm" or u.deployment_phase!="active":continue
		var cached: Dictionary=flag_hints.get(u.id,{})
		if cached.get("until",0)>game.elapsed and cached.get("revision",-1)==game.field.revision:continue
		flag_hints[u.id]={"until":game.elapsed+1.0,"revision":game.field.revision,"data":{"advance_options":flag_options(u).slice(0,2)}}
		return

func flag_hint(u) -> Dictionary:
	var cached: Dictionary=flag_hints.get(u.id,{})
	var valid: bool=cached.get("until",0)>game.elapsed and cached.get("revision",-1)==game.field.revision
	return {"advance_options":cached.data.advance_options if valid else [],"inside_flag":u.pos().distance_to(game.objective)<=game.config.rules.capture_radius,"pending":not valid}

func plan_flag(team: String, squad: Array) -> void:
	if not squads.has(team):squads[team]={"phase":"advance","since":game.elapsed,"reason":"向中央旗点分段推进","mover":"","turn":0,"leader":squad[0].id,"anchor":squad_center(squad),"threat":""}
	var s: Dictionary=squads[team];s.anchor=squad_center(squad)
	if not squad.any(func(u):return u.id==s.mover and not u.route.is_empty()):s.mover=""
	if not squad.any(func(u):return u.id==s.leader):s.leader=squad[0].id
	var healthy: Array=squad.filter(func(u):return u.hp/u.max_hp>=.45 and u.suppression<.65 and game.elapsed>=u.safety_until)
	var defenders: Array=healthy.filter(func(u):return u.pos().distance_to(game.objective)<=game.config.rules.capture_radius)
	for defender in defenders:
		defender.route.clear();defender.goal=defender.pos();defender.order_mode="hold"
	if not defenders.is_empty():
		formations.erase(team);set_phase(team,"defend","守住旗圈，迎击来敌；危险时仍可自保撤离")
		publish(team,"hold")
	else:set_phase(team,"advance","保留掩护，沿低暴露的短路线接近旗点")
	if game.elapsed<float(flag_next.get(team,0)):return
	flag_next[team]=game.elapsed+1.4
	var movers: Array=healthy.filter(func(u):return u.route.is_empty() and not defenders.has(u) and u.grenade_time<0)
	movers.sort_custom(func(a,b):return mover_priority(a,int(s.turn))<mover_priority(b,int(s.turn)))
	for u in movers:
		var target=game.find_target(u)
		if target!=null and game.elapsed-u.last_shot_at<2 and u.in_cover() and game.elapsed-float(flag_progress.get(team,0))<6.0:continue
		var options=flag_options(u)
		if not options.is_empty():
			formations.erase(team);var p: Array=options[0].position
			u.move_to(Vector2(p[0],p[1]));u.order_mode="flag_advance";s.mover=u.id;s.turn+=1;flag_progress[team]=game.elapsed
			if defenders.is_empty():publish(team,"capture")
			return
		# No safe open step: improve a protected station towards the objective.
		if acquire(u,game.objective,.38,false):u.order_mode="take_cover";s.turn+=1;publish(team,"cover");return
	if defenders.is_empty():publish(team,"cover")
