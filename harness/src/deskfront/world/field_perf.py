"""Session-copy battlefield performance: cover buckets, local rebuild cells, shared resources."""


def once(source, before, after):
    count = source.count(before)
    if count == 0:
        return source
    if count != 1:
        raise RuntimeError('Unsupported field perf anchor: '+before[:80])
    return source.replace(before, after, 1)


def patch(source):
    # Share materials; identical colors previously created one StandardMaterial3D each.
    source=once(source,
        'func mat(color: Color, roughness: float = 0.8) -> StandardMaterial3D:\n\tvar m := StandardMaterial3D.new()',
        'func mat(color: Color, roughness: float = 0.8) -> StandardMaterial3D:\n\tvar key: String=str(color)+"|"+str(roughness)\n\tvar cached=harness_mat_cache.get(key)\n\tif cached is StandardMaterial3D:return cached\n\tif harness_mat_cache.size()>64:harness_mat_cache.clear()\n\tvar m := StandardMaterial3D.new()\n\tharness_mat_cache[key]=m')
    # Share BoxMesh resources across cubes of the same size.
    source=once(source,
        '\tvar mesh := MeshInstance3D.new()\n\tvar box := BoxMesh.new()\n\tbox.size = size',
        '\tvar mesh := MeshInstance3D.new()\n\tvar box=harness_box_cache.get(size)\n\tif box==null:\n\t\tbox=BoxMesh.new();box.size=size;harness_box_cache[size]=box')
    # Mark only the cells a cover can actually occupy instead of scanning the whole grid per cover.
    source=once(source,
        '\t\tvar center := Vector2(c.position[0],c.position[1])\n\t\tvar half := Vector2(c.size[0],c.size[1])/2 + Vector2.ONE*.018\n\t\tfor x in range(grid.region.size.x):\n\t\t\tfor y in range(grid.region.size.y):\n\t\t\t\tvar pos := to_world(Vector2i(x,y))',
        '\t\tvar center := Vector2(c.position[0],c.position[1])\n\t\tvar half := Vector2(c.size[0],c.size[1])/2 + Vector2.ONE*.018\n\t\tvar extent: Vector2=half+Vector2.ONE*.075\n\t\tvar cover_lo: Vector2i=to_cell(center-extent)+Vector2i(-1,-1)\n\t\tvar cover_hi: Vector2i=to_cell(center+extent)+Vector2i(1,1)\n\t\tfor x in range(maxi(0,cover_lo.x),mini(grid.region.size.x,cover_hi.x+1)):\n\t\t\tfor y in range(maxi(0,cover_lo.y),mini(grid.region.size.y,cover_hi.y+1)):\n\t\t\t\tvar pos := to_world(Vector2i(x,y))')
    # Ray queries only test covers whose buckets the segment can touch.
    source=once(source,
        'func trace_cover(a: Vector3,b: Vector3,ignore: String="") -> Dictionary:\n\tray_queries+=1\n\tvar best: Dictionary={}\n\tfor c in covers:\n\t\tif not c.alive or c.id==ignore:continue',
        'func trace_cover(a: Vector3,b: Vector3,ignore: String="") -> Dictionary:\n\tray_queries+=1\n\tvar best: Dictionary={}\n\tfor c in harness_covers_near(Vector2(a.x,a.z),Vector2(b.x,b.z)):\n\t\tif not c.alive or c.id==ignore:continue')
    source=once(source,
        '\tfor o in obstacles:\n\t\tif covers.any(func(c):return c.id=="hard_"+o.id):continue',
        '\tfor o in harness_obstacle_list:')
    # Protection checks only consider covers near the body-attacker segment.
    source=once(source,
        'func protection(p: Vector2, attacker: Vector2) -> float:\n\tfor c in covers:\n\t\tif not c.alive: continue',
        'func protection(p: Vector2, attacker: Vector2) -> float:\n\tfor c in harness_covers_near(p,attacker):\n\t\tif not c.alive: continue')
    source+='\n'+HELPERS
    return source


HELPERS = (
    'var harness_mat_cache: Dictionary={}\n'
    'var harness_box_cache: Dictionary={}\n'
    'var harness_cover_buckets: Dictionary={}\n'
    'var harness_cover_built: int=-1\n'
    'var harness_cover_pad: float=.2\n'
    'var harness_obstacle_list: Array=[]\n'
    'func harness_bucket(p: Vector2) -> Vector2i:\n'
    '\treturn Vector2i(floori(p.x/.15),floori(p.y/.15))\n'
    'func harness_index_covers() -> void:\n'
    '\tharness_cover_buckets.clear()\n'
    '\tharness_cover_pad=.05\n'
    '\tfor c in covers:\n'
    '\t\tif not c.get("alive",true):continue\n'
    '\t\tvar radius: float=Vector2(float(c.size[0]),float(c.size[1])).length()*.5\n'
    '\t\tharness_cover_pad=maxf(harness_cover_pad,radius)\n'
    '\t\tvar center:=Vector2(c.position[0],c.position[1])\n'
    '\t\tvar lo: Vector2i=harness_bucket(center-Vector2.ONE*radius)\n'
    '\t\tvar hi: Vector2i=harness_bucket(center+Vector2.ONE*radius)\n'
    '\t\tfor bx in range(lo.x,hi.x+1):\n'
    '\t\t\tfor by in range(lo.y,hi.y+1):\n'
    '\t\t\t\tvar key:=Vector2i(bx,by)\n'
    '\t\t\t\tif not harness_cover_buckets.has(key):harness_cover_buckets[key]=[]\n'
    '\t\t\t\tharness_cover_buckets[key].append(c)\n'
    '\tharness_obstacle_list=[]\n'
    '\tfor o in obstacles:\n'
    '\t\tvar duplicated: bool=false\n'
    '\t\tfor c in covers:\n'
    '\t\t\tif c.id=="hard_"+o.id:duplicated=true;break\n'
    '\t\tif not duplicated:harness_obstacle_list.append(o)\n'
    '\tharness_cover_pad+=.1\n'
    '\tharness_cover_built=revision\n'
    'func harness_covers_near(a: Vector2,b: Vector2) -> Array:\n'
    '\tif harness_cover_built!=revision:harness_index_covers()\n'
    '\tvar lo: Vector2i=harness_bucket(Vector2(minf(a.x,b.x),minf(a.y,b.y))-Vector2.ONE*harness_cover_pad)\n'
    '\tvar hi: Vector2i=harness_bucket(Vector2(maxf(a.x,b.x),maxf(a.y,b.y))+Vector2.ONE*harness_cover_pad)\n'
    '\tvar result: Array=[];var seen: Dictionary={}\n'
    '\tfor bx in range(lo.x,hi.x+1):\n'
    '\t\tfor by in range(lo.y,hi.y+1):\n'
    '\t\t\tfor c in harness_cover_buckets.get(Vector2i(bx,by),[]):\n'
    '\t\t\t\tif seen.has(c.id):continue\n'
    '\t\t\t\tseen[c.id]=true;result.append(c)\n'
    '\treturn result\n'
)
