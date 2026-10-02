"""Spatial selection: one nine-cell draft and one nine-cell revision."""
import copy
import json
import itertools
from collections import Counter
from functools import lru_cache
import time
from jev_client import checked_choice
from .tactical_quality import assess
from .region_graph import LIBRARY, PROPS, CELLS, ENTRY, EXIT, SELECTABLE_MODULES, inspect_regions, validate_graph, compile_graph
from .fortress import apply as fortify
from .assembly import validate as validate_geometry
from .template_cards import cards as template_cards, menu as template_menu, MODEL_CARD_COLUMNS, model_card_row
from .design_memory import describe as describe_design, similarity as design_similarity, material_comparison
from .layout_patterns import connections as pattern_connections, menu as pattern_menu
from .decision_views import builder_view

CARD_ALIAS={module:f'card_{index:02d}' for index,module in enumerate(SELECTABLE_MODULES,1)}
CARD_MODULE={alias:module for module,alias in CARD_ALIAS.items()}


@lru_cache(maxsize=2)
def graph_candidates(dual=False):
    optional=[k for k in CELLS if k not in (ENTRY,EXIT)]
    candidates={}
    for count in range(2,6):
        for cells in itertools.combinations(optional,count):
            used={ENTRY,EXIT,*cells}
            ops=[dict(op='place_region',cell=k,module='open' if k in used else 'empty') for k in CELLS]
            receipt=inspect_regions(ops)
            if not receipt['ok']:continue
            edges=receipt['available_connections']
            # Both complete adjacency and individual closed ports are genuine
            # alternatives. Filter them using the same geometry validator.
            for removed in [(),*((e,) for e in edges),*itertools.combinations(edges,2)]:
                links=[e for e in edges if e not in removed]
                assembled=ops+[dict(op='connect_regions',edge=e) for e in links]+[dict(op='deploy',module='rear')]
                try: check={'graph':compile_graph(assembled)['design_card']}
                except ValueError: continue
                if dual and not check['graph']['alternate_route']:continue
                key='g'+str(len(candidates))
                candidates[key]=dict(operations=ops,edges=links,cells=list(cells),graph=check['graph'])
    return candidates


def footprint(operations):
    return tuple(sorted(o['cell'] for o in operations if o.get('op')=='place_region' and o['module']!='empty'))


def composition_styles(operations):
    return tuple(sorted(int(o['module'].rsplit('_',1)[1]) for o in operations
                        if o.get('op')=='place_region' and o.get('module','').startswith('workshop_')))


def select_graph_menu(task):
    structure,side,*_=task['option'].split('_')
    candidates=graph_candidates(structure=='court')
    preferred='c1r0' if side=='north' else 'c1r2'
    selected={}
    for key,c in candidates.items():
        if task.get('mission_kind')=='rescue':
            if 'c1r1' not in c['cells'] or 'c2r0' in c['cells'] or 'c2r2' in c['cells'] or 'c1r1__c2r1' not in c['edges']:continue
            base=compile_graph(c['operations']+[dict(op='connect_regions',edge=e) for e in c['edges']]+[dict(op='deploy',module='rear')])
            if not validate_geometry(fortify(base,task.get('forces',{}).get('enemy_count',3)))['ok']:continue
        routes=c['graph']['main_regions']+c['graph']['flank_regions']
        if preferred not in routes:continue
        if structure=='gate' and sum(ENTRY in e.split('__') for e in c['edges'])!=1:continue
        if structure=='breach' and len(c['graph']['main_regions'])<5:continue
        selected[key]=c
    if not selected:raise ValueError('no_graph_matches_intent')
    keys=list(selected)
    shift=int(task.get('generation_index',0))%len(keys)
    keys=keys[shift:]+keys[:shift]
    if len(keys)>24:keys=[keys[round(i*(len(keys)-1)/23)] for i in range(24)]
    return {k:selected[k] for k in keys}


def region_roles(graph):
    main=graph['graph']['main_regions'][1:-1]
    alternate=graph['graph']['flank_regions']
    roles={k:'flank' if k in alternate else 'screen' for k in graph['cells']}
    for k in main:roles[k]='advance'
    if main:roles[main[-1]]='defense'
    # Each layout carries distinct region purposes, rather than identical questions.
    if len(set(roles.values()))==1:
        roles[graph['cells'][0]]='screen'
    return roles


