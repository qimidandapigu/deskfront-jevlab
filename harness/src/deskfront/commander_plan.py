"""Generated commander contracts. Rules validate facts, not select tactics."""
import copy
import math

INSTRUCTIONS='''生成整队战术任务，仅返回JSON：
tasks的键必须与上下文living_controlled_unit_ids完全一致：每个当前可控存活小兵恰好一项，已经死亡或不再可控的小兵不要分配任务。previous_plan和recent_events只是历史证据。
首要目标是可信、连贯、可读的小队行为和观赏性，胜负是情境而非最高优化目标。受火时允许卧倒、找掩体、等待同伴和重整，不为抢旗强迫伤员冒死。保持有理由的行动直到完成或敌情改变。集结应形成彼此照应的分散站位；不要挤在同一点、挡住队友枪口或反复集结打断交火。禁止虚构救援动作或以随机犯错制造戏剧。
每项任务使用真实士兵ID作键，assignment中明确写该ID；禁止用“一人、另一个、前者”代替执行者。支援任务明确支援谁(support_for=存活队友ID或空串)、攻击谁(target_id=存活敌人ID或空串)，有已知敌人时两者不能同时为空。partner是需要同步的队友，support_for是受益队友，支援不自动等于等待或跟随。写出要创造的效果与失败条件，例如为green-1压制red-2；不要只写“后方支援”。选择集中或侧击须依据可达射位与武器射程，不能要求全队默认奔向同一区域，也不能凭空宣称侧路安全。没有当前可用射位就让JEV先找位并报告失败，不要把“在支援位置”当作已经开火。
{"objective":"整局胜利目标", "stage":{"id":"阶段标识", "goal":"当前阶段目标", "next_intent":"后续意图，仅供参考"}, "intent":"协同战术", "tasks":{"我方ID":{"command":"occupy|hold|support|flank|eliminate|recover", "target_id":"敌方ID或空串", "partner":"队友ID或空串", "start_when":"immediate|partner_firing|partner_arrived", "wait_timeout_s":5, "on_failure":"reassess|withdraw", "assignment":"本兵职责和约束", "complete_when":{"type":"flag_held|target_dead|recovered|position_reached","value":60}, "replan_when":"明确的重评条件", "region_hint":"可选的参考区域ID"}}}
你决定当前阶段的目标、攻击对象、分工、协作次序和风险边界；JEV依据实时地图工具为每个兵选择下一战术区域和区域内落点，具体路线和移动由游戏引擎寻路、验证。先读tactical_map的二维位置与障碍摘要，再比较approach_corridors提供的相对侧路与射位事实，决定是否正面牵制、侧面接敌、分批占旗。若选择侧击，给执行者一个侧路中途区域ID作region_hint并在assignment写清与谁配合；不要只写“绕后”却把所有人的region_hint都指向旗心。若确有理由集中突入，在intent说明依据。地图和侧路摘要只代表空间、连通和已采样事实，不代表整路安全。region_hint只是参考，不能当作必须到达或具备射界的事实。通常不要给region_id、region_path、坐标或逐帧探头动作。若需要保留一条旧式明确路线，region_id与region_path必须成对提供，全部区域真实存在、每段相邻、路径从本兵当前区域或邻区开始且末项等于region_id；此时它们是硬约束，不是提示。
tasks仅包含当前阶段；next_intent不是可执行任务。准备阶段可用flank+position_reached描述到达由JEV选定的集结位，support+position_reached描述建立有效支援；单纯进入区域不等于能开火。占旗以objective.flag.owner为准，支援以实际射界和开火为准，不能假设尚未发生的掩护或增援。region_opportunities是候选摘要，unknown既不代表安全，也不代表不可用；不要把多个射位的优点拼成同一个万能射位。
position_reached只填写type，区域和精确位置由JEV选择并由工具验证。occupy/hold可用position_reached表示到达当前阶段位置，真正占旗完成用flag_held，value为1到胜利秒数。recover用recovered，value为生命百分比1..100；eliminate用target_dead且必须有target_id；support/flank可用position_reached或target_dead。partner_firing等待伙伴实际开火；partner_arrived必须指定partner，并等待伙伴实际到达其选定位置；wait_region_id仅用于必须在指定区域同步的特例。不能循环依赖，通常让支援兵先独立建立射界。
wait_timeout_s为2..8。partner_arrived 可直接等待伙伴由 JEV 选定的 position_reached 位置；只有必须同步到具体已知区域时才给 wait_region_id。计划覆盖全部存活成员，不能引用死者。若上轮占点兵已获推进许可却仍无位移和占点收益，不要原样重发 partner_firing 等待；改为独立前进、换职责或明确不同的协同条件。工具报告通路受阻、射程外、无可用射位或任务无进展时，应根据事实重分工；局部换位由JEV自主处理。根据血量、威胁和实际任务进展决定继续或调整，不要无故离开有效占点。intent、assignment、replan_when均为必填短字符串，每项不超过120字。'''


