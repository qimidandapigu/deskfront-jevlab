"""Session-only combat rules for the staged Deskfront engine.

The source game remains untouched.  A live route is not by itself a reason to
forbid infantry fire: ordinary movement can shoot less accurately, while a
short, bounded firing halt handles targets outside the movement arc and rockets.
"""

from .stage import apply_hooks


def install(source: str) -> str:
    source = apply_hooks(source, [
        dict(name='moving fire state',
             before='var aim_time: float=0',
             after='var aim_time: float=0\nvar harness_currently_moving: bool=false\nvar harness_fire_pause_until: float=0\nvar harness_fire_pause_ready_at: float=0'),
        dict(name='bounded contact halt without cancelling route',
             before='\tvar moving: bool=not route.is_empty()\n\tupdate_posture(moving)',
             after='\tvar moving: bool=not route.is_empty()\n\tif harness_pause_for_fire(enemy,moving):moving=false\n\tupdate_posture(moving)\n\tif moving and enemy!=null and locomotion=="sprint" and harness_can_slow_for_contact():locomotion="run"\n\tharness_currently_moving=moving'),
        dict(name='weapon-specific fire gate',
             before='\t\tif cooldown<=0 and aligned and (tank or (not moving and not actor.stepping and aim_time>=.16 and cqb_stance!="hide" and suppression<.95)):',
             after='\t\tif cooldown<=0 and aligned and (tank or (not actor.stepping and cqb_stance!="hide" and suppression<.95 and game.elapsed>=safety_until and ((not moving and aim_time>=.16) or harness_mobile_fire_allowed(enemy,moving)))):'),
        dict(name='moving shot dispersion',
             before='\tvar cfg: Dictionary=weapon_config()\n\tvar chance: float=cfg.accuracy*(1-suppression*.32)',
             after='\tvar cfg: Dictionary=weapon_config()\n\tif harness_currently_moving and weapon in ["rifle","smg","pistol"]:\n\t\tcfg.accuracy*=({"rifle":.55,"smg":.70,"pistol":.65}[weapon])\n\t\tcfg.cooldown*=1.15\n\tvar chance: float=cfg.accuracy*(1-suppression*.32)'),
    ])
    source += '''
func harness_can_slow_for_contact() -> bool:
	return game.elapsed>=safety_until and order_mode not in ["retreat","self_preserve","evade_explosive","soldier_rush_to_site"] and deployment_phase=="active"

func harness_pause_for_fire(enemy, route_active: bool) -> bool:
	if not route_active or enemy==null or tank or game.elapsed<safety_until or cqb_stance=="hide" or not harness_can_slow_for_contact() or (actor and actor.stepping):
		harness_fire_pause_until=0
		return false
	if game.elapsed<harness_fire_pause_until:return true
	if game.elapsed<harness_fire_pause_ready_at or cooldown>0 or reload_timer>0:return false
	var to_enemy: Vector2=enemy.pos()-pos()
	if to_enemy.length_squared()<.00001:return false
	var forward: Vector2=(route[0]-pos()).normalized()
	var off_axis: bool=forward.dot(to_enemy.normalized())<.45
	var close: bool=to_enemy.length()<float(weapon_config().range)*.38
	if weapon!="rocket" and not off_axis and not close:return false
	harness_fire_pause_until=game.elapsed+(.55 if weapon=="rocket" else .40)
	harness_fire_pause_ready_at=game.elapsed+(1.7 if weapon=="rocket" else 1.25)
	return true

func harness_mobile_fire_allowed(enemy, moving: bool) -> bool:
	if not moving or enemy==null or weapon not in ["rifle","smg","pistol"] or locomotion not in ["run","crouch_run","walk"] or not harness_can_slow_for_contact():return false
	var to_enemy: Vector2=enemy.pos()-pos()
	if to_enemy.length_squared()<.00001:return false
	var forward:=Vector2(-sin(rotation.y),-cos(rotation.y))
	return forward.dot(to_enemy.normalized())>=.45
'''
    return source
