import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequestManager, responseBackend } from '../src/systemone/request.js';
import { invalidAnswers } from '../src/systemone/validation.js';
import { decisionTrigger, prepareDecision } from '../src/arena/decision.js';
import { createRealtimeMatch, type RealtimeRecord } from '../src/arena/realtime.js';
import { runTurnGame } from '../src/arena/runner.js';
import { createSokobanGame } from '../src/games/sokoban/adapter.js';
import type { Answer, Question, SystemOne } from '../src/systemone/types.js';
import type { RealtimeGame } from '../src/arena/plugin.js';
import { createSystemOneJevClient } from '../src/jgp/jev-real.js';

const qs: Record<string, Question> = { action: { type: 'choice', instructions: '', criteria: { go: '', idle: '' } } };
const answers = (choice = 'go'): Record<string, Answer> => ({ action: { type: 'choice', choice, confidence: 1, probabilities: { [choice]: 1 } } });
const thresholds = { confidence: .6, highRisk: .85 };

test('shared gate rejects nonfinite confidence, invalid distributions and wrong score/noul types', () => {
  for (const bad of [NaN, Infinity, -1, 2]) {
    const raw = answers(); raw.action!.confidence = bad;
    assert.equal(prepareDecision(qs, raw, thresholds).status, 'rejected');
    assert.ok(invalidAnswers({ n: { type: 'noul', instructions: '' } }, { n: { type: 'noul', noul: bad } }));
  }
  for (const probabilities of [{ go: 2 }, { go: .5 }, { go: NaN }, { alien: 1 }] as Record<string, number>[]) {
    assert.ok(invalidAnswers(qs, { action: { type: 'choice', choice: 'go', confidence: 1, probabilities } }));
  }
  assert.ok(invalidAnswers({ s: { type: 'score', instructions: '', levels: { 0: '', 1: '' } } }, { s: { type: 'score', score: 2, confidence: 1, probabilities: { 0: 1 } } }));
  assert.ok(invalidAnswers({ guard: { type: 'noul', purpose: 'protection', instructions: '' } }, {}));
});

test('unsolicited control answer cannot enter a human input branch', () => {
  const raw = { ...answers(), control: answers('idle').action! };
  const prepared = prepareDecision(qs, raw, thresholds);
  assert.equal(prepared.status, 'applied');
  assert.equal(prepared.answers.control, undefined);
  assert.ok(raw.control);
});

test('request policy omits display questions but retains protection and supports diagnostics', async () => {
  const seen: string[][] = [];
  const model: SystemOne = { ask: async (_, questions) => { seen.push(Object.keys(questions)); return {}; } };
  const questions: Record<string, Question> = { ...qs, guard: { type: 'noul', purpose: 'protection', instructions: '' }, meter: { type: 'choice', purpose: 'display', instructions: '', criteria: { low: '', high: '' } } };
  await createRequestManager(model).request({}, questions);
  await createRequestManager(model, { diagnostics: true }).request({}, questions);
  assert.deepEqual(seen, [['action', 'guard'], ['action', 'guard', 'meter']]);
});

test('concurrent results keep their own tokens and actual model; never read legacy mutable usage', async () => {
  const model = responseBackend(async state => {
    const id = state as number;
    await new Promise(r => setTimeout(r, id === 1 ? 10 : 1));
    return { answers: answers(), usage: { totalTokens: id }, resolvedModel: `model-${id}` };
  });
  const manager = createRequestManager(model);
  const responses = await Promise.all([manager.request(1, qs), manager.request(2, qs)]);
  assert.deepEqual(responses.map(r => [r.usage?.totalTokens, r.resolvedModel]), [[1, 'model-1'], [2, 'model-2']]);
  const legacy = await createRequestManager({ ask: async () => answers(), lastUsage: { totalTokens: 999 } }).request({}, qs);
  assert.equal(legacy.usage, undefined); assert.equal(legacy.usageComplete, false);
});

test('timeout and cancellation release noncooperative requests and every attempt consumes budget', async () => {
  const manager = createRequestManager({ ask: () => new Promise(() => {}) }, { timeoutMs: 10, maxRequests: 2 });
  await assert.rejects(manager.request({}, qs), /request-timeout/);
  const pending = manager.request({}, qs); manager.cancel();
  await assert.rejects(pending, /request-cancelled/);
  assert.equal(manager.pending, 0); assert.equal(manager.count, 2);
  await assert.rejects(manager.request({}, qs), /request-budget/);
});

function probe(): RealtimeGame<{ tick: number; command: string }> {
  return { id: 'scheduler', tickMs: 10, decisionMs: 10, initialState: () => ({ tick: 0, command: 'idle' }),
    observe: s => s, questions: () => qs,
    act: (s, a) => ({ ...s, command: a.action?.type === 'choice' ? a.action.choice : 'idle' }),
    step: s => ({ ...s, tick: s.tick + 1 }), isTerminal: () => false,
    decision: { capture: s => ({ progress: 0, position: String(s.tick) }), describe: s => ({ command: s.command }) } };
}

