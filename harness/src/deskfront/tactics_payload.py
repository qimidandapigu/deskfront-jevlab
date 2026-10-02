"""Payload projection for the tactical decision client.

The coordinator remains the owner of live state; this module only assembles the
provider-facing snapshot and candidate question from that state.
"""
import copy
import math

def build_payload(self, obs):
    options = self.options(obs)
    with self.lock:
        task = {'plan': copy.deepcopy(self.plan), 'role': self.plan.get('roles', {}).get(obs['self']['id']), 'version': self.version}
    state = copy.deepcopy(obs)
    with self.lock:
        state['execution_feedback'] = copy.deepcopy(self.units.get(obs['self']['id'], {}))
        state['team_execution'] = copy.deepcopy(self.units)
    state['recent_execution_events'] = copy.deepcopy(self.events[-8:])
    state['spatial_tools'] = self.spatial(obs)
    from objective_timing import build as objective_timing
    uid=obs['self']['id']
    timing=objective_timing(obs,[obs['self']],{uid:state['execution_feedback']},
                            {uid:state['spatial_tools']})
    state['objective_timing']=dict(timing['units'].get(uid,{}),basis=timing['basis'])
    state['recovery_rules'] = '三路前哨步兵双方同规则：连续6秒未受伤或开火、压制不超过0.2且不在敌人有效射界内，每游戏秒恢复2血，不复活。伤员可撤出交火恢复，健康队友接替；无需等满血。' if self.routes else '当前关卡未启用脱战回血'
    state['disengagement_guidance']='先看 threat_forecast 的站立暴露、射击准备时间和路径暴露，不必等掉血。预测假设敌人位置不变，不是命中保证；unknown 不是安全。路线仅给方向，比较射位火力收益与途中威胁；没有威胁时不要仅因爬行更安全而反复改姿态。'+'early_retreat_warning 表示已出现早期撤离信号（压制>=0.35、4秒伤害>=15，或低于65%血且受威胁），不是强制动作。此时优先比较 shelter 短途遮断射线，不等重伤满压制才保护。安全撤离期间优先保持仍有效路径；敌情变化再调整。队友有撤离信号时考虑接替射位或守旗，不能全队追敌。'
    from task_tools import board
    from strategic_regions import catalog,model_catalog
    state['strategic_regions']=model_catalog(catalog(self.routes,self.world))
    from tactical_map_view import build as tactical_map_view
    state['tactical_map']=tactical_map_view(self.world)
    from stage_execution import status
    state['stage_status']=status(self.plan.get('tasks',{}),self.units)
    state['cooperation_board']=board(self.world,self.plan.get('tasks',{}),self.routes)
    state['region_choices']=copy.deepcopy(self.units.get(obs['self']['id'],{}).get('region_choices',
                                          {'query_status':'unknown_no_topology','options':[]}))
    state['execution_feedback'].pop('health_samples',None)
    for row in state['team_execution'].values():row.pop('health_samples',None)
    from stage_execution import fire_status
    state['fire_status']=fire_status(obs['self'],obs['enemies'],obs['time'])
    from micro_context import build
    state['micro_combat']=build(obs['self'],obs['enemies'],state['spatial_tools'],obs['time'])
    state['target_comparison'] = [dict(id=e['id'],hp=e['hp'],distance=round(math.dist(e['position'],obs['self']['position']),3),
        nearby_enemies=sum(v['id']!=e['id'] and math.dist(v['position'],e['position'])<.35 for v in obs['enemies']),
        allies_engaging=[v['id'] for v in obs['allies'] if v.get('last_shot_target')==e['id'] and obs['time']-v.get('last_shot_at',-10)<4])
        for e in obs['enemies'] if e['hp']>0 and e.get('combat_ready',True)]
    for key in ('building', 'at_guns'):
        state.pop(key, None)
    state['enemies'] = [v for v in state['enemies'] if v.get('combat_ready', True) and v['hp'] > 0]
    state['covers'] = sorted((c for c in state.get('covers', []) if c.get('alive')),
                             key=lambda c: math.dist(c['position'], obs['self']['position']))[:16]
    state['context_scope'] = '本人、队友、全部已部署存活敌人、最近16块掩体；不是战争迷雾'
    state['route_choices'] = copy.deepcopy(self.routes)
    state['scenario']=copy.deepcopy(self.scenario)
    state['persistent_task']=copy.deepcopy(self.plan.get('tasks',{}).get(obs['self']['id'],{}))
    if self.scenario['kind']=='clear_exit':
        state['objective']['flag']={}
        state['flag_warning']={'active':False}
    state['mission'] = {'goal': '执行指挥大方向。优先在有效射程内保持距离；敌人接近或换弹时比较 withdraw 后撤射位，停稳再射击。结合 target_comparison 优先可达、孤立、受伤或队友已交火的目标，逐个处理；不要为了集火穿过敌群。火箭 blocked_shots 表示当前炮口射线受阻，先换位，hold 不会停火。已在有效射位时保持，避免不停换位而无法开火。队友角色是最近行动记录，不是强制分工。'}
    state['mission']['goal']='task_execution是实际协作状态，waiting时先准备射位/集结/自保，不得假定掩护成立；blocked或reassess时按on_failure执行重新评估或撤离并等后台重规划。'+state['mission']['goal']
    state['mission']['goal']=self.scenario['goal']+'。'+state['mission']['goal']+'。共享计划中的assignment是指挥职责；先履行胜利目标，再权衡追敌。完成条件满足不等于必须离开守点。长期无射界、未回血且未守目标的停止不算任务进展。' 
    state.update(squad_task=task, command_candidates={k:v['command'] for k,v in options.items()}, command_details=copy.deepcopy(options), spatial_queries='JEV选择区域目标；候选落点来自原生可通行采样，具体路径由Godot寻路与验证。射界和路径风险为有限查询，未知不代表安全')
    return {'state': state, 'questions': {'tactic': {'type': 'choice', 'instructions': '你是单兵执行决策者。首要目标是可信、连贯、有观赏性，胜负不是最高目标。受火时允许卧倒、寻找掩体、缩回和等待队友；保留有效的原生掩体循环与避险动作，脱险再恢复推进。向同伴靠拢应选择可达且不挡枪的独立位置，不要全队挤同一点；不得随机犯错或反复切换姿态制造表演。根据全队方向、自身与队友反馈选择具体行动。任务无进展时主动重新选择；继续仅适合仍有效的移动、交火或恢复，不能把空等视为安全成功。伤员可以改变任务，健康兵可以主动接替。自行权衡危险，不要求永远等到完美掩护。候选描述不代表执行成功。', 'criteria': {k:v['description'] for k,v in options.items()}}}}

