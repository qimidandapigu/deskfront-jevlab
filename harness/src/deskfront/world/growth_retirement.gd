extends RefCounted
## Bounded region retirement for infinite growth.
## Keeps the active route and occupied ground intact before unloading old art.

func retire(growth):
	var game=growth.game
	growth.retirement_blocked=false
	if growth.active_regions.size()<=growth.KEEP_BUILT_REGIONS:return
	while growth.active_regions.size()>growth.KEEP_BUILT_REGIONS:
		var oldest=growth.active_regions[0];var cutoff:float=oldest.right
		for u in game.living():
			if u.pos().x<cutoff+.12:
				growth.retirement_blocked=true;return
			if not u.route.is_empty():
				if u.goal.x<cutoff+.12:growth.retirement_blocked=true;return
				for point in u.route:
					if point.x<cutoff+.12:growth.retirement_blocked=true;return
		for tile in oldest.tiles:
			if is_instance_valid(tile):tile.queue_free()
		for collection in [game.field.covers,game.field.obstacles]:
			for i in range(collection.size()-1,-1,-1):
				var item=collection[i]
				if float(item.position[0])<cutoff:
					if is_instance_valid(item.get("node")):item.node.queue_free()
					collection.remove_at(i)
		for i in range(game.units.size()-1,-1,-1):
			var u=game.units[i]
			if u.hp<=0 and u.pos().x<cutoff:
				game.units.remove_at(i);u.queue_free()
		growth.active_regions.pop_front();growth.retired_regions+=1
		growth.desk_panels=growth.desk_panels.filter(func(panel):return is_instance_valid(panel) and not oldest.tiles.has(panel))
		game.config.world_floor_regions=game.config.world_floor_regions.filter(func(r):return r.right>cutoff)
		game.config.bounds[0]=cutoff
		game.field.base=Vector2(cutoff,game.config.bounds[1])
		game.field.reservations.clear();game.field.slot_cache.clear();game.field.reserved_positions.clear();game.field.unavailable_until.clear()
		var moving:Array=[]
		for u in game.living():
			if not u.route.is_empty():moving.append({"unit":u,"goal":u.goal})
			u.route.clear()
		game.field.rebuild()
		for row in moving:row.unit.move_to(row.goal)
		if growth.harness_green:game.control_epochs.green+=1
		while growth.completed.size()>6:growth.completed.pop_front()
		game.add_event("后方区域已卸载："+str(oldest.index))
