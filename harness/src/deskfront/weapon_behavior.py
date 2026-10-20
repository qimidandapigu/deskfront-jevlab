"""Advisory current-weapon habits composed into existing tactical requests.

This module never selects a role, route, target or action. It reads only the
already-filtered model context, keeps unknown facts unknown, and has no I/O.
"""
import copy


VERSION = 'weapon-behavior/v1'
INSTRUCTIONS = '''# 当前兵种行为习惯插槽
先读weapon_behavior_slots：common是共同约束，habits是软习惯，actors按本兵本次真实weapon绑定，不按名字、出生兵种或队友武器套用。未知兵种没有默认步枪习惯。
每题只把本兵习惯与current_plan、已接受职责、该兵execution_evidence及候选射界/路线事实组合比较；习惯不是强制职责、阵型、距离门槛或动作许可。混编不要求固定几人掩护、几人突击，不等队友开火或装填才允许移动。
已有效射击不为更近而继续贴近；受阻、目标移动、任务、危险或换装时按新事实复评。距离和散布不是命中概率，不能把射程内等同于可开火。小队应选符合本兵射位收益的实际路线终点，不能靠个人短停永久覆盖上级路线。
个人若有hold_fire_position选项，可明确选择在当前位置短期保持射位；这不是停火，也不下达新路线。时长、可用性和真实终态看personal_action_capabilities/firing_hold；结束后原上级路线可能继续。focus_fire指定目标且取消当前运动执行，不保证保留原执行；需要保留已接受路线时比较hold_fire_position，不把两者当成相同成本，也不强制选择保持射位。
'''

HABITS = {
    'rifle': {
        'name': '步枪：有效射界与中距掩护',
        'role_tendency': '比较建立有效射界与掩护职责；分工仍由本题选择，不把指挥中心或敌人身边当作必达点。',
        'spacing': '优先在当前武器射程内利用中距射位；中距是定性软习惯，不是固定范围、最优距离或安全保证。',
        'continue_approach_when': '当前射界受阻、目标在射程外或任务确需推进时，比较合法侧移、探头、绕障与继续机动，不挤同一堵墙。',
        'stop_or_hold_when': '已有真实有效射界时优先比较停稳射击、保持射位；不只因更近散布更小就冲到贴身。小队选择适合持续射击的实际终点。',
        'review_when': '射界/目标、实际火力效果、任务或危险改变时复评；必要冲刺、撤离与近身自卫仍可选。',
    },
    'smg': {
        'name': '冲锋枪：借遮挡接近后集中火力',
        'role_tendency': '比较机动接近、共同推进和暂时掩护，不固定分工人数，不把掩护标签当作队友已经开火。',
        'spacing': '借遮挡取得近距火力位置；preferred_distance_hint仅是建议，不删其他合法候选，也不要求贴身。',
        'continue_approach_when': '当前远距火力持续低效且合法接近方案有实际收益时，比较move_to_site/rush_to_site/prone_approach；不以队友先开火为许可。',
        'stop_or_hold_when': '已取得有效火力位置或承担阶段守备时比较停稳射击与保持；不为更近而自动继续冲。冲刺不保证能边跑边打。',
        'review_when': '实际火力效果、目标、遮挡、通路、任务或原生危险改变时复评，不因兵种叫冲锋枪就忽视危险。',
    },
    'rocket': {
        'name': '火箭：安全射距、破甲与破障',
        'role_tendency': '优先比较反坦克、破障和爆炸火力支援；机动用于取得射界，不以接近敌人或踩到队级目标为完成条件。',
        'spacing': '保留符合真实近炸、友军、枪口检查的安全射距；不凭空设置固定安全距离，不能把射程内称作安全。',
        'continue_approach_when': '当前无法有效射击或任务需要时比较合法换位；障碍可破坏时比较直接破障，不盲目绕到贴身。',
        'stop_or_hold_when': 'rocket_fire_options显示有效且安全的射击/破障机会时比较保持输出；冷却是事实，无限弹药不等于没有冷却。',
        'review_when': '结合rocket_impact、目标、射界、友军与近炸安全改变复评；危险撤离、明确局部机动和必要自卫仍可选。',
    },
}


def build(context, role):
    """Bind habits to current weapons; keep facts in their authoritative block."""
    personal = role == 'personal'
    units = [context.get('self', {})] if personal else context.get('members', [])
    actors, used = {}, {}
    for unit in units:
        if not isinstance(unit, dict) or not unit.get('id'):
            continue
        uid, weapon = unit['id'], unit.get('weapon')
        assignment_path = 'assignment' if personal else 'accepted_assignments.' + uid
        assignment = (context.get('assignment', {}) if personal else
                      context.get('accepted_assignments', {}).get(uid, {}))
        if not assignment and not personal:
            assignment = context.get('engine_squad', {}).get('assignments', {}).get(uid, {})
            assignment_path = 'engine_squad.assignments.' + uid
        candidate_key = 'candidate_sites' if personal else 'member_region_choices'
        actors[uid] = dict(current_weapon=weapon, habit_id=weapon if weapon in HABITS else None,
                          assigned_role=assignment.get('assigned_role', assignment.get('role')),
                          weapon_range=unit.get('weapon_range'),
                          facts_path='execution_evidence' if personal else 'execution_evidence.members.' + uid,
                          assignment_path=assignment_path if assignment else None,
                          candidates_path=('candidate_sites' if personal else 'member_region_choices.' + uid)
                          if candidate_key in context and (personal or uid in context[candidate_key]) else None)
        if weapon in HABITS:
            used[weapon] = copy.deepcopy(HABITS[weapon])
    return dict(schema=VERSION, authority='soft_habits_not_action_filter',
                common='当前任务、合法候选和原生危险/执行权约束优先；事实未知保持未知，模型仍选择本题动作。',
                habits=used, actors=actors)
