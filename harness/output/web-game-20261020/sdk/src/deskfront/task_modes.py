"""Mode task contracts shared by prompting, validation and progress.

A new mode supplies allowed command/completion pairs. Conditions themselves
are implemented by commander_plan.progress; unknown modes fail closed.
"""
import json

COMMON = {'support': ('position_reached', 'target_dead'),
          'flank': ('position_reached', 'target_dead'),
          'eliminate': ('target_dead',), 'recover': ('recovered',)}
MODES = {
    'capture': dict(COMMON, occupy=('flag_held', 'position_reached'), hold=('flag_held', 'position_reached')),
    'clear_exit': dict(COMMON, occupy=('position_reached',), hold=('position_reached', 'target_dead')),
}

def mode_id(state):
    explicit=state.get('task_mode') or state.get('scenario', {}).get('kind')
    world=state.get('world_growth', {})
    name=explicit or ('clear_exit' if world.get('enabled') or 'mission' in world else 'capture')
    if name not in MODES:raise ValueError('unknown task mode: '+str(name))
    return name

def check(state, command, condition, stage=False):
    name=mode_id(state)
    allowed=MODES[name].get(command, ())
    if condition not in allowed:
        raise ValueError(f'{name}: command {command} allows {allowed}, got {condition}')
    if name=='capture' and command in ('hold','occupy') and condition=='position_reached' and not stage:
        raise ValueError('capture: command requires flag_held unless arrival stage supplied')

def contract(state):
    name=mode_id(state)
    return {'mode':name,'command_completions':MODES[name],
            'goal':('保持旗帜控制' if name=='capture' else '消灭敌方；守阵地不等于守旗；到位不等于清场')}

def instructions(base,state):
    if mode_id(state)=='clear_exit':
        # Remove capture-specific guidance rather than append contradictory rules.
        lines=[line for line in base.splitlines() if not line.startswith('position_reached只填写')]
        base='\n'.join(lines).replace('flag_held|','').replace('分批占旗','分批推进').replace('旗心','目标区').replace('占旗以objective.flag.owner为准，','').replace('不为抢旗强迫伤员冒死','不为推进强迫伤员冒死')
    return base+'\n当前模式任务契约（只能使用其中列出的命令与完成条件配对）：'+json.dumps(contract(state),ensure_ascii=False)+'\nposition_reached由JEV选择位置；target_dead必须指定存活敌方target_id；recovered阈值1..100。'
