import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRealtimeMatch, type RealtimeRecord } from '../src/arena/realtime.js';
import { runTurnGame, type TurnRecord } from '../src/arena/runner.js';
import type { RealtimeGame } from '../src/arena/plugin.js';
import type { Answer, SystemOne } from '../src/systemone/types.js';
import type { FeedbackRecord } from '../src/arena/decision.js';
import { createDefaultRegistry } from '../src/games/index.js';
import { createSokobanGame } from '../src/games/sokoban/adapter.js';
import { createBoxingGame } from '../src/games/boxing/adapter.js';

const answer = (choice = 'go', confidence = 1): Record<string, Answer> => ({ action: { type: 'choice', choice, confidence, probabilities: { go: .5, idle: .5 } } });
function deferred() {
  let resolve!: (answers: Record<string, Answer>) => void;
  const backend: SystemOne = { ask: () => new Promise(r => { resolve = r; }) };
  return { backend, resolve: (a = answer()) => resolve(a) };
}
type State = { frame: number; x: number; command: string; until: number; context: number };
function game(): RealtimeGame<State> {
  return {
    id: 'probe', tickMs: 10, decisionMs: 10,
    initialState: () => ({ frame: 0, x: 0, command: 'idle', until: 0, context: 0 }),
    observe: s => ({ state: s }),
    questions: () => ({ action: { type: 'choice', instructions: '', criteria: { go: '', idle: '' } } }),
    act: (s, a) => ({ ...s, command: a.action?.type === 'choice' ? a.action.choice : 'idle', until: s.frame + 2 }),
    step: s => ({ ...s, x: s.x + (s.command === 'go' ? 1 : 0), frame: s.frame + 1 }),
    isTerminal: s => s.frame >= 50,
    decision: {
      capture: s => ({ progress: s.x, position: String(s.x) }), contextKey: s => String(s.context), maxAgeMs: 20,
      describe: s => ({ command: s.command, expiresAt: s.until }), release: s => ({ ...s, command: 'idle' }),
    },
  };
}

test('request snapshots never drift while physics advances; stale answer is recorded but never applied', async () => {
  const d = deferred(), records: RealtimeRecord[] = [];
  const m = createRealtimeMatch(game(), d.backend, { onUpdate: r => records.push(r) });
  const p = m.tick();
  for (let i = 0; i < 3; i++) await m.tick();
  d.resolve(); await p;
  assert.equal(m.state.command, 'idle');
  assert.equal(records[0]!.execution!.reason, 'observation-expired');
  assert.equal((records[0]!.observation as { state: State }).state.frame, 1);
  assert.equal(records[0]!.execution!.requestedAt, 1);
  assert.equal(records[0]!.execution!.resolvedAt, 4);
  m.stop();
});

test('control handoff invalidates pending reply even after AI is re-enabled', async () => {
  const d = deferred(), cancelled: RealtimeRecord[] = [];
  const m = createRealtimeMatch(game(), d.backend, { onDiscard: r => cancelled.push(r) });
  const p = m.tick(); m.applyExternal(answer('idle')); m.setControl('self', true);
  d.resolve(); await p;
  assert.equal(m.state.command, 'idle');
  assert.equal(cancelled.length, 1); assert.equal(cancelled[0]!.execution!.reason, 'control-changed');
  assert.equal(m.summary.decisions, 0); m.stop();
});

test('respawn context and changed candidates reject answers before execution', async () => {
  for (const kind of ['context', 'candidates']) {
    const g = game(), d = deferred(), records: RealtimeRecord[] = [];
    const m = createRealtimeMatch(g, d.backend, { onUpdate: r => records.push(r) });
    const p = m.tick();
    if (kind === 'context') m.state.context++;
    else g.questions = () => ({ action: { type: 'choice', instructions: '', criteria: { idle: '' } } });
    d.resolve(); await p;
    assert.equal(m.state.command, 'idle');
    assert.equal(records[0]!.execution!.reason, kind === 'context' ? 'context-changed' : 'candidates-changed');
    m.stop();
  }
});

