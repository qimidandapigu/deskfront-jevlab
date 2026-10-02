import { fileURLToPath } from 'node:url';
import type { GamePlugin } from '../../arena/plugin.js';
import { JUMP_LEVELS } from './levels.js';
import { createAssistedJumpGame } from './assisted.js';
import { INPUT_LABELS, DURATION_LABELS, TIMED_LABELS } from './adapter.js';

export const jumpPlugin: GamePlugin = {
  id: 'jump',
  name: '萤光小径',
  mode: 'realtime',
  experience: { genre: '森林平台冒险', duration: '8 关 · 逐步进阶', goal: '拿钥匙 → 踩红色开关 → 集齐金币 → 到达旗帜。', tip: '按住跳跃跳得更高，松开则小跳。落水会回到起点，已收集的物品保留。', accent: '#85c8ff', symbol: '↗' },
  variants: JUMP_LEVELS.map(({ id, name }) => ({ id, name })),
  create: variant => createAssistedJumpGame((JUMP_LEVELS.find(l => l.id === variant) ?? JUMP_LEVELS[0]!).level) as ReturnType<GamePlugin['create']>,
  description: '辅助路线模式：模型选择落脚点，本地控制器执行完整跳跃，落稳后再决策；包含物理寻路辅助，不代表模型独立按键通关。通关需要钥匙、开关、全部金币和终点旗。自己玩仍使用方向键与跳跃键。',
  optionLabels: { ...INPUT_LABELS, ...DURATION_LABELS, ...TIMED_LABELS },
  humanControls: {
    help: '← → 或 A/D 移动，↑ / W / 空格跳（空中带方向即左跳/右跳）',
    keys: { ArrowLeft: 'left', a: 'left', ArrowRight: 'right', d: 'right', ArrowUp: 'jump', w: 'jump', ' ': 'jump' },
    combos: { 'jump+left': 'jumpLeft', 'jump+right': 'jumpRight' },
    priority: ['jump', 'left', 'right'],
  },
  clientScript: fileURLToPath(new URL('./client.js', import.meta.url)),
};
