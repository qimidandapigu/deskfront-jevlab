extends RefCounted
## 人类小队的感知边界。
##
## 该类只负责把引擎可见事实整理成小队可用的接触记录；事件写入、
## 小队状态和战术决策仍由 human_squads.gd 持有。

var host

func _init(owner) -> void:
	host=owner

func visible_to(team: String, enemy) -> bool:
	var game=host.game
	if enemy.hp<=0 or enemy.deployment_phase!="active":return false
	return game.living(team).any(func(u):return u.pos().distance_to(enemy.pos())<=float(game.config.get("human_vision_range",1.2)) and game.field.line_of_sight(u.pos(),enemy.pos()))

func update() -> void:
	var game=host.game
	for team in game.control:
		var old: Dictionary=host.perception.get(team,{})
		var current: Dictionary={}
		for id in old:
			if game.elapsed-float(old[id].last_seen)<=6:
				current[id]=old[id].duplicate(true);current[id].visible=false
		for enemy in game.living():
			if enemy.faction==team or not visible_to(team,enemy):continue
			if not old.has(enemy.id) or game.elapsed-float(old[enemy.id].last_seen)>1.5:
				host.emit("contact_acquired",team,"","",{"target_id":enemy.id,"position":[enemy.pos().x,enemy.pos().y]})
			current[enemy.id]={"id":enemy.id,"faction":enemy.faction,"position":[enemy.pos().x,enemy.pos().y],"visible":true,"last_seen":game.elapsed,"kind":"tank" if enemy.tank else "infantry","weapon":enemy.weapon,"hp":enemy.hp}
		host.perception[team]=current

func visible_enemy(u):
	var best=null
	var distance: float=INF
	for enemy in host.game.living():
		if enemy.faction==u.faction or not visible_to(u.faction,enemy):continue
		var d: float=u.pos().distance_to(enemy.pos())
		if d<distance:best=enemy;distance=d
	return best

func threat_points(team: String) -> Array:
	var result: Array=[]
	for contact in host.perception.get(team,{}).values():
		if host.game.elapsed-float(contact.last_seen)<=6:result.append(Vector2(contact.position[0],contact.position[1]))
	return result
