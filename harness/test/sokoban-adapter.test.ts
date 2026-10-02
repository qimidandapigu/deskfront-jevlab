import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createSokobanGame } from '../src/games/sokoban/adapter.js';
import type { SokobanState } from '../src/games/sokoban/engine.js';

const ROWS = [
  '########',
  '#      #',
  '# .    #',
  '# $    #',
  '# @    #',
  '#      #',
  '#      #',
  '########',
];

const CTX = { turn: 1, recent: [] as string[], feedback: null as string | null };
const answer = (choice: string) => ({
  action: { type: 'choice' as const, choice, probabilities: { [choice]: 1 }, confidence: 1 },
  deadlockRisk: { type: 'score' as const, score: 0, probabilities: { '0': 1 }, confidence: 1 },
});

interface PushView {
  id: string; walkSteps: number; onGoal: boolean; deadlock: boolean;
  triedFromThisPosition: number; returnsToVisitedPosition: number;
}
interface SokobanObs {
  entities: { player: { x: number; y: number } };
  availablePushes: PushView[];
  visitsToThisPushPosition: number;
  recentDecisions: Array<{ choice: string }>;
  remainingGoals: Array<{ x: number; y: number }>;
  assignmentGuidance: string;
}

test('observe: 推箱级观测含 availablePushes 与访问记忆', () => {
  const game = createSokobanGame(ROWS);
  const obs = game.observe(game.initialState(), CTX) as unknown as SokobanObs;
  assert.deepEqual(obs.entities.player, { x: 2, y: 4 });
  const up = obs.availablePushes.find(p => p.id === 'push-A-U');
  assert.ok(up && up.walkSteps === 0 && up.onGoal === true && up.deadlock === false);
  assert.equal(up.triedFromThisPosition, 0);
  assert.equal(up.returnsToVisitedPosition, 0);
  assert.equal(obs.visitsToThisPushPosition, 1);
  assert.deepEqual(obs.remainingGoals, [{ x: 2, y: 2 }]);
  assert.deepEqual(obs.recentDecisions, []);
  assert.ok(obs.assignmentGuidance.includes('死锁'));
});

test('observe: 纯函数，重复调用结果一致且不累积记忆', () => {
  const game = createSokobanGame(ROWS);
  const state = game.initialState();
  const a = game.observe(state, CTX);
  const b = game.observe(state, CTX);
  assert.deepEqual(a, b);
});

test('questions: action 选项是推箱 id，带中文标签与警告后缀', () => {
  const game = createSokobanGame(ROWS);
  const qs = game.questions(game.initialState());
  const action = qs['action'];
  assert.ok(action && action.type === 'choice');
  assert.equal(action.label, '动作');
  assert.ok(Object.keys(action.criteria).every(k => /^push-[A-D]-[UDLR]$/.test(k)), '初始局面没有 undo 选项');
  assert.ok(action.criteria['push-A-U']!.includes('把 A 箱向上推到 (2,2)'));
  assert.ok(action.criteria['push-A-U']!.includes('到达目标点'));
  const risk = qs['deadlockRisk'];
  assert.ok(risk && risk.type === 'score');
  assert.equal(risk.label, '死锁风险');
});

test('act: 推箱 id 自动走位并推箱，上目标即终局', () => {
  const game = createSokobanGame(ROWS);
  const r = game.act(game.initialState(), answer('push-A-U'));
  assert.equal(r.feedback, null);
  assert.ok(game.isTerminal(r.state));
});

