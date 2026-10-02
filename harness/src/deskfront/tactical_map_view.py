"""A compact, read-only top-down map of sampled Deskfront state.

One display cell may contain many native navigation samples. The map shows
where observations exist, not whether an entire display cell is walkable,
safe, visible, or inside weapon range.
"""
import math


def _number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def _point(value):
    return isinstance(value,(list,tuple)) and len(value)==2 and all(_number(v) for v in value)


def _bounds(value):
    return (isinstance(value,(list,tuple)) and len(value)==4 and all(_number(v) for v in value)
            and value[2]>value[0] and value[3]>value[1])


def _unit_order(unit):
    name=str(unit.get('id',''))
    tail=name.rsplit('-',1)[-1]
    return (int(tail) if tail.isdigit() else math.inf,name)


def build(state,max_cols=40,max_rows=32):
    """Render the full sampled extent in at most 40 columns by 32 rows."""
    max_cols=max(1,min(40,int(max_cols)))
    max_rows=max(1,min(32,int(max_rows)))
    topology=state.get('strategic_topology') or {}
    samples=[p for p in topology.get('cells',{}).values() if _point(p)]
    living=[u for u in state.get('units',[]) if u.get('hp',0)>0 and _point(u.get('position'))]
    covers=[c for c in state.get('covers',[]) if c.get('alive',True) and _point(c.get('position'))]
    flag=state.get('objective',{}).get('position')
    flag=flag if _point(flag) else None
    original=state.get('bounds') if _bounds(state.get('bounds')) else None
    native_bounds=topology.get('bounds') if _bounds(topology.get('bounds')) else None
    all_points=samples+[u['position'] for u in living]+[c['position'] for c in covers]+([flag] if flag else [])
    if original:
        xmin,zmin,xmax,zmax=original
    elif native_bounds:
        xmin,zmin,xmax,zmax=native_bounds
    elif all_points:
        xmin=min(p[0] for p in all_points);xmax=max(p[0] for p in all_points)
        zmin=min(p[1] for p in all_points);zmax=max(p[1] for p in all_points)
    else:
        return dict(status='no_geometry',rows=[],legend={},
                    limitation='没有边界、可通行采样或实体坐标，无法绘制地图')
    if native_bounds:
        xmin=min(xmin,native_bounds[0]);zmin=min(zmin,native_bounds[1])
        xmax=max(xmax,native_bounds[2]);zmax=max(zmax,native_bounds[3])
    if all_points:
        xmin=min(xmin,min(p[0] for p in all_points));zmin=min(zmin,min(p[1] for p in all_points))
        xmax=max(xmax,max(p[0] for p in all_points));zmax=max(zmax,max(p[1] for p in all_points))
    step=topology.get('step',.075)
    step=step if _number(step) and step>0 else .075
    if xmax<=xmin:xmin-=step/2;xmax+=step/2
    if zmax<=zmin:zmin-=step/2;zmax+=step/2
    size=max((xmax-xmin)/max_cols,(zmax-zmin)/max_rows,step)
    cols=min(max_cols,max(1,math.ceil((xmax-xmin)/size)))
    rows=min(max_rows,max(1,math.ceil((zmax-zmin)/size)))
    canvas=[['?']*cols for _ in range(rows)]

    def cell(point):
        col=min(cols-1,max(0,math.floor((point[0]-xmin)/size)))
        row=min(rows-1,max(0,math.floor((point[1]-zmin)/size)))
        return row,col

    for point in samples:
        row,col=cell(point);canvas[row][col]='.'
    for cover in covers:
        row,col=cell(cover['position']);canvas[row][col]='#'
    flag_cell=None
    if flag:
        flag_cell=cell(flag);canvas[flag_cell[0]][flag_cell[1]]='F'

    greens=sorted((u for u in living if u.get('faction')=='green'),key=_unit_order)
    reds=sorted((u for u in living if u.get('faction')=='red'),key=_unit_order)
    other=sorted((u for u in living if u.get('faction') not in ('green','red')),key=_unit_order)
    symbols={};legend={'.':'格内至少有一个原生可通行采样点',
                       '?':'未采样或不可通行，无法区分',
                       '#':'掩体中心，非精确占地','F':'旗点/目标中心',
                       '*':'多个单位落在同一显示格，见 stacked_units'}
    for group,glyphs in ((greens,'123456789'),(reds,'ABCDEGHIJKLMNOPQRSTUVWXYZ')):
        for unit,glyph in zip(group,glyphs):
            symbols[unit['id']]=glyph;legend[glyph]=unit['id']
    unlabeled=[u for u in greens+reds+other if u['id'] not in symbols]
    for unit in unlabeled:symbols[unit['id']]='@'
    if unlabeled:legend['@']='未分配单独字母的单位，见 other_units'
    stacks={}
    for unit in greens+reds+other:
        row,col=cell(unit['position']);key=(row,col)
        stacks.setdefault(key,[]).append(unit['id'])
        canvas[row][col]=symbols.get(unit['id'],'@') if len(stacks[key])==1 else '*'
    stacked=[dict(row=row,col=col,unit_ids=ids) for (row,col),ids in sorted(stacks.items()) if len(ids)>1]
    rendered=[''.join(line) for line in canvas]
    return dict(status='ready' if samples else 'partial_no_navigation_samples',
                rows=rendered,cols=cols,row_count=rows,
                bounds=[round(v,4) for v in (xmin,zmin,xmax,zmax)],
                cell_size_world=round(size,4),
                axis='列从左到右为 +x；行从上到下为 +z；第0行/列对应边界最小值。坐标朝向是世界坐标，不是摄像机画面。',
                legend=legend,stacked_units=stacked[:8],
                omitted_stacks=max(0,len(stacked)-8),
                flag_under_unit=bool(flag_cell and flag_cell in stacks),
                bounds_expanded=bool(original and (xmin<original[0] or zmin<original[1] or
                                                   xmax>original[2] or zmax>original[3])),
                other_units=[u['id'] for u in unlabeled],
                limitation='等比例粗网格：. 仅表明格内存在可通行采样点；? 同时包含未采样和障碍。# 只标掩体中心。覆盖符号不改变底层地形；无法从此图推断精确路线、射界、射程或安全。')
