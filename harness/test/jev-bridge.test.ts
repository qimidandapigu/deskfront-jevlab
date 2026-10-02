import { responseBackend } from '../src/systemone/request.js';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createSystemOneJevClient, toJevAnswer } from '../src/jgp/jev-real.js';
import { createMockSystemOne } from '../src/systemone/mock.js';
import type { SystemOne } from '../src/systemone/types.js';

test('bridge: 任意 SystemOne 后端可驱动 JGP（mock 离线可用）', async () => {
  const client = createSystemOneJevClient(createMockSystemOne(), { model: 'mock' });
  const res = await client.systemOne({
    state: {},
    questions: { action: { type: 'choice', criteria: { chase: 'x', hold: 'y' } } },
  });
  assert.equal(res.model, 'local-heuristic-v1');
  assert.equal(res.answers['action']?.choice, 'chase'); // mock 启发式不适用时取第一个选项
  assert.equal(typeof res.answers['action']?.confidence, 'number');
});

test('bridge: choice 问题的分级字段（highRisk/safeAction/allowOther）透传给 SystemOne', async () => {
  let seen: unknown = null;
  const inner: SystemOne = {
    async ask(_state, questions) {
      seen = questions['q'];
      return { q: { type: 'choice', choice: 'a', probabilities: { a: 1 }, confidence: 1 } };
    },
  };
  const client = createSystemOneJevClient(inner);
  await client.systemOne({
    state: {},
    questions: { q: { type: 'choice', criteria: { a: 'A' }, highRisk: ['a'], safeAction: 'a', allowOther: true } },
  });
  assert.deepEqual(seen, {
    type: 'choice', instructions: '', criteria: { a: 'A' },
    allowOther: true, highRisk: ['a'], safeAction: 'a',
  });
});

test('bridge: noul confidence 优先用后端值，缺失时按 max(p, 1-p) 合成', () => {
  assert.deepEqual(toJevAnswer({ type: 'noul', noul: 0.9 }), { noul: true, confidence: 0.9 });
  assert.deepEqual(toJevAnswer({ type: 'noul', noul: 0.1 }), { noul: false, confidence: 0.9 });
  assert.deepEqual(toJevAnswer({ type: 'noul', noul: 0.9, confidence: 0.7 }), { noul: true, confidence: 0.7 });
});

test('bridge: usage 从本次 response 透传进 JevResponse', async () => {
  const inner = responseBackend(async () => ({ answers: { q: { type: 'noul', noul: 1, confidence: 1 } }, usage: { promptTokens: 1, completionTokens: 2, totalTokens: 3 } }));
  const client = createSystemOneJevClient(inner);
  const res = await client.systemOne({ state: {}, questions: { q: { type: 'noul' } } });
  assert.deepEqual(res.usage, { promptTokens: 1, completionTokens: 2, totalTokens: 3 });
});
