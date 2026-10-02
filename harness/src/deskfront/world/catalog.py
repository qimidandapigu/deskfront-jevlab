"""Authored components and placement sockets; JEV chooses their composition."""
import itertools

CHOICES = {
    'structure': {'gate':'收窄后展开：窄入口进入宽广场', 'stagger':'转角推进：沿侧向走廊转入出口', 'court':'双路包抄：中央缺口分隔上下两路并在末端汇合', 'breach':'双室突破：先进入集结庭院，再穿侧向破口攻击第二庭院'},
    'side': {'north':'上侧通路', 'south':'下侧通路'},
    'props': {'books':'高书堆：强遮挡', 'crates':'笔袋：较低遮挡'},
    'defense': {'cross':'并列防线：两路守备与侧翼警戒，可增加外侧和出口守军；交叉射界需实际验证', 'depth':'纵深防线：前哨、后卫、侧翼分层驻守，绕过前哨后仍需处理后卫'},
    'position': {'tight':'内侧位置槽：遮挡靠近中路，中央视野较窄', 'wide':'外侧位置槽：遮挡向外围移动，中央视野较宽'},
}

def compose(structure, side, props, defense, position):
    sign=-1 if side=='north' else 1
    # Local floor rectangles [min_x,min_z,max_x,max_z] define both mesh and navigation.
    floors={
        'gate':[[0,-.4,.55,.4],[.55,-1.1,1.8,1.1]],
        'stagger':[[0,-.4,.45,.4],[.35,.05,1.65,1.1],[1.35,-.4,1.8,.4]],
        'court':[[0,-1.05,.65,1.05],[.65,.3,1.15,1.05],[.65,-1.05,1.15,-.3],[1.15,-1.05,1.8,1.05]],
        'breach':[[0,-.4,.48,.4],[.35,-1.05,.95,1.05],[.85,.45,1.35,.9],[1.25,-1.05,1.8,1.05]],
    }[structure]
    if structure in ('stagger','breach') and sign<0:floors=[[a,-d,c,-b] for a,b,c,d in floors]
    kind='bookstack' if props=='books' else 'crate'
    shift=.10 if position=='wide' else 0
    if structure=='gate':
        support=[[.62,-.18],[.62,.18]]
        flank=[[.25,sign*.22],[.62,sign*.96],[1.5,sign*.96],[1.65,sign*.06]]
        sockets=[(.9,-.6-shift,.32,.3),(.9,.6+shift,.32,.3)]
        defenders=[[1.3,-.18,'rifle','前沿守备'],[1.4 if defense=='cross' else 1.62,.18,'rifle','纵深守备'],[1.48,sign*.86,'smg','侧翼警戒']]
    elif structure=='stagger':
        support=[[.45,sign*.42],[.45,sign*.84]]
        flank=[[.22,0],[.4,sign*.86],[1.52,sign*.86],[1.62,sign*.16]]
        sockets=[(.83,sign*(.4+shift),.28,.24),(1.12,sign*(.78+shift),.25,.2)]
        defenders=[[1.28,sign*.45,'rifle','转角守备'],[1.55 if defense=='cross' else 1.65,sign*.15,'rifle','出口后卫'],[1.48,sign*.83,'smg','外侧警戒']]
    elif structure=='court':
        support=[[.48,-.56],[.48,.56]]
        flank=[[.35,sign*.9],[.88,sign*.9],[1.42,sign*.9],[1.65,sign*.06]]
        sockets=[(.87,-.49-shift,.24,.18),(.87,.49+shift,.24,.18)]
        defenders=[[1.32,-.52,'rifle','下路守备'],[1.32 if defense=='cross' else 1.61,.52,'rifle','上路守备'],[1.62,0,'smg','汇合点警戒']]
    else:
        support=[[.48,-sign*.2],[.48,sign*.55]]
        flank=[[.22,0],[.55,sign*.85],[1.04,sign*.72],[1.4,sign*.83],[1.68,0]]
        sockets=[(.73,-sign*(.62+shift),.23,.30),(1.5,sign*(.1+shift),.24,.3)]
        defenders=[]
    # Ordered sockets preserve an intentional two/three-person baseline and add
    # layers rather than stack extra troops at the same position.
    formations={
        'gate':{
            'cross':[(1.30,-.18),(1.40,.18),(1.48,sign*.86),(1.65,-.55),(1.70,.48),(1.70,-sign*.86)],
            'depth':[(1.20,sign*.04),(1.67,.4),(1.4,sign*.85),(1.68,-.4),(1.20,-sign*.72),(1.70,-sign*.92)]},
        'stagger':{
            'cross':[(1.28,sign*.45),(1.62,sign*.16),(1.48,sign*.86),(1.1,sign*.18),(1.72,-sign*.2),(1.59,sign*.6)],
            'depth':[(1.02,sign*.15),(1.68,sign*.05),(1.5,sign*.9),(1.35,sign*.52),(1.7,-sign*.26),(1.59,sign*.52)]},
        'court':{
            'cross':[(1.32,-.52),(1.32,.52),(1.62,0),(1.55,-.84),(1.58,.83),(1.74,sign*.36)],
            'depth':[(1.28,sign*.78),(1.68,-sign*.5),(1.64,sign*.4),(1.32,-sign*.85),(1.74,sign*.86),(1.35,-sign*.26)]},
        'breach':{
            'cross':[(1.42,sign*.78),(1.65,sign*.48),(1.55,-sign*.68),(1.67,sign*.91),(1.30,-sign*.4),(1.73,-sign*.18)],
            'depth':[(1.37,sign*.61),(1.68,-sign*.4),(1.42,-sign*.85),(1.72,sign*.82),(1.3,-sign*.3),(1.76,sign*.18)]},
    }
    roles=['前哨守备','纵深后卫','侧翼警戒','外侧守备','出口守备','侧翼后卫']
    weapons=['rifle','rifle','smg','rocket','pistol','rifle']
    defenders=[[x,z,weapons[i],roles[i]] for i,(x,z) in enumerate(formations[structure][defense])]
    covers=[[x+.1,z,.045,.2,'sandbag',.043] for x,z in support]
    covers += [[x,z,w,d,kind,.22 if props=='books' else .12] for x,z,w,d in sockets]
    # Defence has authored protection too; retain a gap to both the soldier
    # socket and the route. Preview, collision and native validator use this.
    if structure=='gate': defensive_covers=[(1.19,-.18),(1.29,.18)] if defense=='cross' else [(1.09,sign*.04),(1.56,.4)]
    elif structure=='stagger': defensive_covers=[(1.17,sign*.45)] if defense=='cross' else [(1.54,0)]
    elif structure=='court': defensive_covers=[(1.21,-.52),(1.21,.52)] if defense=='cross' else [(1.57,-sign*.5)]
    else: defensive_covers=[(1.31,sign*.78)] if defense=='cross' else [(1.57,-sign*.4)]
    covers += [[x,z,.045,.20,'sandbag',.043] for x,z in defensive_covers]
    design={
        'gate':dict(tactical_problem='入口收窄，展开后面对多处守备',route_tradeoff='中央短路与外围绕行',signature='narrow_to_wide'),
        'stagger':dict(tactical_problem='转角遮断视野，逐步接近后卫',route_tradeoff='沿侧向走廊推进，在转角准备射位',signature='turning_corridor'),
        'court':dict(tactical_problem='中央缺口，必须经上下桥路接敌',route_tradeoff='两路分进并在后场汇合',signature='split_merge'),
        'breach':dict(tactical_problem='两庭院由偏置破口连接，分阶段突破',route_tradeoff='先集结，再穿侧向窄口展开',signature='offset_chambers'),
    }[structure]
    design.update(defense=defense,capacity=6,validation='geometry_and_reachability; combat_effect_requires_playtest')
    return dict(name=CHOICES['structure'][structure].split('：')[0]+' / '+CHOICES['side'][side],
        intent=CHOICES['structure'][structure]+'；'+CHOICES['defense'][defense]+'；清除全部守军即展开下一段',
        selection=dict(structure=structure,side=side,props=props,defense=defense,position=position),
        design_card=design,side=sign,floors=floors,covers=covers,defenders=defenders[:3],defender_slots=defenders,
        entry=[.06,0],exit=[1.7,0],support=support,flank=flank)


