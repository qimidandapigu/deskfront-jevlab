import { fileURLToPath } from 'node:url';
import type { GamePlugin } from '../../arena/plugin.js';
import { createSokobanGame } from './adapter.js';

export const SOKOBAN_LEVELS: { id: string; name: string; rows: string[] }[] = [
  { id: 'first-push', name: '入门 1 · 第一次推箱', rows: [
    '########', '#      #', '#  .   #', '#  $   #', '#  @   #', '#      #', '#      #', '########',
  ] },
  { id: 'two-goals', name: '入门 2 · 绕到箱子背后', rows: [
    '########', '#      #', '# .  . #', '# $  $ #', '# @    #', '#      #', '#      #', '########',
  ] },
  {
    id: 'gravel',
    name: '第1关 · 碎石阵 ★★★',
    rows: [
      '########',
      '#      #',
      '# # $  #',
      '#  @$. #',
      '#      #',
      '#.  .$ #',
      '#      #',
      '########',
    ],
  },
  {
    id: 'twin-halls',
    name: '第2关 · 双箱回廊 ★★★',
    rows: [
      '########',
      '#     ##',
      '#      #',
      '#  .#  #',
      '#  *@$ #',
      '#  .$  #',
      '#  #   #',
      '########',
    ],
  },
  {
    id: 'triangle',
    name: '第3关 · 三角牵制 ★★★★',
    rows: [
      '########',
      '#   #  #',
      '#.   . #',
      '#  @   #',
      '#. $ $ #',
      '#   $  #',
      '#      #',
      '########',
    ],
  },
  {
    id: 'wall-pair',
    name: '第4关 · 贴墙二连 ★★★★',
    rows: [
      '########',
      '#      #',
      '#   #  #',
      '#  $   #',
      '# #@$ .#',
      '#  $.. #',
      '#      #',
      '########',
    ],
  },
  {
    id: 'edge',
    name: '第5关 · 死角边缘 ★★★★',
    rows: [
      '########',
      '#      #',
      '#  $   #',
      '# . .  #',
      '#    # #',
      '## $ # #',
      '#+$    #',
      '########',
    ],
  },
  {
    id: 'sandwich',
    name: '第6关 · 上下夹击 ★★★★★',
    rows: [
      '########',
      '#.   # #',
      '#   $@##',
      '#  $ $ #',
      '#      #',
      '#      #',
      '#   . .#',
      '########',
    ],
  },
  {
    id: 'deep-store',
    name: '第7关 · 高墙深仓 ★★★★★',
    rows: [
      '##########',
      '#   .    #',
      '#   $    #',
      '#  ###   #',
      '# . $ #  #',
      '#  ##    #',
      '# @  $ . #',
      '#        #',
      '#        #',
      '##########',
    ],
  },
  {
    id: 'loop-maze',
    name: '第8关 · 回字迷宫 ★★★★★',
    rows: [
      '##########',
      '#        #',
      '# ###### #',
      '# #    $ #',
      '# # $  . #',
      '# # ##   #',
      '# #  @   #',
      '# ######.#',
      '#        #',
      '##########',
    ],
  },
];

export const sokobanPlugin: GamePlugin = {
  id: 'sokoban',
  name: '推箱子',
  mode: 'turn',
  experience: { genre: '空间解谜', duration: '不限时 · 10 关', goal: '把每个木箱推到一个金色标记处。只能推，不能拉。', tip: '方向键或 WASD 移动，Z 撤销。先从两关入门练习开始；推错了随时退一步。', accent: '#f2cf83', symbol: '▧' },
  variants: SOKOBAN_LEVELS.map(({ id, name }) => ({ id, name })),
  create: (variant) => {
    const level = SOKOBAN_LEVELS.find(l => l.id === variant) ?? SOKOBAN_LEVELS[0]!;
    return createSokobanGame(level.rows) as ReturnType<GamePlugin['create']>;
  },
  description: '把所有木箱推到金色标记处。只能推不能拉，箱子推进无目标的死角就无法挽回（观测中 facts.corneredBoxes 会列出已卡死的箱子）。每次从候选推箱动作中选一个，走位由引擎自动完成，失误可撤销上一次推箱。AI 观战：右侧显示每个候选推箱的概率分布与死锁风险评分。',
  optionLabels: { U: '上', D: '下', L: '左', R: '右' },
  clientScript: fileURLToPath(new URL('./client.js', import.meta.url)),
};
