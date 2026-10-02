"""Provider bridge for world experience regulation.

This adapter owns model/local regulation only; WorldDirector owns lifecycle,
receipts, preparation, and commit state.
"""
import copy
import math

from jev_client import checked_choice
from .director_contract import AXES, PHASES
from .context import context_chars

class MacroBridge:
    def __init__(self, state, game):
        self.state, self.game = state, game

    def regulate(self, context):
        if self.game.config.get('backend', 'mock') != 'mock':
            instructions=('你是体验分析员，在当前关进行时分析当前关，并提出下一关的体验目标。禁止选择具体关卡、道具、位置或兵力。依据可见的交火、伤亡、推进和任务结果，不把AI观战当成人类技能。仅输出JSON：'
                '{"phase":"explore|build_up|peak|relax","hormones":{"pressure":0.5,"recovery":0.5,"expansion":0.5,"teaching":0.5,"novelty":0.5},'
                '"current_analysis":"这一关已观察到什么，哪些尚不确定",'
                '"next_goal":{"experience":"下一关希望玩家经历什么","tactical_problem":"给策划者的具体战术问题","avoid":"下一关应避免重复或失衡的情况","layout_change":"根据本关current_design和战斗，下一关在路线或文具遮挡上要改变的具体关系","route_preference":"flank|direct|varied|none"},'
                '"reason":"简短依据","player_assessment":"证据与不确定性"}。'
                'phase必须从这些值选择，各强度为0到1的有限数值。若current_design存在，layout_change须指明当前九格里观察到的具体重复点与下一关预期的不同构图；不选择固定卡号或坐标。目标会在本关结束时结合最终回执再由策划者执行，不要把尚未发生的结局写成事实。')
            # Keep the full macro snapshot for local validation and the
            # experience receipt, but remove duplicate per-cell material
            # labels from the provider view.  The analyst still receives each
            # cell's card/rotation/props, routes and material profile; only
            # props_basis/material_counts that repeat the same profile are
            # de-duplicated by design_view.
            model_context=copy.deepcopy(context)
            if isinstance(model_context.get('current_design'), dict):
                from .decision_views import design_view
                model_context['current_design']=design_view(model_context['current_design'])
            previous_view=model_context.get('previous_understanding')
            if isinstance(previous_view, dict):
                model_context['previous_understanding']={
                    key: copy.deepcopy(previous_view[key])
                    for key in ('observed_at', 'world_revision', 'source', 'phase',
                                'hormones', 'assessment', 'reason',
                                'current_analysis', 'next_goal', 'player_assessment')
                    if key in previous_view
                }
            response=self.game.ask(model_context,{'regulation':dict(type='json',instructions=instructions)},role='experience_analyst')
            macro=response['answers']['regulation']['value']
            if not isinstance(macro,dict) or macro.get('phase') not in PHASES:raise ValueError('invalid_director_phase')
            h=macro.get('hormones')
            if not isinstance(h,dict) or set(h)!=set(AXES) or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in h.values()):raise ValueError('invalid_director_hormones')
            for key in ('reason','player_assessment'):
                if not isinstance(macro.get(key),str) or not macro[key].strip():raise ValueError('invalid_director_explanation')
            self.game.record(dict(type='world-macro',context=copy.deepcopy(context),
                model_context=copy.deepcopy(model_context),context_chars=context_chars(context),
                model_context_chars=context_chars(model_context),**response))
            return macro,response['requestId']
        levels = {'low': '低 0.2', 'medium': '中 0.5', 'high': '高 0.8'}
        questions = {'phase': {'type': 'choice', 'instructions': '调节战场节奏：探索、升温、高潮、舒缓，不持续加难。无玩家证据时只调观战节奏。',
            'criteria': dict(zip(PHASES, ('探索', '升温', '高潮', '舒缓')))}}
        labels = dict(pressure='交战压力', recovery='休整支持', expansion='探索扩展', teaching='明显教学机会', novelty='新鲜变化')
        for axis in AXES:
            questions[axis] = {'type': 'choice', 'instructions': '选择下一阶段'+labels[axis]+'的目标强度。不得把 AI 表现当玩家能力，强项提供发挥机会而非惩罚加难。', 'criteria': levels}
        response = self.game.ask(context, questions, role='experience_analyst')
        answers = response['answers']
        macro = dict(phase=checked_choice(answers['phase'], questions['phase']['criteria']),
            hormones={axis: {'low': .2, 'medium': .5, 'high': .8}[checked_choice(answers[axis], levels)] for axis in AXES},
            reason='依据近期战况选择阶段与五项节奏目标', player_assessment='仅有状态样本，技能与偏好证据不足；未建立长期玩家画像',
            current_analysis='模拟后端只汇总当前关状态；没有独立的战术推理',
            next_goal=dict(experience='下一关保持可推进且有掩体选择',tactical_problem='提供可到达的推进与侧路',
                avoid='避免全部路线完全暴露',layout_change='改变主路和侧路的遮挡关系',route_preference='varied'))
        self.game.record(dict(type='world-macro', context=copy.deepcopy(context),
            context_chars=context_chars(context), **response))
        return macro, response['requestId']

