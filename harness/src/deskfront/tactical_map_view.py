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


def _footprint(cover):
    """Godot's oriented physical x/z box, never the navigation AABB."""
    if cover.get('kind') != 'hard':return None
    ray=cover.get('ray_size')
    size=[ray[0],ray[2]] if isinstance(ray,(list,tuple)) and len(ray)==3 else cover.get('size')
    if not _point(size) or min(size)<=0:return None
    yaw=cover.get('yaw',0) or 0
    if not _number(yaw):return None
    cx,cz=cover['position'];c=math.cos(yaw);s=math.sin(yaw)
    return [(cx+c*x+s*z,cz-s*x+c*z) for x,z in
            [(-size[0]/2,-size[1]/2),(size[0]/2,-size[1]/2),
             (size[0]/2,size[1]/2),(-size[0]/2,size[1]/2)]]


def _overlap(box,x0,z0,size):
    """Separating axes: positive area overlap, not mere edge contact."""
    tile=[(x0,z0),(x0+size,z0),(x0+size,z0+size),(x0,z0+size)]
    axes=[(1,0),(0,1)]+[(box[(i+1)%4][1]-box[i][1],
                         box[i][0]-box[(i+1)%4][0]) for i in (0,1)]
    for ax,az in axes:
        a=[x*ax+z*az for x,z in box];b=[x*ax+z*az for x,z in tile]
        if min(max(a),max(b))-max(min(a),min(b))<=1e-10:return False
    return True


def build(state,max_cols=40,max_rows=32,*,fixed_grid=False):
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
    footprints=[box for cover in covers if (box:=_footprint(cover))]
    all_points=samples+[u['position'] for u in living]+[c['position'] for c in covers]+([flag] if flag else [])
    all_points += [list(p) for box in footprints for p in box]
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
    if fixed_grid:
        # Stable global display coordinates across roles and world expansion.
        size=.15
        xmin=math.floor(xmin/size)*size;zmin=math.floor(zmin/size)*size
        cols=max(1,math.ceil((xmax-xmin)/size));rows=max(1,math.ceil((zmax-zmin)/size))
        focus=next((u['position'] for u in living if u['id']==state.get('self_id')),None)
        if focus is None and living:focus=[sum(u['position'][i] for u in living)/len(living) for i in range(2)]
        if cols>80:
            xmin=max(xmin,math.floor(((focus or [xmin,zmin])[0]/size)-40)*size);cols=80
        if rows>48:
            zmin=max(zmin,math.floor(((focus or [xmin,zmin])[1]/size)-24)*size);rows=48
        xmax=xmin+cols*size;zmax=zmin+rows*size
    canvas=[['?']*cols for _ in range(rows)]

    def cell(point):
        col=min(cols-1,max(0,math.floor((point[0]-xmin)/size)))
        row=min(rows-1,max(0,math.floor((point[1]-zmin)/size)))
        return row,col

    def inside(point):return xmin<=point[0]<xmax and zmin<=point[1]<zmax
    outside_units=[u['id'] for u in living if not inside(u['position'])] if fixed_grid else []
    if fixed_grid:living=[u for u in living if inside(u['position'])]
    for point in samples:
        if fixed_grid and not inside(point):continue
        row,col=cell(point);canvas[row][col]='.'
    for box in footprints:
        r0,c0=cell([min(p[0] for p in box),min(p[1] for p in box)])
        r1,c1=cell([max(p[0] for p in box),max(p[1] for p in box)])
        for row in range(r0,r1+1):
            for col in range(c0,c1+1):
                if _overlap(box,xmin+col*size,zmin+row*size,size):
                    canvas[row][col]=':' if canvas[row][col] in ('.',':') else '#'
    for cover in covers:
        if not _footprint(cover):
            if fixed_grid and not inside(cover['position']):continue
            row,col=cell(cover['position'])
            if canvas[row][col] not in ('#',':'):canvas[row][col]='o'
    flag_cell=None
    if flag and (not fixed_grid or inside(flag)):
        flag_cell=cell(flag);canvas[flag_cell[0]][flag_cell[1]]='F'

    greens=sorted((u for u in living if u.get('faction')=='green'),key=_unit_order)
    reds=sorted((u for u in living if u.get('faction')=='red'),key=_unit_order)
    other=sorted((u for u in living if u.get('faction') not in ('green','red')),key=_unit_order)
    symbols={};legend={'.':'格内至少有一个原生可通行采样点',
                       '?':'没有可通行采样或已知硬障碍占地证据，通行未知',
                       '#':'已知硬障碍占地与此格相交，不代表整格封闭',
                       ':':'此格既有硬障碍占地也有可通行采样，属于混合边界',
                       'o':'非硬障碍或缺少尺寸的掩体中心','F':'旗点/目标中心',
                       '*':'多个单位落在同一显示格，见 stacked_units'}
    for group,glyphs in ((greens,'123456789'),(reds,'ABCDEGHIJKLMNOPQRSTUVWXYZ')):
        for unit,glyph in zip(group,glyphs):
            symbols[unit['id']]=glyph;legend[glyph]=unit['id']
    unlabeled=[u for u in greens+reds+other if u['id'] not in symbols]
    for unit in unlabeled:symbols[unit['id']]='@'
    if unlabeled:legend['@']='未分配单独字母的单位，见 other_units'
    self_id=state.get('self_id')
    self_unit=next((u for u in living if u['id']==self_id),None)
    if self_unit:
        old=symbols[self_id]
        if old!='@':legend.pop(old,None)
        symbols[self_id]='我'
        legend['我']=self_id
    stacks={}
    for unit in greens+reds+other:
        row,col=cell(unit['position']);key=(row,col)
        stacks.setdefault(key,[]).append(unit['id'])
        canvas[row][col]=symbols.get(unit['id'],'@') if len(stacks[key])==1 else '*'
    if self_unit:
        row,col=cell(self_unit['position'])
        canvas[row][col]='我'
    stacked=[dict(row=row,col=col,unit_ids=ids) for (row,col),ids in sorted(stacks.items()) if len(ids)>1]
    rendered=[''.join(line) for line in canvas]
    result=dict(status='ready' if samples else 'partial_no_navigation_samples',
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
                limitation='等比例粗网格：# 绘制实际硬障碍占地，: 是障碍与通行采样共存的边界格，? 仅表示证据不足。单位覆盖符号不改变底层地形；窄入口可能小于一格，连接以region_graph为准。无法从此图推断精确路线、射界、射程或安全。')
    if self_unit:
        row,col=cell(self_unit['position'])
        result['self']=dict(unit_id=self_id,symbol='我',row=row,col=col,
                           co_located_unit_ids=[uid for uid in stacks[(row,col)] if uid!=self_id])
        result['limitation']+=' 我是本次个人模型控制的士兵，原始ID见self.unit_id；与其他单位同格时仍显示我，同格成员见self.co_located_unit_ids。每个字符是一格，不能按字体显示宽度换算距离。'
    if fixed_grid:
        result['outside_units']=outside_units
        result['grid_origin']=[round(xmin/size),round(zmin/size)]
        result['coordinate_frame']='global-display-grid/v1'
    return result
