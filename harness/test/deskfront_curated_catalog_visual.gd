extends SceneTree

# Render the actual stationery meshes in one labelled contact sheet. Supply
# curated-cards.json from the Python author catalogue in the staged project.
const TILE := Vector2i(380, 320)
const COLUMNS := 4

func _initialize(): call_deferred("run")

func run():
	var data = JSON.parse_string(FileAccess.get_file_as_string("res://curated-cards.json"))
	if not data is Array:
		push_error("Missing curated-cards.json"); quit(1); return
	var columns:int=mini(COLUMNS,data.size())
	root.size = Vector2i(TILE.x * columns, TILE.y * int(ceil(float(data.size()) / columns)))
	root.content_scale_mode = Window.CONTENT_SCALE_MODE_DISABLED
	root.content_scale_size = root.size
	root.content_scale_factor = 1.0
	var background = ColorRect.new()
	background.color = Color("eae7df"); background.size = Vector2(root.size)
	root.add_child(background)
	var font = SystemFont.new()
	font.font_names = PackedStringArray(["Microsoft YaHei UI", "Microsoft YaHei"])
	var art = load("res://scripts/world_props.gd")
	var colors = ["cdb484", "d9bd91", "b9ae91", "cdbfa4", "bd9b73", "d2c6a6", "b3aea0", "c4b495"]
	for index in range(data.size()):
		var card = data[index]
		var host = SubViewportContainer.new()
		host.position = Vector2((index % columns) * TILE.x, (index / columns) * TILE.y + 46)
		host.size = Vector2(TILE.x, TILE.y - 46)
		root.add_child(host)
		var viewport = SubViewport.new()
		viewport.size = Vector2i(TILE.x, TILE.y - 46)
		viewport.world_3d = World3D.new()
		viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
		host.add_child(viewport)
		var scene = Node3D.new(); viewport.add_child(scene)
		var env = WorldEnvironment.new(); scene.add_child(env)
		env.environment = Environment.new()
		env.environment.background_mode = Environment.BG_COLOR
		env.environment.background_color = Color("eae7df")
		env.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
		env.environment.ambient_light_color = Color.WHITE
		env.environment.ambient_light_energy = .15
		env.environment.tonemap_mode = Environment.TONE_MAPPER_FILMIC
		var sun = DirectionalLight3D.new(); scene.add_child(sun)
		sun.rotation_degrees = Vector3(-50, -30, 0)
		sun.light_energy = .18; sun.shadow_enabled = true
		var desk = MeshInstance3D.new(); scene.add_child(desk)
		var box = BoxMesh.new(); box.size = Vector3(.6, .024, .7); desk.mesh = box
		desk.position.y = -.012
		var material = StandardMaterial3D.new()
		material.albedo_color = Color(colors[int(index / 3)%colors.size()])
		desk.material_override = material
		for part in card.parts:
			var prop = Node3D.new(); scene.add_child(prop)
			prop.position = Vector3(float(part[0]), .001, float(part[1]))
			art.build(null, prop, [0, 0, part[2], part[3], part[4], part[5]])
		var camera = Camera3D.new(); scene.add_child(camera)
		camera.projection = Camera3D.PROJECTION_ORTHOGONAL; camera.size = .91
		camera.position = Vector3(.78, .94, 1.1)
		camera.look_at(Vector3(0, .025, 0)); camera.current = true
		var label = Label.new(); root.add_child(label)
		label.position = Vector2(host.position.x + 12, host.position.y - 43)
		label.size = Vector2(TILE.x - 24, 43)
		label.add_theme_font_override("font", font)
		label.add_theme_font_size_override("font_size", 16)
		label.add_theme_color_override("font_color", Color("233632"))
		label.text = "%02d  %s" % [index + 1, str(card.label).split("／")[0]]
	for index in range(24): await process_frame
	await RenderingServer.frame_post_draw
	DirAccess.make_dir_recursive_absolute("res://output/world")
	var path = "res://output/world/curated-catalog-%d.png"%data.size()
	var error = root.get_texture().get_image().save_png(path)
	print(JSON.stringify({"ok":error == OK, "image":ProjectSettings.globalize_path(path), "cards":data.size()}))
	quit(0 if error == OK else 1)
