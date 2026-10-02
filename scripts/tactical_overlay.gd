extends Control
## 战术可视化只读原生状态，不参与决策，不显示隐藏敌情。
var game
var enabled: bool=true
var redraw_clock: float=0
var font:=SystemFont.new()
var toggle: Button
const ROLES={"observe":"观察","recover":"自保","reload":"装填","blocked":"受阻","approach":"移动","support":"支援","acquire_fire":"建立射界"}
const CYAN=Color("6edbea")
const GOLD=Color("ffda80")
func _ready():
	mouse_filter=Control.MOUSE_FILTER_IGNORE
	font.font_names=PackedStringArray(["Microsoft YaHei","sans-serif"])
	toggle=Button.new();toggle.text="战术视图 [F8]";toggle.toggle_mode=true;toggle.button_pressed=true
	toggle.position=Vector2(16,100);toggle.size=Vector2(112,25);toggle.add_theme_font_size_override("font_size",11)
	toggle.toggled.connect(func(value):enabled=value;queue_redraw())
	add_child(toggle)
func _input(event):
	if game.human_squad and event is InputEventKey and event.pressed and not event.echo and event.keycode==KEY_F8:
		toggle.button_pressed=not toggle.button_pressed;get_viewport().set_input_as_handled()
func _process(dt):
	redraw_clock-=dt
	if redraw_clock>0:return
	redraw_clock=.10
	visible=is_instance_valid(game) and game.human_squad
	if visible:
		toggle.position=Vector2(16,get_viewport_rect().size.y-150)
		queue_redraw()
func point(p: Vector2) -> Vector2:
	return game.camera.unproject_position(Vector3(p.x,game.field.height+.012,p.y))
func tag(p: Vector2,text: String,color: Color):
	var width: float=font.get_string_size(text,HORIZONTAL_ALIGNMENT_LEFT,-1,8).x+6
	draw_style_box(panel(),Rect2(p,Vector2(width,13)))
	draw_string(font,p+Vector2(3,10),text,HORIZONTAL_ALIGNMENT_LEFT,-1,8,color)
func panel() -> StyleBoxFlat:
	var box:=StyleBoxFlat.new();box.bg_color=Color(.04,.09,.12,.88);box.set_corner_radius_all(5);return box
func arrow(a: Vector2,b: Vector2,color: Color,dashed: bool=false):
	if a.distance_to(b)<3:return
	if dashed:draw_dashed_line(a,b,color,.45,5,true)
	else:draw_line(a,b,Color(.02,.04,.06,.3),.9,true);draw_line(a,b,color,.5,true)
	var d: Vector2=(b-a).normalized();var n:=Vector2(-d.y,d.x)
	draw_colored_polygon(PackedVector2Array([b,b-d*3.5+n*1.3,b-d*3.5-n*1.3]),color)
# 只平滑显示：保留首尾与障碍拐点，不改变单位的导航队列。
func display_route(raw: PackedVector2Array) -> PackedVector2Array:
	var points:=PackedVector2Array()
	for p in raw:
		if points.is_empty() or points[-1].distance_to(p)>.0001:points.append(p)
	if points.size()<3:return points
	# 仅消除原路径窄走廊内的网格阶梯；不能跨墙或跨越大段绕行。
	var pulled:=PackedVector2Array([points[0]]);var cursor: int=0
	while cursor<points.size()-1:
		var best: int=cursor+1
		for target in range(cursor+2,mini(cursor+7,points.size())):
			var a: Vector2=points[cursor];var b: Vector2=points[target]
			if a.distance_to(b)>.15:break
			var valid: bool=true
			for k in range(cursor+1,target):
				if points[k].distance_to(Geometry2D.get_closest_point_to_segment(points[k],a,b))>.018:valid=false;break
			if not valid:continue
			var steps: int=maxi(1,ceili(a.distance_to(b)/.006))
			for k in range(steps+1):
				if not game.field.walkable(a.lerp(b,float(k)/steps)):valid=false;break
			if valid:best=target
		pulled.append(points[best]);cursor=best
	points=pulled
	var simplified:=PackedVector2Array([points[0]])
	for i in range(1,points.size()-1):
		var incoming: Vector2=(points[i]-simplified[-1]).normalized()
		var outgoing: Vector2=(points[i+1]-points[i]).normalized()
		if incoming.dot(outgoing)<.999:simplified.append(points[i])
	simplified.append(points[-1])
	var rounded:=PackedVector2Array([simplified[0]])
	for i in range(1,simplified.size()-1):
		var corner: Vector2=simplified[i]
		var radius: float=minf(.016,minf(corner.distance_to(simplified[i-1]),corner.distance_to(simplified[i+1]))*.3)
		var entry: Vector2=corner.move_toward(simplified[i-1],radius)
		var leave: Vector2=corner.move_toward(simplified[i+1],radius)
		var curve:=PackedVector2Array();var safe: bool=true
		for j in range(9):
			var t: float=j/8.0
			var p: Vector2=entry.lerp(corner,t).lerp(corner.lerp(leave,t),t)
			if not game.field.walkable(p):safe=false
			curve.append(p)
		if safe:rounded.append_array(curve)
		else:rounded.append(corner)
	rounded.append(simplified[-1]);return rounded

