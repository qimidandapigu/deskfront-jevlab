extends CanvasLayer
# Harness-owned spectator presentation. No combat commands or model calls.
var player: AudioStreamPlayer
var panel: PanelContainer
var caption: Label
var current: Dictionary={}
var last_command: String=""
var phase: String="idle"
var until: float=0.0
var next_poll: float=0.0
var directory: String=""
var enabled: bool=false
var duck_levels: Dictionary={}
var duck_db: float=0.0

func _ready():
	process_mode=Node.PROCESS_MODE_ALWAYS
	layer=120
	directory=OS.get_environment("QUICKPLAY_OUTPUT_DIR")
	var bus=AudioServer.get_bus_index("HarnessCommentary")
	if bus<0:
		AudioServer.add_bus();bus=AudioServer.bus_count-1
		AudioServer.set_bus_name(bus,"HarnessCommentary")
		var limiter=AudioEffectLimiter.new();limiter.ceiling_db=-1
		AudioServer.add_bus_effect(bus,limiter)
	player=AudioStreamPlayer.new();player.bus="HarnessCommentary";add_child(player)
	panel=PanelContainer.new();add_child(panel)
	panel.mouse_filter=Control.MOUSE_FILTER_IGNORE
	var style=StyleBoxFlat.new();style.bg_color=Color(0.025,0.04,0.055,0.72)
	style.set_corner_radius_all(6);style.content_margin_left=12;style.content_margin_right=12
	style.content_margin_top=6;style.content_margin_bottom=6
	panel.add_theme_stylebox_override("panel",style)
	caption=Label.new();panel.add_child(caption)
	caption.mouse_filter=Control.MOUSE_FILTER_IGNORE
	caption.autowrap_mode=TextServer.AUTOWRAP_WORD_SMART
	caption.horizontal_alignment=HORIZONTAL_ALIGNMENT_CENTER
	caption.add_theme_font_size_override("font_size",18)
	caption.add_theme_color_override("font_color",Color.WHITE)
	caption.add_theme_color_override("font_outline_color",Color.BLACK)
	caption.add_theme_constant_override("outline_size",1)
	if ResourceLoader.exists("res://assets/fonts/DeskfrontUI.otf"):
		var ui_font=load("res://assets/fonts/DeskfrontUI.otf").duplicate()
		var emoji_font=SystemFont.new();emoji_font.font_names=PackedStringArray(["Segoe UI Emoji"])
		ui_font.fallbacks=[emoji_font]
		caption.add_theme_font_override("font",ui_font)
	panel.hide()
	player.finished.connect(func():phase="idle";panel.hide();write_status())
	write_status()

func game():return get_tree().current_scene

func write_status():
	if directory=="":return
	var g=game()
	var status={"ready":true,"session":OS.get_environment("DESKFRONT_INSTANCE_ID"),
		"run_id":str(g.get("run_id")) if is_instance_valid(g) else "",
		"phase":phase,"id":current.get("id",""),"text":caption.text,
		"updated_at":Time.get_unix_time_from_system()*1000,
		"remaining_ms":maxf(0,until-Time.get_unix_time_from_system())*1000,
		"subtitle_visible":panel.visible,"audio_playing":player.playing}
	var path=directory.path_join("commentary-status.json")
	var f=FileAccess.open(path+".tmp",FileAccess.WRITE)
	if f:
		f.store_string(JSON.stringify(status));f.close();DirAccess.rename_absolute(path+".tmp",path)

func stop_playback():
	player.stop();panel.hide();phase="idle";until=0;write_status()

func layout_caption():
	var viewport=get_viewport().get_visible_rect().size
	var font_size=int(clampf(viewport.x/72,16,20))
	caption.add_theme_font_size_override("font_size",font_size)
	var font=caption.get_theme_font("font")
	var width=clampf(font.get_string_size(caption.text,HORIZONTAL_ALIGNMENT_LEFT,-1,font_size).x+28,160,viewport.x*.62)
	caption.custom_minimum_size.x=width-24
	var height=ceil(font.get_string_size(caption.text,HORIZONTAL_ALIGNMENT_LEFT,-1,font_size).x/maxf(1,width-24))*font.get_height(font_size)+12
	panel.size=Vector2(width,height)
	panel.position=Vector2((viewport.x-width)/2,viewport.y-136-height)


func update_duck(delta: float):
	var target=-8.0 if player.playing and player.volume_db>-60 else 0.0
	duck_db=move_toward(duck_db,target,delta*(40 if target<duck_db else 16))
	for name in ["Weapons","Blasts"]:
		var index=AudioServer.get_bus_index(name)
		if index<0:continue
		if not duck_levels.has(name):duck_levels[name]=AudioServer.get_bus_volume_db(index)
		AudioServer.set_bus_volume_db(index,float(duck_levels[name])+duck_db)

func _exit_tree():
	for name in duck_levels:
		var index=AudioServer.get_bus_index(name)
		if index>=0:AudioServer.set_bus_volume_db(index,float(duck_levels[name]))

func _process(_delta):
	update_duck(_delta)
	if directory=="":return
	var now=Time.get_unix_time_from_system()
	var g=game()
	if not is_instance_valid(g):return
	layout_caption()
	if phase=="playing" and (g.get("paused")==true or str(g.get("run_id"))!=str(current.get("run_id",""))):
		stop_playback()
	if phase=="playing" and not player.playing and now>=until:stop_playback()
	if now<next_poll:return
	next_poll=now+.2
	var path=directory.path_join("commentary-command.json")
	if FileAccess.file_exists(path):
		var command=JSON.parse_string(FileAccess.get_file_as_string(path))
		if command is Dictionary and command.get("session")==OS.get_environment("DESKFRONT_INSTANCE_ID"):
			player.volume_db=linear_to_db(clampf(float(command.get("volume",1.0)),0,1))+3.0
			if not command.get("enabled",false):
				if enabled:stop_playback()
				enabled=false
			elif str(command.get("command_id",""))!=last_command:
				last_command=str(command.get("command_id",""));enabled=true
				if command.get("action")=="stop":stop_playback()
				elif command.get("action")=="play" and float(command.get("expires_at",0))>now*1000 and str(command.get("run_id",""))==str(g.get("run_id")) and not g.get("paused"):
					stop_playback();current=command;caption.text=str(command.get("text","")).left(110)
					layout_caption();panel.show();phase="playing"
					if command.get("audio",false):
						var stream=AudioStreamMP3.new();stream.data=FileAccess.get_file_as_bytes(directory.path_join("commentary.mp3"))
						player.stream=stream;player.play();until=now+stream.get_length()
					else:until=now+maxf(4,caption.text.length()/5.0)
					var capture=directory.path_join("commentary-capture.png")
					if command.get("audio",false) and FileAccess.file_exists(directory.path_join("commentary-capture.request")) and not FileAccess.file_exists(capture):capture_frame.call_deferred(capture)
	write_status()

func capture_frame(path: String):
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	await RenderingServer.frame_post_draw
	get_viewport().get_texture().get_image().save_png(path)
