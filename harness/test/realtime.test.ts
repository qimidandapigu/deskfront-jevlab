import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { RealtimeRecord } from '../src/arena/realtime.js';
import { readFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createRealtimeMatch, runRealtimeGame } from '../src/arena/realtime.js';
import { createJsonlLogger } from '../src/arena/logger.js';
import type { RealtimeGame } from '../src/arena/plugin.js';
import type { Answer, SystemOne } from '../src/systemone/types.js';

interface FakeState { frame: number; command: string; }

function fakeGame(terminalAt: number): RealtimeGame<FakeState> {
  return {
    id: 'fake', tickMs: 50,
    initialState: () => ({ frame: 0, command: 'idle' }),
    observe: s => ({ frame: s.frame }),
    questions: () => ({ action: { type: 'choice', instructions: 'x', criteria: { idle: '停', go: '走' } } }),
    act: (s, answers) => {
      const a = answers['action'];
      return { ...s, command: a && a.type === 'choice' ? a.choice : s.command };
    },
    step: s => ({ ...s, frame: s.frame + 1 }),
    isTerminal: s => s.frame >= terminalAt,
  };
}

const goBackend: SystemOne = {
  ask: async () => ({ action: { type: 'choice', choice: 'go', probabilities: { go: 1 }, confidence: 1 } }) as Record<string, Answer>,
};

test('模型失败及时发布错误，后续恢复后正常继续执行', async () => {
  const records: RealtimeRecord[] = [];
  let calls = 0;
  const match = createRealtimeMatch(fakeGame(20), { ask: async () => {
    if (++calls === 1) throw new Error('HTTP 503');
    return goBackend.ask({}, {});
  } }, { decisionMs: 50, pauseWhileDeciding: true, onUpdate: r => records.push(r) });
  await match.tick();
  assert.match(records[0]!.error!, /HTTP 503/);
  assert.equal(records[0]!.failureCount, 1);
  assert.equal(match.state.command, 'idle');
  await match.tick();
  assert.equal(match.state.command, 'go');
  assert.equal(records[1]!.error, undefined);
  assert.equal(match.summary.decisions, 1);
});

test('终局后迟到的模型成功或失败均不修改状态和结算', async () => {
  for (const reject of [false, true]) {
    let complete!: () => void;
    const waiting = new Promise<void>(resolve => { complete = resolve; });
    const backend: SystemOne = { ask: async () => {
      await waiting;
      if (reject) throw new Error('late failure');
      return goBackend.ask({}, {});
    } };
    let updates = 0;
    const match = createRealtimeMatch(fakeGame(3), backend, {
      decisionMs: 50, maxFailures: 1, onUpdate: () => { updates++; },
    });
    const pending = match.tick();
    await match.tick();
    await match.tick();
    const before = { ...match.summary };
    complete();
    await pending;
    assert.equal(match.done, true);
    assert.equal(match.state.command, 'idle');
    assert.deepEqual(match.summary, before);
    assert.equal(updates, 0);
  }
});

test('中止立即返回，不等待在途模型，迟到结果不能改结算', async () => {
  let settled = false;
  let ticks = 0;
  const backend: SystemOne = { ask: async () => {
    await new Promise(resolve => setTimeout(resolve, 30));
    settled = true;
    return goBackend.ask({}, {});
  } };
  const summary = await runRealtimeGame(fakeGame(100), backend, {
    decisionMs: 50, tickSleepMs: 0,
    onTick: () => { ticks++; }, shouldAbort: () => ticks >= 2,
  });
  assert.equal(settled, false);
  await new Promise(resolve => setTimeout(resolve, 40));
  assert.equal(settled, true);
  assert.equal(summary.outcome, 'aborted');
  assert.equal(summary.decisions, 0);
});

test('初始终局不推进物理、不请求模型，并保留胜负', async () => {
  const summary = await runRealtimeGame({ ...fakeGame(0), outcome: () => 'won' }, {
    ask: async () => { throw new Error('must not ask'); },
  }, { tickSleepMs: 0 });
  assert.equal(summary.outcome, 'won');
  assert.equal(summary.ticks, 0);
  assert.equal(summary.failures, 0);
});

test('200ms 决策窗口：50ms tick 下每 4 tick 决策一次，答案即 act', async () => {
  const match = createRealtimeMatch(fakeGame(8), goBackend, { decisionMs: 200 });
  for (let i = 0; i < 8; i++) await match.tick();
  assert.equal(match.summary.outcome, 'finished');
  assert.equal(match.summary.decisions, 1);   // 400ms 已终局，不再提问
  assert.equal(match.state.command, 'go');
});

test('慢后端 skip：上一轮未返回的窗口不重复发', async () => {
  let calls = 0;
  const slowBackend: SystemOne = {
    ask: async () => { calls++; await new Promise(r => setTimeout(r, 30)); return { action: { type: 'choice', choice: 'go', probabilities: { go: 1 }, confidence: 1 } }; },
  };
  // tick() 内 await ask 落地，为制造 in-flight 重叠，用不 await 的方式连续 tick：
  const match = createRealtimeMatch(fakeGame(100), slowBackend, { decisionMs: 200 });
  const pending: Promise<void>[] = [];
  for (let i = 0; i < 12; i++) pending.push(match.tick());   // 不 await，模拟墙钟竞争
  await Promise.all(pending);
  assert.ok(calls < 3, `calls=${calls} 应远少于窗口数（in-flight 时 skip）`);
  assert.ok(match.summary.skipped >= 1 || calls <= 2, '应有 skip 发生');
});

