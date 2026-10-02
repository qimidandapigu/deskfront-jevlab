"""Use the squad's 0.2 s perception snapshot for advisory target selection.

The engine's actual fire admission still performs a fresh muzzle/cover trace.
"""


def patch(source: str) -> str:
    before = '''func visible_enemy(u):
	var best=null
	var distance: float=INF
	for enemy in game.living():
		if enemy.faction==u.faction or not visible_to(u.faction,enemy):continue
		var d: float=u.pos().distance_to(enemy.pos())
		if d<distance:best=enemy;distance=d
	return best'''
    after = '''func visible_enemy(u):
	var contacts: Dictionary=perception.get(u.faction,{})
	if contacts.is_empty():return null
	var best=null
	var distance: float=INF
	for enemy in game.living():
		if enemy.faction==u.faction:continue
		var contact: Dictionary=contacts.get(enemy.id,{})
		if not bool(contact.get("visible",false)):continue
		var d: float=u.pos().distance_to(enemy.pos())
		if d<distance:best=enemy;distance=d
	return best'''
    if source.count(before) == 1:
        return source.replace(before, after, 1)

    # Newer native game builds keep perception in human_squad_perception.gd
    # and leave human_squads.gd with a compatibility wrapper. Keep the same
    # staged cache semantics without pulling the helper back into the facade.
    helper_before = '''func visible_enemy(u):
	var best=null
	var distance: float=INF
	for enemy in host.game.living():
		if enemy.faction==u.faction or not visible_to(u.faction,enemy):continue
		var d: float=u.pos().distance_to(enemy.pos())
		if d<distance:best=enemy;distance=d
	return best'''
    helper_after = '''func visible_enemy(u):
	var contacts: Dictionary=host.perception.get(u.faction,{})
	if contacts.is_empty():return null
	var best=null
	var distance: float=INF
	for enemy in host.game.living():
		if enemy.faction==u.faction:continue
		var contact: Dictionary=contacts.get(enemy.id,{})
		if not bool(contact.get("visible",false)):continue
		var d: float=u.pos().distance_to(enemy.pos())
		if d<distance:best=enemy;distance=d
	return best'''
    if source.count(helper_before) == 1:
        return source.replace(helper_before, helper_after, 1)
    if 'PerceptionLogic=preload("res://scripts/human_squad_perception.gd")' in source:
        # The facade delegates to the helper; stage_squads patches that file
        # separately below.
        return source
    raise RuntimeError('Unsupported shared perception anchor')
