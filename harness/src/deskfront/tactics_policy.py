"""Pure tactical policy constants and small scheduling predicates.

This module has no coordinator or engine state; it is intentionally safe to import
from controllers, tests, and payload builders.
"""
STYLES = {
    'covered_advance': '掩体推进：先建立射位，一人短途推进，到位开火后接替',
    'flank_pressure': '侧翼施压：正面保持火力，机动兵寻找可达侧翼射角',
    'hold_perimeter': '外围固守：圈内保留必要人员，其他成员控制接近路线',
    'regroup': '重整阵地：受压成员寻找保护，健康成员保持火力后重新推进',
    'solo_contest': '单兵争夺：独立寻找进圈机会或射击守军，不等待队友掩护和接替',
    'solo_hold': '单兵守点：利用现有保护独立守住旗点，不安排接替',
}
ROLES = {'support': '正面掩护', 'maneuver': '机动推进', 'reserve': '外围支援'}
EXECUTOR_INTERVAL = 0.5
COMMANDER_INTERVAL = 10.0
COMMANDER_EVENT_COOLDOWN = 5.0


class DecisionSchedule(dict):
    """Keep upstream urgent/stale resets inside the per-unit request rate limit."""
    def __init__(self, values, starts):
        super().__init__(values)
        self.starts = starts

    def __setitem__(self, uid, due):
        super().__setitem__(uid, max(due, self.starts.get(uid, -100) + EXECUTOR_INTERVAL))


def fit(u):
    return u['hp'] / max(1, u.get('max_hp', 100)) >= .45 and u.get('suppression', 0) < .65 and not u.get('survival_reason')


def support_ready(u, now):
    from cover_evidence import recent_support
    return recent_support(u,now)


def row_waiting(row):
    task=row.get('task_execution',{})
    return task.get('phase') in ('waiting','waiting_partner','recovering')

