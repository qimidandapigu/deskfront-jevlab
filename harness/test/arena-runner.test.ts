import { responseBackend } from '../src/systemone/request.js';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runTurnGame } from '../src/arena/runner.js';
import { createJsonlLogger } from '../src/arena/logger.js';
import { createSokobanGame } from '../src/games/sokoban/adapter.js';
import { createMockSystemOne } from '../src/systemone/mock.js';
import type { SystemOne } from '../src/systemone/types.js';

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

/** 当前局面的推箱选项 id（push-A-U 在最前，零走位直接推上目标）。 */
function pushIds(game: ReturnType<typeof createSokobanGame>): string[] {
  const action = game.questions(game.initialState())['action'];
  if (!action || action.type !== 'choice') throw new Error('action 应为 choice 问题');
  return Object.keys(action.criteria).filter(k => k !== 'undo');
}

test('runner: mock 优先推箱上目标，一次推箱后获胜', async () => {
  // reachablePushes 按 UDLR 键序，push-A-U 在最前；首回合即推箱到目标
  const summary = await runTurnGame(createSokobanGame(ROWS), createMockSystemOne(), { maxTurns: 10 });
  assert.equal(summary.outcome, 'won');
  assert.equal(summary.turns, 1);
});

test('runner: 持续非法动作达上限判负', async () => {
  const badBackend: SystemOne = {
    async ask() {
      return { action: { type: 'choice', choice: 'Q', probabilities: { Q: 1 }, confidence: 1 } };
    },
  };
  const summary = await runTurnGame(createSokobanGame(ROWS), badBackend, { maxTurns: 10, maxInvalid: 3 });
  assert.equal(summary.outcome, 'invalid-limit');
  assert.equal(summary.invalidCount, 3);
  assert.equal(summary.turns, 3);
});

