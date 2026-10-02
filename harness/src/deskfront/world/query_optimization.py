"""Conservative session-only optimizations; never reuse across simulation ticks."""

def once(source, before, after):
    count = source.count(before)
    if count == 0:
        return source
    if count != 1:
        raise RuntimeError('Unsupported query optimization anchor: '+before[:80])
    return source.replace(before, after, 1)

def unit(source):
    # Cache the target search per unit for ~0.3s (staggered), the cadence
    # classic squad RTS AI uses; full re-search on request/revision change.
    first='\tvar enemy=game.find_target(self,target_id if target_id!="" else focus_id)'
    source=once(source,first,'\tvar enemy=harness_find_target(target_id if target_id!="" else focus_id)')
    second='\tenemy=game.find_target(self,target_id if target_id!="" else focus_id)'
    source=once(source,second,'\tenemy=harness_find_target(target_id if target_id!="" else focus_id)')
    # Peek decisions read the 0.2s perception cache instead of per-frame LOS rays.
    peek='\t\tvar enemy=game.human_squads.visible_enemy(self) if game.human_squad else game.closest_enemy(self)'
    source=once(source,peek,'\t\tvar enemy=harness_perceived_enemy() if game.human_squad else game.closest_enemy(self)')
    # Corpses no longer cast shadows; the settled ragdoll pose stays visible.
    death='\t\tstate="dead";route.clear();game.field.release(id);animate("death");hp_fill.visible=false;ring.visible=false'
    source=once(source,death,death+'\n\t\tif actor:\n\t\t\tfor corpse_mesh in actor.find_children("*","MeshInstance3D",true,false):corpse_mesh.cast_shadow=GeometryInstance3D.SHADOW_CASTING_SETTING_OFF')
    # Instrument the real expensive subcall, including failed searches.
    line='\tvar slot: Dictionary=game.field.choose_cover(id,pos(),threat,near_goal,options)'
    source=once(source,line,'\tvar cover_started: int=Time.get_ticks_usec()\n'+line+'\n\tgame.record_cost("unit_detail/seek_cover_query",cover_started)')
    source+='\n'+HELPERS
    return source

def field(source):
    # Reject impossible distances before occupancy and walkability queries.
    before='\t\tfor s in slots(c):\n\t\t\tif reservations.has(s.key)'
    after='\t\tfor s in slots(c):\n\t\t\tif from.distance_squared_to(s.position)>max_travel*max_travel:continue\n\t\t\tif reservations.has(s.key)'
    source=once(source,before,after)
    source=once(source,'\tvar max_travel: float=options.get("max_travel",.70)\n\tfor c in covers:\n\t\tif not c.alive:continue',
        '\tvar max_travel: float=options.get("max_travel",.70)\n\tfor c in covers:\n\t\tif not c.alive:continue\n\t\tif not harness_cover_near(c,from,max_travel):continue')
    source=once(source,'\t\tif not c.alive: continue\n\t\tfor s in slots(c):',
        '\t\tif not c.alive: continue\n\t\tif not harness_cover_near(c,p,.06):continue\n\t\tfor s in slots(c):')
    source+='''
func harness_cover_near(c: Dictionary, point: Vector2, distance: float) -> bool:
	# Bounds include every existing hard/soft cover slot, not just the visible box.
	var radius: float=Vector2(c.size[0],c.size[1]).length()*.5+.10+distance
	return point.distance_squared_to(Vector2(c.position[0],c.position[1]))<=radius*radius
'''
    return source

HELPERS = (
    'var harness_target: Dictionary={}\n'
    'func harness_find_target(requested: String):\n'
    '\tvar now: float=game.elapsed\n'
    '\tif not harness_target.is_empty():\n'
    '\t\tvar cached=harness_target.enemy\n'
    '\t\tvar fresh: bool=now<float(harness_target.until) and requested==harness_target.requested and game.field.revision==harness_target.revision\n'
    '\t\tif fresh and cached!=null:\n'
    '\t\t\tif not is_instance_valid(cached) or cached.hp<=0 or cached.deployment_phase!="active":fresh=false\n'
    '\t\t\telif pos().distance_to(cached.pos())>float(game.config.weapons[weapon].range)*1.15:fresh=false\n'
    '\t\tif fresh:return cached\n'
    '\tvar enemy=game.find_target(self,requested)\n'
    '\tharness_target={"enemy":enemy,"until":now+.30+float(absi(id.hash())%150)/1000.0,"requested":requested,"revision":game.field.revision}\n'
    '\treturn enemy\n'
    'func harness_perceived_enemy():\n'
    '\tvar contacts: Dictionary=game.human_squads.perception.get(faction,{})\n'
    '\tvar best=null;var distance: float=INF\n'
    '\tfor key in contacts:\n'
    '\t\tif not bool(contacts[key].get("visible",false)):continue\n'
    '\t\tfor enemy in game.living():\n'
    '\t\t\tif enemy.id==key and enemy.faction!=faction:\n'
    '\t\t\t\tvar d: float=pos().distance_to(enemy.pos())\n'
    '\t\t\t\tif d<distance:best=enemy;distance=d\n'
    '\treturn best\n'
)
