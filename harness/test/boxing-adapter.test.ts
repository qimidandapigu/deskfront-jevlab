import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRealtimeMatch } from '../src/arena/realtime.js';
import { createBoxingGame } from '../src/games/boxing/adapter.js';
import { BOXING } from '../src/games/boxing/engine.js';
import type { Answer, SystemOne } from '../src/systemone/types.js';

const jabBackend: SystemOne = {
  ask: async () => ({
    action: { type: 'choice', choice: 'jab', probabilities: { jab: 1 }, confidence: 1 },
    needGuard: { type: 'noul', noul: 0.1 },
  }) as Record<string, Answer>,
};

test('questions: action 十选项含中文描述与标签，needGuard 为 noul，danger 为 score', () => {
  const game = createBoxingGame();
  const qs = game.questions(game.initialState());
  const action = qs['action'];
  assert.ok(action && action.type === 'choice');
  assert.deepEqual(Object.keys(action.criteria).sort(), ['advance','dash','guard','heavy','idle','jab','jump','retreat','special','throw']);
  assert.ok(action.criteria['jab']!.includes('刺拳'));
  assert.equal(action.label, '动作');
  assert.ok(qs['needGuard'] && qs['needGuard'].type === 'noul');
  assert.equal(qs['needGuard']!.label, '是否需要格挡');
  const danger = qs['danger'];
  assert.ok(danger && danger.type === 'score');
  assert.equal(danger.label, '危险');
  assert.deepEqual(Object.keys(danger.levels), ['0', '1', '2']);
});

test('observe 分组且 facts 预计算射程/命中倒计时/时间压力', () => {
  const game = createBoxingGame();
  const obs = game.observe(game.initialState()) as {
    match: { secondsLeft: number }; fighters: { self: { hp: number } }; distance: number;
    facts: { inRange: string[]; oppAttackMsLeft: number; selfAttackMsLeft: number; timePressure: number };
  };
  assert.equal(obs.distance, 420);
  assert.equal(obs.fighters.self.hp, BOXING.hp);
  assert.equal(obs.match.secondsLeft, 45);
  // 初始距离 420 超出全部招式射程（最远 125）；双方未出招；时间满格
  assert.deepEqual(obs.facts.inRange, []);
  assert.equal(obs.facts.oppAttackMsLeft, 0);
  assert.equal(obs.facts.selfAttackMsLeft, 0);
  assert.equal(obs.facts.timePressure, 1);
});

test('observe facts: 贴近时 inRange 含全部招式，双方起手时各有 AttackMsLeft', () => {
  const game = createBoxingGame();
  const s = game.initialState();
  // 把双方拉到距离 100，对手起手刺拳（startup 2 tick = 100ms），自己起手重拳（7 tick = 350ms）
  s.bout.fighters[0]!.x = 400; s.bout.fighters[1]!.x = 500;
  s.bout.fighters[1]!.attack = { kind: 'jab', age: 0, tried: false };
  s.bout.fighters[0]!.attack = { kind: 'heavy', age: 0, tried: false };
  const obs = game.observe(s) as { facts: { inRange: string[]; oppAttackMsLeft: number; selfAttackMsLeft: number } };
  assert.deepEqual(obs.facts.inRange.sort(), ['heavy', 'jab', 'throw']);
  assert.equal(obs.facts.oppAttackMsLeft, 100);
  assert.equal(obs.facts.selfAttackMsLeft, 350);
});

test('needGuard 仅展示，不覆盖低置信度动作', () => {
  const game = createBoxingGame();
  const s0 = game.initialState();
  const lowConf = { type: 'choice', choice: 'jab', probabilities: { jab: 0.5, idle: 0.5 }, confidence: 0.5 } as const;
  const s1 = game.act(s0, { action: lowConf, needGuard: { type: 'noul', noul: 0.9 } });
  assert.equal(s1.command, 'jab');
  // needGuard 不足：按原答案执行
  const s2 = game.act(s0, { action: lowConf, needGuard: { type: 'noul', noul: 0.3 } });
  assert.equal(s2.command, 'jab');
  // 置信度足够：不拦截
  const s3 = game.act(s0, {
    action: { type: 'choice', choice: 'jab', probabilities: { jab: 1 }, confidence: 0.9 },
    needGuard: { type: 'noul', noul: 0.9 },
  });
  assert.equal(s3.command, 'jab');
});

