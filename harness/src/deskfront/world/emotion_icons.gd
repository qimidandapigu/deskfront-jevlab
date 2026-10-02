extends Control

# Twemoji artwork is loaded once per scene. The model chooses a feeling;
# death remains a native engine state and never requires a model request.
const CODES = {
	"calm": "1f610", "alert": "1f928", "nervous": "1f630",
	"afraid": "1f628", "determined": "1f623", "angry": "1f620",
	"relieved": "1f60c", "sad": "1f622", "surprised": "1f62e",
	"confused": "1f914", "exhausted": "1f629", "hurt": "1f915",
	"happy": "1f603", "dead": "1f635",
}
const FACE_SIZE := 18.0
var game
var enabled := true
var toggle: Button
var redraw_clock := 0.0
var textures: Dictionary = {}

func _ready():
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	for feeling in CODES:
		var path = "res://assets/twemoji/" + CODES[feeling] + ".png"
		var image = Image.new()
		if image.load_png_from_buffer(FileAccess.get_file_as_bytes(path)) == OK:
			textures[feeling] = ImageTexture.create_from_image(image)
	toggle = Button.new()
	toggle.text = "情绪表情 [F9]"
	toggle.toggle_mode = true
	toggle.button_pressed = enabled
	toggle.size = Vector2(112, 25)
	toggle.add_theme_font_size_override("font_size", 11)
	toggle.toggled.connect(func(value): enabled = value; queue_redraw())
	add_child(toggle)

func _input(event):
	if is_instance_valid(game) and game.human_squad and event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_F9:
		toggle.button_pressed = not toggle.button_pressed
		get_viewport().set_input_as_handled()

func _process(dt):
	toggle.visible = is_instance_valid(game) and game.human_squad
	toggle.position = Vector2(140, get_viewport_rect().size.y - 150)
	if not enabled: return
	redraw_clock -= dt
	if redraw_clock <= 0:
		redraw_clock = .05
		queue_redraw()

func _draw():
	if not enabled or not is_instance_valid(game) or not game.human_squad: return
	for u in game.units:
		if not u.visible or u.deployment_phase != "active": continue
		var feeling: String = _feeling(u)
		if not textures.has(feeling): continue
		var world: Vector3 = _world_anchor(u)
		if game.camera.is_position_behind(world): continue
		var p: Vector2 = game.camera.unproject_position(world)
		p.y -= 10
		if not get_viewport_rect().grow(-9).has_point(p): continue
		_draw_face(p, feeling)

func _world_anchor(u) -> Vector3:
	if u.hp <= 0 and is_instance_valid(u.actor) and is_instance_valid(u.actor.skeleton):
		var skeleton: Skeleton3D = u.actor.skeleton
		var head_id := skeleton.find_bone("Head")
		if head_id >= 0:
			return (skeleton.global_transform * skeleton.get_bone_global_pose(head_id)).origin
	return u.global_position + Vector3(0, .17, 0)

func _feeling(u) -> String:
	if u.hp <= 0: return "dead"
	if u.emotion != "" and game.elapsed < u.emotion_until and textures.has(u.emotion):
		return u.emotion
	# Local Bot soldiers do not receive model emotion commands. Give their
	# presentation a small, factual fallback so the opposing side is not blank.
	if u.tank or game.control.get(u.faction, "") == "lm": return ""
	if u.hp < u.max_hp * .35: return "hurt"
	if u.suppression >= .7: return "afraid"
	if u.suppression >= .35: return "nervous"
	if game.elapsed - u.last_shot_at < 2.5: return "determined"
	if u.state in ["aim", "cover", "suppressed"]: return "alert"
	return "calm"

func _draw_face(p: Vector2, feeling: String):
	var texture: Texture2D = textures.get(feeling)
	if texture == null: return
	draw_circle(p + Vector2(0,1), 9, Color(0,0,0,.16))
	draw_texture_rect(texture, Rect2(p - Vector2.ONE * FACE_SIZE * .5, Vector2.ONE * FACE_SIZE), false)
