import { fileURLToPath } from 'node:url';
import type { GamePlugin } from '../../arena/plugin.js';
import { createSoldiersGame } from './adapter.js';

export const soldiersPlugin: GamePlugin = {
  capabilities: { seed: true },
  id: 'soldiers',
  name: '玩具兵打枪',
  mode: 'realtime',
  experience: { genre: '掩体战术', duration: '3 分钟上限', goal: '2v2 小队对抗，击倒对方两名队员获胜。', tip: '双方属性相同：100 血、10 伤害，同速同射程。自动瞄准射程内可见敌人。双方开枪都先锁定位置 0.5 秒，红线是敌方开枪预警，离开锁定点即可躲避；6 发打完退回掩体换弹，可边走边射。', accent: '#c5e884', symbol: '⌖' },
  create: (_variant, options) => createSoldiersGame(options?.seed) as ReturnType<GamePlugin['create']>,
  description: '掩体突击：自由移动、边走边射；优先瞄准射程内可见敌人。6 发弹匣，R 换弹 1.2 秒；敌人锁定位置 0.5 秒后开火，红线亮起就侧移或躲进掩体。双方各两人，击倒对方全队获胜；时间到平局。',
  optionLabels: { switch: '切换队员 · Q', 'ally-1': '绿方队员 2', reposition: '绕障找射角', short: '0.2 秒', normal: '0.5 秒', long: '1 秒', left: '左侧移', right: '右侧移', cease: '停火', 'enemy-0': '敌兵 1', 'enemy-1': '敌兵 2', player: '绿方队员 1', north: '向上', south: '向下', west: '向左', east: '向右', reload: '换弹', shoot: '开火', advance: '推进', hold: '据守', peek: '探头射击', flank: '侧移', retreat: '后撤' },
  humanControls: {
    help: 'Q 切换队员 · 队友与对手使用相同 AI 模型 · WASD / 方向键自由移动 · 按住空格 / J 连射（可边走边打）· R 换弹 · 红线锁定后立刻走开',
    events: ['switch'],
    keys: { q: 'switch', w: 'north', ArrowUp: 'north', s: 'south', ArrowDown: 'south', a: 'west', ArrowLeft: 'west', d: 'east', ArrowRight: 'east', ' ': 'shoot', j: 'shoot', r: 'reload' },
    combos: Object.fromEntries(
      [['north', 'west'], ['north', 'east'], ['south', 'west'], ['south', 'east'], ['north'], ['south'], ['west'], ['east']]
        .flatMap(parts => ['shoot', 'reload', ''].map(action => {
          const keys = action ? [...parts, action] : parts;
          return [keys.join('+'), keys.join('_')];
        })).sort((a, b) => b[0]!.split('+').length - a[0]!.split('+').length),
    ),
    priority: ['reload', 'shoot', 'north', 'south', 'west', 'east', 'hold'],
    oneShot: ['shoot'], idle: 'hold',
  },
  clientScript: fileURLToPath(new URL('./client.js', import.meta.url)),
  sideLabels: { self: '绿', rival: '红' },
};
