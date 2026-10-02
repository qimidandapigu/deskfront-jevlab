import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createMockSystemOne } from '../src/systemone/mock.js';

test('mock: choice 确定性选第一个选项，概率和为 1', async () => {
  const backend = createMockSystemOne();
  const answers = await backend.ask({ board: '...' }, {
    move: { type: 'choice', instructions: '下一步', criteria: { U: '向上', D: '向下', L: '向左' } },
    risk: { type: 'score', instructions: '死锁风险', levels: { '0': '无', '1': '中', '2': '高' } },
    stuck: { type: 'noul', instructions: '是否卡死' },
  });
  const move = answers['move'];
  assert.ok(move && move.type === 'choice');
  assert.equal(move.choice, 'U');
  const sum = Object.values(move.probabilities).reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(sum - 1) < 1e-9);
  assert.equal(typeof move.confidence, 'number');
  const risk = answers['risk'];
  assert.ok(risk && risk.type === 'score' && typeof risk.score === 'number');
  const stuck = answers['stuck'];
  assert.ok(stuck && stuck.type === 'noul' && stuck.noul === 0.5);
  if ('confidence' in stuck) {
    assert.equal(typeof stuck.confidence, 'number');
    assert.ok(stuck.confidence! >= 0 && stuck.confidence! <= 1, 'noul 的 confidence 应在 [0,1]');
  }
});

test('mock: 单选项 choice 概率为 1，概率和为 1', async () => {
  const backend = createMockSystemOne();
  const answers = await backend.ask({}, {
    only: { type: 'choice', instructions: 'x', criteria: { A: '唯一选项' } },
  });
  const only = answers['only'];
  assert.ok(only && only.type === 'choice');
  assert.equal(only.choice, 'A');
  assert.equal(only.probabilities['A'], 1);
  const sum = Object.values(only.probabilities).reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(sum - 1) < 1e-9);
});

test('mock: 两次调用结果一致（确定性）', async () => {
  const backend = createMockSystemOne();
  const q = { m: { type: 'choice', instructions: 'x', criteria: { a: 'A', b: 'B' } } } as const;
  const r1 = await backend.ask({}, q);
  const r2 = await backend.ask({}, q);
  assert.deepEqual(r1, r2);
});

test('mock: sokoban 推箱级优先选非死锁的上目标推箱', async () => {
  const backend = createMockSystemOne();
  const state = {
    availablePushes: [
      { id: 'push-A-R', onGoal: false, deadlock: false, walkSteps: 2 },
      { id: 'push-B-U', onGoal: true, deadlock: false, walkSteps: 5 },
      { id: 'push-B-L', onGoal: true, deadlock: true, walkSteps: 0 },
    ],
  };
  const answers = await backend.ask(state, {
    action: { type: 'choice', instructions: 'x', criteria: { 'push-A-R': 'a', 'push-B-U': 'b', 'push-B-L': 'c', undo: '撤销' } },
  });
  const action = answers['action'];
  assert.ok(action && action.type === 'choice');
  assert.equal(action.choice, 'push-B-U'); // 死锁的上目标推箱不选，undo 不选
});

test('mock: sokoban 推箱级无目标推箱时选走位最少的非死锁候选，全死锁选第一个', async () => {
  const backend = createMockSystemOne();
  const state = {
    availablePushes: [
      { id: 'push-A-R', onGoal: false, deadlock: false, walkSteps: 4 },
      { id: 'push-A-U', onGoal: false, deadlock: true, walkSteps: 0 },
      { id: 'push-A-L', onGoal: false, deadlock: false, walkSteps: 1 },
    ],
  };
  const answers = await backend.ask(state, {
    action: { type: 'choice', instructions: 'x', criteria: { 'push-A-R': 'a', 'push-A-U': 'b', 'push-A-L': 'c' } },
  });
  const action = answers['action'];
  assert.ok(action && action.type === 'choice');
  assert.equal(action.choice, 'push-A-L');

  const deadlocked = await backend.ask({ availablePushes: [
    { id: 'push-A-R', deadlock: true }, { id: 'push-A-L', deadlock: true },
  ] }, {
    action: { type: 'choice', instructions: 'x', criteria: { 'push-A-R': 'a', 'push-A-L': 'b' } },
  });
  const picked = deadlocked['action'];
  assert.ok(picked && picked.type === 'choice');
  assert.equal(picked.choice, 'push-A-R');
});

test('mock: sokoban 启发式优先推箱上目标点', async () => {
  const backend = createMockSystemOne();
  const state = {
    board: { rows: ['#####', '#@$.#', '#####'] },
    entities: { goals: [{ x: 3, y: 1 }] },
    facts: { corneredBoxes: [] },
    legalMoves: [
      { action: 'R', playerTo: { x: 2, y: 1 }, boxTo: { x: 3, y: 1 }, boxOnGoal: true },
      { action: 'D', playerTo: { x: 1, y: 2 } },
    ],
  };
  const answers = await backend.ask(state, {
    action: { type: 'choice', instructions: 'x', criteria: { R: '推', D: '走' } },
    deadlockRisk: { type: 'score', instructions: 'x', levels: { '0': '无', '1': '低', '2': '高', '3': '卡死' } },
  });
  const action = answers['action'];
  assert.ok(action && action.type === 'choice');
  assert.equal(action.choice, 'R');
  const risk = answers['deadlockRisk'];
  assert.ok(risk && risk.type === 'score');
  assert.equal(risk.score, 0);
});

test('mock: sokoban 启发式避开把箱子推入死角', async () => {
  const backend = createMockSystemOne();
  const state = {
    board: { rows: ['#####', '#@$ #', '#####'] },
    entities: { goals: [{ x: 4, y: 1 }] },
    facts: { corneredBoxes: [{ x: 3, y: 1 }] },
    legalMoves: [
      { action: 'R', playerTo: { x: 2, y: 1 }, boxTo: { x: 3, y: 1 }, boxOnGoal: false },
      { action: 'D', playerTo: { x: 1, y: 2 } },
    ],
  };
  const answers = await backend.ask(state, {
    action: { type: 'choice', instructions: 'x', criteria: { R: '推', D: '走' } },
    deadlockRisk: { type: 'score', instructions: 'x', levels: { '0': '无', '1': '低', '2': '高', '3': '卡死' } },
  });
  const action = answers['action'];
  assert.ok(action && action.type === 'choice');
  assert.equal(action.choice, 'D');
  const risk = answers['deadlockRisk'];
  assert.ok(risk && risk.type === 'score');
  assert.equal(risk.score, 3);
});
