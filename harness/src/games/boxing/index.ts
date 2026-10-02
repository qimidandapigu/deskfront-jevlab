import { fileURLToPath } from 'node:url';
import type { GamePlugin } from '../../arena/plugin.js';
import { createBoxingGame } from './adapter.js';

export const boxingPlugin: GamePlugin = {
  id: 'boxing',
  name: '打拳',
  mode: 'realtime',
  experience: { genre: '距离与反击', duration: '45 秒一局', goal: '击倒对手，或在倒计时结束时保有更多血量。', tip: 'Shift 冲刺接近，W 跳跃避投。J 命中立刻接 K，气满 50 再接 I 必杀；打空不能取消收招。', accent: '#ffb86b', symbol: 'VS' },
  variants: [{ id: 'match', name: '正式对战' }, { id: 'practice-idle', name: '练习：距离与命中', rival: false }, { id: 'practice-guard', name: '练习：抱摔破防', rival: false }, { id: 'practice-heavy', name: '练习：重拳反击', rival: false }],
  create: variant => createBoxingGame(variant?.startsWith('practice-') ? variant : undefined) as ReturnType<GamePlugin['create']>,
  description: '街机对打：刺拳快，适合截击；重拳伤害高，但打空后收招很长；抱摔破解贴身格挡。后退诱使对手打空，再前进抓收招，额外 +2 伤害。头顶显示起手 / 判定 / 收招，蓝色火花表示格挡，PUNISH 表示反击。练习开局有100气，仍是45秒：对手分别站立、持续格挡或重复重拳。先靠近再试招。AI 异步决策，战斗不停表。',
  optionLabels: { idle: '站立', advance: '前进', retreat: '后退', jab: '刺拳', heavy: '重拳', guard: '格挡', throw: '抱摔', jump: '跳跃', dash: '冲刺', special: '烈焰冲拳' },
  humanControls: {
    help: '→ / D 前进 · ← / A 后退 · J 刺拳 · K 重拳 · U 抱摔 · L 格挡 · W/↑ 跳跃 · Shift 冲刺 · I 必杀（50气）',
    keys: { ArrowRight: 'advance', d: 'advance', ArrowLeft: 'retreat', a: 'retreat', j: 'jab', k: 'heavy', u: 'throw', l: 'guard', w: 'jump', ArrowUp: 'jump', Shift: 'dash', i: 'special' },
    combos: { 'advance+jump': 'jumpForward', 'jump+retreat': 'jumpBack' },
    priority: ['special', 'jump', 'dash', 'jab', 'heavy', 'throw', 'guard', 'advance', 'retreat'],
    oneShot: ['jump', 'dash', 'special', 'jab', 'heavy', 'throw'],
  },
  clientScript: fileURLToPath(new URL('./client.js', import.meta.url)),
  sideLabels: { self: '左', rival: '右' },
};
