extends RefCounted
## Presentation-only construction for generated Deskfront regions.
## Mission state, navigation and combat stay owned by world_growth.gd.

static func build(game, revision: int, left: float, parent: Node3D, visual_pattern: String = "open_field", main_regions: Array = []) -> Array:
	var panels: Array = []
	var art = preload("res://scripts/world_props.gd")
	var z: float = (game.config.bounds[1] + game.config.bounds[3]) * .5
	var woods = ["d6b081", "a97752", "c99e71", "ad805f", "dfbd8b", "a87755", "d0a275", "b48862", "c69a72"]
	var accent = "8faeb2"
	match visual_pattern:
		"rescue":
			woods = ["d4b889", "b89d73", "dbc294", "bca77d", "d8bf91", "ad9872", "d0b68a", "bda47b", "d7bd91"]
			accent = "d5c47b"
		"north_screen":
			woods = ["b8b9aa", "a9afa4", "c2c0ad", "a4aba1", "b9b8a8", "a5a99d", "c0bba8", "a8ada2", "b5b6a7"]
			accent = "e0c982"
		"south_screen":
			woods = ["a9b4b5", "b5bdbb", "a0afb3", "b4b8b1", "9daeb1", "aab8b9", "a2b3b8", "b9c0bb", "a3b5b8"]
			accent = "eee0ae"
		"central_gate":
			woods = ["c5a78d", "bd9b80", "cba98a", "b49078", "c6a383", "b7967d", "c8a78c", "b7967d", "c5a286"]
			accent = "e5d4a8"
		"zigzag":
			woods = ["b8aeb4", "a89fab", "bfb2b8", "a9a0ad", "b6aab4", "aaa2ad", "bdb0b8", "a9a1ac", "b8adb6"]
			accent = "e4d7a0"
		"diagonal":
			woods = ["c4bf9f", "adb59e", "c8c1a0", "afb8a2", "c5bea1", "aeb49d", "c7c3a7", "aab39c", "c3bf9f"]
			accent = "eee2b9"
	var lifts = [.004, -.003, .002, -.004, .003, -.002, .002, -.004, .004]
	for x in range(3):
		for row in range(3):
			var index: int = x * 3 + row
			var panel = Node3D.new()
			panel.name = "Desk_%d_%d_%d" % [revision, x, row]
			parent.add_child(panel)
			var cx: float = left + (x + .5) * .6
			var cz: float = z + (row - 1) * .7
			panel.position = Vector3(cx, 0, cz)
			var top: float = game.field.height + lifts[index]
			panel.set_meta("desk_top", top)
			panel.set_meta("region_index", revision)
			panel.set_meta("cell", Vector2i(x, row))
			panel.set_meta("wood_color", woods[index])
			# Twelve-millimeter joins expose the dark space between individual tops.
			art.box(panel, Vector3(0, top - .013, 0), Vector3(.588, .026, .688), woods[index])
			# Paint is visual-only and follows the actual chosen passage graph.
			art.box(panel, Vector3(0, top + .002, -.298), Vector3(.46, .003, .018), accent)
			var cell_id: String = "c%dr%d" % [x, row]
			var route_index: int = main_regions.find(cell_id)
			if route_index >= 0:
				art.box(panel, Vector3(0, top + .002, 0), Vector3(.065, .003, .065), accent)
				for neighbor_index in [route_index - 1, route_index + 1]:
					if neighbor_index < 0 or neighbor_index >= main_regions.size():
						continue
					var neighbor: String = str(main_regions[neighbor_index])
					var dx: int = int(neighbor.substr(1, 1)) - x
					var dz: int = int(neighbor.substr(3, 1)) - row
					if dx != 0:
						art.box(panel, Vector3(float(dx) * .145, top + .002, 0), Vector3(.29, .003, .045), accent)
					elif dz != 0:
						art.box(panel, Vector3(0, top + .002, float(dz) * .17), Vector3(.045, .003, .34), accent)
			art.box(panel, Vector3(0, top - .030, .326), Vector3(.55, .035, .018), "684a38")
			for dx in [-.25, .25]:
				for dz in [-.28, .28]:
					art.box(panel, Vector3(dx, top - .43, dz), Vector3(.025, .80, .025), "876247")
			art.batch(panel)
			panels.append(panel)
	return panels