def validate(value,members,state,routes):
    if not isinstance(value,dict):raise ValueError('plan must be object')
    from strategic_regions import catalog
    regions=catalog(routes,state)
    ids={u['id'] for u in members}
    positions={u['id']:u['position'] for u in members}
    tasks=value.get('tasks')
    if not isinstance(tasks,dict):raise ValueError('plan must cover living squad exactly')
    task_ids=set(tasks)
    # A casualty may die while a model response is in flight. Extra tasks for
    # confirmed dead members can be discarded only if all living actors are
    # already covered; never synthesize a missing living assignment.
    dead_ids={u['id'] for u in state['units'] if u['faction']==members[0]['faction'] and u['hp']<=0}
    extra=task_ids-ids
    if not ids<=task_ids or not extra<=dead_ids:raise ValueError('plan must cover living squad exactly')
    tasks={uid:t for uid,t in tasks.items() if uid in ids}
    enemies={u['id'] for u in state['units'] if u['faction']!=members[0]['faction'] and u['hp']>0}
    def text(v):
        if not isinstance(v,str) or not v.strip() or len(v)>300:raise ValueError('invalid plan text')
        return v
    if state.get('strategic_topology') and not value.get('stage'):raise ValueError('stage required: id, goal, next_intent; tasks must describe current stage only')
    result=dict(intent=text(value.get('intent')),tasks={})
    if value.get('stage') is not None:
        stage=value['stage']
        if not isinstance(stage,dict):raise ValueError('stage must be object')
        result['stage']={k:text(stage.get(k)) for k in ('id','goal','next_intent')}
        result['objective']=text(value.get('objective'))
    for uid,t in tasks.items():
        if not isinstance(t,dict):raise ValueError('invalid task')
        t=copy.deepcopy(t)
        region=t.get('region_id')
        hint=t.get('region_hint')
        if hint is not None and (not isinstance(hint,str) or hint not in regions):
            raise ValueError(uid+': unknown region_hint '+str(hint))
        if 'region_id' in t and not region:
            raise ValueError(uid+': region_id must name a known region')
        location=t.get('complete_when',{}).get('position')
        if not region and isinstance(location,str):
            if state.get('strategic_topology'):
                raise ValueError(uid+': JEV selects the position; do not provide a region as complete_when.position')
            if location not in regions:raise ValueError(uid+': unknown position region '+location)
            region=location
        if state.get('strategic_topology') and ('region_id' in t) != ('region_path' in t):
            raise ValueError(uid+': region_id and region_path must be supplied together')
        wait_region=t.get('wait_region_id')
        if region:
            if region not in regions:raise ValueError(uid+': unknown region_id '+str(region))
            t['route']=regions[region]['route']
            if t.get('complete_when',{}).get('type')=='position_reached':
                t['complete_when']['position']=regions[region]['center'];t['complete_when']['radius']=regions[region]['radius']
        region_path=None
        if 'region_path' in t:
            if not region:
                raise ValueError(uid+': region_path requires region_id')
            from region_routing import validate_region_path
            try:region_path=validate_region_path(t['region_path'],region,regions,positions[uid],state.get('strategic_topology'))
            except ValueError as error:raise ValueError(uid+': '+str(error)) from error
        if wait_region and wait_region not in regions:raise ValueError(uid+': unknown wait_region_id '+str(wait_region))
        route=t.get('route','adaptive');target=t.get('target_id','');partner=t.get('partner','')
        if route not in routes and route!='adaptive':raise ValueError('unknown route')
        if target and target not in enemies:raise ValueError('unknown target')
        if partner and (partner not in ids or partner==uid):raise ValueError('unknown partner')
        support_for=t.get('support_for') or (partner if t.get('command')=='support' else '')
        if support_for and (support_for not in ids or support_for==uid):raise ValueError('unknown support_for')
        if t.get('actor_id',uid)!=uid:raise ValueError('actor_id must match task key')
        if t.get('command')=='support' and enemies and not target and not support_for:
            raise ValueError(uid+': support requires a named target_id or support_for')
        c=t.get('complete_when',{});kind=c.get('type')
        if kind not in ('flag_held','target_dead','recovered','position_reached'):raise ValueError('unknown completion condition')
        condition={'type':kind}
        if kind in ('flag_held','recovered'):
            number=c.get('value')
            maximum=state['objective'].get('score_to_win',60) if kind=='flag_held' else 100
            if isinstance(number,bool) or not isinstance(number,(int,float)) or not math.isfinite(number) or not 1<=number<=maximum:raise ValueError('invalid threshold')
            condition['value']=number
        if kind=='target_dead' and not target:raise ValueError('missing target')
        if kind=='position_reached':
            if state.get('strategic_topology') and not region:
                if 'position' in c or 'radius' in c:raise ValueError(uid+': JEV selects the position; do not provide coordinates')
            else:
                p=c.get('position');bounds=state['bounds']
                if not isinstance(p,list) or len(p)!=2 or any(isinstance(n,bool) or not isinstance(n,(float,int)) or not math.isfinite(n) for n in p):raise ValueError('invalid position')
                if not (bounds[0]<=p[0]<=bounds[2] and bounds[1]<=p[1]<=bounds[3]):raise ValueError('position outside bounds')
                radius=c.get('radius',.15)
                if isinstance(radius,bool) or not isinstance(radius,(int,float)) or not math.isfinite(radius) or not .08<=radius<=.3:raise ValueError('invalid arrival radius')
                condition['position']=p;condition['radius']=radius
        command=t.get('command');start=t.get('start_when');timeout=t.get('wait_timeout_s',5 if start=='immediate' else None);failure=t.get('on_failure')
        if command not in ('occupy','hold','support','flank','eliminate','recover'):raise ValueError('invalid command')
        if start not in ('immediate','partner_firing','partner_arrived') or (start!='immediate' and not partner):raise ValueError('invalid start condition')
        if isinstance(timeout,bool) or not isinstance(timeout,(float,int)) or not 2<=timeout<=8:raise ValueError('invalid wait timeout')
        if failure not in ('reassess','withdraw'):raise ValueError('invalid failure action')
        from task_modes import check, mode_id
        check(state,command,kind,bool(value.get('stage')))
        result['tasks'][uid]=dict(command=command,start_when=start,wait_timeout_s=timeout,on_failure=failure,assignment=text(t.get('assignment')),route=route,target_id=target,partner=partner,complete_when=condition,replan_when=text(t.get('replan_when')))
        result['tasks'][uid].update(actor_id=uid,support_for=support_for,task_mode=mode_id(state))
        if region:
            result['tasks'][uid]['region_id']=region
            result['tasks'][uid]['destination_area']=regions[region]
        if hint:result['tasks'][uid]['region_hint']=hint
        if region_path is not None:result['tasks'][uid]['region_path']=region_path
        if wait_region:result['tasks'][uid]['wait_area']=regions[wait_region]
        if wait_region:result['tasks'][uid]['wait_region_id']=wait_region;result['tasks'][uid]['wait_position']=regions[wait_region]['center'];result['tasks'][uid]['wait_radius']=regions[wait_region]['radius']
    for uid,t in result['tasks'].items():
        if t['start_when']=='partner_arrived' and not t.get('wait_position') and result['tasks'][t['partner']]['complete_when']['type']!='position_reached':raise ValueError('partner has no arrival destination')
        visited={uid};current=t
        while current['start_when']!='immediate':
            partner=current['partner']
            if partner in visited:raise ValueError('cyclic task dependency')
            visited.add(partner);current=result['tasks'][partner]
    return result