func route_line(raw: PackedVector2Array,color: Color,width: float,endpoint: bool=false):
	var route: PackedVector2Array=display_route(raw)
	if route.size()<2:return
	var screen:=PackedVector2Array()
	for p in route:screen.append(point(p))
	draw_polyline(screen,Color(.02,.04,.06,.35),width+.25,true)
	draw_polyline(screen,color,width,true)
	# 圆端与圆连接，取消每个网格段重新起笔的虚线碎片。
	draw_circle(screen[0],width*.5,color);draw_circle(screen[-1],width*.5,color)
	if endpoint:
		var tip: Vector2=screen[-1]
		var tail: Vector2=screen[0]
		for i in range(screen.size()-2,-1,-1):
			if screen[i].distance_to(tip)>7:tail=screen[i];break
		var d: Vector2=(tip-tail).normalized();var n:=Vector2(-d.y,d.x)
		draw_colored_polygon(PackedVector2Array([tip,tip-d*3+n*1.2,tip-d*3-n*1.2]),color)

func ring(center: Vector2,radius: float,color: Color):
	var points:=PackedVector2Array()
	for i in range(49):points.append(point(center+Vector2.from_angle(TAU*i/48)*radius))
	draw_colored_polygon(points,Color(color,.035));draw_polyline(points,Color(color,.45),.5,true)
func _draw():
	if not is_instance_valid(game) or not game.human_squad or not enabled:return
	var bottom: float=get_viewport_rect().size.y
	tag(Vector2(16,bottom-121),"青线：实际路径   金圈：阶段位置   连线：有效支援",CYAN)
	tag(point(game.objective)+Vector2(8,12),"最终目标：占旗",CYAN)
	var occupied: Array[Rect2]=[]
	var y: float=bottom-98
	for s in game.human_squads.squads.values():
		var members: Array=game.living(s.faction).filter(func(u):return s.unit_ids.has(u.id))
		if members.is_empty():continue
		ring(s.goal,s.radius,GOLD)
		var team_name: String="绿队" if s.faction=="green" else "红队"
		var label: String="阶段位置" if s.goal.distance_to(game.objective)>game.config.rules.capture_radius else "占旗接近点"
		tag(point(s.goal)+Vector2(8,-26 if s.faction=="green" else -42),team_name+" · "+label,GOLD)
		# 战略路径来自执行器已有寻路结果，不把直线画成可通行路线。
		var path: PackedVector2Array=s.path
		route_line(path,Color(GOLD,.24),.4)
		tag(Vector2(16,y),s.faction+" · "+str(s.reason),GOLD);y+=21
		for u in members:
			var origin: Vector2=point(u.pos())
			if not u.route.is_empty():
				var route:=PackedVector2Array([u.pos()]);route.append_array(u.route)
				route_line(route,Color(CYAN,.55),.5,true)
			var duty: Dictionary=s.get("duties",{}).get(u.id,{})
			var role: String=ROLES.get(duty.get("role","observe"),"观察")
			if s.mover==u.id:role="接替射位" if u.route.is_empty() else "推进者"
			var caption: String=u.id.get_slice("-",1)+"号 · "+role
			var label_pos: Vector2=origin+Vector2(9,12)
			var label_size:=Vector2(font.get_string_size(caption,HORIZONTAL_ALIGNMENT_LEFT,-1,8).x+6,17)
			label_pos.x=clampf(label_pos.x,4,get_viewport_rect().size.x-label_size.x-4)
			for attempt in range(10):
				if not occupied.any(func(rect):return rect.grow(3).intersects(Rect2(label_pos,label_size))):break
				label_pos.y+=17
			occupied.append(Rect2(label_pos,label_size))
			if label_pos.distance_to(origin)>40:draw_line(origin,label_pos+Vector2(0,12),Color(CYAN,.6),1,true)
			tag(label_pos,caption,Color("f7bb8f") if role in ["受阻","自保"] else CYAN)
			if s.mover==u.id:
				for supporter in game.human_squads.supporting_members(u,members):arrow(point(supporter.pos()),origin,GOLD,true)
