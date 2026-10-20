"""Immutable prompt and event contract for the human squad controller.

Keeping these public values separate makes the controller easier to audit while
preserving the import surface of :mod:`human_squad`.  This module must stay
free of runtime state and engine dependencies: it describes the protocol, it
does not schedule requests or execute orders.
"""

INTENTS = {
    'advance': '结伴推进：需要接近目标、尚无有效交火时按各成员路线前进；受火由引擎自保，不要求先有压制',
    'cover': '建立保护：先沿各成员明确选择的路线到任务保护位置，再观察和复评；当前位置有掩体不代表已到所选位置，装填或队友没开火不阻止移动',
    'bound': '交替推进：按明确分工与所选路线轮换机动；近期射击、弹药和装填是风险事实，不是其他成员移动的许可；缺少实际火力不称作已经受到掩护，真实危险仍由引擎处理',
    'flank': '分路接敌：正面火力与另一接近路线能共同作用于已知战区时分路；绕行有时间代价，左右标签本身不是收益',
    'hold': '任务区驻守：选择守备目的和成员区域路线，未到位先前往所选区域；已到位可继续有效守备或等敌进入，不用无意义换位。每次续守明确复评依据；距离远或暂时没敌人不自动否决守备',
    'regroup': '任务内重整：按各成员明确选择的路线到收拢或恢复位置；可以保持已有有效位置，不自动替换为原集合点或后方掩体，无可见敌人不等于需要后撤',
}
LOCAL_EVENTS = {'survival_review_due', 'incoming_explosive', 'new_contact', 'contact_lost', 'danger_close', 'new_threat',
                'suppression', 'suppression_started', 'cover_lost', 'cover_destroyed',
                'member_lost', 'unit_lost', 'support_lost', 'support_interrupted', 'support_restored',
                'arrived', 'squad_arrived', 'path_blocked', 'squad_blocked',
                'order_blocked', 'order_complete', 'navigation_changed', 'stage_review_due', 'task_review_due', 'cooperation_review_due', 'participation_gap', 'equipment_changed'}
PLAN_EVENTS = {'member_lost', 'unit_lost', 'cover_destroyed', 'path_blocked',
               'squad_blocked', 'order_blocked', 'order_complete', 'squad_arrived', 'arrived',
               'navigation_changed', 'plan_invalid', 'stage_review_due', 'participation_gap', 'equipment_changed'}
CRITICAL_EVENTS = {'incoming_explosive', 'danger_close', 'new_threat', 'cover_lost', 'cover_destroyed',
                   'member_lost', 'unit_lost', 'support_lost', 'support_interrupted',
                   'path_blocked', 'squad_blocked', 'order_blocked', 'navigation_changed'}
EVENT_ALIASES = {'cover_ready': 'order_complete', 'regrouped': 'order_complete', 'contact_acquired': 'new_contact', 'ally_down': 'member_lost',
                 'route_failed': 'path_blocked', 'cooperation_member_terminal': 'cooperation_review_due'}
EVENT_TEXT = {'survival_review_due': '成员当前藏身保护已被原生判定无效，需要重审位置与任务；不自动撤退，原生即时安全仍优先', 'incoming_explosive': '发现来袭爆炸物，引擎立即避险并重审协作', 'authority_changed': '已同步本局控制权', 'new_contact': '发现新的敌方目标',
              'danger_close': '敌人进入近距离危险范围', 'member_lost': '小队成员倒下',
              'cover_destroyed': '原有掩体已损毁', 'cover_lost': '原有位置不再遮挡当前威胁',
              'path_blocked': '当前行进或协作条件受阻',
              'support_lost': '掩护火力中断', 'support_restored': '观察到对应威胁的实际火力恢复，供重新评估协作风险；不是移动许可', 'arrived': '小队到达目标区域',
              'navigation_changed': '地形变化，需要重新检查通路',
              'plan_invalid': '当前目标区域不可达，需要重新规划', 'order_started': '引擎开始维护小队行动',
              'stage_review_due': '阶段观察期限已到，需要评估继续、推进或重整',
              'task_review_due': '成员已到任务区域，本次保持观察窗口结束，需要模型复评是否续守；不自动冲锋或重播路线',
              'cooperation_review_due': '本次配合成员步骤已完成、失败或到期，按真实state与reason复核；未变成员继续，失败步骤不能续期或自动复活',
              'participation_gap': '部分成员持续没有接近或火力贡献，需要重审位置与任务',
              'equipment_changed': '已发现炮位的控制、操作或接管条件改变，需要重新比较当前方案'}
STAGES = {'approach', 'engage', 'recover', 'reposition', 'hold'}
# Compatibility exports; runtime composes only capabilities present this turn.
from combat_prompt import instructions
PLAN_INSTRUCTIONS = instructions('commander', {}, clear=False, all_capabilities=True)
CLEAR_PLAN_INSTRUCTIONS = instructions('commander', {}, clear=True, all_capabilities=True)
EXECUTOR_INSTRUCTIONS = instructions('executor', {}, all_capabilities=True)

__all__ = [
    "INTENTS", "LOCAL_EVENTS", "PLAN_EVENTS", "CRITICAL_EVENTS",
    "EVENT_ALIASES", "EVENT_TEXT", "STAGES", "PLAN_INSTRUCTIONS",
    "CLEAR_PLAN_INSTRUCTIONS", "EXECUTOR_INSTRUCTIONS",
]
