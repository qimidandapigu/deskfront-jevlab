import { test } from 'node:test';
import assert from 'node:assert/strict';
import { assistDecision, createNavigationAssist, createStallRecoveryAssist, type AssistanceTool } from '../src/arena/assistance.js';
import { createMinimalRealtimeGame, createMinimalTurnGame } from '../src/arena/minimal.js';
import { runTurnGame, type TurnRecord } from '../src/arena/runner.js';
import { createRealtimeMatch, type RealtimeRecord } from '../src/arena/realtime.js';
import { createMinimalBoxing, createMinimalSokoban } from '../src/games/minimal-examples.js';
import { SOKOBAN_LEVELS } from '../src/games/sokoban/index.js';
import type { Answers, DecisionFeedback } from '../src/arena/decision.js';
import type { Question } from '../src/systemone/types.js';

const answers = (choice: string): Answers => ({ action: { type: 'choice', choice, confidence: 1, probabilities: { [choice]: 1 } } });
const questions: Record<string, Question> = { action: { type: 'choice', instructions: '', criteria: { wait: '', east: '', north: '' } } };
const stalled: DecisionFeedback = { decisionId: 'x', status: 'unchanged', progressDelta: 0, moved: false, repeats: 3, reason: '', at: 3 };
const navigation = createNavigationAssist();

test('same navigation tool works for a grid and a named-room graph; disconnected and bounded graphs abstain', () => {
  for (const nodes of [['0,0', '1,0', '1,1'], ['lobby', 'stairs', 'office']]) {
    const result = assistDecision({ tools: [navigation], ports: () => ({ navigation: {
      question: 'action', start: nodes[0]!, goal: nodes[2]!, neighbors: n => n === nodes[0] ? [{ to: nodes[1]!, action: 'east' }]
        : n === nodes[1] ? [{ to: nodes[2]!, action: 'north' }] : [],
    } }) }, {}, questions, answers('wait'));
    assert.equal(result.answers.action?.type === 'choice' && result.answers.action.choice, 'east');
    assert.equal(result.trace[0]?.status, 'applied');
  }
  for (const limit of [1, 5]) {
    const result = assistDecision({ tools: [createNavigationAssist(limit)], ports: () => ({ navigation: {
      question: 'action', start: '0', goal: 'missing', neighbors: n => [{ to: String(Number(n) + 1), action: 'east' }],
    } }) }, {}, questions, answers('wait'));
    assert.deepEqual(result.answers, answers('wait'));
  }
});

test('off, absent capability, tool failure and invalid/injected commands preserve valid decisions', () => {
  assert.deepEqual(assistDecision(undefined, {}, questions, answers('wait')).trace, []);
  assert.equal(assistDecision({ tools: [navigation], ports: () => ({}) }, {}, questions, answers('wait')).trace[0]?.reason, 'missing-capability');
  const broken: AssistanceTool = { id: 'broken', requires: [], propose: () => { throw Error('broken'); } };
  const invalid: AssistanceTool = { id: 'invalid', requires: [], propose: () => ({ answers: answers('teleport'), reason: '' }) };
  const injected: AssistanceTool = { id: 'injected', requires: [], propose: () => ({ answers: { ...answers('east'), control: answers('east').action! }, reason: '' }) };
  const result = assistDecision({ tools: [broken, invalid, injected], ports: () => ({}) }, {}, questions, answers('wait'));
  assert.deepEqual(result.trace.map(t => t.status), ['error', 'rejected', 'rejected']);
  assert.deepEqual(result.answers, answers('wait'));
});

test('recovery requires actual stalled feedback; unknown or moving states are not recovered', () => {
  const policy = { tools: [createStallRecoveryAssist()], ports: () => ({ alternatives: { question: 'action', choices: ['east'] } }) };
  for (const feedback of [undefined, { ...stalled, moved: true }, { ...stalled, status: 'unknown' as const }])
    assert.deepEqual(assistDecision(policy, {}, questions, answers('wait'), feedback).answers, answers('wait'));
  assert.deepEqual(assistDecision(policy, {}, questions, answers('wait'), stalled).answers, answers('east'));
});

test('minimal turn adapter preserves engine defeat and unknown effects', async () => {
  const records: TurnRecord[] = [];
  const game = createMinimalTurnGame({ id: 'defeat', instructions: '', initial: () => false,
    inspect: done => ({ observation: { done }, actions: { go: 'go' }, outcome: done ? 'lost' : null }),
    execute: () => ({ state: true, accepted: true }) });
  const result = await runTurnGame(game, { ask: async () => answers('go') }, { onUpdate: r => records.push(r) });
  assert.equal(result.outcome, 'lost');
  assert.equal(records[0]?.execution?.feedback?.status, 'unknown');
});

test('turn runner applies assistance with original decision and intervention audit intact', async () => {
  const records: TurnRecord[] = [];
  const game = createMinimalTurnGame({ id: 'walk', instructions: '', initial: () => 0,
    inspect: x => ({ observation: { x }, actions: { wait: '', east: '' }, outcome: x === 1 ? 'won' : null }),
    execute: (x, action) => ({ state: x + (action === 'east' ? 1 : 0), accepted: true }),
    assistance: { tools: [navigation], ports: () => ({ navigation: { question: 'action', start: 'a', goal: 'b', neighbors: () => [{ to: 'b', action: 'east' }] } }) } });
  assert.equal((await runTurnGame(game, { ask: async () => answers('wait') }, { onUpdate: r => records.push(r) })).outcome, 'won');
  const e = records[0]!.execution!;
  assert.deepEqual(e.rawAnswers, answers('wait'));
  assert.deepEqual(e.executedAnswers, answers('east'));
  assert.equal(e.assistance?.[0]?.tool, navigation.id);
});

test('realtime lease releases old input while the next model response is pending', async () => {
  let calls = 0;
  const game = createMinimalRealtimeGame({ id: 'lease', instructions: '', tickMs: 10, actionTicks: 2,
    initial: () => ({ x: 0, input: false }),
    inspect: s => ({ observation: s, actions: { go: '' }, outcome: null }),
    execute: (s) => ({ state: { ...s, input: true }, accepted: true }),
    step: s => ({ ...s, x: s.x + Number(s.input) }), release: s => ({ ...s, input: false }),
  });
  const match = createRealtimeMatch(game, { ask: () => ++calls === 1 ? Promise.resolve(answers('go')) : new Promise(() => {}) });
  await match.tick();
  for (let i = 0; i < 6; i++) await match.tick(false);
  assert.equal(match.state.world.x, 2);
  assert.equal(match.state.world.input, false);
  match.stop();
});

test('real sokoban and boxing engines run via thin adapters; shared recovery is opt-in', async () => {
  const puzzle = createMinimalSokoban(SOKOBAN_LEVELS[0]!.rows);
  assert.equal((await runTurnGame(puzzle, { ask: async () => answers('U') })).outcome, 'won');
  assert.equal(puzzle.decision?.assistance, undefined);
  assert.equal(createMinimalSokoban(SOKOBAN_LEVELS[0]!.rows, true).decision?.assistance?.tools[0]?.id,
    createMinimalBoxing(true).decision?.assistance?.tools[0]?.id);
  const records: RealtimeRecord[] = [];
  const match = createRealtimeMatch(createMinimalBoxing(true), { ask: async () => answers('idle') }, { onUpdate: r => records.push(r) });
  for (let i = 0; i < 45; i++) await match.tick();
  assert.ok(records.some(r => r.execution?.assistance?.some(t => t.status === 'applied')));
  match.stop();
});
