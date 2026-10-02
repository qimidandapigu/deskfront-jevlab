"""Stable named navigation areas derived from authored route nodes, not safe zones."""
import math

def catalog(routes,state=None):
    if state and state.get("strategic_topology"):
        from auto_regions import generate
        return generate(state["strategic_topology"])[0]
    out={}
    for lane,route in routes.items():
        prefix={'left':'L','center':'C','right':'R'}.get(lane,lane.upper())
        ids=[prefix+str(i+1) for i in range(len(route['points']))]
        for i,(key,p) in enumerate(zip(ids,route['points'])):
            out[key]=dict(id=key,name=route['name'].split('：')[0]+str(i+1),center=p,radius=.15,route=lane,index=i,neighbors=ids[max(0,i-1):i]+ids[i+1:i+2],purpose='路线集结区域；射界和安全需实时查询')
    if state and state.get('bounds'):
        x0,z0,x1,z1=state['bounds'];size=.3
        for ix in range(math.ceil(x0/size),math.ceil(x1/size)+1):
            for iz in range(math.ceil(z0/size),math.ceil(z1/size)+1):
                # World anchored cells retain IDs as the generated map expands.
                lo=[max(x0,(ix-1)*size),max(z0,(iz-1)*size)]
                hi=[min(x1,ix*size),min(z1,iz*size)]
                if hi[0]<=lo[0] or hi[1]<=lo[1]:continue
                key=f'G{ix}_{iz}'
                out[key]=dict(id=key,center=[(a+b)/2 for a,b in zip(lo,hi)],bounds=lo+hi,radius=.15,route='adaptive',walkability='unknown_requires_native_query',purpose='全图定位网格；不代表可达或安全')
    return out

def memberships(position,regions):
    return [key for key,r in regions.items() if contains(position,r)]


def navigation_anchor(position,regions,topology=None,max_distance=.12):
    """Resolve only a navigation/planning origin near a native sample gap.

    ``observed_regions`` remains strict. An anchor is not an arrival event or a
    guarantee that the unobserved bridge segment is unobstructed. The engine
    must validate that short bridge before the unit moves.
    """
    observed=memberships(position,regions)
    result=dict(observed_regions=observed,anchor_regions=list(observed),
                anchor_position=list(position) if observed else None,
                anchor_cell=None,anchor_distance=0.0 if observed else None,
                mode='observed' if observed else 'unresolved',requires_native_validation=False)
    if observed:return result
    cells=(topology or {}).get('cells',{})
    if not cells:
        # Auto regions carry native sample positions too. Never promote a
        # hand-authored region center into a supposed walkability observation.
        cells={str(tuple(p)):p for region in regions.values() for p in region.get('cells',[])}
    if not cells:return result
    nearest=min(cells,key=lambda key:(math.dist(position,cells[key]),str(key)))
    point=cells[nearest];distance=math.dist(position,point)
    if distance>min(.12,max_distance)+1e-8:return result
    owners=memberships(point,regions)
    if not owners:return result
    return dict(result,anchor_regions=owners,anchor_position=list(point),anchor_cell=nearest,
                anchor_distance=round(distance,6),mode='nearby_native_sample',requires_native_validation=True)


def contains(position,region):
    if 'cells' in region:
        half=region.get('sample_step',.075)/2+1e-6
        return any(abs(position[0]-p[0])<=half and abs(position[1]-p[1])<=half for p in region['cells'])
    if 'bounds' in region:
        a,b,c,d=region['bounds'];return a<=position[0]<=c and b<=position[1]<=d
    return math.dist(position,region['center'])<=region['radius']


def model_catalog(regions):
    return {key:{k:r[k] for k in ('center','neighbors') if k in r} for key,r in regions.items()}
