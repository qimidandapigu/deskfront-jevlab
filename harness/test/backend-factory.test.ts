import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createSystemOne } from '../src/systemone/index.js';

test('factory: 默认 mock', () => {
  assert.doesNotThrow(() => createSystemOne({}));
});

test('factory: deepseek 缺 key 抛错', () => {
  assert.throws(() => createSystemOne({ SYSTEMONE_BACKEND: 'deepseek' }), /MODEL_API_KEY/);
});

test('factory: jev 缺 key 抛错', () => {
  assert.throws(() => createSystemOne({ SYSTEMONE_BACKEND: 'jev' }), /TYPESAFE_API_KEY/);
});
