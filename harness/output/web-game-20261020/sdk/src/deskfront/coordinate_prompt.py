"""Provider-only coordinate protocol. The binding stays local to each request.

Models select verified map coordinates; native IDs and exact original positions
remain in the controller. Decoding never snaps an invented coordinate to a point.
"""
import copy
import json
import math
import re
from collections import Counter

from map_packet import expand, _pack, _size
from combat_prompt import route_facts

VERSION = 'deskfront-coordinates/v1'

GUIDE = '''\n# 统一地图坐标协议（取代上文区域编号输出）
地图右+x、下+y；(x,y)是列、行，可用小数表达格内精确落点。所有position/center/goal/route_positions均用本图坐标；不使用Godot坐标。当前帧的图原点见origin，地图扩展不重编号。历史日志的legacy_frame只在该次请求内有效。
regions的键是可选目标坐标，不是R编号；区域连通仅是后台导航事实，中心可达不保证任意点可达。路线选项直接写终点坐标；同一终点的不同通路带/via1等后缀，必须比较region_path。个人选项直接写动作:坐标:目标。不能凭图创造未列出的落点。
地图##是硬障碍占地，::是障碍与通行采样混合边界，??是证据不足；单位符号覆盖的地形见under_units。坐标到达不等于能开火，仍要看原生fire_checks、endpoint_obstructions。未验证不能当通畅。
shared_facts中保存完全相同的重复事实，{"ref":数字}引用对应项，不代表未知。除位置、地图几何size外，其余距离/射程数值保留同一原生长度单位，可乘distance_to_cells换成格数。
指挥plan及tactical_brief.steps中的区域都用"destination":[x,y]替代region_id，仅选regions列出的目标；若同坐标有多个任务范围，destination用完整坐标字符串含/area后缀，其他字段不变。tactical_brief仅实体步骤可省略destination。小队和个人选择本次questions的坐标选项。实体ID仍用于指定攻击、操炮和成员身份。
'''