test('act 写入指令，step 推进对局；全程可分出胜负', async () => {
  const game = createBoxingGame();
  const match = createRealtimeMatch(game, jabBackend, { decisionMs: 200, maxTicks: 2000 });
  for (let i = 0; i < 2000 && match.summary.outcome === 'finished'; i++) await match.tick();
  const bout = (match.state as { bout: { status: string; winner: number | null } }).bout;
  assert.equal(bout.status, 'done');
  assert.ok(match.summary.decisions > 0);
});

test('act 对非法 choice 保持原指令', () => {
  const game = createBoxingGame();
  const s0 = game.initialState();
  const s1 = game.act(s0, { action: { type: 'choice', choice: 'fly', probabilities: { fly: 1 }, confidence: 1 } });
  assert.equal(s1.command, 'idle');
});

test('act 识别真人 control 输入（观测站自己玩），非法 control 保持原指令', () => {
  const game = createBoxingGame();
  const s0 = game.initialState();
  const s1 = game.act(s0, { control: { type: 'choice', choice: 'jab', probabilities: { jab: 1 }, confidence: 1 } });
  assert.equal(s1.command, 'jab');
  const s2 = game.act(s1, { control: { type: 'choice', choice: 'fly', probabilities: { fly: 1 }, confidence: 1 } });
  assert.equal(s2.command, 'jab');
});

import { prepareDecision } from '../src/arena/decision.js';

test('no probability gate: a 1% selected action with zero confidence executes unchanged', () => {
  const raw: Record<string, Answer> = { action: { type: 'choice', choice: 'jab', confidence: 0, probabilities: { jab: .01, guard: .99 } } };
  const result = prepareDecision({ action: { type: 'choice', instructions: '', criteria: { jab: '', guard: '' }, highRisk: ['jab'], safeAction: 'guard' } }, raw, { confidence: 1, highRisk: 1 });
  assert.equal(result.skip, false);
  assert.deepEqual(result.answers, raw);
  assert.equal(result.gate.hesitation, false);
  assert.equal(result.gate.capped, undefined);
});

test('boxing both sides replace unaffordable special with actual movement, preserve raw model evidence', async () => {
  const game = createBoxingGame(), initial = game.initialState;
  game.initialState = () => {
    const s = initial(); s.bout.fighters[0].x = 400; s.bout.fighters[1].x = 538;
    s.bout.fighters[0].meter = 25; s.bout.fighters[1].meter = 44;
    return s;
  };
  const raw: Record<string, Answer> = { action: { type: 'choice', choice: 'special', confidence: 0, probabilities: { special: .36, advance: .24, dash: .21, jab: .07, guard: .05, idle: .07 } } };
  const records: import('../src/arena/realtime.js').RealtimeRecord[] = [];
  const backend: SystemOne = { ask: async () => structuredClone(raw) };
  const match = createRealtimeMatch(game, backend, { decisionMs: 50, rivalBackend: backend, onUpdate: r => records.push(r), onRivalUpdate: r => records.push(r) });
  await match.tick(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(records.length, 2);
  for (const record of records) {
    assert.equal(record.execution!.status, 'applied');
    assert.equal(record.execution!.action!.command, 'advance');
    assert.match(record.execution!.reason!, /气不足50/);
    assert.deepEqual(record.execution!.rawAnswers, raw);
    assert.equal((record.execution!.executedAnswers!.action as { choice: string }).choice, 'advance');
  }
  await match.tick();
  assert.ok(match.state.bout.fighters[0].x > 400);
  assert.ok(match.state.bout.fighters[1].x < 538);
  match.stop();
});

test('boxing legal special executes at zero confidence; unavailable controls use physics fallbacks only', () => {
  const g = createBoxingGame();
  const choice = (action: string): Record<string, Answer> => ({ action: { type: 'choice', choice: action, confidence: 0, probabilities: { [action]: 1 } } });
  let s = g.initialState(); s.bout.fighters[0].x = 400; s.bout.fighters[1].x = 500;
  s.bout.fighters[0].meter = 50;
  s = g.act(s, choice('special')); assert.equal(s.command, 'special');
  s = g.step(s); assert.equal(s.bout.fighters[0].attack?.kind, 'special'); assert.equal(s.bout.fighters[0].meter, 0);
  s = g.initialState(); s.bout.fighters[0].dashCooldown = 5;
  assert.equal(g.act(s, choice('dash')).command, 'advance');
  s.bout.fighters[0].y = 20;
  assert.equal(g.act(s, choice('throw')).command, 'advance');
  assert.equal(g.act(s, choice('guard')).command, 'advance');
  // A deliberate legal idle is still a choice, not an abstention.
  assert.equal(g.act(s, choice('idle')).command, 'idle');
});
