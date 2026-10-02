"""Keep engine avoidance near the selected destination's physical shortest route.

This patches session copies only. It does not choose another region or reject a
model-selected destination. Real terrain and temporary gun obstacles remain hard
constraints; risk and teammate proximity may only add a small travel detour.
"""


def patch(source: str) -> str:
    changes = [
        (
            'nav.set_point_weight_scale(id,restored[id]+12)',
            # Teammates are transient local traffic, not a reason to leave the
            # engagement area. Physical separation remains in unit steering.
            'nav.set_point_weight_scale(id,restored[id]+2)',
        ),
        (
            '\tvar result: PackedVector2Array=nav.get_point_path(start,nearest(dest))\n'
            '\tfor id in blocked_cells:nav.set_point_solid(id,false)',
            '\tvar finish:=nearest(dest)\n'
            '\tvar result: PackedVector2Array=nav.get_point_path(start,finish)\n'
            '\t# Cheap lower bound avoids a second search for already short routes.\n'
            '\tif not result.is_empty() and route_length(result)>harness_navigation_limit(to_world(start).distance_to(to_world(finish))):\n'
            '\t\ttactical_profile.detour_checks=int(tactical_profile.get("detour_checks",0))+1\n'
            '\t\t# Use the unweighted terrain graph with the SAME temporary hard\n'
            '\t\t# obstacles. Never fall back through a field gun or closed passage.\n'
            '\t\tvar temporary: Array=[]\n'
            '\t\tfor id in blocked_cells:\n'
            '\t\t\tif not grid.is_point_solid(id):grid.set_point_solid(id);temporary.append(id)\n'
            '\t\tpath_queries+=1\n'
            '\t\tvar shortest: PackedVector2Array=grid.get_point_path(start,finish)\n'
            '\t\tfor id in temporary:grid.set_point_solid(id,false)\n'
            '\t\tif not shortest.is_empty() and route_length(result)>harness_navigation_limit(route_length(shortest)):\n'
            '\t\t\tresult=shortest\n'
            '\t\t\ttactical_profile.detour_fallbacks=int(tactical_profile.get("detour_fallbacks",0))+1\n'
            '\tfor id in blocked_cells:nav.set_point_solid(id,false)',
        ),
    ]
    for before, after in changes:
        count = source.count(before)
        if count == 0:
            continue
        if count != 1:
            raise RuntimeError('Unsupported bounded navigation anchor: ' + before[:80])
        source = source.replace(before, after, 1)
    return source + '''
# Physical path length is authoritative; this budget only limits soft avoidance.
# Intermediate region destinations selected by JEV remain separate destinations.
func harness_navigation_limit(shortest_length: float) -> float:
	return shortest_length+clampf(shortest_length*.35,.06,.18)
'''
