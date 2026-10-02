import { responseBackend } from '../src/systemone/request.js';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runBenchmark, summarizeBenchmark } from '../src/arena/benchmark.js';
import type { GamePlugin } from '../src/arena/plugin.js';
import { createSokobanGame } from '../src/games/sokoban/adapter.js';
import { createMockSystemOne } from '../src/systemone/mock.js';

const seeds: number[] = [];
const plugin: GamePlugin = { id: 'sokoban', name: 'probe', mode: 'turn', clientScript: '', create: (_variant, options) => {
  seeds.push(options!.seed!); return createSokobanGame(['########', '# @$.  #', '#      #', '#      #', '#      #', '#      #', '#      #', '########']) as ReturnType<GamePlugin['create']>;
} };

test('benchmark pairs identical seeds and includes failed backends in denominator', async () => {
  seeds.length = 0;
  const runs = await runBenchmark({ plugins: [plugin], seeds: [2, 8], backends: ['mock', 'failed'],
    createBackend: n => { if (n === 'failed') throw Error('unavailable'); return createMockSystemOne(); } });
  assert.equal(runs.length, 4); assert.deepEqual(seeds, [2, 8]);
  assert.deepEqual(runs.map(r => r.outcome), ['won', 'error', 'won', 'error']);
  assert.equal(summarizeBenchmark(runs)[1]!.successRate, 0);
  assert.equal(runs[0]!.estimatedCostUsd, 0); assert.equal(runs[1]!.estimatedCostUsd, null);
  assert.match(runs[0]!.provenance!.initialStateSha256, /^[a-f0-9]{64}$/);
  assert.deepEqual(runs[0]!.provenance!.resolvedModels, ['local-heuristic-v1']);
});

test('unknown usage never becomes zero paid cost; supplied pricing uses actual token counts', async () => {
  const runs = await runBenchmark({ plugins: [plugin], backends: ['priced', 'unknown'], prices: { priced: { inputPerMillion: 2, outputPerMillion: 4 } },
    createBackend: n => responseBackend(async (state, questions) => ({ answers: await createMockSystemOne().ask(state, questions), ...(n === 'priced' ? { usage: { promptTokens: 100, completionTokens: 10, totalTokens: 110 } } : {}) })) });
  assert.equal(runs[0]!.estimatedCostUsd, .00024);
  assert.equal(runs[1]!.usageComplete, false); assert.equal(runs[1]!.estimatedCostUsd, null);
  assert.deepEqual(runs[1]!.provenance!.resolvedModels, []);
});

test('hung turn backend times out; last allowed request can still win', async () => {
  const runs = await runBenchmark({ plugins: [plugin], backends: ['hung', 'mock'], maxRequests: 1, requestTimeoutMs: 10,
    createBackend: n => n === 'hung' ? { ask: () => new Promise(() => {}) } : createMockSystemOne() });
  assert.equal(runs[0]!.outcome, 'error'); assert.equal(runs[0]!.requests, 1);
  assert.equal(runs[1]!.outcome, 'won'); assert.equal(runs[1]!.requests, 1);
});
