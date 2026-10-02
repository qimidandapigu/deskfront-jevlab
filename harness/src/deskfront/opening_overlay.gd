extends RefCounted
var layer: CanvasLayer
var label: Label
var tween: Tween
var last_text := ""
func show(tree, value: String):
	if value==last_text:return
	last_text=value
	if not is_instance_valid(layer):
		layer=CanvasLayer.new();layer.layer=100;tree.root.add_child(layer)
		label=Label.new();layer.add_child(label)
		label.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		label.horizontal_alignment=HORIZONTAL_ALIGNMENT_CENTER;label.vertical_alignment=VERTICAL_ALIGNMENT_CENTER
		label.mouse_filter=Control.MOUSE_FILTER_IGNORE
		label.add_theme_font_size_override("font_size",120)
		label.add_theme_color_override("font_color",Color("fff3b0"))
		label.add_theme_color_override("font_outline_color",Color("182924"))
		label.add_theme_constant_override("outline_size",12)
	if tween and tween.is_valid():tween.kill()
	label.text=value;label.visible=true;label.modulate.a=1
	label.add_theme_font_size_override("font_size",32 if value.length()>4 else 120)
	label.pivot_offset=Vector2(tree.root.size)/2
	label.scale=Vector2.ONE*1.25
	tween=tree.create_tween()
	tween.tween_property(label,"scale",Vector2.ONE,.25).set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	if value=="开战":
		tween.tween_interval(.4)
		tween.tween_property(label,"modulate:a",0.0,.3)
