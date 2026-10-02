"""Unit behavior hook installation."""
from pathlib import Path

from .stage_contract import PASSING_HOOK, apply_hooks

def _patch_unit(destination: Path, here: Path):
    unit = destination / 'scripts/unit.gd'
    code=unit.read_text(encoding='utf-8')
    code=apply_hooks(code,[PASSING_HOOK])
    code=apply_hooks(code,[dict(name='satchel uses real grenade release with its own payload',
        before='\t\t\tif is_instance_valid(grenade_target) and game.fx.launch(self,grenade_target,"grenade",true):game.shots+=1\n\t\t\telse:grenade_count+=1',
        after='\t\t\tvar satchel: bool=bool(get_meta("harness_satchel_active",false))\n'
              '\t\t\tvar payload: Dictionary=get_meta("harness_satchel_config",{}) if satchel else {}\n'
              '\t\t\tif is_instance_valid(grenade_target) and game.fx.launch(self,grenade_target,"grenade",true,payload):\n'
              '\t\t\t\tgame.shots+=1\n'
              '\t\t\t\tif satchel:set_meta("harness_satchel_result",{"status":"launched","time":game.elapsed,"target_id":grenade_target.id})\n'
              '\t\t\telif satchel:set_meta("harness_satchel_result",{"status":"blocked","time":game.elapsed,"reason":get_meta("fire_block_reason","")})\n'
              '\t\t\telse:grenade_count+=1\n'
              '\t\t\tif satchel:set_meta("harness_satchel_active",false)')])
    code=apply_hooks(code,[dict(name='damaged tank loses mobility',
        before='\t\tvar speed: float=base_speed*(game.config.soldier.speed/.12 if not tank else 1.0)*(1-suppression*.18)*formation_speed',
        after='\t\tvar speed: float=base_speed*(game.config.soldier.speed/.12 if not tank else 1.0)*(1-suppression*.18)*formation_speed\n'
              '\t\tif tank and bool(get_meta("harness_engine_damaged",false)):speed*=.55\n'
              '\t\telif tank and game.elapsed<float(get_meta("harness_crew_shock_until",0.0)):speed*=.7')])
    # Recent native game revisions drive a mortar crew through FieldGun.drive
    # inside the existing gun branch.  Older revisions exposed the presentation
    # anchor below; keep the adapter compatible with both without rewriting the
    # native unit implementation.
    if '\tif gun_id!="":\n\t\tactor.weapon.hide()\n\t\tfor gun in game.at_guns:\n\t\t\tif gun.id==gun_id:gun.pose_crew(self)' in code:
        code=apply_hooks(code,[dict(name='mortar guard keeps its authored presentation',
            before='''\tif gun_id!="":
\t\tactor.weapon.hide()
\t\tfor gun in game.at_guns:
\t\t\tif gun.id==gun_id:gun.pose_crew(self)''',
            after='''\tif gun_id!="":
\t\tactor.weapon.hide()
\t\tfor gun in game.at_guns:
\t\t\tif gun.id==gun_id:gun.pose_crew(self)
\telse:
\t\tfor gun in game.at_guns:
\t\t\tif gun.get("guard_id")==id:gun.pose_crew(self);break''')])
    code=apply_hooks(code,[dict(name='mortar is a valid direct-fire target',
        before='func can_engage(enemy) -> bool:\n',
        after='''func can_engage(enemy) -> bool:
	if enemy.has_method("is_mortar_target"):
		if deployment_phase!="active" or enemy.hp<=0 or enemy.faction==faction:return false
		var origin:Vector3=muzzle_position(enemy.aim_point())
		var hit:Dictionary=game.field.trace_cover(origin,enemy.aim_point())
		return hit.is_empty() or str(hit.get("cover_id",""))==str(enemy.id)
''')])
    code=apply_hooks(code,[dict(name='exposed infantry makes a bounded retreat without instant cover',
        before='''\t\tvar escape: Vector2=pos()
\t\tvar backward: Vector2=(pos()-enemy.pos()).normalized()
\t\tfor direction in [backward,backward.orthogonal(),-backward.orthogonal()]:
\t\t\tvar candidate: Vector2=pos()+direction*.12
\t\t\tif not game.field.segment_walkable(pos(),candidate) or game.field.line_of_sight(candidate,enemy.pos()):continue
\t\t\tif game.living().any(func(v):return v!=self and v.pos().distance_to(candidate)<.04):continue
\t\t\tescape=candidate;break''',
        after='''\t\tvar escape: Vector2=pos()
\t\tvar retreat: Vector2=pos()
\t\tvar backward: Vector2=(pos()-enemy.pos()).normalized()
\t\tfor direction in [backward,backward.orthogonal(),-backward.orthogonal()]:
\t\t\tvar candidate: Vector2=pos()+direction*.12
\t\t\tif not game.field.segment_walkable(pos(),candidate):continue
\t\t\tif game.living().any(func(v):return v!=self and v.pos().distance_to(candidate)<.04):continue
\t\t\tif not game.field.line_of_sight(candidate,enemy.pos()):escape=candidate;break
\t\t\tif outmatched and retreat==pos() and candidate.distance_to(enemy.pos())>pos().distance_to(enemy.pos())+.07:retreat=candidate
\t\tif escape==pos() and outmatched:escape=retreat''')])
    from .unit_profile import instrument
    from . import query_optimization
    from .moving_fire import install as install_moving_fire
    from .hit_reaction import install as install_hit_reaction
    from .antiarmor_charge import install as install_antiarmor_charge
    unit.write_text(query_optimization.unit(instrument(install_hit_reaction(install_antiarmor_charge(install_moving_fire(code))))),encoding='utf-8')


