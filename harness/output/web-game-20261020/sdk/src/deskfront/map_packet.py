"""Map-first provider representation. Pure formatting; no tactical selection.

Facts can be expanded exactly for audits. Terrain is an overview, while native
connectivity/fire checks remain the authority. Existing IDs stay unchanged.
"""
import copy
import json
import math
from merged_map import build as merged_map


def _size(value):
    return len(json.dumps(value,ensure_ascii=False,separators=(',',':')))


def _pack(rows):
    columns=list(dict.fromkeys(k for row in rows for k in row))
    # Presence mask distinguishes missing from explicit null, false and zero.
    values=[[copy.deepcopy(row.get(k)) for k in columns] for row in rows]
    missing={str(i):[j for j,k in enumerate(columns) if k not in row]
             for i,row in enumerate(rows) if any(k not in row for k in columns)}
    return dict(columns=columns,rows=values,**({'missing':missing} if missing else {}))


def _unpack(table):
    return [{k:copy.deepcopy(v) for j,(k,v) in enumerate(zip(table['columns'],row))
             if j not in table.get('missing',{}).get(str(i),[])}
            for i,row in enumerate(table['rows'])]


def _cell(point,grid):
    if not isinstance(point,(list,tuple)) or len(point)!=2:return None
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in point):return None
    x0,z0,x1,z1=grid['bounds'];size=grid['cell_size_world']
    if not (x0<=point[0]<=x1 and z0<=point[1]<=z1):return None
    return (min(grid['row_count']-1,int((point[1]-z0)/size)),
            min(grid['cols']-1,int((point[0]-x0)/size)))


def project(context):
    """Render markers beside terrain rows and compact repeated fact schemas."""
    result=copy.deepcopy(context)
    terrain=result.get('tactical_map',{}).get('overview',{})
    if not (isinstance(terrain,dict) and terrain.get('rows') and
            terrain.get('cell_size_world',0)>0 and terrain.get('bounds')):
        return result
    if result['tactical_map'].get('format') in ('map-first/v1','merged-symbols/v1'):return result
    from combat_prompt import route_facts
    merged=merged_map(result,terrain,route_facts)
    terrain.pop('rows')
    terrain['diagram']=merged.pop('diagram')
    result['tactical_map']['merged']=merged
    result['tactical_map']['format']='merged-symbols/v1'
    # The same coordinates/checks are retained once per row, field names once
    # per table. Small/irregular collections remain ordinary objects.
    paths=[('tactical_map','region_graph'),('tactical_map','local_hard_covers'),
           ('regions',),('candidate_sites',)]
    for path in paths:
        parent=result
        for key in path[:-1]:parent=parent[key]
        key=path[-1];collection=parent.get(key)
        if not collection:continue
        keyed=isinstance(collection,dict)
        rows=list(collection.values()) if keyed else collection
        if not all(isinstance(row,dict) for row in rows):continue
        table=_pack(rows)
        if keyed:table['keys']=list(collection)
        if _size(table)<_size(collection):parent[key]=table
    return result


def expand(context):
    """Diagnostic decoder: recover every original fact, including unknowns."""
    result=copy.deepcopy(context)
    packet=result.get('tactical_map',{})
    format=packet.get('format')
    if format not in ('map-first/v1','merged-symbols/v1'):return result
    packet.pop('format');packet.pop('merged',None)
    terrain=packet['overview']
    lines=[line.split('|',2)[1] for line in terrain.pop('diagram').splitlines()]
    terrain['rows']=[''.join(token[0] for token in line.split()) for line in lines] if format=='merged-symbols/v1' else lines
    for path in [('tactical_map','region_graph'),('tactical_map','local_hard_covers'),
                 ('regions',),('candidate_sites',)]:
        parent=result
        for key in path[:-1]:parent=parent[key]
        key=path[-1];table=parent.get(key)
        if isinstance(table,dict) and 'columns' in table and 'rows' in table:
            rows=_unpack(table)
            parent[key]=dict(zip(table['keys'],rows)) if 'keys' in table else rows
    return result


def preview(context,role):
    """Old recorded request -> current display preview, never rewrite a log."""
    if context.get('tactical_map',{}).get('format')=='deskfront-coordinates/v1':
        return dict(state=copy.deepcopy(context),diagram=context['tactical_map']['diagram'],
                    beforeChars=_size(context),afterChars=_size(context),savedPercent=0,
                    note='这是日志保存的实际坐标版输入；未重写历史记录。')
    from combat_prompt import model_view
    baseline=model_view(expand(context),role,map_first=False)
    current=project(baseline)
    before,after=_size(baseline),_size(current)
    # Historical coarse maps can be re-drawn only from geometry recorded in
    # that same request. Do not load today's topology or infer new walk points.
    display=copy.deepcopy(baseline)
    packet=display.get('tactical_map',{});grid=packet.get('overview',{})
    legacy=isinstance(grid,dict) and 'rows' in grid and '中心' in grid.get('legend',{}).get('#','')
    if legacy and grid.get('cell_size_world',0)>0:
        from tactical_map_view import _footprint,_overlap
        canvas=[list(line.replace('#','o')) for line in grid['rows']]
        x0,z0,x1,z1=grid['bounds'];size=grid['cell_size_world']
        for cover in packet.get('local_hard_covers',[]):
            box=_footprint(dict(cover,kind='hard'))
            if not box:continue
            c0=max(0,math.floor((min(p[0] for p in box)-x0)/size));c1=min(grid['cols']-1,math.floor((max(p[0] for p in box)-x0)/size))
            r0=max(0,math.floor((min(p[1] for p in box)-z0)/size));r1=min(grid['row_count']-1,math.floor((max(p[1] for p in box)-z0)/size))
            for row in range(r0,r1+1):
                for col in range(c0,c1+1):
                    ch=canvas[row][col]
                    if ch in '.?:o#' and _overlap(box,x0+col*size,z0+row*size,size):
                        canvas[row][col]=':' if ch in '.:' else '#'
        grid['rows']=[''.join(line) for line in canvas]
        grid['legend'].update({'#':'记录中的硬障碍占地相交',':':'障碍与通行采样混合边界','o':'旧图仅记录的掩体中心','?':'通行证据不足'})
    if role=='personal' and isinstance(grid,dict) and grid.get('rows'):
        unit=display.get('self',{});cell=_cell(unit.get('position'),grid)
        if cell and unit.get('id'):
            row,col=cell;canvas=[list(line) for line in grid['rows']];canvas[row][col]='我'
            grid['rows']=[''.join(line) for line in canvas];grid['legend']['我']=unit['id']
    displayed=project(display)
    return dict(state=current,diagram=current.get('tactical_map',{}).get('overview',{}).get('diagram',''),
                displayDiagram=displayed.get('tactical_map',{}).get('overview',{}).get('diagram',''),
                terrainReconstructed=legacy,
                beforeChars=before,afterChars=after,savedPercent=round((1-after/before)*100,1) if before else 0,
                note='输入压缩统计保留日志地形原样；新版墙形另用同次请求的障碍尺寸重画。二者明确分开，不改写旧日志、不加载当前场景冒充历史现场。字符数不是服务商token；查看页不调用模型。')