test('连续失败达上限判 void', async () => {
  const badBackend: SystemOne = { ask: async () => { throw new Error('boom'); } };
  const match = createRealtimeMatch(fakeGame(10_000), badBackend, { decisionMs: 200, maxFailures: 3, maxTicks: 100 });
  for (let i = 0; i < 100 && match.summary.outcome === 'finished'; i++) await match.tick();
  assert.equal(match.summary.outcome, 'void');
  assert.equal(match.summary.failures, 3);
});

test('墙钟循环：慢 ask 不停表，决策窗口 skip 而非排队', async () => {
  // ask 500ms，tick 50ms、窗口 200ms：旧串行实现会停表等 ask，总时长被拉数倍；
  // fire-and-forget 下墙钟按 tickMs 走，in-flight 期间窗口 skip。
  const slowBackend: SystemOne = {
    ask: async () => {
      await new Promise(r => setTimeout(r, 500));
      return { action: { type: 'choice', choice: 'go', probabilities: { go: 1 }, confidence: 1 } };
    },
  };
  const started = Date.now();
  const summary = await runRealtimeGame(fakeGame(20), slowBackend, { decisionMs: 200, maxTicks: 30 });
  const wall = Date.now() - started;
  assert.equal(summary.outcome, 'finished');
  assert.ok(summary.skipped >= 1, `skipped=${summary.skipped}，慢 ask 期间应有窗口被 skip`);
  assert.ok(wall < 3000, `wall=${wall}ms，20 tick（1s 局）+ 收尾一个 ask 不应超过 3s`);
  assert.ok(summary.ticks >= 20);
});

test('onUpdate + createJsonlLogger：实时记录落盘为 JSONL', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'jev-rt-'));
  try {
    const logPath = join(dir, 'rt.jsonl');
    const log = createJsonlLogger(logPath);
    const match = createRealtimeMatch(fakeGame(8), goBackend, { decisionMs: 200, onUpdate: log });
    for (let i = 0; i < 8; i++) await match.tick();
    const lines = readFileSync(logPath, 'utf8').trim().split('\n');
    assert.equal(lines.length, 1);
    const first = JSON.parse(lines[0]!) as { game: string; frame: number; answers: Record<string, unknown> };
    assert.equal(first.game, 'fake');
    assert.equal(first.frame, 4);
    assert.ok(first.answers['action']);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('决策延迟回喂：上一次决策耗时进入下一次观测的 timing.lastDecisionMs', async () => {
  const observations: unknown[] = [];
  const spy: SystemOne = {
    ask: async state => {
      observations.push(state);
      return { action: { type: 'choice', choice: 'go', probabilities: { go: 1 }, confidence: 1 } };
    },
  };
  const match = createRealtimeMatch(fakeGame(12), spy, { decisionMs: 200 });
  for (let i = 0; i < 12; i++) await match.tick();
  assert.ok(observations.length >= 2, `决策次数=${observations.length}`);
  assert.ok(!('timing' in (observations[0] as object)), '首次决策无 timing 键');
  const second = observations[1] as { timing?: { lastDecisionMs: number } };
  assert.ok(second.timing && typeof second.timing.lastDecisionMs === 'number' && second.timing.lastDecisionMs >= 0);
});

test('实时低置信度高风险动作照常执行，保留原始回答', async () => {
  const game: RealtimeGame<FakeState> = {
    ...fakeGame(8),
    questions: () => ({ action: { type: 'choice', instructions: 'x', criteria: { idle: '停', go: '走' }, highRisk: ['go'], safeAction: 'idle' } }),
  };
  // Legacy threshold settings cannot override a legal choice.
  const backend: SystemOne = {
    ask: async () => ({ action: { type: 'choice', choice: 'go', probabilities: { go: 0.7, idle: 0.3 }, confidence: 0.7 } }) as Record<string, Answer>,
  };
  const records: RealtimeRecord[] = [];
  const match = createRealtimeMatch(game, backend, { decisionMs: 200, onUpdate: r => records.push(r) });
  for (let i = 0; i < 8; i++) await match.tick();
  assert.equal(match.state.command, 'go');
  assert.equal((records[0]!.execution!.rawAnswers.action as { choice: string }).choice, 'go');
  assert.equal((records[0]!.execution!.executedAnswers!.action as { choice: string }).choice, 'go');
  assert.equal(records[0]?.hesitation, undefined);
  assert.equal(records[0]?.capped, undefined);
});

test('unresolved main model never pauses ticks, even with legacy pause option enabled', async () => {
  const never: SystemOne = { ask: () => new Promise(() => {}) };
  const m = createRealtimeMatch(fakeGame(5), never, { decisionMs: 50, pauseWhileDeciding: true });
  void m.tick();
  for (let i = 0; i < 4; i++) await m.tick();
  assert.equal(m.done, true); assert.equal(m.state.frame, 5);
});

test('slow main and slow rival cannot block the opposite side decisions', async () => {
  for (const slowRival of [false, true]) {
    let mainCalls = 0, rivalCalls = 0;
    const game = fakeGame(20);
    game.rival = { observe: game.observe, act: s => s };
    const never: SystemOne = { ask: () => new Promise(() => {}) };
    const main: SystemOne = slowRival ? { ask: async () => { mainCalls++; return goBackend.ask({}, {}); } } : never;
    const rival: SystemOne = slowRival ? never : { ask: async () => { rivalCalls++; return goBackend.ask({}, {}); } };
    const m = createRealtimeMatch(game, main, { decisionMs: 50, rivalBackend: rival });
    for (let i = 0; i < 12; i++) { void m.tick(); await new Promise(r => setImmediate(r)); }
    assert.equal(m.state.frame, 12);
    assert.ok(slowRival ? mainCalls >= 10 : rivalCalls >= 10);
    m.stop();
  }
});