test('act: 推箱后可 undo 恢复（含走位），空栈 undo 报错', () => {
  const game = createSokobanGame(ROWS);
  const initial = game.initialState();
  const pushed = game.act(initial, answer('push-A-L'));
  assert.equal(pushed.feedback, null);
  assert.notDeepEqual(pushed.state, initial);
  // undoStack 非空，questions 出现 undo 选项
  const qs = game.questions(pushed.state);
  const action = qs['action']!;
  assert.ok(action.type === 'choice' && action.criteria['undo']!.includes('撤销上一次推箱决策'));
  const undone = game.act(pushed.state, answer('undo'));
  assert.equal(undone.feedback, null);
  assert.deepEqual(undone.state, initial);
  // 栈已空，再 undo 报错
  const again = game.act(undone.state, answer('undo'));
  assert.ok(again.feedback && again.feedback.includes('撤销'));
  assert.equal(again.state, undone.state);
});

test('act: 记忆只在 act 成功后更新（tried / pushVisits / recentDecisions）', () => {
  const game = createSokobanGame(ROWS);
  const initial = game.initialState();
  const pushed = game.act(initial, answer('push-A-L'));
  const obs1 = game.observe(pushed.state, CTX) as unknown as SokobanObs;
  assert.equal(obs1.visitsToThisPushPosition, 1);
  assert.equal(obs1.recentDecisions.length, 1);
  assert.equal(obs1.recentDecisions[0]!.choice, 'push-A-L');
  const undone = game.act(pushed.state, answer('undo'));
  const obs2 = game.observe(undone.state, CTX) as unknown as SokobanObs;
  // 回到初始局面：访问计 2（初始 + undo 回来），push-A-L 已试 1 次且会回到旧局面
  assert.equal(obs2.visitsToThisPushPosition, 2);
  const left = obs2.availablePushes.find(p => p.id === 'push-A-L')!;
  assert.equal(left.triedFromThisPosition, 1);
  assert.equal(left.returnsToVisitedPosition, 1);
  assert.equal(obs2.recentDecisions.length, 2);
  assert.equal(obs2.recentDecisions[1]!.choice, 'undo');
});

test('observe: 角落箱子列入 corneredBoxes', () => {
  const game = createSokobanGame([
    '########',
    '#$     #',
    '#      #',
    '#      #',
    '#    . #',
    '#  @   #',
    '#      #',
    '########',
  ]);
  const obs = game.observe(game.initialState(), CTX) as { facts: { corneredBoxes: Array<{ x: number; y: number }> } };
  assert.deepEqual(obs.facts.corneredBoxes, [{ x: 1, y: 1 }]);
});

test('act: 非法推箱 id 不推进并给出反馈', () => {
  const game = createSokobanGame(ROWS);
  const before: SokobanState = game.initialState();
  const r = game.act(before, answer('push-Z-U'));
  assert.equal(r.state, before);
  assert.ok(r.feedback && r.feedback.includes('push-Z-U'));
  // 非法动作不污染记忆
  const obs = game.observe(before, CTX) as unknown as SokobanObs;
  assert.equal(obs.visitsToThisPushPosition, 1);
  assert.equal(obs.recentDecisions.length, 0);
});

test('act: 推箱返回 playMs（走位动画时长）供观战端节奏控制', () => {
  const game = createSokobanGame(ROWS);
  const r = game.act(game.initialState(), answer('push-A-U'));
  assert.equal(r.feedback, null);
  assert.ok((r.playMs ?? 0) > 0);
  const longer = createSokobanGame(ROWS);
  const walkAndPush = longer.act(longer.initialState(), answer('push-A-D'));
  assert.ok((walkAndPush.playMs ?? 0) > r.playMs!, '需要绕路的推箱动作应留出更长播放时间');
});

test('上目标也能撤销，玩家不会被进度规则锁死', () => {
  const game = createSokobanGame(['########', '# .  . #', '# $  $ #', '# @    #', '#      #', '#      #', '#      #', '########']);
  const initial = game.initialState();
  const result = game.act(initial, answer('U'));
  assert.equal(result.feedback, null);
  assert.equal(game.isTerminal(result.state), false);
  const restored = game.act(result.state, answer('undo'));
  assert.equal(restored.feedback, null);
  assert.deepEqual(restored.state, initial);
});
