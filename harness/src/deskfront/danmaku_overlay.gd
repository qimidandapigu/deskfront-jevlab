extends CanvasLayer
# Spectator-only overlay. At most three labels, no physics or navigation queries.
var directory: String=""
var pending: Array=[]
var active: Array=[]
var seen: Dictionary={}
var next_poll: float=0
var badge: Label
var run_key: String=""
var displayed: int=0
func _ready():
 process_mode=Node.PROCESS_MODE_ALWAYS;layer=119
 directory=OS.get_environment("QUICKPLAY_OUTPUT_DIR")
 badge=Label.new();badge.text="AI 生成弹幕";badge.position=Vector2(260,150)
 badge.add_theme_font_size_override("font_size",12);badge.modulate=Color(1,1,1,.65)
 badge.mouse_filter=Control.MOUSE_FILTER_IGNORE;add_child(badge);badge.hide()
func clear_comments():
 pending.clear()
 for row in active:row.label.queue_free()
 active.clear();badge.hide()
func _process(delta):
 if directory.is_empty():return
 var g=get_tree().current_scene
 if not is_instance_valid(g):return
 var growth=g.get("growth")
 var revision:int=int(growth.revision) if growth else 0
 var key=str(g.get("run_id"))+":"+str(revision)
 if key!=run_key:clear_comments();seen.clear();run_key=key
 if g.get("paused"):clear_comments()
 var now:float=Time.get_unix_time_from_system()*1000
 var viewport=get_viewport().get_visible_rect().size
 badge.position=Vector2(maxf(230,viewport.x*.2),maxf(100,viewport.y*.16))
 for row in active.duplicate():
  row.age+=delta
  var left:float=maxf(230,viewport.x*.2)
  row.label.position.x=lerpf(viewport.x-row.label.size.x-16,left,row.age/7.0)
  row.label.modulate.a=minf(1.0,(7.0-row.age)*2)
  if row.age>=7.0:row.label.queue_free();active.erase(row)
 if now>=next_poll:
  next_poll=now+250
  var path=directory.path_join("danmaku-command.json")
  if FileAccess.file_exists(path):
   var c=JSON.parse_string(FileAccess.get_file_as_string(path))
   if c is Dictionary and c.get("session")==OS.get_environment("DESKFRONT_INSTANCE_ID"):
    if not c.get("enabled",false):clear_comments()
    elif str(c.get("run_id"))==str(g.get("run_id")) and int(c.get("revision",-1))==revision and not g.get("paused"):
     badge.show()
     for item in c.get("items",[]):
      if seen.has(item.id):continue
      seen[item.id]=true
      if float(item.expires)>now:pending.append(item)
  var status={"ready":true,"session":OS.get_environment("DESKFRONT_INSTANCE_ID"),"run_id":str(g.get("run_id")),"updated_at":now,"visible":active.size(),"displayed":displayed}
  var file=FileAccess.open(directory.path_join("danmaku-status.json.tmp"),FileAccess.WRITE)
  if file:
   file.store_string(JSON.stringify(status));file.close()
   DirAccess.rename_absolute(directory.path_join("danmaku-status.json.tmp"),directory.path_join("danmaku-status.json"))
 for item in pending.duplicate():
  if now>=float(item.expires):pending.erase(item);continue
  if now<float(item.at) or active.size()>=3:continue
  var lane:int=0
  while active.any(func(row):return row.lane==lane):lane+=1
  var label=Label.new();label.text=str(item.text).left(60);label.mouse_filter=Control.MOUSE_FILTER_IGNORE
  label.add_theme_font_size_override("font_size",20);label.add_theme_constant_override("outline_size",4)
  label.add_theme_color_override("font_outline_color",Color(0,0,0,.85))
  if ResourceLoader.exists("res://assets/fonts/DeskfrontUI.otf"):
   var font=load("res://assets/fonts/DeskfrontUI.otf").duplicate()
   var emoji=SystemFont.new();emoji.font_names=PackedStringArray(["Segoe UI Emoji"]);font.fallbacks=[emoji]
   label.add_theme_font_override("font",font)
  label.position=Vector2(viewport.x-300,badge.position.y+24+lane*32)
  add_child(label);active.append({"label":label,"lane":lane,"age":0.0});displayed+=1;pending.erase(item)