def progress(task,u,state):
    from task_modes import mode_id, check
    c=task.get('complete_when',{});kind=c.get('type');achieved=False
    if task.get('task_mode',mode_id(state))!=mode_id(state):
        return dict(condition=copy.deepcopy(c),achieved=False,note='任务模式已变更，需要重新规划',invalidated=True)
    check(state,task.get('command'),kind,True)
    if kind=='flag_held':
        flag=state['objective'].get('flag',{})
        achieved=flag.get('owner')==u['faction'] and flag.get('held_seconds',0)>=c['value']
    elif kind=='target_dead':achieved=any(v['id']==task.get('target_id') and v['hp']<=0 for v in state['units'])
    elif kind=='recovered':achieved=u['hp']/max(1,u.get('max_hp',100))*100>=c['value']
    elif kind=='position_reached':
        from strategic_regions import contains
        achieved=contains(u['position'],task['destination_area']) if task.get('destination_area') else bool(c.get('position') and math.dist(u['position'],c['position'])<=c.get('radius',.15))
        if task.get('region_path'):
            achieved=achieved and task.get('_region_progress',{}).get('index',0)>=len(task['region_path'])
        if task.get('command')=='support':
            target=task.get('target_id')
            combat=u.get('combat',{})
            achieved=achieved and bool(combat.get('engageable_targets')) and 0<=state['time']-u.get('last_shot_at',-100)<2.3
            if target:achieved=achieved and target in combat.get('engageable_targets',[]) and u.get('last_shot_target')==target
    return dict(condition=copy.deepcopy(c),achieved=achieved,note='完成条件已满足，请维持有效守点或重分工' if achieved else '尚未满足完成条件')
