"""Overlay and UI asset installation phases."""
import json
from pathlib import Path
import shutil

def _install_overlay_assets(destination: Path, here: Path):
    overlay = destination / 'scripts/tactical_overlay.gd'
    if overlay.exists():
        overlay_code=overlay.read_text(encoding='utf-8')
        overlay_code=overlay_code.replace('var enabled: bool=true','var enabled: bool=false').replace('toggle.button_pressed=true','toggle.button_pressed=enabled')
        overlay_code=overlay_code.replace('\t\tqueue_redraw()','\t\tif enabled:queue_redraw()')
        overlay_code=overlay_code.replace('"最终目标：占旗"','("最终目标：清除守军" if game.growth else "最终目标：占旗")')
        overlay_code=overlay_code.replace('"占旗接近点"','("接敌位置" if game.growth else "占旗接近点")')
        overlay_code=overlay_code.replace('HORIZONTAL_ALIGNMENT_LEFT,-1,8','HORIZONTAL_ALIGNMENT_LEFT,-1,7')
        overlay_code=overlay_code.replace('.x+6','.x+4').replace('Vector2(width,13)','Vector2(width,11)').replace('Vector2(3,10)','Vector2(2,8)').replace('set_corner_radius_all(5)','set_corner_radius_all(4)')
        overlay.write_text(overlay_code,encoding='utf-8')
    bubbles = destination / 'scripts/emotion_bubbles.gd'
    if bubbles.exists():
        code=bubbles.read_text(encoding='utf-8')
        for before, after in {
            'anchor.x-18':'anchor.x-15', 'viewport_size.x-40':'viewport_size.x-34',
            'anchor.y-17':'anchor.y-14', 'Vector2(36,14)':'Vector2(30,12)',
            'box.position.y-=17':'box.position.y-=14', 'Vector2(0,7)':'Vector2(0,6)',
            'Vector2(6,7)':'Vector2(5,6)', 'draw_circle(face,3.5,color)':'draw_circle(face,3.0,color)',
            'Vector2(12,10)':'Vector2(10,9)', 'HORIZONTAL_ALIGNMENT_LEFT,-1,8':'HORIZONTAL_ALIGNMENT_LEFT,-1,7',
            'set_corner_radius_all(4)':'set_corner_radius_all(3)',
        }.items():
            code=code.replace(before,after)
        code=code.replace('anchor.x-15','anchor.x-6').replace('Vector2(30,12)','Vector2(12,12)').replace('Vector2(5,6)','Vector2(6,6)')
        code='\n'.join(line for line in code.splitlines() if 'draw_string(font,' not in line)+'\n'
        code=code.replace('var game\n','var game\nvar enabled: bool=true\nvar toggle: Button\n')
        code=code.replace('func _process(_dt):queue_redraw()', '''func _process(_dt):
	if toggle:
		toggle.visible=is_instance_valid(game) and game.human_squad
		toggle.position=Vector2(140,get_viewport_rect().size.y-150)
	queue_redraw()
func _input(event):
	if is_instance_valid(game) and game.human_squad and event is InputEventKey and event.pressed and not event.echo and event.keycode==KEY_F9:
		toggle.button_pressed=not toggle.button_pressed
		get_viewport().set_input_as_handled()''')
        code=code.replace('\tmouse_filter=Control.MOUSE_FILTER_IGNORE','''	mouse_filter=Control.MOUSE_FILTER_IGNORE
	toggle=Button.new();toggle.text="情绪表情 [F9]";toggle.toggle_mode=true;toggle.button_pressed=true
	toggle.size=Vector2(112,25);toggle.add_theme_font_size_override("font_size",11)
	toggle.toggled.connect(func(value):enabled=value;queue_redraw())
	add_child(toggle)''')
        code=code.replace('func _draw():','func _draw():\n\tif not enabled:return')
        bubbles.write_text(code,encoding='utf-8')
    shutil.copyfile(here/'battle_sidebar.gd',destination/'scripts/battle_sidebar.gd')
    shutil.copytree(here/'ui_icons',destination/'ui_icons',dirs_exist_ok=True)
    shutil.copyfile(here/'emotion_icons.gd',destination/'scripts/emotion_bubbles.gd')
    emoji_source = here/'twemoji'
    emoji_target = destination/'assets/twemoji'
    emoji_target.mkdir(parents=True, exist_ok=True)
    emoji_codes = json.loads((emoji_source/'selected.json').read_text(encoding='utf-8'))
    for code in set(emoji_codes.values()):
        shutil.copyfile(emoji_source/(code+'.png'), emoji_target/(code+'.png'))
    for name in ('LICENSE-GRAPHICS', 'SOURCE.txt', 'selected.json'):
        shutil.copyfile(emoji_source/name, emoji_target/name)
    return emoji_codes


def _install_overlay_autoload(destination: Path):
    project = destination/'project.godot'
    project_code = project.read_text(encoding='utf-8')
    autoload = 'HarnessDanmaku="*res://scripts/harness_danmaku.gd"\nHarnessCommentary="*res://scripts/harness_commentary.gd"\n'
    if '[autoload]' in project_code:
        project_code = project_code.replace('[autoload]', '[autoload]\n'+autoload, 1)
    else:
        project_code += '\n[autoload]\n'+autoload
    project.write_text(project_code, encoding='utf-8')


