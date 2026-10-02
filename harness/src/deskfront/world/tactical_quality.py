"""Static, auditable firing-lane estimates; not a simulation of combat outcomes."""
import math
from .region_graph import compile_graph,LIBRARY,WORKSHOP_STYLE_COUNT,validate_graph
from .fortress import apply as fortify
from .assembly import validate as validate_geometry


def clear_ray(a,b,covers,height=.068):
    for x,z,w,d,_,h in covers:
        if h<height:continue
        low,high=0.,1.
        for start,end,center,half in ((a[0],b[0],x,w/2),(a[1],b[1],z,d/2)):
            delta=end-start
            if abs(delta)<1e-9:
                if not center-half<=start<=center+half:low,high=1.,0.;break
            else:
                first,last=sorted(((center-half-start)/delta,(center+half-start)/delta))
                low=max(low,first);high=min(high,last)
        if high>=low and high>.002 and low<.998:return False
    return True


def assess(spec,enemy_count=3):
    card=spec['design_card']
    centers={k:LIBRARY['cells'][k]['open']['center'] for k in LIBRARY['cells']}
    enemies=spec['defender_slots'][:enemy_count]
    def measure(ids):
        if not ids:return None
        length=0.;samples=[]
        for first,last in zip(ids,ids[1:]):
            a,b=centers[first],centers[last];dist=math.dist(a,b);length+=dist
            for i in range(max(1,math.ceil(dist/.06))):
                t=i/max(1,math.ceil(dist/.06));samples.append([a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t])
        exposed=sum(any(math.dist(p,e[:2])<=.9 and clear_ray(p,e,spec['covers']) for e in enemies) for p in samples)
        return dict(length=round(length,2),exposed_fraction=round(exposed/max(1,len(samples)),3),samples=len(samples))
    main=measure(card['main_regions']);flank=measure(card['flank_regions'])
    contrast=abs(main['exposed_fraction']-flank['exposed_fraction']) if flank else 0
    return dict(main=main,flank=flank,route_exposure_difference=round(contrast,3),
        distinct_routes=bool(flank),basis='static standing-height rays, 0.9m range, initial defenders; not dynamic combat or actual muzzle queries')


def compositions(graph,roles,enemy_count,depth=False,rescue=False):
    # Joint candidates avoid each independently selected orientation cancelling
    # the cover relationships of its neighbours. Every returned item is playable.
    out={}
    ports={cell:0 for cell in roles}
    for edge in graph['edges']:
        a,b=edge.split('__');ax,az=int(a[1]),int(a[3]);bx,bz=int(b[1]),int(b[3])
        if a in ports:ports[a]|=1 if bx>ax else 8
        if b in ports:ports[b]|=2 if bx>ax else 4
    for variant in range(12):
        ops=[]
        for index,o in enumerate(graph['operations']):
            cell=o['cell'];module=o['module']
            if cell in roles:
                module=f'workshop_{roles[cell]}_{ports[cell]}_{(variant+index)%WORKSHOP_STYLE_COUNT}'
            ops.append(dict(o,module=module))
        ops += [dict(op='connect_regions',edge=e) for e in graph['edges']]+[dict(op='deploy',module='layered' if depth else ('rear' if variant>=6 else 'distributed'))]
        receipt=validate_graph(ops)
        if not receipt['ok']:continue
        spec=compile_graph(ops)
        if rescue:
            spec=fortify(spec,enemy_count)
            receipt=validate_geometry(spec)
            if not receipt['ok']:continue
            receipt['graph']=spec['design_card']
        quality=assess(spec,enemy_count)
        out[f'layout_{variant}']=dict(operations=ops,quality=quality,validation=receipt)
    # Preserve a few tactically credible but visually distinct choices. The
    # old .08 cutoff often left one layout, so the generator repeated it.
    ranked=sorted(out.items(),key=lambda row:-row[1]['quality']['route_exposure_difference'])
    selected={};seen=set()
    for key,row in ranked:
        difference=row['quality']['route_exposure_difference']
        if difference<.04 and selected:continue
        signature=tuple(sorted({int(op['module'].rsplit('_',1)[1]) for op in row['operations']
                                if op.get('module','').startswith('workshop_')}))
        if signature in seen:continue
        selected[key]=row;seen.add(signature)
        if len(selected)==4:break
    return selected or dict(ranked[:4])