CATALOG={ '_'.join(values):compose(*values) for values in itertools.product(*(list(v) for v in CHOICES.values())) }
DESCRIPTIONS={key:spec['intent']+'；'+CHOICES['props'][spec['selection']['props']]+'；'+CHOICES['side'][spec['selection']['side']] for key,spec in CATALOG.items()}

def eligible(world,hormones=None):
    keys=[k for k in world.get('options',[]) if k in CATALOG]
    h=hormones or {}
    # Pacing steers authored compositions; force budgets are chosen separately as coupled packages.
    if h.get('recovery',0)>=.6:
        keys=[k for k in keys if CATALOG[k]['selection']['defense']=='depth']
    elif h.get('pressure',0)>=.6:
        keys=[k for k in keys if CATALOG[k]['selection']['defense']=='cross']
    if h.get('teaching',0)>=.6 or h.get('expansion',0)>=.6:
        keys=[k for k in keys if CATALOG[k]['selection']['position']=='wide']
    recent=world.get('completed',[])
    if recent:
        old=CATALOG.get(recent[-1]['option'],{}).get('selection',{}).get('structure')
        alternatives=[k for k in keys if CATALOG[k]['selection']['structure']!=old]
        if alternatives:keys=alternatives
        if h.get('novelty',0)>=.6:
            previous_props=CATALOG.get(recent[-1]['option'],{}).get('selection',{}).get('props')
            alternatives=[k for k in keys if CATALOG[k]['selection']['props']!=previous_props]
            if alternatives:keys=alternatives
    return {k:DESCRIPTIONS[k] for k in keys}


def shortlist(choices, world, limit=8):
    """Small deterministic menu of compatible authored layouts, not 64 raw specs.

    Prefer new tactical structures/formations. A prop swap alone contributes
    very little to diversity. These are design descriptors, not combat scores.
    """
    recent = [CATALOG[r['option']]['selection'] for r in world.get('completed', [])[-6:]
              if r.get('option') in CATALOG]
    weights = dict(structure=3., defense=1.5, side=.5, position=.5, props=.2)
    def distance(a, b):
        return sum(w for axis, w in weights.items() if a[axis] != b[axis])
    def repetition(key):
        a=CATALOG[key]['selection']
        return sum((i+1)*(3*(a['structure']==b['structure'])
            + 2*(a['structure']==b['structure'] and a['defense']==b['defense']))
            for i,b in enumerate(recent))
    candidates=sorted((k for k in choices if k in CATALOG),key=lambda k:(repetition(k),k))
    selected=[]
    while candidates and len(selected)<limit:
        best=max(candidates,key=lambda k: (
            min((distance(CATALOG[k]['selection'],CATALOG[p]['selection']) for p in selected),default=0),
            -repetition(k)))
        selected.append(best);candidates.remove(best)
    return {k:choices[k]+'；'+CHOICES['position'][CATALOG[k]['selection']['position']]
            for k in selected}
