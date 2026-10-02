extends PanelContainer
# Read-only spectator HUD. Coordinates and identifiers never become commands.
var game
var clock: float=0
var stage_key: String=""
var retired: Dictionary={}
var textures: Dictionary={}
var map_y: float=0
var display: Dictionary={}
var rows: Array=[]
var tips: Array=[]
var canvas: Control
var font=SystemFont.new()
var aliases: Dictionary={}
var bounds: Rect2
const GREEN=Color("9bd6aa")
const RED=Color("efa398")
const INK=Color("d5dedd")
const TASKS={"maneuver":"推进","fire_support":"掩护","establish_fire":"建立火力","reserve":"待命","support":"支援","recover":"恢复","hold":"守住","advance":"推进","cover":"建立掩护","assault":"突击","retreat":"撤退","regroup":"集结","flank":"绕侧","rescue":"待救援"}
class Content extends Control:
	var hud
	func _draw():hud.paint(self)
	func _get_tooltip(at: Vector2) -> String:
		for tip in hud.tips:
			if tip.rect.has_point(at):return tip.text
		return ""
func setup(arena):
	game=arena;position=Vector2(10,108);scale=Vector2(.86,.86)
	for name in ["soldier","fire","aim","move","cover","rescue"]:
		var im=Image.new()
		if im.load_svg_from_string(FileAccess.get_file_as_string("res://ui_icons/"+name+".svg"))==OK:textures[name]=ImageTexture.create_from_image(im)
	font.font_names=PackedStringArray(["Microsoft YaHei","sans-serif"])
	var style=StyleBoxFlat.new();style.bg_color=Color(.035,.055,.07,.86)
	style.set_corner_radius_all(8);style.content_margin_left=10;style.content_margin_right=10;style.content_margin_top=10;style.content_margin_bottom=10
	add_theme_stylebox_override("panel",style)
	var scroll=ScrollContainer.new();scroll.horizontal_scroll_mode=ScrollContainer.SCROLL_MODE_DISABLED;add_child(scroll)
	canvas=Content.new();canvas.hud=self;canvas.custom_minimum_size=Vector2(166,400);scroll.add_child(canvas)
	refresh()
func _process(dt):
	if not is_instance_valid(game):return
	size=Vector2(196,minf(canvas.custom_minimum_size.y+20,maxf(110,(get_viewport_rect().size.y-215)/.86)))
	clock-=dt
	if clock<=0:clock=.25;refresh()
func status(u) -> String:
	if u.hp<=0:return "dead"
	if u.deployment_phase=="captive" or u.order_mode=="waiting_rescue":return "rescue"
	if game.paused:return "pause"
	if u.grenade_time>=0:return "throw"
	if game.elapsed<u.safety_until:return "escape"
	if u.state=="blocked" or (u.route.is_empty() and u.path_failure=="no_safe_route"):return "blocked"
	if u.reload_timer>0:return "reload"
	if game.elapsed-u.last_shot_at<.7:return "fire"
	if not u.route.is_empty():return "move"
	if u.in_cover():return "cover"
	return "wait"
func readable(raw: String) -> String:
	var re=RegEx.new();re.compile("N-?[0-9]+,-?[0-9]+")
	var result=raw.replace("\n"," ")
	var hits=re.search_all(result)
	hits.reverse()
	for hit in hits:
		var replacement: String=aliases.get(hit.get_string(),"区域")
		result=result.substr(0,hit.get_start())+replacement+result.substr(hit.get_end())
	return result
func refresh():
	display={};rows=[];aliases={}
	var key: String=str(game.run_id)+":"+str(game.growth.mission.get("index",0) if game.growth else 0)
	if key!=stage_key:
		stage_key=key
		for u in game.units:
			if u.hp<=0:retired[u.get_instance_id()]=true
	if FileAccess.file_exists("res://battle-sidebar.json"):
		var parsed=JSON.parse_string(FileAccess.get_file_as_string("res://battle-sidebar.json"))
		if parsed is Dictionary and parsed.get("run_id")==game.run_id:display=parsed.get("teams",{})
	var b=game.config.bounds
	bounds=Rect2(Vector2(b[0],b[1]),Vector2(b[2]-b[0],b[3]-b[1]))
	for team in ["green","red"]:
		var data: Dictionary=display.get(team,{})
		if data.get("goal",[]).size()==2 and not str(data.get("region_id","")).is_empty():aliases[str(data.region_id)]="A点" if team=="green" else "B点"
	var height: float=160
	for team in ["green","red"]:
		var squads: Array=[]
		if game.human_squads:
			for s in game.human_squads.squads.values():
				if s.faction==team:squads.append(s)
		var plans: Array[String]=[]
		for s in squads:
			var summary: String=TASKS.get(s.intent,"执行任务")
			if not plans.has(summary):plans.append(summary)
		var local_ai: bool=game.control.get(team)=="game_ai"
		var command: String=readable(str(display.get(team,{}).get("commander","")))
		if command.is_empty():command="本地作战" if local_ai else "等待指挥"
		var members: Array=[]
		for u in game.units:
			if u.faction!=team or retired.has(u.get_instance_id()):continue
			var role="unknown"
			for s in squads:
				if s.unit_ids.has(u.id):role=str(s.get("assignments",{}).get(u.id,{}).get("role",s.intent));break
			if u.hp>0 and (u.deployment_phase=="captive" or u.order_mode=="waiting_rescue"):role="rescue"
			members.append({"unit":u,"role":role,"status":status(u)})
		rows.append({"team":team,"command":command,"squad":" / ".join(plans) if not plans.is_empty() else "自主作战" if local_ai else "等待部署","members":members})
		height+=79+members.size()*24+(command_lines("指挥："+command).size()-1)*17
	canvas.custom_minimum_size.y=height
	canvas.queue_redraw()
