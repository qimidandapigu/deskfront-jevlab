"""One symbolic map from recorded facts. Never selects routes or actions."""
import math


def build(context, grid, route_facts):
    rows=grid['rows'];height=len(rows);width=grid['cols']
    x0,z0,x1,z1=grid['bounds'];size=grid['cell_size_world']
    marks={};legend={};types={};outside=[]
    def cell(point):
        if not isinstance(point,(list,tuple)) or len(point)!=2:return None
        if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in point):return None
        if not (x0<=point[0]<=x1 and z0<=point[1]<=z1):return None
        return min(height-1,int((point[1]-z0)/size)),min(width-1,int((point[0]-x0)/size))
    def put(symbol,kind,id,point=None,at=None,**facts):
        facts={key:value for key,value in facts.items() if value is not None}
        legend[symbol]=dict(id=id,**facts) if facts else id
        types[symbol]=kind
        where=at if at is not None else cell(point)
        if where is None:outside.append(symbol);return
        marks.setdefault(where,[]).append(symbol)
    packet=context['tactical_map'];graph=packet.get('region_graph',{})
    aliases={rid:row.get('symbol') or f'R{i+1}' for i,(rid,row) in enumerate(sorted(graph.items()))}
    for rid,row in graph.items():put(aliases[rid],'region_label',rid,row.get('center'))
    for i,cover in enumerate(packet.get('local_hard_covers',[])):
        if cover.get('id'):put(f'W{i+1}','hard_obstacle_label',cover['id'],cover.get('position'))
    own=context.get('self',{}).get('id') or packet.get('focus_unit_id')
    # Existing map legend and stacks are already restricted to known units.
    terrain_symbols={'.','#','?',':','o','F','*','@'}
    unit_cells={}
    for r,line in enumerate(rows):
        for c,glyph in enumerate(line):
            if glyph not in terrain_symbols and glyph in grid.get('legend',{}):
                unit_cells.setdefault(grid['legend'][glyph],(r,c))
    for stack in grid.get('stacked_units',[]):
        for uid in stack['unit_ids']:unit_cells[uid]=(stack['row'],stack['col'])
    friends={u['id'] for u in context.get('members',[]) if u.get('id')}
    if own:friends.add(own)
    reports=context.get('contacts',context.get('teammate_reports',[]))
    enemy_ids={u['id'] for u in reports if u.get('visible') and u.get('id')}
    team=context.get('faction') or (own.split('-',1)[0] if isinstance(own,str) and '-' in own else None)
    counters={'U':0,'E':0}
    for uid,where in sorted(unit_cells.items()):
        if uid==own:symbol='ME'
        else:
            prefix='E' if uid in enemy_ids or (team and isinstance(uid,str) and uid.split('-',1)[0]!=team) else 'U'
            counters[prefix]+=1;symbol=prefix+str(counters[prefix])
        put(symbol,'unit',uid,at=where)
    if own and own not in unit_cells:
        put('ME','unit',own,context.get('self',{}).get('position'))
    # No ID is renamed in actual menus/assignments. R aliases are display-only.
    for site in context.get('candidate_sites',[]):
        if site.get('id'):put(site['id'],'candidate',site['id'],site.get('position'),region=aliases.get(site.get('region_id'),site.get('region_id')))
    index=0
    for uid in context.get('member_region_choices',{}):
        for pid,route in route_facts(context,uid).items():
            index+=1;put(f'P{index}','route_endpoint',uid+'/'+pid,route.get('position'))
    for i,gun in enumerate(context.get('battlefield_equipment',[])):
        if gun.get('id'):put(f'M{i+1}','equipment',gun['id'],gun.get('position'))
    for gate in packet.get('gateways',[]):
        put(gate['symbol'],'native_region_connection',gate['id'],gate['position'],
            regions=[aliases.get(rid,rid) for rid in gate['region_ids']])
    plan=context.get('current_plan') or {};assignment=context.get('assignment') or {}
    links={}
    if plan.get('region_id'):
        links['commander_target']=dict(region=aliases.get(plan['region_id'],plan['region_id']),
                                      region_id=plan['region_id'],objective=plan.get('objective'))
        if plan.get('position') is not None:
            put('ST','commander_target',plan['region_id'],plan['position']);links['commander_target']['marker']='ST'
    if assignment:
        rid=assignment.get('target_region_id',assignment.get('region_id'))
        links['personal_assignment']=dict(region=aliases.get(rid,rid),region_id=rid,
            route=[aliases.get(r,r) for r in assignment.get('region_path',[])],
            role=assignment.get('role'),intent=assignment.get('intent'))
        if assignment.get('goal') is not None:
            put('TT','assigned_goal',rid,assignment['goal']);links['personal_assignment']['marker']='TT'
    for r,line in enumerate(rows):
        for c,glyph in enumerate(line):
            if glyph=='F' and not any(types[s] in ('commander_target','assigned_goal') for s in marks.get((r,c),[])):
                put('ST','observed_team_goal',None,at=(r,c))
    # The first character preserves the exact raster. Brackets add co-located
    # labels without deleting terrain, units, goals or other candidates.
    diagram='\n'.join(f'{r:02} |'+' '.join(glyph+('['+'/'.join(marks[(r,c)])+']' if (r,c) in marks else '')
                    for c,glyph in enumerate(line))+'|' for r,line in enumerate(rows))
    return dict(diagram=diagram,markers=legend,task_links=links,**({'outside_markers':outside} if outside else {}))