test('runner: 写 JSONL 日志且反馈进入下一回合观察', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'jev-runner-'));
  try {
    const logPath = join(dir, 'test-run.jsonl');
    const seen: unknown[] = [];
    const spyBackend: SystemOne = {
      async ask(state) { seen.push(state); return { action: { type: 'choice', choice: 'Q', probabilities: { Q: 1 }, confidence: 1 } }; },
    };
    await runTurnGame(createSokobanGame(ROWS), spyBackend, { maxInvalid: 2, onUpdate: createJsonlLogger(logPath) });
    const lines = readFileSync(logPath, 'utf8').trim().split('\n').map(l => JSON.parse(l));
    assert.equal(lines.length, 2);
    assert.equal(lines[0].turn, 1);
    assert.ok(lines[0].answers.action);
    // 第二回合的 observation 携带上一回合的非法反馈
    const second = seen[1] as { feedback: string | null };
    assert.ok(second.feedback && second.feedback.includes('Q'));
    // JSONL 行的观测字段名为 observation
    assert.ok(lines[0].observation);
    assert.equal(lines[0].state, undefined);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('runner: onUpdate 每回合回调，末回合 done=true 且带 outcome', async () => {
  const records: Array<{ turn: number; done: boolean; outcome: string | null }> = [];
  const summary = await runTurnGame(createSokobanGame(ROWS), createMockSystemOne(), {
    maxTurns: 10,
    onUpdate: (record, snapshot) => records.push({ turn: record.turn, done: snapshot.done, outcome: snapshot.outcome }),
  });
  assert.equal(summary.outcome, 'won');
  assert.equal(records.length, 1);
  assert.deepEqual(records[0], { turn: 1, done: true, outcome: 'won' });
});

test('runner: 低置信度不拦截，动作照常执行且概率完整保留', async () => {
  const game = createSokobanGame(ROWS);
  const [win, other] = pushIds(game);
  const lowConf: SystemOne = {
    async ask() {
      return {
        action: { type: 'choice', choice: win!, probabilities: { [win!]: 0.3, [other!]: 0.7 }, confidence: 0.1 },
        deadlockRisk: { type: 'score', score: 1, probabilities: { '0': 1 }, confidence: 1 },
      };
    },
  };
  const records: import('../src/arena/runner.js').TurnRecord[] = [];
  const summary = await runTurnGame(game, lowConf, { maxTurns: 1, onUpdate: r => records.push(r) });
  assert.equal(summary.invalidCount, 0); // 合法推箱动作，照常执行
  assert.equal(records[0]!.hesitation, undefined);
  const action = records[0]!.answers['action'];
  assert.equal(action!.type, 'choice');
  if (action!.type === 'choice') {
    assert.equal(action!.choice, win);
    assert.deepEqual(action!.probabilities, { [win!]: 0.3, [other!]: 0.7 });
  }
});

test('runner: 低置信度高风险动作也按原选择执行', async () => {
  const game = createSokobanGame(ROWS);
  const [win, ...rest] = pushIds(game);
  const origQuestions = game.questions.bind(game);
  game.questions = state => {
    const qs = origQuestions(state);
    const action = qs['action']!;
    if (action.type === 'choice') {
      action.highRisk = rest;
      action.safeAction = win;
    }
    return qs;
  };
  const risky: SystemOne = {
    async ask() {
      return {
        action: { type: 'choice', choice: rest[0]!, probabilities: { [rest[0]!]: 0.5, [win!]: 0.5 }, confidence: 0.5 },
        deadlockRisk: { type: 'score', score: 1, probabilities: { '0': 1 }, confidence: 1 },
      };
    },
  };
  const records: import('../src/arena/runner.js').TurnRecord[] = [];
  const summary = await runTurnGame(game, risky, { maxTurns: 1, onUpdate: r => records.push(r) });
  assert.equal(summary.invalidCount, 0);
  assert.equal(records[0]!.capped, undefined);
  assert.equal(records[0]!.hesitation, undefined);
  const action = records[0]!.answers['action'];
  if (action!.type === 'choice') {
    assert.equal(action!.choice, rest[0]); // 原选择不被低置信度替换
    assert.deepEqual(action!.probabilities, { [rest[0]!]: 0.5, [win!]: 0.5 }); // 原始概率保留
  }
});

test('runner: 高风险无安全默认也不做概率标记', async () => {
  const game = createSokobanGame(ROWS);
  const [win] = pushIds(game);
  const origQuestions = game.questions.bind(game);
  game.questions = state => {
    const qs = origQuestions(state);
    const action = qs['action']!;
    if (action.type === 'choice') action.highRisk = [win!];
    return qs;
  };
  const risky: SystemOne = {
    async ask() {
      return {
        action: { type: 'choice', choice: win!, probabilities: { [win!]: 1 }, confidence: 0.5 },
        deadlockRisk: { type: 'score', score: 1, probabilities: { '0': 1 }, confidence: 1 },
      };
    },
  };
  const records: import('../src/arena/runner.js').TurnRecord[] = [];
  const summary = await runTurnGame(game, risky, { maxTurns: 1, onUpdate: r => records.push(r) });
  assert.equal(summary.outcome, 'won'); // 仍执行推箱上目标
  assert.equal(records[0]!.blocked, undefined);
});

test('runner: allowOther 问题返回 other 记 abstained 并按安全默认执行', async () => {
  const game = createSokobanGame(ROWS);
  const [win, other] = pushIds(game);
  const origQuestions = game.questions.bind(game);
  game.questions = state => {
    const qs = origQuestions(state);
    const action = qs['action']!;
    if (action.type === 'choice') {
      action.allowOther = true;
      action.safeAction = win;
    }
    return qs;
  };
  const abstain: SystemOne = {
    async ask() {
      return {
        action: { type: 'choice', choice: 'other', probabilities: { [win!]: 0.4, [other!]: 0.3, other: 0.3 }, confidence: 0.2 },
        deadlockRisk: { type: 'score', score: 1, probabilities: { '0': 1 }, confidence: 1 },
      };
    },
  };
  const records: import('../src/arena/runner.js').TurnRecord[] = [];
  const summary = await runTurnGame(game, abstain, { maxTurns: 1, onUpdate: r => records.push(r) });
  assert.equal(summary.outcome, 'won'); // 安全默认 push-A-U 生效
  assert.equal(records[0]!.abstained, true);
  assert.equal(records[0]!.feedback, null);
});

test('runner: abstained 且无安全默认时仍选择并执行合法动作', async () => {
  const game = createSokobanGame(ROWS);
  const origQuestions = game.questions.bind(game);
  game.questions = state => {
    const qs = origQuestions(state);
    const action = qs['action']!;
    if (action.type === 'choice') action.allowOther = true;
    return qs;
  };
  const abstain: SystemOne = {
    async ask() {
      return {
        action: { type: 'choice', choice: 'other', probabilities: { other: 1 }, confidence: 1 },
        deadlockRisk: { type: 'score', score: 1, probabilities: { '0': 1 }, confidence: 1 },
      };
    },
  };
  const records: import('../src/arena/runner.js').TurnRecord[] = [];
  const summary = await runTurnGame(game, abstain, { maxTurns: 1, onUpdate: r => records.push(r) });
  assert.equal(records[0]!.execution!.status, 'applied');
  assert.ok(records[0]!.execution!.executedAnswers);
  assert.notEqual((records[0]!.execution!.executedAnswers!.action as { choice: string }).choice, 'other');
  assert.equal(summary.invalidCount, 0);
});

test('runner: 后端提供 usage 时写入 TurnRecord', async () => {
  const game = createSokobanGame(ROWS);
  const [win] = pushIds(game);
  const withUsage = responseBackend(async () => ({
    usage: { promptTokens: 120, completionTokens: 3, totalTokens: 123 },
    answers: { action: { type: 'choice', choice: win!, probabilities: { [win!]: 1 }, confidence: 1 } },
  }));
  const records: import('../src/arena/runner.js').TurnRecord[] = [];
  await runTurnGame(game, withUsage, { maxTurns: 1, onUpdate: r => records.push(r) });
  assert.deepEqual(records[0]!.usage, { promptTokens: 120, completionTokens: 3, totalTokens: 123 });
  assert.equal(records[0]!.hesitation, undefined); // 高置信度不打标
});

test('runner: 局面重复达上限判死循环', async () => {
  // 奇数回合推箱、偶数回合 undo，局面每两回合回到起点
  const game = createSokobanGame(ROWS);
  const sideways = pushIds(game).find(id => id !== 'push-A-U')!;
  const pingpong: SystemOne = {
    async ask(state) {
      const turn = (state as { turn: number }).turn;
      const choice = turn % 2 === 1 ? sideways : 'undo';
      return { action: { type: 'choice', choice, probabilities: { [choice]: 1 }, confidence: 1 } };
    },
  };
  const summary = await runTurnGame(game, pingpong, { maxTurns: 20 });
  assert.equal(summary.outcome, 'loop');
  assert.equal(summary.turns, 4);
});

test('runner: shouldAbort 中止对局', async () => {
  // 用推箱/undo 往返的后端避免提前获胜，第二回合检查时应中止
  const game = createSokobanGame(ROWS);
  const sideways = pushIds(game).find(id => id !== 'push-A-U')!;
  const pingpong: SystemOne = {
    async ask(state) {
      const turn = (state as { turn: number }).turn;
      const choice = turn % 2 === 1 ? sideways : 'undo';
      return { action: { type: 'choice', choice, probabilities: { [choice]: 1 }, confidence: 1 } };
    },
  };
  let calls = 0;
  const summary = await runTurnGame(game, pingpong, {
    maxTurns: 50,
    shouldAbort: () => ++calls > 1,
  });
  assert.equal(summary.outcome, 'aborted');
});

test('runner: playMsPacing 按动作播放时长等待下一回合', async () => {
  const game = createSokobanGame(ROWS);
  const sideways = pushIds(game).find(id => id !== 'push-A-U')!;
  const backend: SystemOne = {
    async ask() {
      return { action: { type: 'choice', choice: sideways, probabilities: { [sideways]: 1 }, confidence: 1 } };
    },
  };
  const t0 = Date.now();
  const summary = await runTurnGame(game, backend, { maxTurns: 2, playMsPacing: true });
  const elapsed = Date.now() - t0;
  assert.equal(summary.turns, 2);
  assert.ok(elapsed >= 400, `playMsPacing 应至少等待一次推箱动画（≥480ms），实际 ${elapsed}ms`);
});

test('runner: nonterminal action result is published immediately, preserving decision input', async () => {
  const game = createSokobanGame(['########', '# .    #', '#      #', '# $    #', '# @    #', '#      #', '#      #', '########']);
  let published = false;
  await runTurnGame(game, { async ask() { return { action: {type: 'choice',choice:'push-A-U',probabilities:{'push-A-U':1},confidence:1} }; } }, {
    maxTurns: 2,
    shouldAbort: () => published,
    onUpdate(record, snapshot) {
      const before = record.observation as { entities: { player: { y: number } } };
      const after = record.resultObservation as typeof before;
      assert.equal(snapshot.done, false);
      assert.equal(before.entities.player.y, 4);
      assert.equal(after.entities.player.y, 3);
      published = true;
    },
  });
  assert.equal(published, true);
});