func text(c,at: Vector2,value: String,color: Color=INK,limit: int=166):
	var line=value
	while font.get_string_size(line,HORIZONTAL_ALIGNMENT_LEFT,-1,11).x>limit and line.length()>1:line=line.left(line.length()-2)+"…"
	c.draw_string(font,at,line,HORIZONTAL_ALIGNMENT_LEFT,-1,11,color)
func command_lines(value: String)->Array[String]:
	var lines: Array[String]=[]
	var line: String=""
	for ch in value:
		if font.get_string_size(line+ch,HORIZONTAL_ALIGNMENT_LEFT,-1,11).x>166 and not line.is_empty():
			lines.append(line);line=""
			if lines.size()==2:
				var remainder=value.substr(lines[0].length()+lines[1].length())
				lines.append(remainder);return lines
		line+=ch
	if not line.is_empty():lines.append(line)
	return lines

func icon(c,p: Vector2,kind: String,color: Color):
	var key: String=kind
	if kind in ["maneuver","advance","assault","flank","escape","retreat"]:key="move"
	if kind in ["fire_support","establish_fire","support"]:key="aim"
	if kind=="hold":key="cover"
	if textures.has(key):
		c.draw_texture_rect(textures[key],Rect2(p-Vector2(10,10),Vector2(20,20)),false,color)
		return
	if kind=="soldier":
		c.draw_arc(p+Vector2(0,-4),5,PI,TAU,12,color,2,true);c.draw_line(p+Vector2(-6,-4),p+Vector2(6,-4),color,2,true)
		c.draw_circle(p+Vector2(0,-1),3,color);c.draw_line(p+Vector2(-5,7),p+Vector2(-4,3),color,3,true);c.draw_line(p+Vector2(-4,3),p+Vector2(4,3),color,3,true);c.draw_line(p+Vector2(4,3),p+Vector2(5,7),color,3,true)
	elif kind in ["move","maneuver","advance","assault","flank","escape","retreat"]:
		c.draw_line(p+Vector2(-7,0),p+Vector2(7,0),color,2,true);c.draw_line(p+Vector2(2,-5),p+Vector2(7,0),color,2,true);c.draw_line(p+Vector2(2,5),p+Vector2(7,0),color,2,true)
	elif kind in ["fire","fire_support","establish_fire","support"]:
		if kind=="fire":
			for i in range(8):
				var d=Vector2.from_angle(i*TAU/8);c.draw_line(p+d*3,p+d*8,color,2,true)
		else:
			c.draw_arc(p,5,0,TAU,20,color,1.5,true)
			c.draw_line(p+Vector2(-8,0),p+Vector2(8,0),color,1,true);c.draw_line(p+Vector2(0,-8),p+Vector2(0,8),color,1,true)
	elif kind in ["cover","hold"]:
		c.draw_polyline(PackedVector2Array([p+Vector2(-6,-6),p+Vector2(6,-6),p+Vector2(5,3),p+Vector2(0,8),p+Vector2(-5,3),p+Vector2(-6,-6)]),color,2,true)
	elif kind in ["reload","recover","regroup"]:
		c.draw_arc(p,6,.4,5.6,20,color,2,true);c.draw_line(p+Vector2(5,-5),p+Vector2(5,0),color,2,true)
	elif kind=="dead":
		c.draw_line(p-Vector2(5,5),p+Vector2(5,5),color,2,true);c.draw_line(p+Vector2(-5,5),p+Vector2(5,-5),color,2,true)
	elif kind=="blocked":text(c,p+Vector2(-3,4),"!",Color("ffcc77"))
	elif kind=="unknown":
		c.draw_circle(p,4,Color(color,.3))
	elif kind in ["wait","reserve"]:
		for x in [-5,0,5]:c.draw_circle(p+Vector2(x,0),1.5,color)
	else:
		c.draw_line(p+Vector2(-3,-5),p+Vector2(-3,5),color,2,true);c.draw_line(p+Vector2(3,-5),p+Vector2(3,5),color,2,true)