def assemble_props(graph, proposal, enemy_count, rescue=False):
    """Compile a model's individual prop placements; never repair its choices silently."""
    if not isinstance(proposal,dict) or proposal.get('deployment') not in ('rear','distributed','forward','layered'):
        return None,dict(ok=False,reason='invalid_prop_plan_deployment')
    props=proposal.get('props')
    if not isinstance(props,list) or len(props)>12:return None,dict(ok=False,reason='invalid_prop_count')
    ops=copy.deepcopy(graph['operations'])+[dict(op='connect_regions',edge=e) for e in graph['edges']]
    for index,part in enumerate(props):
        if not isinstance(part,dict):return None,dict(ok=False,reason='invalid_prop_record',index=index)
        # Do not accept model-supplied dimensions, collision, or executable data.
        row={key:part.get(key) for key in ('cell','asset','x','z','rotation')}
        ops.append(dict(op='place_prop',**row))
    ops.append(dict(op='deploy',module=proposal['deployment']))
    receipt=validate_graph(ops)
    if not receipt['ok']:return None,receipt
    spec=compile_graph(ops)
    if rescue:
        spec=fortify(spec,enemy_count)
        receipt=validate_geometry(spec)
        if not receipt['ok']:return None,receipt
        receipt['graph']=spec['design_card']
    receipt['tactical_estimate']=assess(spec,enemy_count)
    receipt['placed_props']=len(props)
    return ops,receipt


def mock_props(graph, enemy_count, rescue=False):
    """Deterministic baseline for the mock backend, visibly distinct from model work."""
    props=[]
    candidates=(('bookstack',-.14,-.17,0),('tissues',.14,.16,90),('mouse',-.14,.16,0),
        ('book_atlas',.14,-.17,90),('mug',-.14,-.17,0))
    for index,cell in enumerate(graph['cells']):
        if rescue and cell=='c1r1':continue
        cx,cz=LIBRARY['cells'][cell]['open']['center']
        for offset in range(len(candidates)):
            asset,dx,dz,rotation=candidates[(index+offset)%len(candidates)]
            trial=props+[dict(cell=cell,asset=asset,x=round(cx+dx,3),z=round(cz+dz,3),rotation=rotation)]
            if len(trial)<2 or assemble_props(graph,dict(props=trial,deployment='rear'),enemy_count,rescue)[1]['ok']:
                props=trial;break
    return dict(props=props,deployment='rear')


def defender_preview(graph, enemy_count, rescue):
    """Show JEV where each legal deployment would put defenders, before it designs cover."""
    base=copy.deepcopy(graph['operations'])+[dict(op='connect_regions',edge=edge) for edge in graph['edges']]
    result={}
    for deployment in ('rear','distributed','forward','layered'):
        spec=compile_graph(base+[dict(op='deploy',module=deployment)])
        if rescue:spec=fortify(spec,enemy_count)
        result[deployment]=[dict(x=x,z=z,weapon=weapon,role=role)
            for x,z,weapon,role in spec['defender_slots'][:enemy_count]]
    return result


MOTIF_PURPOSES={
    'workstations':{'coding','admin'},
    'paper_archive':{'archive','study','packing'},
    'small_tools':{'drafting','hobby','refreshment'},
    'mixed_desks':set(),
}


def menu_for_cell(cell, available, brief=None, recent=None, neutral=False):
    """Describe real materials in all nine menus; retain every authored choice."""
    catalog=template_cards()
    motif=(brief or {}).get('visual_motif')
    preferred=MOTIF_PURPOSES.get(motif,set())
    previous=Counter(old.get('cells',{}).get(cell,{}).get('card') for old in recent or [])
    material_counts=Counter()
    for old in recent or []:material_counts.update(old.get('materials',{}))
    # Rotate equal-rank display order, not the chosen map. Avoid presenting the
    # same three legacy military layouts as the default answer for every desk.
    keys=list(available);shift=list(CELLS).index(cell)*5 % len(keys)
    keys=keys[shift:]+keys[:shift]
    keys.sort(key=lambda key:catalog[key]['purpose'] not in preferred)
    result={}
    for key in keys:
        card=catalog[key];heroes=card['hero_assets']
        hero_names=[PROPS.get(asset,{}).get('label',asset) for asset in heroes]
        # Detailed items/coordinates are shared once in context.templates.
        label=card['name'] if neutral else available[key]+'｜主物件：'+'、'.join(hero_names)
        if card['purpose'] in preferred:label+='｜符合本关主题'
        if previous[key]:label+=f'｜最近{len(recent)}关此格已用{previous[key]}次'
        if recent and not neutral:
            label+='｜主物件近期出现：'+','.join(f'{name}{material_counts[asset]}' for asset,name in zip(heroes,hero_names))
        result[CARD_ALIAS[key] if neutral else key]=label
    return result