test('expiry releases inputs while model is unresolved and feeds completed effects to next request', async () => {
  const seen: unknown[] = [], effects: FeedbackRecord[] = [];
  let calls = 0;
  const d = deferred();
  const backend: SystemOne = { ask: (obs, qs) => { seen.push(obs); return ++calls === 1 ? Promise.resolve(answer()) : d.backend.ask(obs, qs); } };
  const m = createRealtimeMatch(game(), backend, { onFeedback: r => effects.push(r), maxDecisionAgeMs: 1000 });
  await m.tick(); const second = m.tick(); await m.tick(); await m.tick();
  assert.equal(m.state.command, 'idle'); assert.equal(m.state.x, 2);
  assert.equal(effects[0]!.feedback.status, 'progressed');
  assert.equal(effects[0]!.feedback.progressDelta, 2);
  assert.equal(effects[0]!.feedback.reason, 'expired');
  assert.equal((seen[1] as { decisionFeedback: { progressDelta: number } }).decisionFeedback.progressDelta, 1);
  m.stop(); d.resolve(); await second;
});

test('rival shares gating, rejection and lifecycle logs', async () => {
  const g = game(), records: RealtimeRecord[] = [];
  g.rival = { observe: g.observe, act: g.act, decision: g.decision,
    questions: () => ({ action: { type: 'choice', instructions: '', criteria: { go: '', idle: '' }, highRisk: ['go'], safeAction: 'idle' } }) };
  const m = createRealtimeMatch(g, { ask: async () => answer('idle') }, { rivalBackend: { ask: async () => answer('go', .2) }, onRivalUpdate: r => records.push(r) });
  m.setControl('self', false); await m.tick(); await new Promise(r => setImmediate(r));
  assert.equal(records[0]!.execution!.side, 'rival');
  assert.equal(records[0]!.execution!.action!.command, 'go');
  assert.equal((records[0]!.execution!.rawAnswers.action as { choice: string }).choice, 'go');
  m.stop();
});

test('turn runner preserves a low-confidence legal choice and its actual effect', async () => {
  const g = createSokobanGame(['########', '# @$.  #', '#      #', '#      #', '#      #', '#      #', '#      #', '########']);
  const q = g.questions(g.initialState()).action!;
  assert.equal(q.type, 'choice');
  if (q.type !== 'choice') return;
  const selected = Object.keys(q.criteria).find(k => k.endsWith('-R'))!;
  const raw: Record<string, Answer> = { action: { type: 'choice', choice: selected, confidence: 0, probabilities: { [selected]: 1 } } }, records: TurnRecord[] = [];
  await runTurnGame(g, { ask: async () => raw }, { onUpdate: r => records.push(r) });
  const e = records[0]!.execution!;
  assert.equal(e.status, 'applied');
  assert.deepEqual(e.rawAnswers, raw);
  assert.equal((e.executedAnswers!.action as { choice: string }).choice, selected);
  assert.equal(e.feedback!.status, 'progressed');
});

test('boxing low confidence executes the selected command without a guard override', async () => {
  const records: RealtimeRecord[] = [], g = createBoxingGame();
  const m = createRealtimeMatch(g, { ask: async () => ({ action: { type: 'choice', choice: 'heavy', confidence: .1, probabilities: { heavy: 1 } }, needGuard: { type: 'noul', noul: .9 } }) }, { decisionMs: 50, onUpdate: r => records.push(r) });
  await m.tick();
  assert.equal(records[0]!.execution!.action!.command, 'heavy');
  assert.equal(records[0]!.execution!.reason, null);
  assert.equal((records[0]!.execution!.rawAnswers.action as { choice: string }).choice, 'heavy'); m.stop();
});

test('all registered games and model rivals provide semantic hooks', () => {
  for (const plugin of createDefaultRegistry().list()) {
    const g = plugin.create(undefined, { seed: 42 }), state = g.initialState();
    assert.ok(g.decision, plugin.id);
    assert.ok(Number.isFinite(g.decision.capture(state).progress));
    if ('rival' in g && g.rival) assert.ok(g.rival.decision, `${plugin.id}/rival`);
  }
});