func map_point(p: Vector2) -> Vector2:
	var scale_factor: float=minf(158/maxf(bounds.size.x,.01),86/maxf(bounds.size.y,.01))
	return Vector2(83,map_y+65)+(p-bounds.get_center())*scale_factor
func paint(c):
	if not is_instance_valid(game):return
	var hovered: String=""
	for tip in tips:
		if tip.rect.has_point(c.get_local_mouse_position()):hovered=str(tip.get("unit_id",""));break
	tips=[]
	var y: float=12
	for row in rows:
		if row.team=="red":
			map_y=y;paint_map(c,hovered);y+=145
		var color=GREEN if row.team=="green" else RED
		text(c,Vector2(0,y),"绿方" if row.team=="green" else "红方",color);y+=18
		var lines=command_lines("指挥："+row.command)
		tips.append({"rect":Rect2(0,y-12,166,17*lines.size()),"text":"指挥："+row.command})
		for line in lines:
			text(c,Vector2(0,y),line,color);y+=17
		text(c,Vector2(0,y),"小队："+row.squad,color);y+=17
		text(c,Vector2(5,y),"士兵       任务       状态",Color(.60,.66,.67));y+=15
		for member in row.members:
			var u=member.unit;var ink=color if u.hp>0 else Color(.45,.48,.48)
			icon(c,Vector2(13,y),"soldier",ink);icon(c,Vector2(80,y),member.role,ink);icon(c,Vector2(137,y),member.status,ink)
			var names={"fire":"正在开火","move":"移动中","cover":"掩体内","wait":"待命","pause":"暂停","escape":"避险中","blocked":"路径受阻","reload":"装填中","throw":"投掷中","dead":"已阵亡","rescue":"待救援"}
			var detail: String="小兵 "+str(u.id)+" · "+str(TASKS.get(member.role,"未分配任务"))+" · "+str(names.get(member.status,"待命"))
			if game.growth and u.hp>0 and not u.tank and u.has_method("can_satchel"):
				var remaining: float=maxf(0,u.harness_satchel_ready_at-game.elapsed)
				detail+=" · 炸药包"+("就绪" if remaining<=0 else "冷却 "+str(ceili(remaining))+"秒")
			tips.append({"rect":Rect2(0,y-10,166,24),"unit_id":str(u.id),"text":detail})
			c.draw_rect(Rect2(5,y+10,16,2),Color(.24,.29,.28));c.draw_rect(Rect2(5,y+10,16*clampf(u.hp/maxf(u.max_hp,1),0,1),2),ink)
			y+=24
		y+=12
	tips.append({"rect":Rect2(0,y-12,166,33),"text":"Icons: Lorc, sbed, Skoll / Game-icons.net / CC BY 3.0"})

func paint_map(c,hovered: String):
	text(c,Vector2(0,map_y+11),"战场简图 · 俯视")
	c.draw_rect(Rect2(0,map_y+19,166,94),Color(.10,.14,.16))
	for cover in game.field.covers:
		if not cover.get("alive",false):continue
		var p=cover.position;var sz=cover.size
		var a=map_point(Vector2(p[0]-sz[0]/2,p[1]-sz[1]/2));var z=map_point(Vector2(p[0]+sz[0]/2,p[1]+sz[1]/2))
		c.draw_rect(Rect2(a,z-a),Color(.37,.40,.36))
	for u in game.units:
		if u.faction not in ["green","red"] or u.hp<=0:continue
		var p=map_point(u.pos());c.draw_circle(p,2.5,GREEN if u.faction=="green" else RED)
		if str(u.id)==hovered:c.draw_arc(p,5.5,0,TAU,20,Color.WHITE,1.5,true)
		tips.append({"rect":Rect2(p-Vector2(4,4),Vector2(8,8)),"text":"小兵 "+str(u.id)})
	for team in ["green","red"]:
		var data: Dictionary=display.get(team,{})
		if data.get("goal",[]).size()!=2:continue
		var p=map_point(Vector2(data.goal[0],data.goal[1]));var color=GREEN if team=="green" else RED
		c.draw_arc(p,6,0,TAU,20,color,1.5,true);text(c,p+Vector2(7,-4),"A" if team=="green" else "B",color)
	text(c,Vector2(0,map_y+128),"A 绿方目标    B 红方目标",Color(.65,.72,.72))
