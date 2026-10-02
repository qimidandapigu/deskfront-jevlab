import { test } from 'node:test';
import assert from 'node:assert/strict';
import { confidenceFrom } from '../src/systemone/types.js';

test('confidence: 全集中分布接近 1', () => {
  const c = confidenceFrom({ a: 0.97, b: 0.02, c: 0.01 });
  assert.ok(c > 0.85, `expected > 0.85, got ${c}`);
});

test('confidence: 均匀分布接近 0', () => {
  const c = confidenceFrom({ a: 0.25, b: 0.25, c: 0.25, d: 0.25 });
  assert.ok(c < 0.05, `expected < 0.05, got ${c}`);
});

test('confidence: 单选项恒为 1', () => {
  assert.equal(confidenceFrom({ only: 1 }), 1);
});
