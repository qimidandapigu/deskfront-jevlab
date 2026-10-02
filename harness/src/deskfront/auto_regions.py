"""Connected local regions built only from engine-validated navigation edges."""
import math

def generate(topology, region_size=.6):
    cells=topology['cells'];adj={k:[] for k in cells}
    for a,b in topology['edges']:adj[a].append(b);adj[b].append(a)
    def tile(k):return tuple(math.floor(v/region_size) for v in cells[k])
    remaining=set(cells);regions={};owners={}
    while remaining:
        seed=min(remaining);group=[];todo=[seed];remaining.remove(seed)
        while todo:
            k=todo.pop();group.append(k)
            for n in adj[k]:
                if n in remaining and tile(n)==tile(seed):remaining.remove(n);todo.append(n)
        key='N'+seed;mean=[sum(cells[k][i] for k in group)/len(group) for i in (0,1)]
        center=cells[min(group,key=lambda k:math.dist(cells[k],mean))]
        regions[key]=dict(id=key,center=center,radius=.1,route='adaptive',neighbors=[],cells=[cells[k] for k in group],sample_step=topology.get('step',.075),cell_count=len(group),walkability='native_sampled',purpose='原生通行检测后按连通性分区；仍需检查射界')
        for k in group:owners[k]=key
    for a,b in topology['edges']:
        x,y=owners[a],owners[b]
        if x!=y:
            if y not in regions[x]['neighbors']:regions[x]['neighbors'].append(y)
            if x not in regions[y]['neighbors']:regions[y]['neighbors'].append(x)
    return regions,owners