def encode_placement(module,turn):
    return f'p{CARD_ALIAS[module][-2:]}{turn//90}'


def placement_menu(cell, available, brief=None, recent=None):
    """One judgment chooses the card AND its angle; no unseen sibling answer."""
    names=menu_for_cell(cell,available,brief,recent,neutral=True)
    catalog=template_cards()
    # The shared card table already explains each card. Keep the repeated
    # nine-cell option IDs short: p013 = card_01 rotated 270 degrees.
    # The compact key already carries the quarter-turn. Keep the description
    # numeric but omit the repeated degree symbol; shared choice_semantics
    # explains the mapping once for the request.
    return {encode_placement(CARD_MODULE[alias],turn):str(turn)
        for alias in names for turn in catalog[CARD_MODULE[alias]]['allowed_rotations']}


def decode_placement(choice):
    if len(choice)==4 and choice[0]=='p' and choice[1:].isdigit():
        alias=f'card_{choice[1:3]}'
        turn=int(choice[3])*90
    else:
        alias,turn=choice.rsplit('_r',1)
        turn=int(turn)
    return dict(template=CARD_MODULE[alias],rotation=turn)


def is_placement(choice):
    return (len(choice)==4 and choice[0]=='p' and choice[1:].isdigit()
        or choice.startswith('card_') and '_r' in choice)


def desk_instruction(brief,cell):
    desk=(brief.get('desks') or {}).get(cell)
    if not desk:return scene_job(brief.get('scene_shape'),cell)
    heroes='、'.join(PROPS.get(asset,{}).get('label',asset) for asset in desk.get('hero_assets',[]))
    return (f"用途={desk.get('purpose')}；主物件={heroes}；作用={desk.get('role')}；"
            f"邻桌关系={desk.get('neighbor_relation')}")