def _json(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def _point(value):
    return isinstance(value,(tuple,list)) and len(value)==2 and all(
        isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in value)


def _clean(number):
    return int(round(number)) if abs(number-round(number))<.00001 else round(number,3)


def label(point):
    return '('+','.join(str(_clean(v)) for v in point)+')'


def share(value):
    """Deduplicate repeated structured facts, retaining all false/empty/unknowns."""
    counts=Counter()
    def scan(v):
        if isinstance(v,(dict,list)):
            text=_json(v)
            if len(text)>=100:counts[text]+=1
            for child in (v.values() if isinstance(v,dict) else v):scan(child)
    scan(value); refs={}; facts=[]
    def visit(v):
        if isinstance(v,(dict,list)):
            text=_json(v)
            if counts[text]>1:
                if text not in refs:
                    refs[text]=len(facts);facts.append(copy.deepcopy(v))
                return {'ref':refs[text]}
            return {k:visit(x) for k,x in v.items()} if isinstance(v,dict) else [visit(x) for x in v]
        return v
    result=visit(value)
    if facts:result['shared_facts']=facts
    return result


def unshare(context):
    facts=context.get('shared_facts',[])
    def visit(v):
        if isinstance(v,dict):
            if list(v)==['ref']:return copy.deepcopy(facts[v['ref']])
            return {k:visit(x) for k,x in v.items() if k!='shared_facts'}
        if isinstance(v,list):return [visit(x) for x in v]
        return v
    return visit(context)


def inspect_state(context):
    """Readable coordinate facts, without changing the saved provider request."""
    from map_packet import _unpack
    state=unshare(context)
    for parent,key in [(state,'regions'),(state,'candidate_sites'),(state.get('tactical_map',{}),'local_hard_covers')]:
        table=parent.get(key)
        if isinstance(table,dict) and 'columns' in table and 'rows' in table:
            rows=_unpack(table);parent[key]=dict(zip(table['keys'],rows)) if 'keys' in table else rows
    return state


class Binding:
    def __init__(self,grid):
        self.grid=grid;self.regions={};self.choices={};self.region_aliases={}
        self.size=grid['cell_size_world']
        self.fixed=grid.get('coordinate_frame')=='global-display-grid/v1'
        self.base=[0,0] if self.fixed else grid['bounds'][:2]

    def xy(self,p):
        return [_clean((p[i]-self.base[i])/self.size) for i in range(2)]

    def decode(self,response):
        result=copy.deepcopy(response)
        answers=result.get('answers',{})
        if 'plan' in answers:
            value=answers['plan'].get('value',{})
            destination=value.pop('destination',None)
            if not (_point(destination) or isinstance(destination,str)):raise ValueError('coordinate_destination_required')
            key=label(destination) if _point(destination) else destination
            if key not in self.regions:raise ValueError('coordinate_destination_not_offered')
            value['region_id']=self.regions[key]
            brief=value.get('tactical_brief')
            if isinstance(brief,dict) and isinstance(brief.get('steps'),list):
                valid=True
                for step in brief['steps']:
                    if not isinstance(step,dict):valid=False;break
                    if 'destination' not in step:continue
                    destination=step.pop('destination')
                    key=label(destination) if _point(destination) else destination if isinstance(destination,str) else None
                    if key not in self.regions:valid=False;break
                    step['region_id']=self.regions[key]
                if not valid:value.pop('tactical_brief',None)
        for name,mapping in self.choices.items():
            answer=answers.get(name)
            if answer is None:continue  # Existing admission validates required answers.
            if answer.get('choice') not in mapping:raise ValueError('coordinate_choice_not_offered:'+name)
            answer['choice']=mapping[answer['choice']]
            if isinstance(answer.get('probabilities'),dict):
                answer['probabilities']={mapping.get(k,k):v for k,v in answer['probabilities'].items()}
        return result


def prepare(context,questions,role):
    """Return actual wire context/questions plus a private answer binding."""
    if context.get('prompt_contract',{}).get('version')==VERSION:
        return copy.deepcopy(context),copy.deepcopy(questions),None
    source=expand(context);grid=source.get('tactical_map',{}).get('overview',{})
    if not grid.get('rows') or not grid.get('cell_size_world'):return source,copy.deepcopy(questions),None
    binding=Binding(grid);packet=source['tactical_map'];aliases=binding.region_aliases
    graph=packet.get('region_graph',{})
    for rid,row in {**graph,**source.get('regions',{})}.items():
        if _point(row.get('center')):aliases[rid]=label(binding.xy(row['center']))
    counts=Counter(aliases.values());seen=Counter()
    for rid,key in list(aliases.items()):
        if counts[key]>1:seen[key]+=1;aliases[rid]=key+'/area'+str(seen[key])
    for rid,row in source.get('regions',{}).items():
        key=aliases.get(rid)
        if key:binding.regions[key]=rid
    points={site['id']:label(binding.xy(site['position'])) for site in source.get('candidate_sites',[]) if _point(site.get('position'))}
    # Distinct native sites must never silently collapse into one option.
    if len(set(points.values()))!=len(points):
        counts=Counter(points.values());seen=Counter()
        for sid,key in list(points.items()):
            if counts[key]>1:seen[key]+=1;points[sid]=key+'/site'+str(seen[key])
    route_maps={}
    for uid in source.get('member_region_choices',{}):
        routes=route_facts(source,uid);seen=Counter();mapping={}
        for pid,row in routes.items():
            point=label(binding.xy(row['position']));seen[point]+=1
            mapping[pid]=point+'/via'+str(seen[point])
        route_maps[uid]=mapping
        source['member_region_choices'][uid]={mapping[pid]:row for pid,row in routes.items()}
    source.pop('route_columns',None)
    def text(value):
        for old,new in sorted(aliases.items(),key=lambda p:-len(p[0])):
            value=re.sub(re.escape(old)+r'(?!\d)',lambda _:new,value)
        for old,new in points.items():
            value=re.sub(r'\b'+re.escape(old)+r'\b',lambda _:new,value)
        return value
    positions={'position','center','goal','target_position','flag_position','destination','assigned_position','last_position',
               'anchor','peek','area_position','hold_position'}
    paths={'route_positions','path_positions','waypoints'}
    def convert(v,key=''):
        if key in positions and _point(v):return binding.xy(v)
        if key in paths and isinstance(v,list):return [binding.xy(p) if _point(p) else convert(p) for p in v]
        if isinstance(v,str):return points.get(v,aliases.get(v,text(v)))
        if isinstance(v,list):return [convert(x,key) for x in v]
        if isinstance(v,dict):return {aliases.get(k,k):convert(x,k) for k,x in v.items() if k not in ('symbol','endpoint_id')}
        return v
    # Avoid a second set of region labels, gateways and per-candidate diagram marks.
    # Connectivity and native endpoint checks remain in the converted fact context.
    raw_map=source.pop('tactical_map')
    result=convert(source)
    hard=convert(raw_map.get('local_hard_covers',[]))
    for c in hard:
        if _point(c.get('size')):c['size']=[_clean(v/binding.size) for v in c['size']]
    cells=[list(row) for row in grid['rows']]
    legends=grid.get('legend',{});under={};unit_marks={}
    self_id=source.get('self',{}).get('id') or raw_map.get('focus_unit_id')
    for row in cells:
        for i,char in enumerate(row):
            if char not in '.#:?o':row[i]='?'
    # Entity positions are exact, all other positions are selected by coordinates.
    units={u['id']:u for u in source.get('members',[])+source.get('contacts',[])+source.get('teammate_reports',[]) if u.get('id') and _point(u.get('position')) and u.get('visible',True)}
    own=source.get('self',{})
    if own.get('id') and _point(own.get('position')):units[own['id']]=own
    # Old overview glyphs need not have full unit records (historical inspector).
    for y,line in enumerate(grid['rows']):
        for x,ch in enumerate(line):
            uid=legends.get(ch)
            if ch not in '.#:?oF*@' and isinstance(uid,str) and uid not in units:
                units[uid]={'id':uid,'position':[grid['bounds'][0]+(x+.5)*binding.size,grid['bounds'][1]+(y+.5)*binding.size]}
    faction=source.get('faction',str(self_id).split('-')[0]);counts=Counter()
    outside_units={}
    for uid,u in sorted(units.items()):
        prefix='U' if uid.startswith(faction+'-') else 'E';counts[prefix]+=1
        mark='ME' if uid==self_id else prefix+str(counts[prefix])
        px,py=u['position'];x=int((px-grid['bounds'][0])/binding.size+1e-6);y=int((py-grid['bounds'][1])/binding.size+1e-6)
        if not (0<=x<grid['cols'] and 0<=y<grid['row_count']):
            outside_units[uid]=binding.xy(u['position']);continue
        key=f'{x},{y}';under.setdefault(key,cells[y][x]);cells[y][x]=(cells[y][x]+'/'+mark if key in unit_marks else mark);unit_marks[key]=True
        unit_marks[mark]=uid
    origin=grid.get('grid_origin',[0,0]);diagram='    '+' '.join(f'{origin[0]+i:02}' for i in range(grid['cols']))+'\n'
    diagram+='\n'.join(f'{origin[1]+y:02} |'+' '.join(ch*2 if ch in '.#?:o' else ch for ch in row)+'|' for y,row in enumerate(cells))
    result['tactical_map']=dict(format=VERSION,origin=origin,diagram=diagram,
        entities={k:v for k,v in unit_marks.items() if isinstance(v,str)},outside_units=outside_units,
        under_units={label([origin[0]+int(k.split(',')[0]),origin[1]+int(k.split(',')[1])]):v for k,v in under.items()},
        connections={aliases.get(r,r):[aliases.get(n,n) for n in d.get('neighbors',[])] for r,d in graph.items()},
        local_hard_covers=hard,navigation_revision=raw_map.get('navigation_revision'),
        omitted_region_count=raw_map.get('omitted_region_count',0),
        omitted_hard_cover_count=raw_map.get('omitted_hard_cover_count',0),
        distance_to_cells=round(1/binding.size,6),legacy_frame=not binding.fixed)
    q=copy.deepcopy(questions)
    for name,question in q.items():
        criteria=question.get('criteria')
        if not isinstance(criteria,dict):continue
        mapping={}
        if name.startswith('route_'):
            uid=name[6:];mapping=dict(route_maps.get(uid,{}))
            if 'keep_assignment' in criteria: mapping['keep_assignment']='keep_assignment'
            question['criteria']={mapping.get(k,k):(text(v) if k=='keep_assignment' else '通路和终点检查见 member_region_choices.'+uid+'.'+mapping.get(k,k)) for k,v in criteria.items()}
        elif name=='action':
            for key in criteria:
                parts=key.split(':');mapping[key]=':'.join(points.get(part,part) for part in parts)
            question['criteria']={mapping[k]:text(v) for k,v in criteria.items()}
        else:question['criteria']={k:text(v) for k,v in criteria.items()}
        if mapping:binding.choices[name]={v:k for k,v in mapping.items()}
    for question in q.values():
        if 'instructions' in question:question['instructions']=text(question['instructions'])
    primary={'commander':'plan','executor':'intent','personal':'action'}[role]
    if primary in q:
        instruction=q[primary].get('instructions','')
        instruction='\n'.join(line for line in instruction.splitlines() if not line.startswith('先读tactical_map.overview.diagram'))
        instruction=instruction.replace('只从regions选择下一阶段region_id和目的，不能创造坐标', '只从regions选择下一阶段destination坐标和目的，不选未验证坐标')
        instruction=instruction.replace('"region_id":"本次候选ID"','"destination":[x,y]')
        instruction=instruction.replace('候选编号每次重新生成。','候选坐标的可用性每次重新验证。')
        q[primary]['instructions']=instruction+GUIDE
    result['prompt_contract']={'version':VERSION,'role':role}
    result=share(result)
    # Keep one field schema for repeated route rows. All choices/checks survive.
    routes=result.get('member_region_choices',{})
    if routes:
        columns=list(dict.fromkeys(k for options in routes.values() for row in options.values() for k in row))
        packed={uid:{rid:[row.get(k,{'missing':True}) for k in columns] for rid,row in options.items()} for uid,options in routes.items()}
        if _size(packed)+_size(columns)<_size(routes):
            result['member_region_choices']=packed;result['route_columns']=columns
    for parent,key in [(result,'regions'),(result,'candidate_sites'),(result['tactical_map'],'local_hard_covers')]:
        rows=parent.get(key)
        if not rows:continue
        keyed=isinstance(rows,dict);values=list(rows.values()) if keyed else rows
        table=_pack(values)
        if keyed:table['keys']=list(rows)
        if _size(table)<_size(rows):parent[key]=table
    return result,q,binding
