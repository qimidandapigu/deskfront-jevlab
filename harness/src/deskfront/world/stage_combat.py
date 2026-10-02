"""Combat and projectile presentation hook installation."""
from pathlib import Path
import shutil

from .stage_contract import apply_hooks

def _patch_combat_fx(destination: Path, here: Path):
    actor = destination / 'scripts/toy_actor.gd'
    actor_code = actor.read_text(encoding='utf-8')
    actor_code = apply_hooks(actor_code,[dict(name='settled ragdoll keeps final pose',
        before=' if dead:\n  rag_age+=dt',
        after=' if dead:\n  if rag_settled:return\n  rag_age+=dt')])
    actor.write_text(actor_code,encoding='utf-8')
    combat_fx = destination / 'scripts/combat_fx.gd'
    fx_code = combat_fx.read_text(encoding='utf-8')
    fx_code=apply_hooks(fx_code,[dict(name='mortar defers native dispersion to its team weapon adapter',
        before='\tif game.human_squad:\n',
        after='\tif game.human_squad and not cfg.get("harness_mortar",false):\n')])
    fx_code=apply_hooks(fx_code,[dict(name='mortar uses its indirect safety trajectory',
        before='\tvar blocked: String=explosive_fire_block(shooter,from,end,cfg,weapon)',
        after='\tvar safety_weapon: String="mortar" if cfg.get("harness_mortar",false) else weapon\n\tvar blocked: String=explosive_fire_block(shooter,from,end,cfg,safety_weapon)')])
    fx_code=apply_hooks(fx_code,[dict(name='mortar safety gate accepts the team weapon',
        before='\tif weapon not in ["rocket","cannon","at_cannon","grenade"]:return ""',
        after='\tif weapon not in ["rocket","cannon","at_cannon","grenade","mortar"]:return ""')])
    fx_code=apply_hooks(fx_code,[dict(name='mortar muzzle ignores its own proxy cover',
        before='\t\tcollision=trace(previous,point,shooter.id)\n\t\tif not collision.is_empty():break',
        after='\t\tcollision=trace(previous,point,shooter.id)\n\t\tif collision.get("kind","")=="cover" and str(collision.get("cover_id",""))==str(shooter.id):collision={}\n\t\tif not collision.is_empty():break')])
    fx_code=apply_hooks(fx_code,[dict(name='mortar flight passes its own base proxy',
        before='\t\tvar collision: Dictionary=trace(previous,next,p.shooter)\n\t\tif not collision.is_empty():next=collision.point',
        after='\t\tvar collision: Dictionary=trace(previous,next,p.shooter)\n\t\tif collision.get("kind","")=="cover" and p.cfg.get("harness_mortar",false) and str(collision.get("cover_id",""))==str(p.shooter):collision={}\n\t\tif not collision.is_empty():next=collision.point')])
    fx_code=apply_hooks(fx_code,[dict(name='actual projectile damage attribution',
        before='\t\t\ttarget.hit(damage,float(p.cfg.pressure),p.from,.12);target.receive_pressure(0,p.from)',
        after='\t\t\tvar before_hp: float=target.hp\n\t\t\ttarget.hit(damage,float(p.cfg.pressure),p.from,.12);target.receive_pressure(0,p.from)\n\t\t\tif game.human_squad and target.hp<before_hp:mark_harness_hit(str(p.shooter))'),
        dict(name='actual blast damage attribution',
        before='\t\t\tenemy.hit(damage,float(p.cfg.pressure)*(.12 if shield else 1.0),blast,.55*(1-distance/float(p.cfg.splash)))',
        after='\t\t\tvar before_hp: float=enemy.hp\n\t\t\tenemy.hit(damage,float(p.cfg.pressure)*(.12 if shield else 1.0),blast,.55*(1-distance/float(p.cfg.splash)))\n\t\t\tif game.human_squad and enemy.hp<before_hp:mark_harness_hit(str(p.shooter))')])
    fx_code=apply_hooks(fx_code,[dict(name='satchel pack projectile appearance',
        before='\tif weapon=="grenade":\n\t\tvar shell=load("res://assets/models/grenade.glb").instantiate();n.add_child(shell);shell.scale=Vector3.ONE*.075;n.mesh=null\n\t\tfor part in shell.find_children("*","MeshInstance3D",true,false):part.material_override=game.field.mat(game.colors[shooter.faction],.32)',
        after='\tif weapon=="grenade":\n\t\tif cfg.get("harness_satchel",false):\n\t\t\tvar satchel_builder=preload("res://scripts/satchel_presentation.gd")\n\t\t\tsatchel_builder.build(n,self,game.colors.get(str(shooter.faction),Color(.34,.28,.18)))\n\t\telse:\n\t\t\tvar shell=load("res://assets/models/grenade.glb").instantiate();n.add_child(shell);shell.scale=Vector3.ONE*.075;n.mesh=null\n\t\t\tfor part in shell.find_children("*","MeshInstance3D",true,false):part.material_override=game.field.mat(game.colors[shooter.faction],.32)'),
        dict(name='satchel impact attribution',
        before='"weapon":p.weapon,"kind":kind',
        after='"weapon":"mortar" if p.cfg.get("harness_mortar",false) else ("satchel" if p.cfg.get("harness_satchel",false) else p.weapon),"kind":kind')])
    fx_code=apply_hooks(fx_code,[dict(name='mortar shell uses the checked high arc',
        before='if weapon=="grenade":point.y+=sin(t*PI)*.20',
        after='if weapon=="grenade" or weapon=="mortar":point.y+=sin(t*PI)*float(cfg.get("harness_arc_height",.20))'),
        dict(name='mortar projectile follows the same high arc',
        before='if p.weapon=="grenade":next.y+=sin(clampf(p.age/p.duration,0,1)*PI)*.20',
        after='if p.weapon=="grenade" or p.weapon=="mortar":next.y+=sin(clampf(p.age/p.duration,0,1)*PI)*float(p.cfg.get("harness_arc_height",.20))'),
        dict(name='mortar hits tank top armor',
        before='if enemy.tank:damage*=float(p.cfg.armor_multiplier)*enemy.armor_multiplier(Vector2(p.from.x,p.from.z))',
        after='if enemy.tank:damage*=1.0 if p.cfg.get("harness_top_attack",false) else float(p.cfg.armor_multiplier)*enemy.armor_multiplier(Vector2(p.from.x,p.from.z))')])
    fx_code=apply_hooks(fx_code,[dict(name='mortar blast damages the gun proxy',
        before='\t\tfor enemy in game.living():',
        after='''\t\tvar mortar_target=p.get("target")
\t\tif kind=="cover" and mortar_target!=null and mortar_target.has_method("is_mortar_target") and str(collision.get("cover_id",""))==str(mortar_target.id):
\t\t\tmortar_target.hit(float(p.cfg.damage),float(p.cfg.pressure),blast,.55)
\t\tfor enemy in game.living():''')])
    fx_code=apply_hooks(fx_code,[dict(name='mortar direct impact damages the gun proxy',
        before='\t\tif kind=="cover":game.field.damage_cover(collision.cover_id,float(p.cfg.get("cover_damage",.3)))',
        after='''\t\tif kind=="cover":
\t\t\tvar mortar_target=p.get("target")
\t\t\tif mortar_target!=null and mortar_target.has_method("is_mortar_target") and str(collision.get("cover_id",""))==str(mortar_target.id):
\t\t\t\tmortar_target.hit(float(p.cfg.damage),float(p.cfg.pressure),p.from,.12)
\t\t\telse:game.field.damage_cover(collision.cover_id,float(p.cfg.get("cover_damage",.3)))''')])
    fx_code+='\nfunc mark_harness_hit(shooter_id: String) -> void:\n\tfor unit in game.units:\n\t\tif unit.id==shooter_id and unit.get("harness_last_hit_at")!=null:\n\t\t\tunit.harness_last_hit_at=game.elapsed;return\n'
    from .artillery_hooks import install as install_artillery_presentation
    fx_code=install_artillery_presentation(fx_code)
    shutil.copyfile(here/'artillery_presentation.gd',destination/'scripts/artillery_presentation.gd')
    shutil.copyfile(here/'satchel_presentation.gd',destination/'scripts/satchel_presentation.gd')
    combat_fx.write_text(fx_code,encoding='utf-8')



