import test from 'node:test';
import assert from 'node:assert/strict';
import { buildLevel, randomPlan, validateLevel, decodePlan, generationQuestions, generateLevel } from '../src/games/soldiers/endless.js';
import { stepFirefight } from '../src/games/soldiers/engine.js';

test('endless maps: 1000 seeds have safe reachable spawns, changing layouts, and deterministic generation', () => {
  const layouts = new Set<string>();
  for (let seed = 0; seed < 1000; seed++) {
    const p = randomPlan(seed), f = buildLevel(p, seed, 55);
    assert.ok(validateLevel(f));
    assert.deepEqual(f, buildLevel(p, seed, 55));
    assert.ok(f.enemies.length >= 2 && f.enemies.length <= 4);
    assert.ok(f.player.hp >= 55 && f.player.hp <= 100);
    layouts.add(JSON.stringify(f.sandbags));
    f.command = 'north_shoot';
    for (let i = 0; i < 10; i++) stepFirefight(f);
    assert.ok(Number.isFinite(f.player.x));
  }
  assert.ok(layouts.size > 30, 'random layouts should not collapse to a few repeated maps');
});
test('invalid model choices are rejected rather than presented as generated maps', () => {
  assert.throws(() => decodePlan({}));
});
test('generation sends performance and returns actual typed decisions', async () => {
  const state = { hp: 24, damage: 76, seconds: 45, movingRatio: .3, stage: 2, recent: [] };
  const result = await generateLevel({ async ask(input, questions) {
    assert.equal((input as typeof state).hp, state.hp); assert.match((input as { healthCondition: string }).healthCondition, /critical/); assert.equal(questions, generationQuestions);
    return Object.fromEntries(Object.entries(questions).map(([k, q]) => {
      assert.equal(q.type, 'choice');
      const selected = k === 'pressure' ? 'recovery' : Object.keys(q.type === 'choice' ? q.criteria : {})[0]!;
      return [k, { type: 'choice' as const, choice: selected, probabilities: { [selected]: 1 }, confidence: 1 }];
    }));
  } }, state);
  assert.equal(result.plan.pressure, 'recovery');
  assert.ok(validateLevel(buildLevel(result.plan, 1, 24)));
});

import { appendTerrain, trimTerrain } from '../src/games/soldiers/endless.js';
test('continuous terrain preserves combat state and supports travel across seams without kills', () => {
  const f = buildLevel(randomPlan(42), 42, 100);
  f.endless = { minY: 0, maxY: 19 };
  const player = f.player; player.ammo = 3; player.reload = 12;
  appendTerrain(f, randomPlan(43), 43, 2);
  assert.equal(f.player, player); assert.equal(player.ammo, 3); assert.equal(player.reload, 12);
  assert.equal(f.endless.minY, -20);
  f.enemies = []; f.player.x = 20; f.player.y = 1;
  f.command = 'north';
  for (let i = 0; i < 8; i++) stepFirefight(f);
  assert.equal(f.status, 'running'); assert.equal(f.player.y, -3);
  f.tick = 4000; stepFirefight(f); assert.equal(f.status, 'running');
  f.player.hp = 0; stepFirefight(f); assert.equal(f.status, 'done');
});
test('continuous terrain recycles old strips while keeping memory bounded', () => {
  const f = buildLevel(randomPlan(1), 1, 100);
  f.endless = { minY: 0, maxY: 19 };
  for (let i = 1; i <= 200; i++) {
    appendTerrain(f, randomPlan(i), i, i);
    f.player.y = f.endless.minY + 15;
    trimTerrain(f);
    assert.ok(f.sandbags.length < 250);
    assert.ok(f.enemies.length <= 12);
  }
  assert.equal(f.endless.minY, -4000);
});
