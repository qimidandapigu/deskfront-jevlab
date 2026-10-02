"""Strict data-only authoring, followed by the same Godot navigation gate used at load."""
import copy
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TEAMS=['green','blue','red']
WEAPONS=['rifle','smg','rocket','pistol']


def catalog():
    levels=json.loads((ROOT/'data/sandbox-maps.json').read_text())['levels']
    return {'schema_version':1,'scope':'现有桌面地形上的数据化战术关卡；三阵营各3兵，中央守旗','teams':TEAMS,'weapons':WEAPONS,'limits':{'covers':[4,14],'hold_seconds':[20,90],'cover_size':[[.08,.4],[.035,.09],[.035,.16]],'yaw':[0,90]},'templates':[{'index':i,'name':l['name'],'bounds':l['bounds'],'spawns':l['spawns'],'objective':[.54,2.38] if l['id']=='river' else l['objective'],'fixed_objects':[o for o in l['objects'] if o['kind'] not in ['sandbag','crate']]} for i,l in enumerate(levels) if i<3],'example':example()}


def example():
    level=json.loads((ROOT/'data/sandbox-maps.json').read_text())['levels'][0]
    return {'schema_version':1,'name':'交叉火力与侧路夺旗','briefing':'绿色沿沙包交替推进，蓝方利用侧路，红方守住旗点入口。','tactical_plan':['中央旗区留出多向接近通道','两翼掩体支撑交替推进，避免全员冲锋','每队保留火箭兵应对红方装甲'],'base_map':0,'objective':level['objective'],'hold_seconds':30,'spawns':level['spawns'],'loadouts':{t:['rifle','smg','rocket'] for t in TEAMS},'covers':[dict({k:o[k] for k in ['kind','position','size']},yaw=90 if o['yaw']==90 else 0) for o in level['objects'] if o['kind'] in ['sandbag','crate']]}


def vector(value,n):
    return isinstance(value,list) and len(value)==n and all(type(x) in [int,float] and math.isfinite(x) for x in value)


def compile_scenario(spec,id):
    if not isinstance(spec,dict) or set(spec)-{'schema_version','name','briefing','tactical_plan','base_map','objective','hold_seconds','spawns','loadouts','covers'}:raise ValueError('invalid_scenario_fields')
    if spec.get('schema_version')!=1:raise ValueError('invalid_schema_version')
    index=spec.get('base_map')
    if type(index) is not int or index not in range(3):raise ValueError('invalid_base_map')
    for field,limit in [('name',80),('briefing',1200)]:
        if not isinstance(spec.get(field),str) or not 1<=len(spec[field])<=limit:raise ValueError('invalid_'+field)
    plans=spec.get('tactical_plan')
    if not isinstance(plans,list) or not 2<=len(plans)<=6 or any(not isinstance(x,str) or not 1<=len(x)<=400 for x in plans):raise ValueError('tactical_plan_requires_2_to_6_points')
    hold=spec.get('hold_seconds')
    if type(hold) not in [int,float] or not math.isfinite(hold) or not 20<=hold<=90:raise ValueError('invalid_hold_seconds')
    level=copy.deepcopy(json.loads((ROOT/'data/sandbox-maps.json').read_text())['levels'][index]);b=level['bounds']
    def position(p):return vector(p,2) and b[0]+.04<=p[0]<=b[2]-.04 and b[1]+.04<=p[1]<=b[3]-.04
    if not position(spec.get('objective')):raise ValueError('invalid_objective')
    if not isinstance(spec.get('spawns'),list) or len(spec['spawns'])!=3 or not all(position(p) for p in spec['spawns']):raise ValueError('invalid_spawns')
    loadouts=spec.get('loadouts')
    if not isinstance(loadouts,dict) or set(loadouts)!=set(TEAMS):raise ValueError('invalid_loadouts')
    for weapons in loadouts.values():
        if not isinstance(weapons,list) or len(weapons)!=3 or any(w not in WEAPONS for w in weapons) or 'rocket' not in weapons:raise ValueError('each_team_requires_three_weapons_and_anti_armor')
    covers=spec.get('covers')
    if not isinstance(covers,list) or not 4<=len(covers)<=14:raise ValueError('cover_count_4_to_14')
    level['objects']=[o for o in level['objects'] if o['kind'] not in ['sandbag','crate']]
    for i,c in enumerate(covers):
        if not isinstance(c,dict) or set(c)!= {'kind','position','size','yaw'} or c.get('kind') not in ['sandbag','crate','building'] or not position(c.get('position')) or not vector(c.get('size'),3) or type(c.get('yaw')) not in [int,float] or c['yaw'] not in [0,90]:raise ValueError('invalid_cover')
        if not all(lo<=v<=hi for v,(lo,hi) in zip(c['size'],[(.08,.4),(.035,.28 if c['kind']=='building' else .09),(.035,.30 if c['kind']=='building' else .16)])):raise ValueError('invalid_cover_size')
        sx,_,sz=c['size'];sx,sz=(sz,sx) if c['yaw']==90 else (sx,sz)
        if not (b[0]+.02<=c['position'][0]-sx/2 and c['position'][0]+sx/2<=b[2]-.02 and b[1]+.02<=c['position'][1]-sz/2 and c['position'][1]+sz/2<=b[3]-.02):raise ValueError('cover_out_of_bounds')
        level['objects'].append(dict(c,id='studio-cover-'+str(i),color='#b1aa83' if c['kind']=='sandbag' else '#898775',collision=True,destructible=True))
    level.update({k:copy.deepcopy(spec[k]) for k in ['name','briefing','tactical_plan','spawns','loadouts','objective','hold_seconds']})
    level.update(id='studio-'+id,scenario_id=id,base_map=index)
    return level


def preflight(level):
    from project import binary
    with tempfile.TemporaryDirectory(prefix='deskfront-scenario-') as d:
        file=Path(d)/'level.json';file.write_text(json.dumps(level,ensure_ascii=False))
        result=subprocess.run([binary('godot'),'--headless','--path',str(ROOT),'--script','tests/scenario_preflight.gd'],env=dict(os.environ,DESKFRONT_SCENARIO_FILE=str(file)),capture_output=True,text=True,timeout=45)
        for line in result.stdout.splitlines():
            if line.startswith('SCENARIO_VALIDATION '):return json.loads(line.split(' ',1)[1])
        raise ValueError('godot_preflight_failed')