test('AI can resume before an old hung response resolves; old finally cannot clear new pending', async () => {
  let calls = 0, resolveSecond!: (a: Record<string, Answer>) => void;
  const model: SystemOne = { ask: () => ++calls === 1 ? new Promise(() => {}) : new Promise(r => { resolveSecond = r; }) };
  const m = createRealtimeMatch(probe(), model);
  const first = m.tick(); m.setControl('self', false); m.setControl('self', true);
  const second = m.tick(); await first;
  assert.equal(calls, 2);
  await m.tick(false); assert.equal(calls, 2);
  resolveSecond(answers()); await second;
  assert.equal(m.state.command, 'go'); m.stop();
});

test('retaining an old command is skipped, while a legitimate idle is applied', async () => {
  const g = probe(); let retained = false;
  g.decision!.describe = s => ({ command: s.command, disposition: retained ? 'retained' : 'accepted', reason: retained ? 'route-in-progress' : undefined });
  const records: RealtimeRecord[] = [];
  const m = createRealtimeMatch(g, { ask: async () => answers('idle') }, { onUpdate: r => records.push(r) });
  await m.tick(); retained = true; await m.tick(); m.stop();
  assert.equal(records[0]!.execution!.status, 'applied');
  assert.equal(records[1]!.execution!.status, 'skipped');
  assert.equal(records[1]!.execution!.executedAnswers, null);
  assert.equal(m.summary.decisions, 1);
});

test('both sides dispatch even if self is hung; rival honors the same ready policy', async () => {
  const g = probe(); let ready = true, rivalCalls = 0;
  g.rival = { observe: g.observe, questions: g.questions, act: g.act,
    decision: { ...g.decision!, schedule: { ready: () => ready } } };
  const m = createRealtimeMatch(g, { ask: () => new Promise(() => {}) }, { rivalBackend: { ask: async () => { rivalCalls++; return answers(); } } });
  const pending = m.tick(); await new Promise(r => setImmediate(r));
  assert.equal(rivalCalls, 1); ready = false;
  await m.tick(false); await new Promise(r => setImmediate(r)); assert.equal(rivalCalls, 1);
  m.stop(); await pending;
});

test('scheduler protects routes but accepts game-declared interrupts and maximum wait', () => {
  const g = probe(), s = g.initialState(), hooks = g.decision!;
  hooks.schedule = { ready: () => false, eventKey: () => 'changed', canInterrupt: () => false, maxWaitMs: 20 };
  assert.equal(decisionTrigger(hooks, s, 100, 0, 10, 'old'), null);
  hooks.schedule.canInterrupt = () => true;
  assert.equal(decisionTrigger(hooks, s, 100, 0, 10, 'old'), 'event-changed');
  assert.equal(decisionTrigger(hooks, s, 100, 0, 10, 'changed'), 'max-wait');
});

test('turn cancellation and JGP disposal stop waiting for hung providers', async () => {
  const backend: SystemOne = { ask: () => new Promise(() => {}) };
  const controller = new AbortController();
  const turn = runTurnGame(createSokobanGame(['########', '# @$.  #', '#      #', '#      #', '#      #', '#      #', '#      #', '########']), backend, { signal: controller.signal });
  controller.abort(); assert.equal((await turn).outcome, 'aborted');
  const bridge = createSystemOneJevClient(backend);
  const pending = bridge.systemOne({ state: {}, questions: { q: { type: 'noul' } } });
  bridge.dispose(); await assert.rejects(pending, /client-disposed/);
});

test('runtime budget ends normally rather than retrying budget errors as provider failures', async () => {
  const m = createRealtimeMatch(probe(), { ask: async () => answers() }, { requests: { maxRequests: 1 } });
  await m.tick(); await m.tick();
  assert.equal(m.summary.outcome, 'request-budget'); assert.equal(m.summary.failures, 0);
});

test('game recovery changes executed input but preserves the model answer and reason', async () => {
  const g = probe(), records: RealtimeRecord[] = [];
  g.decision!.recover = (_s, a) => ({ answers: { ...a, action: { ...a.action!, type: 'choice', choice: 'idle', probabilities: { idle: 1 }, confidence: 1 } }, reason: 'game-specific-recovery' });
  const m = createRealtimeMatch(g, { ask: async () => answers() }, { onUpdate: r => records.push(r) });
  await m.tick(); m.stop();
  const e = records[0]!.execution!;
  assert.equal((e.rawAnswers.action as { choice: string }).choice, 'go');
  assert.equal((e.executedAnswers!.action as { choice: string }).choice, 'idle');
  assert.equal(e.reason, 'game-specific-recovery');
});
