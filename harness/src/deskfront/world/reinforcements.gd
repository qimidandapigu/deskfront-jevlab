extends Node3D
## Local, finite reinforcements. Announce, wait, validate the entry, then walk in.
var game
var serial: int=0
var orders: Array=[]
var indicators: Dictionary={}

func setup(g):game=g

func request(team: String, entrance: Vector2, operation: String) -> String:
	if orders.any(func(o):return o.team==team and o.status=="announced"):return ""
	serial+=1
	var id: String="expedition_%s_%d"%[team,serial]
	orders.append({"id":id,"team":team,"entrance":[entrance.x,entrance.y],"operation_id":operation,"status":"announced","elapsed":0.0,"spawned":[]})
	var sign=Label3D.new();add_child(sign);sign.text=("友军增援" if team=="green" else "敌军进入")+" / 5 秒预告"
	sign.position=Vector3(entrance.x,game.field.height+.18,entrance.y);sign.font_size=40;sign.pixel_size=.002;sign.billboard=BaseMaterial3D.BILLBOARD_ENABLED
	sign.modulate=Color(.3,1,.7) if team=="green" else Color(1,.4,.25);indicators[id]=sign
	game.add_event(sign.text);return id

func tick(dt: float):
	for order in orders:
		if order.status!="announced":continue
		order.elapsed+=dt
		if order.elapsed<5:continue
		var p=Vector2(order.entrance[0],order.entrance[1])
		var enemies: Array=game.living().filter(func(u):return u.faction!=order.team)
		var reserved:int=game.units.filter(func(u):return u.faction==order.team and u.hp>0 and u.deployment_phase=="captive").size()
		var capacity: bool=game.living().size()+reserved<15 and game.living(order.team).size()+reserved<6
		var safe: bool=game.field.walkable(p) and not game.living().any(func(u):return u.pos().distance_to(p)<.16) and not enemies.any(func(u):return u.pos().distance_to(p)<.6)
		if capacity and safe:
			var unit=game.spawn_unit(order.id,order.team,p);unit.equip("rifle")
			unit.move_to(game.objective);unit.order_mode="reinforcement_entry"
			order.status="deployed";order.spawned=[order.id];game.add_event("增援从标记入口进入："+order.id)
		elif order.elapsed<25:
			indicators[order.id].text="入口受阻 / 等待安全间距";continue
		else:
			order.status="blocked";game.add_event("增援取消：入口不安全或人数已满")
		indicators[order.id].queue_free();indicators.erase(order.id)
	# Keep a bounded local receipt history.
	while orders.size()>32 and orders[0].status!="announced":orders.pop_front()

func snapshot() -> Array:return orders.duplicate(true)
