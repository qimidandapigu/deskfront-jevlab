"""Finite JEV goal choices when no current commander plan is available.

This is a provider menu/binding, not a tactical fallback. Only a real selected
choice installs a plan; native topology and the existing validators still bind
the destination, stage and later member routes.
"""
from human_squad_contract import STAGES

STAGE_TEXT = dict(approach='接近任务区', engage='建立交战',
                  reposition='调整接近方向', hold='守备区域', recover='局部恢复')

INSTRUCTIONS = '''你是JEV小队，当前没有可用的指挥方案。直接根据本队任务、当前成员、已知敌情、导航与执行事实，自主选择下一阶段目标，不等待指挥接口。
本题是有限Choice：每个选项同时绑定一个原生区域和可选阶段，只能选已提供的项，不能自造坐标。选择后的逐兵职责、路线与协作由下一轮小队Choice明确安排，经原生接受后执行。
清敌任务需比较接近敌军、建立射界和绕障的收益；守备任务需比较守什么、等什么和何时复评。受火、未开火、距离远均是事实，不自动禁止机动或要求冲锋。没有完美安全位置也不代表无事可做。
迟到的指挥方案只能在后续小队复核边界接入，不能撤销正在形成或已接受的路线。这里不得冒称指挥已经下令，或把计划当作已移动、已开火。'''


def choices(regions):
    criteria, options = {}, {}
    for rid, region in regions.items():
        allowed = region.get('allowed_stages', STAGES)
        for stage in STAGES:
            if stage not in allowed:
                continue
            key = 'G' + str(len(options) + 1)
            text = STAGE_TEXT.get(stage, stage)
            criteria[key] = f'{text}；区域 {rid}；位置、连通与风险事实见regions.{rid}'
            options[key] = dict(region_id=rid, stage=stage,
                objective=f'JEV自主选择：{text} · {rid}',
                risk='当前路线、射界和威胁需按原生事实复验；候选不保证安全或命中',
                wait_for='按实际进展、接触、危险及任务变化复评')
    return criteria, options


def equipment_choices(equipment, members):
    """Expose the existing validated equipment phases; never nominate crew."""
    from battlefield_equipment import validate_equipment_goal
    criteria, options = {'none': '本阶段不安排装备任务'}, {'none': None}
    phases = dict(reconnoitre='侦察炮位', attack_crew='打击已知炮组',
                  capture='接管可夺取炮位', support_fire='使用己方炮位支援')
    for gun in equipment:
        for phase, text in phases.items():
            value = dict(equipment_id=gun.get('id'), phase=phase,
                reason='JEV自主选择：' + text,
                risk='装备任务仍需原生资格、通路、射界、安全与接管状态复验')
            try:
                validate_equipment_goal(value, equipment, members)
            except ValueError:
                continue
            key = 'E' + str(len(options))
            criteria[key] = text + ' · ' + str(gun.get('id')) + '；人员由后续小队Choice明确选择'
            options[key] = value
    return criteria, options
