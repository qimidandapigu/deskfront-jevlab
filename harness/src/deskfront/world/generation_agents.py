"""Two JEV roles: encounter planning, then tool-backed spatial assembly."""
import copy
import time
from collections import Counter

from jev_client import checked_choice
from .catalog import CATALOG
from .forces import force_packages
from .template_cards import inventory
from .decision_views import planner_view
from .desk_programmes import PURPOSE_ROLES, candidates as desk_programmes, menu as programme_menu, model_programme

RESCUE_INTERVAL_REVISIONS = 3


def plan(game, context, choices, state):
    menu={}
    for key in choices:
        s=CATALOG[key]['selection']
        signature=(s['structure'],s['side'],s['defense'])
        if signature not in [tuple(CATALOG[k]['selection'][a] for a in ('structure','side','defense')) for k in menu]:
            menu[key]=CATALOG[key]['intent']
    world=state.get('world_growth',{})
    green=sum(u.get('hp',0)>0 and u.get('faction')=='green' and u.get('deployment_phase','active')=='active'
              for u in state.get('units',[]))
    last_rescue=max((row.get('index',-99) for row in world.get('completed',[])
                     if row.get('design',{}).get('design_card',{}).get('mission_kind')=='rescue'),default=-99)
    revision=world.get('revision',0)
    tank_rule=bool(game.config.get('gameOptions',{}).get('secondStageTankRule',True)) and revision==1
    packages=force_packages(state,context['hormones'],context['phase'],ensure_rocket=tank_rule)
    if not menu or not packages:raise ValueError('no_eligible_encounter_or_forces')
    rescue_available=green<6 and revision-last_rescue>=RESCUE_INTERVAL_REVISIONS
    mission_menu=({'rescue':'解救任务：攻破外围防线，救出堡垒内的友军并加入小队',
                   'assault':'普通推进：清除本段守军'} if rescue_available else
                  {'assault':'普通推进：清除本段守军'})
    living_rocket=any(
        u.get('hp', 0) > 0 and u.get('faction') == 'green'
        and u.get('weapon') == 'rocket' for u in state.get('units', []))
    armored_available=revision >= 1 and (living_rocket or
        tank_rule and any(row['friendly_count'] > 0 for row in packages.values()))
    support_menu={'infantry':'步兵交火：由本关守军编成决定步枪、冲锋枪和手枪的分工'}
    if revision >= 1:
        support_menu['rocket_team']='火箭兵支援：守军后侧有一名火箭兵，前沿仍由步兵防守'
    if armored_available:
        support_menu['tank']='坦克增援：本段敌方有一辆坦克；'+('我方现有火箭兵可反制' if living_rocket else '本段补充一名火箭兵以便反制')+'，坦克位置需由引擎确认'
    if (game.config.get('gameOptions', {}).get('secondStageTankShowcase') or tank_rule) and revision == 1:
        if not armored_available:raise ValueError('tank_showcase_requires_living_rocket')
        support_menu={'tank':support_menu['tank']+'；本局演示目标为第二关坦克遭遇'}
    recent_support=Counter(row.get('support_type','infantry')
        for row in world.get('completed', [])[-3:])
    support_menu={key:f'{label}；最近三段已选{recent_support[key]}次'
        for key,label in support_menu.items()}
    recent_mix=Counter(row.get('defender_mix','balanced')
        for row in world.get('completed', [])[-3:])
    mix_labels={
        'balanced':'混合守备：步枪、冲锋枪、手枪分守远近；适合需要三种交火距离的场面',
        'rifle_screen':'步枪前哨：前线以步枪牵制，冲锋枪和手枪在后方或近路补位',
        'close_patrol':'近距巡逻：冲锋枪和手枪在前沿活动，步枪压住后路',
    }
    mix_menu={key:f'{label}；最近三段已选{recent_mix[key]}次'
        for key,label in mix_labels.items()}
    goal=(context.get('experience_report') or {}).get('next_goal')
    approach_menu={
        'screened_advance':'逐段靠掩体推进，保留一条不过度暴露的路线',
        'flank_pressure':'正面牵制与侧路绕行形成不同代价',
        'layered_defense':'前哨与后卫分层，先处理前沿再接近目标',
        'short_contact':'较短接敌距离，快速出现可理解的交火',
    }
    scene_menu={
        'north_hook':'北侧迂回成为主变化；中央吸引火力，敌侧北翼出现转折',
        'south_hook':'南侧迂回成为主变化；中央吸引火力，敌侧南翼出现转折',
        'split_lanes':'南北两条路线各有不同遮挡和交火代价，在敌侧汇合',
        'central_breach':'中央连续推进和侧翼短暂避险交替出现',
        'offset_pockets':'掩护点错列分布；推进需要在左右之间转移',
        'defended_corner':'敌侧一角形成明显坚固据点，另一角留可理解的突破口',
    }
    recent_briefs=context.get('recent_layout_briefs') or []
    scene_choices={key:label+f"｜最近三关已选{sum(row.get('scene_shape')==key for row in recent_briefs)}次"
        for key,label in scene_menu.items()}
    programmes=desk_programmes(context)
    programme_choices=programme_menu(programmes)
    questions=dict(blueprint=dict(type='choice',instructions='根据当前关分析及最终清场事实，选择关卡结构、通路侧和防守关系。搭建员负责具体文具摆放。',criteria=menu),
        mission_kind=dict(type='choice',instructions='选择遭遇目标。解救任务须清除堡垒外的包围守军，队伍有空位时可增加一名友军。',criteria=mission_menu),
        force_package=dict(type='choice',instructions='选择本关双方兵力，已有足够友军时不补员；若支援选择坦克，敌方步兵固定为2人，替代套餐中的守军人数。',criteria={k:v['label'] for k,v in packages.items()}),
        defender_mix=dict(type='choice',instructions='选择守军的步兵武器编成。步枪、冲锋枪、手枪都可进入关卡；若另选火箭兵支援，则一名守军携火箭筒。根据当前战况和最近三关编成选择，不要机械重复。',criteria=mix_menu),
        support_type=dict(type='choice',instructions='选本关的支援兵种。选择坦克时仅搭配2名步兵，不再叠加普通守军人数。坦克属于本段必须击败的守军，不是反坦克炮；若地形无法让它安全入场，引擎会明确回报未部署。',criteria=support_menu),
        tactical_approach=dict(type='choice',instructions='根据当前关体验目标选择要交给搭建员的战术关系，不替搭建员摆文具。',criteria=approach_menu),
        scene_shape=dict(type='choice',instructions='先构思整张九格桌面的主要空间变化。结合最近关卡的完整布局和战斗结果，选择本关真正要改变的路线及防守形状；若沿用上关形状，请确保当前战斗提供了理由。这只是交给搭建员的设计意图，不直接指定卡片。',criteria=scene_choices),
        desk_programme=dict(type='choice',instructions='为下一关选择一份完整九桌用途编排。逐项查看 desk_programmes 中九桌的主物件、工作区交接和近期使用证据，判断哪套关系最适合当前战况与下一关目标。用户明确偏好跨关可见的用途、主物件和布局变化；当前战况相近或观察被冻结，并不要求下一关照搬同一套九桌。请同时看根方案选用次数、same_desks_recently和连续次数，continue_recent不是新方案名称。没有明确战术或剧情理由延续时，优先引入近期缺失的用途和主物件，让它们在整关有可辨认的作用，而不只换方向或小配件。它是一整份选择，不是九道互相看不到答案的用途题。连续工作区可以重复用途，有理由的延续仍可选择；变化是设计偏好，不是禁重复或必须轮换的规则。这些是用途和视觉分工，不决定入口、出口、通路连接或具体卡片，搭建员仍可选择全部卡片。',criteria=programme_choices))
    started=time.monotonic()
    planning_context=dict(context,agent='level_planner',schema='level-planner-v7',next_goal=goal,
        available_stationery=inventory(),
        desk_programmes={key:model_programme(value) for key,value in programmes.items()},
        desk_role_by_purpose=PURPOSE_ROLES,
        desk_relation_rule='c0我方、c1中段、c2目标侧；同用途相邻格连续成工作区，异用途相邻格形成交接。完整每格职责和邻桌关系在选定方案后展开给搭建员。',
        programme_contract='整体用途表先由策划选择，再作为九格搭建的共享输入。用途表不指定或筛掉任何卡片；scene_shape只提出战术构图，搭建员用朝向、接口与具体摆法把两者结合。',
        visual_evidence_rule='用近期真实成图的material_profile判断物件是否重复；更换卡号、方向或主题名称不等于换了素材。根据可用文具决定下一关应突出的主物件和不同桌面的用途。',
        final_state_rule='当前teams和mission以及终局回执优先于较早的体验报告；本关进行中草案不能覆盖最终伤亡。')
    result=game.ask(planning_context if game.config.get('backend','mock')=='mock' else planner_view(planning_context),questions)
    option=checked_choice(result['answers']['blueprint'],menu)
    mission_kind=checked_choice(result['answers']['mission_kind'],mission_menu)
    package=checked_choice(result['answers']['force_package'],questions['force_package']['criteria'])
    defender_mix=checked_choice(result['answers']['defender_mix'],mix_menu)
    support_type=checked_choice(result['answers']['support_type'],support_menu)
    approach=checked_choice(result['answers']['tactical_approach'],approach_menu)
    scene=checked_choice(result['answers']['scene_shape'],scene_choices)
    programme_id=checked_choice(result['answers']['desk_programme'],programme_choices)
    programme=programmes[programme_id]
    tactical_problem=CATALOG[option]['intent']+'；'+approach_menu[approach]
    layout_brief=dict(scene_shape=scene,scene_intent=scene_menu[scene],
        visual_motif=programme['visual_motif'],visual_intent=programme['programme_intent'],
        programme_id=programme_id,source_programme_id=programme['source_programme_id'],
        desk_fingerprint=programme['desk_fingerprint'],programme_intent=programme['programme_intent'],
        desks=copy.deepcopy(programme['desks']))
    layout_change=(goal or {}).get('layout_change')
    build_directive=((layout_change+'；') if layout_change else '')+(approach_menu[approach]+'；'+scene_menu[scene]+'；'+programme['programme_intent']
        +'。先读已选定的完整九桌用途、主物件和邻桌关系；一次选定九格文具模板、方向和相邻连接，再根据整图回执批量修改，使通路和掩体实际支持这一关系。用途表是共享设计意图，不是限卡或强制去重规则。')
    requested_route=(goal or {}).get('route_preference')
    # A planner may refine the brief, but may not erase an explicit safe-flank
    # or varied-route goal without any explanation channel in JEV's choice API.
    route_preference=(requested_route if requested_route in ('flank','varied') else
        'flank' if approach=='flank_pressure' else 'direct' if approach=='short_contact' else
        requested_route or 'varied')
    result_plan=dict(option=option,forces={k:packages[package][k] for k in ('friendly_count','enemy_count')},
        mission_kind=mission_kind,defender_mix=defender_mix,support_type=support_type,intent=tactical_problem,build_directive=build_directive,
        route_preference=route_preference,next_goal=goal,layout_brief=layout_brief,
        force_package=package,request_id=result['requestId'])
    result_plan['spatial_goal']=dict(tactical_relation=tactical_problem,
        scene=scene_menu[scene],visual=programme['programme_intent'],next_goal=copy.deepcopy(goal))
    if support_type=='tank':result_plan['forces']['enemy_count']=2
    game.record(dict(type='world-planner',agent='level_planner',plan=result_plan,elapsed_ms=round((time.monotonic()-started)*1000),**result))
    return result_plan

