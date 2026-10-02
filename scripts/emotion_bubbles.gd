extends Control
# Presentation only: the accepted model choice never overrides movement or survival.
var game
var font:=SystemFont.new()
const LABELS={"calm":"冷静","alert":"警觉","nervous":"紧张","afraid":"害怕","determined":"坚定","relieved":"安心"}
const COLORS={"calm":Color("b6e2ec"),"alert":Color("ffe29a"),"nervous":Color("ffd1a3"),"afraid":Color("f4b8ce"),"determined":Color("c9c2f5"),"relieved":Color("bee6c5")}
func _ready():
	mouse_filter=Control.MOUSE_FILTER_IGNORE
	font.font_names=PackedStringArray(["Microsoft YaHei","Noto Sans CJK SC","sans-serif"])
func _process(_dt):queue_redraw()
func _draw():
	if not is_instance_valid(game) or not game.human_squad:return
	var occupied: Array[Rect2]=[]
	var viewport_size: Vector2=get_viewport_rect().size
	for u in game.units:
		if u.hp<=0 or not u.visible or u.deployment_phase!="active" or u.emotion=="" or game.elapsed>=u.emotion_until:continue
		var world: Vector3=u.global_position+Vector3(0,.085,0)
		if game.camera.is_position_behind(world):continue
		var anchor: Vector2=game.camera.unproject_position(world)
		if not Rect2(Vector2.ZERO,viewport_size).has_point(anchor):continue
		var box:=Rect2(Vector2(clampf(anchor.x-18,4,viewport_size.x-40),clampf(anchor.y-17,90,viewport_size.y-90)),Vector2(36,14))
		for attempt in range(6):
			if not occupied.any(func(r):return r.grow(2).intersects(box)):break
			box.position.y-=17
		occupied.append(box)
		var color: Color=COLORS.get(u.emotion,Color.WHITE)
		var style:=StyleBoxFlat.new();style.bg_color=Color("18262bed");style.border_color=color
		style.set_border_width_all(1);style.set_corner_radius_all(4)
		draw_line(box.get_center()+Vector2(0,7),anchor,Color(color,.35),.4,true)
		draw_style_box(style,box)
		var face: Vector2=box.position+Vector2(6,7)
		draw_circle(face,3.5,color)
		draw_circle(face+Vector2(-2,-1),.9,Color("223039"));draw_circle(face+Vector2(2,-1),.9,Color("223039"))
		if u.emotion in ["afraid","nervous"]:draw_circle(face+Vector2(0,3),1.4,Color("223039"))
		else:draw_line(face+Vector2(-2,3),face+Vector2(2,3),Color("223039"),1.5,true)
		draw_string(font,box.position+Vector2(12,10),LABELS.get(u.emotion,u.emotion),HORIZONTAL_ALIGNMENT_LEFT,-1,8,color)