def rotated_descriptions(card):
    """Share physical orientation evidence once, not 9 copies in option labels."""
    from .template_cards import direction
    result={}
    for turn in card['allowed_rotations']:
        positions=[]
        for item in card['items']:
            if item['asset'] not in card['hero_assets']:continue
            x,z=item['offset']
            for _ in range(turn//90):x,z=-z,x
            positions.append(direction(x,z)+item['name'])
        result[str(turn)]='、'.join(positions)
    return result


def rotated_item_description(item,turn):
    from .template_cards import direction
    x,z=item['offset']
    for _ in range(turn//90):x,z=-z,x
    return f"{direction(x,z)}{item['name']}，实际偏移({x:.3f},{z:.3f})"


def scene_job(scene, cell):
    """Translate a whole-level composition into a distinct role for each cell."""
    col,row=int(cell[1]),int(cell[3])
    if scene=='north_hook':
        return ('北线连续转角' if row==0 else '中央牵制点' if row==1 else '南线较短的支援通道')
    if scene=='south_hook':
        return ('北线较短的支援通道' if row==0 else '中央牵制点' if row==1 else '南线连续转角')
    if scene=='split_lanes':
        return ('北线低暴露推进' if row==0 else '两路之间的可见争夺地' if row==1 else '南线较快但有受火代价的推进')
    if scene=='central_breach':
        return ('中央推进的短暂侧向避险' if row!=1 else '连续的正面争夺线')
    if scene=='offset_pockets':
        return ('左侧掩护停靠点' if (col+row)%2==0 else '右侧转移与下一停靠点')
    if scene=='defended_corner':
        return ('据点外侧较坚固的角落' if col==2 and row==0 else
            '敌侧另一角的突破机会' if col==2 else '通往敌侧两角的选择')
    return ''


def build(game,task,reserve_request):
    """Choose the whole nine-cell layout in one call, then revise it in one call."""
    calls=[]
    mock=getattr(game,'config',{}).get('backend','mock')=='mock'
    def visible_card(module):
        return module if mock else CARD_ALIAS.get(module,module)
    enemy_count=task.get('forces',{}).get('enemy_count',3)
    rescue=task.get('mission_kind')=='rescue'
    all_cards=template_cards();catalog={key:value for key,value in all_cards.items() if rescue or key!='fortress_base'}
    available=template_menu()
    brief=task.get('layout_brief') or {}
    recent=task.get('recent_designs')
    if recent is None:
        recent=[description for ops in task.get('recent_builds',[])
            if (description:=describe_design(ops))]
    model_recent=copy.deepcopy(recent)
    if not mock:
        for old in model_recent:
            for part in old.get('cells',{}).values():
                part['card']=visible_card(part['card'])
                part.pop('family',None)
    shared_task=copy.deepcopy({k:v for k,v in task.items() if k not in ('recent_builds','recent_designs')})
    if 'layout_brief' in shared_task:shared_task['layout_brief'].pop('desks',None)
    if (shared_task.get('layout_brief') or {}).get('programme_intent') == brief.get('visual_intent'):
        shared_task.get('layout_brief',{}).pop('programme_intent',None)
    # A request id is a trace key, not design evidence. Keep it in local logs.
    shared_task.pop('request_id',None)
    context=dict(schema='region-builder-v14',agent='spatial_builder',
        task=shared_task,
        board='3列3行；c0我方侧、c2敌方侧，r0北、r2南。普通关选整图通路骨架，救援关逐接口选择；九格文具摆法、朝向与入口出口同批作答。',
        cells={cell:LIBRARY['cells'][cell]['open']['center'] for cell in CELLS},
        adjacency={name:[edge['a'],edge['b']] for name,edge in LIBRARY['edges'].items()},
        template_item_columns=['asset','offset_x','offset_z','width','depth','height'],
        template_columns=list(MODEL_CARD_COLUMNS),
        template_item_note='templates按卡号查行，每行字段依template_columns；items字段的每件物件依template_item_columns，其下标就是编辑index。偏移相对格中心，单位米。完整几何共享一次。',
        asset_catalog={key:[v['label'],v['width'],v['depth'],v['height']] for key,v in PROPS.items()},
        asset_columns=['name','width','depth','height'],
        templates=({CARD_ALIAS[key]:model_card_row(value) for key,value in catalog.items() if key in CARD_ALIAS}
            if not mock else catalog),recent_designs=model_recent,
        orientation_evidence={visible_card(key):rotated_descriptions(value) for key,value in catalog.items() if key in CARD_ALIAS},
        planner_desks=brief.get('desks',{}),
        choice_semantics='同次请求各题独立，以planner_desks为共同任务书。选项pXXQ表示共享templates.card_XX的整套卡片绕格中心旋转Q×90度，例如p013是card_01旋转270度；单件大型物件仅提供四向通路均可用的朝向。名称、实物、通道和方向证据均在共享表。一个选项完整决定卡片和角度，不假设能看到其他题本次答案。',
        rescue_objective=catalog.get('fortress_base') if rescue else None,
        instruction='设计卡来自真实几何。你选中的入口和出口格不能是empty，所有非empty格必须从入口可达。封闭接口会出现实体文件墙。普通卡已按全九格连续铺设验证。'+('救援关按堡垒出口逐接口选择通路。' if rescue else '普通关先选整图通路骨架。')+'再按策划的整关构图分配九格职责，选择文具与方向；对照最近关的实际通路、卡片、材料和路线。允许有战术作用的重复卡片；引擎不会替你修改。'+('敌方坦克支援已选定；敌侧需要至少一片适合车辆停靠和转向的开阔桌面，避免用高文具把所有射界堵死。' if task.get('support_type')=='tank' else '')+('救援任务中选择一个堡垒格，它同时是出口；该格由堡垒基底占据，你还要选择其余八格文具摆法。' if rescue else ''))
    # Every question still identifies its cell and relevant state explicitly.
    # Shared requirements are not expanded nine times in its instructions.
    context['cell_scene_jobs']={cell:scene_job(brief.get('scene_shape'),cell) for cell in CELLS}
    context['draft_choice_rule']=(
        '九格均参考planner_desks中的用途、主物件、作用、邻桌关系，以及cell_scene_jobs的路线任务。'
        '用途是意图不是限卡；地形需要时可以偏离，全部普通卡及实际可用朝向均可选。'
        '整关文具意图见task.spatial_goal.visual（旧任务见task.layout_brief.visual_intent），未指定时不同桌面应有可辨认的用途与主物件；近期每格卡片见recent_designs.cells。'
        '优先兑现主题和路线变化；沿用相同卡须仍有不同作用。相邻桌互补，可有意延续阵地，不强制不同。'
        'templates的主物件、topology和orientation_evidence提供实物与方向证据。')
    def ask_choice(stage,questions,choice_context=None):
        request_context=dict(context if choice_context is None else choice_context,stage=stage)
        started=time.monotonic();result=game.ask(request_context if mock else builder_view(request_context),questions)
        calls.append(result['requestId'])
        choices={}
        for key,question in questions.items():
            choice=checked_choice(result['answers'][key],question['criteria'])
            choices[key]=CARD_MODULE.get(choice,choice) if key.startswith('template_') or key.endswith('_template') else choice
        return choices,result,round((time.monotonic()-started)*1000)
    rows=('北侧','中间','南侧')
    port_questions={
        'entry_cell':dict(type='choice',instructions='选择本关我方接入桌面的格子。',criteria={f'c0r{i}':label for i,label in enumerate(rows)})}
    port_questions['fortress_cell' if rescue else 'exit_cell']=dict(type='choice',
        instructions='选择救援堡垒所在格；此格同时是出口，其余右侧两格单独选普通摆法。' if rescue else '选择本关向敌方后续桌面接出的格子。',
        criteria={f'c2r{i}':label for i,label in enumerate(rows)})
    # JEV's executor supports typed choices, not a JSON answer. Give all nine
    # questions in one request, but make their tactical jobs distinct.
    questions=dict(port_questions)
    for cell in CELLS:
        questions[f'template_{cell}']=dict(type='choice',instructions=(
            f'{cell}规划任务：{desk_instruction(brief,cell)}；路线关系：{scene_job(brief.get("scene_shape"),cell)}。'
            f'为{cell}选完整卡片与方向；按任务书和draft_choice_rule，'
            f'参照共享templates、orientation_evidence及recent_designs中该格记录。'
            +('若fortress_cell最终选中本格，本普通卡答案不执行，采用你选的救援堡垒；否则原样执行。' if rescue else '')),
            criteria=placement_menu(cell,available,brief,recent))
    edge_menu={'open':'两格之间可通行','closed':'封闭接口，形成实体文件墙与路线转折'}
    patterns=pattern_menu(recent,brief.get('scene_shape')) if not rescue else None
    if patterns:
        questions['layout_pattern']=dict(type='choice',instructions=(
            '选择整张九格桌面的通路骨架；每个选项同时决定十二个接口的开闭。'
            '菜单标出与上关真实通路的差异，按本关构图和战斗需要选，不要仅换文具却保持相同路网。'
            '彩色桌面标记会跟随这条真实路线，不能代替可达性校验。'),criteria=patterns)
    else:
        # Rescue fortress geometry depends on the independently selected exit.
        for name,edge in LIBRARY['edges'].items():
            questions[f'edge_{name}']=dict(type='choice',instructions=(
                f'{edge["a"]}与{edge["b"]}之间是否通行？救援堡垒需保留实际可达的出口。'),criteria=edge_menu)
    selected,draft_result,draft_elapsed=ask_choice('layout_draft',questions)
    exit_cell=selected['fortress_cell' if rescue else 'exit_cell']
    draft={cell:decode_placement(selected[f'template_{cell}']) for cell in CELLS}
    if rescue:
        draft[exit_cell]=dict(template='fortress_base',rotation=0)
    draft={cell:draft[cell] for cell in CELLS}
    entry_cell=selected['entry_cell']
    draft_pattern=selected['layout_pattern'] if patterns else 'rescue'
    draft_links=(pattern_connections(draft_pattern) if patterns else
        {name for name in LIBRARY['edges'] if selected[f'edge_{name}']=='open'})
    def operations(layout,entry,exit,deployment,edits=(),links=None):
        active={cell for cell,part in layout.items() if part['template']!='empty'}
        if links is None:links=set(LIBRARY['edges'])
        ops=[dict(op='set_ports',entry=entry,exit=exit)]
        ops += [dict(op='place_region',cell=cell,module=part['template'],rotation=part['rotation']) for cell,part in layout.items()]
        ops += [dict(op='connect_regions',edge=name) for name,edge in LIBRARY['edges'].items()
            if name in links and edge['a'] in active and edge['b'] in active]
        ops += list(edits)
        return ops+[dict(op='deploy',module=deployment)]
    def technical_receipt(ops):
        receipt=validate_graph(ops)
        if not receipt['ok']:return receipt
        spec=compile_graph(ops)
        if rescue:
            try:spec=fortify(spec,enemy_count)
            except ValueError as exc:return dict(ok=False,reason=str(exc))
        friendly_count=task.get('forces',{}).get('friendly_count',0)
        spec['friendlies']=(spec['friendly_slots'][:friendly_count] if 'friendly_slots' in spec else
            [[.12,round(spec['entry'][1]+(i*2-1)*.28,3)] for i in range(friendly_count)])
        receipt=validate_geometry(spec)
        if not receipt['ok']:return receipt
        receipt['graph']=spec['design_card']
        receipt['tactical_estimate']=assess(spec,enemy_count)
        return receipt
    draft_ops=operations(draft,entry_cell,exit_cell,'rear',links=draft_links)
    preview=technical_receipt(draft_ops)
    game.record(dict(type='world-builder',agent='spatial_builder',stage='layout_draft',
        proposal=dict(cells=copy.deepcopy(draft),entry_cell=entry_cell,exit_cell=exit_cell,
            layout_pattern=draft_pattern,connections=sorted(draft_links)),
        operations=copy.deepcopy(draft_ops),technical_preview=preview,elapsed_ms=draft_elapsed,**draft_result))
    context['draft_layout']={cell:dict(part,template=visible_card(part['template']),name=catalog[part['template']]['name'])
        for cell,part in draft.items()}
    context['draft_ports']=dict(entry=entry_cell,exit=exit_cell)
    counts=Counter(part['template'] for part in draft.values() if part['template'] not in ('empty','fortress_base'))
    context['draft_design_feedback']=dict(distinct_ordinary_cards=len(counts),largest_repeat=max(counts.values(),default=0),
        by_card={visible_card(key):value for key,value in counts.items()},
        cover_counts={cell:catalog[part['template']]['functional_cover_count'] for cell,part in draft.items()})
    draft_design=(describe_design(draft_ops,option=task.get('option'),
        tactical=preview.get('tactical_estimate')) if preview.get('ok') else None)
    context['draft_design_feedback']['recent_design_similarity']=[design_similarity(draft_design,old) for old in recent]
    context['draft_design_feedback']['material_profile']=(draft_design or {}).get('material_profile')
    context['draft_design_feedback']['recent_material_comparisons']=[material_comparison(draft_design,old) for old in recent] if draft_design else []
    context['draft_design_feedback']['materials_by_cell']={cell:part['props'] for cell,part in (draft_design or {}).get('cells',{}).items()}
    context['draft_design_feedback']['material_desk_counts']=dict(Counter(
        asset for part in draft.values() for asset in {item['asset'] for item in catalog[part['template']]['items']}))
    seen_templates=set();repeated_cells=[]
    for cell,part in draft.items():
        if part['template'] not in ('empty','fortress_base') and part['template'] in seen_templates:
            repeated_cells.append(cell)
        seen_templates.add(part['template'])
    context['draft_design_feedback']['repeated_cells']=repeated_cells
    context['draft_design_feedback']['reused_recent_cells']=[cell for cell,part in draft.items()
        if any(part['template']==old.get('cells',{}).get(cell,{}).get('card') for old in recent)]
    context['draft_design_feedback']['interpretation']='卡号或方向改变并不等于素材改变。请先看material_profile和materials_by_cell：是否仍由同几样物件铺满九桌，再决定哪些桌面要换用途或主物件。综合构图相似度不能证明视觉有新鲜感。'
    context['technical_preview']=copy.deepcopy(preview)
    # Grid/debug counts and identifiers do not inform a design choice. The
    # unabridged receipt remains in world-builder logs and the final receipt.
    for key in ('reachable_points','walkable_cells'):
        context['technical_preview'].pop(key,None)
    for key in ('signature','navigation','entry_cell','exit_cell'):
        context['technical_preview'].get('graph',{}).pop(key,None)
    if not preview['ok']:
        diagnosis=inspect_regions(draft_ops)
        context['draft_diagnosis']=dict(reason=preview['reason'],entry_template=visible_card(draft[selected['entry_cell']]['template']),
            exit_template=visible_card(draft[exit_cell]['template']),unreachable=diagnosis['unreachable'],
            disconnected_cells=[cell for cell in CELLS if draft[cell]['template']!='empty' and cell in diagnosis['unreachable']])
    if preview['ok']:
        draft_spec=compile_graph(draft_ops)
        context['draft_routes']=dict(main=draft_spec['main_route'],flank=draft_spec['flank'],
            entry=draft_spec['entry'],exit=draft_spec['exit'])
        context['defender_preview']={}
        for deployment in ('rear','distributed','forward','layered'):
            candidate=compile_graph(operations(draft,entry_cell,exit_cell,deployment,links=draft_links))
            if rescue:candidate=fortify(candidate,enemy_count)
            context['defender_preview'][deployment]=[
                dict(x=x,z=z,weapon=weapon,role=role)
                for x,z,weapon,role in candidate['defender_slots'][:enemy_count]]
    context['edit_contract']='一次答完整图。请先看 draft_design_feedback 的近期构图相似度以及最近关各格卡片：若初稿再次复制旧关，请在需要变化的格批量换卡/转向/改接口，使整关主题、路线和阵地用途真正有区别；连续阵地可以保留重复卡，不强制每格不同。普通格可保持、换整格、旋转，或增添/移动/移除/替换一件文具；救援堡垒格保持目标位置。若初稿不连通，可把必要接口改为open或更换empty格：入口/出口不能empty，所有启用格要连到入口。技术回执指出失败原因；引擎只执行你最终提交的操作，不代你修图。'
    context['revision_choice_rule']=(
        '每格按planner_desks的规划任务批量修改，查看其recent_designs记录与其他八格可见初稿。'
        'draft_design_feedback.materials_by_cell和material_profile显示实物分布；相同物件换卡仍会雷同。'
        'material_desk_counts给出各物件出现桌数，repeated_cells与reused_recent_cells标出初稿或近期重复格。'
        '重复桌可检查是否形成有意连续阵地，按整关构图决定；可保持，不强制去重。'
        '所有卡片与方向选项是完整换桌动作，不假设其他题本次也会同步换卡。')
    reserve_request()
    if mock:
        revision_questions={'mock_revision':dict(type='choice',instructions='模拟后端保持初稿。',criteria={'keep':'保持'})}
        _,revision_result,revision_elapsed=ask_choice('batch_revision',revision_questions)
        revised=copy.deepcopy(draft);entry=entry_cell;exit=exit_cell;deployment='rear';edits=[];actions={cell:'keep' for cell in CELLS};final_links=draft_links;final_pattern=draft_pattern
    else:
        revision_questions={'entry_cell':port_questions['entry_cell']} if rescue else dict(port_questions)
        revision_questions['deployment']=dict(type='choice',instructions='选择最终守军部署。',
            criteria={'rear':'后场','distributed':'分区','forward':'前沿','layered':'前哨与后卫分层'})
        if patterns:
            revision_questions['layout_pattern']=dict(type='choice',instructions=(
                f'最终整图通路骨架。初稿选了{draft_pattern}；查看技术回执、实际路线和上关差异。'
                '若初稿不通行或与上一关仍很像，选择另一套骨架；选择会整体改变接口，不是局部物件修饰。'),criteria=patterns)
        else:
            for name,edge in LIBRARY['edges'].items():
                revision_questions[f'edge_{name}']=dict(type='choice',instructions=(
                    f'{edge["a"]}与{edge["b"]}的最终接口。初稿为{"通行" if name in draft_links else "封闭"}；结合救援出口和可建造性回执决定。'),criteria=edge_menu)
        for cell,part in draft.items():
            prefix=f'edit_{cell}_';items=catalog[part['template']]['items']
            fixed=rescue and cell==exit_cell
            actions={'keep':'保持救援堡垒' if fixed else '保持当前卡片与方向'}
            if not fixed:
                # Choosing a new whole desk is a single complete operation.
                # Independent action/template/rotation answers could contradict.
                actions.update(placement_menu(cell,available,brief,recent))
                if task.get('allow_prop_edits',True):
                    actions.update(add='添一件文具')
                    for item in items:
                        label=rotated_item_description(item,part['rotation'])
                        actions[f'remove_{item["index"]}']='移除'+label
                        actions[f'move_{item["index"]}']='移动'+label
                        actions[f'replace_{item["index"]}']='替换'+label
            revision_questions[prefix+'action']=dict(type='choice',instructions=(
                f'{cell}规划任务：{desk_instruction(brief,cell)}。'
                f'为{cell}选最终修改；看任务书、draft_layout、draft_design_feedback和recent_designs中该格记录，'
                f'遵循revision_choice_rule/edit_contract。'),criteria=actions)
        edited,revision_result,revision_elapsed=ask_choice('batch_revision',revision_questions)
        revised=copy.deepcopy(draft);entry=edited['entry_cell'];exit=exit_cell if rescue else edited['exit_cell'];deployment=edited['deployment'];edits=[];actions={}
        final_pattern=edited['layout_pattern'] if patterns else 'rescue'
        final_links=(pattern_connections(final_pattern) if patterns else
            {name for name in LIBRARY['edges'] if edited[f'edge_{name}']=='open'})
        detail_cells=[cell for cell in CELLS if edited[f'edit_{cell}_action']=='add' or
            edited[f'edit_{cell}_action'].startswith(('move_','replace_'))]
        details={}
        if detail_cells:
            # The first revision still lets JEV edit all nine desks together.
            # Ask for coordinates only for cells where it actually chose a
            # single-prop edit; unused answers were the dominant token waste.
            reserve_request()
            x_menu={str(v):label for v,label in ((-.16,'靠西'),(-.08,'略靠西'),(0,'居中'),(.08,'略靠东'),(.16,'靠东'))}
            z_menu={str(v):label for v,label in ((-.18,'靠北'),(-.09,'略靠北'),(0,'居中'),(.09,'略靠南'),(.18,'靠南'))}
            asset_menu={key:value['label'] for key,value in PROPS.items()}
            detail_questions={}
            for cell in detail_cells:
                action=edited[f'edit_{cell}_action'];part=draft[cell]
                prefix=f'edit_{cell}_'
                if action=='add' or action.startswith('replace_'):
                    detail_questions[prefix+'asset']=dict(type='choice',instructions=f'{cell}要添加或替换成的文具。',criteria=asset_menu)
                if action=='add' or action.startswith(('move_','replace_')):
                    detail_questions[prefix+'x']=dict(type='choice',instructions=f'{cell}物件相对格中心的东西偏移。',criteria=x_menu)
                    detail_questions[prefix+'z']=dict(type='choice',instructions=f'{cell}物件相对格中心的南北偏移。',criteria=z_menu)
                    detail_questions[prefix+'item_rotation']=dict(type='choice',instructions=f'{cell}物件的横竖方向。',criteria={'0':'原方向','90':'旋转90度'})
            detail_context={key:value for key,value in context.items() if key not in
                ('templates','orientation_evidence','recent_designs','draft_design_feedback','technical_preview','defender_preview',
                 'draft_choice_rule','revision_choice_rule','edit_contract','choice_semantics','cell_scene_jobs')}
            detail_context['templates']={visible_card(draft[cell]['template']):context['templates'][visible_card(draft[cell]['template'])]
                for cell in detail_cells}
            detail_context['revision_selection']=dict(entry=entry,exit=exit,layout_pattern=final_pattern,
                actions={cell:edited[f'edit_{cell}_action'] for cell in CELLS})
            details,detail_result,detail_elapsed=ask_choice('prop_edit_details',detail_questions,detail_context)
            game.record(dict(type='world-builder',agent='spatial_builder',stage='prop_edit_details',
                cells=detail_cells,elapsed_ms=detail_elapsed,**detail_result))
        for cell in CELLS:
            prefix=f'edit_{cell}_';action=edited[prefix+'action'];actions[cell]=action
            if is_placement(action):
                revised[cell]=decode_placement(action)
                actions[cell]=('keep' if revised[cell]==draft[cell] else
                    'rotate' if revised[cell]['template']==draft[cell]['template'] else 'template')
            elif action=='add' or action.startswith(('move_','remove_','replace_')):
                cx,cz=LIBRARY['cells'][cell]['open']['center']
                if not action.startswith('remove_'):
                    x=round(cx+float(details[prefix+'x']),3);z=round(cz+float(details[prefix+'z']),3)
                    turn=int(details[prefix+'item_rotation'])
                if action=='add':edits.append(dict(op='place_prop',cell=cell,asset=details[prefix+'asset'],x=x,z=z,rotation=turn))
                else:
                    kind,index=action.split('_',1)
                    op=dict(op='edit_component',cell=cell,index=int(index),action=kind)
                    if kind!='remove':op.update(x=x,z=z,rotation=turn)
                    if kind=='replace':op['asset']=details[prefix+'asset']
                    edits.append(op)
    final_ops=operations(revised,entry,exit,deployment,edits,links=final_links)
    receipt=technical_receipt(final_ops)
    game.record(dict(type='world-builder',agent='spatial_builder',stage='batch_revision',
        proposal=dict(cells=copy.deepcopy(revised),entry_cell=entry,exit_cell=exit,
            deployment=deployment,layout_pattern=final_pattern,
            connections=sorted(final_links),actions=actions,edits=copy.deepcopy(edits)),
        operations=copy.deepcopy(final_ops),tool_receipt=receipt,elapsed_ms=revision_elapsed,**revision_result))
    if not receipt['ok']:raise ValueError('unbuildable_jev_design:'+receipt['reason'])
    final_counts=Counter(part['template'] for part in revised.values()
                         if part['template'] not in ('empty','fortress_base'))
    final_design=describe_design(final_ops,option=task.get('option'),
        tactical=receipt.get('tactical_estimate'))
    similarities=[design_similarity(final_design,old) for old in recent]
    receipt['design_observations']=dict(template_count=len(available),rescue_special_available=rescue,
        layout_pattern=final_pattern,connection_count=len(final_links),
        edited_cells=sum(action!='keep' for action in actions.values()),
        distinct_ordinary_cards=len(final_counts),largest_card_repeat=max(final_counts.values(),default=0),
        by_card=dict(final_counts),
        recent_footprint_repeated=footprint(final_ops) in {footprint(o) for o in task.get('recent_builds',[]) if o},
        recent_design_similarity=similarities,
        material_profile=final_design.get('material_profile'),
        recent_material_comparisons=[material_comparison(final_design,old) for old in recent])
    return final_ops,calls,receipt
