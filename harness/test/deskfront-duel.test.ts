import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { createSessionService } from '../src/arena/sessions.js';
import { createDefaultRegistry } from '../src/games/index.js';
import { createDefaultRuntimeRegistry } from '../src/games/runtimes.js';
import { createMockSystemOne } from '../src/systemone/mock.js';
import type { SystemOne } from '../src/systemone/types.js';

test('legacy 1v1 adapter leaves source intact: six active infantry, opposite controllers and real receipts', {
  skip: process.env.DESKFRONT_LIVE_TEST !== '1', timeout: 100000,
}, async () => {
  const configuredRoot = process.env.DESKFRONT_ROOT;
  const root = configuredRoot
    ? resolve(configuredRoot)
    : [resolve('..'), resolve('../deskfront-jevlab')]
      .find(candidate => existsSync(resolve(candidate, 'project.godot')))
    ?? resolve('../deskfront-jevlab');
  const before = execFileSync('git', ['diff', '--', '*.gd', '*.py', '*.json', '*.js', '*.html'], { cwd: root });
  const mock = createMockSystemOne();
  const backend: SystemOne = { async ask(state, questions) {
    const answers = await mock.ask(state, questions);
    const tactic = questions.tactic;
    if (tactic?.type === 'choice' && tactic.criteria.capture_flag) answers.tactic = { type: 'choice', choice: 'capture_flag', confidence: 1,
      probabilities: Object.fromEntries(Object.keys(tactic.criteria).map(key => [key, key === 'capture_flag' ? 1 : 0])) };
    return answers;
  } };
  const sessions = createSessionService({ registry: createDefaultRegistry(), runtimes: createDefaultRuntimeRegistry(), backend,
    backends: { names: ['mock'], defaultName: 'mock', create: () => backend }, logDir: 'output/deskfront-duel-test' });
  try {
    const id = sessions.start('deskfront', { backend: 'mock', variant: 'duel-headless',
      gameOptions: { modelFaction: 'red', behavior: 'legacy' }, runtime: { maxRequests: 12, durationMs: 90000 } }).matchId;
    let verified = false;
    for (let i = 0; i < 340; i++) {
      await new Promise(r => setTimeout(r, 250));
      const state = sessions.state(id);
      assert.notEqual(state.outcome, 'error', state.error);
      const world = state.latest?.observation as { demo?: { phase: string; participants: string[] }; control: Record<string, string>;
        units: { faction: string; deployment_phase?: string; kind: string }[]; tank_spawned: boolean } | undefined;
      if (world?.demo?.phase === 'battle') {
        const active = world.units.filter(u => (u.deployment_phase ?? 'active') === 'active');
        assert.deepEqual(world.demo.participants, ['green', 'red']);
        assert.equal(active.length, 6);
        assert.ok(active.every((u: any) => u.max_hp === 30 && u.hp <= 30), "all deployed infantry use 30 hp");
        assert.ok(active.every(u => u.faction !== 'blue' && u.kind !== 'tank'));
        assert.equal(world.control.red, 'lm'); assert.equal(world.control.green, 'game_ai');
        assert.equal(world.tank_spawned, false);
        const rows = sessions.history(id).history as { record?: { receipt?: { accepted?: boolean } } }[];
        if (rows.some(r => r.record?.receipt?.accepted === true)) { verified = true; break; }
      }
      if (state.status === 'done') break;
    }
    assert.ok(verified, 'Duel must finish deployment and execute a model-selected command');
    sessions.stop(id); await sessions.wait(id);
  } finally {
    await sessions.close();
    assert.deepEqual(execFileSync('git', ['diff', '--', '*.gd', '*.py', '*.json', '*.js', '*.html'], { cwd: root }), before,
      'Harness must not modify game source');
  }
});

test('human 1v1 opens only after a real squad receipt, then preserves six native infantry', {
  skip: process.env.DESKFRONT_LIVE_TEST !== '1', timeout: 90000,
}, async () => {
  const backend = createMockSystemOne();
  const sessions = createSessionService({ registry: createDefaultRegistry(), runtimes: createDefaultRuntimeRegistry(), backend,
    backends: { names: ['mock'], defaultName: 'mock', create: () => backend }, logDir: 'output/deskfront-human-duel-test' });
  try {
    const id = sessions.start('deskfront', { backend: 'mock', variant: 'duel-headless',
      gameOptions: { modelFaction: 'green', behavior: 'human_squad', opponent: 'game_ai' }, runtime: { maxRequests: 20, durationMs: 70000 } }).matchId;
    let verified = false;
    for (let i = 0; i < 280; i++) {
      await new Promise(r => setTimeout(r, 250));
      const state = sessions.state(id);
      assert.notEqual(state.outcome, 'error', state.error);
      const world = state.latest?.observation as any;
      const game = (state.payload as any)?.game;
      if (world?.demo?.phase === 'battle' && Number(world.time) > .5 && !world.paused) {
        assert.equal(world.squad_behavior.enabled, true);
        assert.equal(game.lm.controller, 'human_squad');
        assert.equal(game.lm.squad.source, 'local_rules_baseline');
        assert.ok(game.lm.run_accepted_orders >= 1, 'battle must wait for Godot acceptance');
        assert.deepEqual(world.demo.participants, ['green', 'red']);
        const active = world.units.filter((u: any) => (u.deployment_phase ?? 'active') === 'active');
        assert.equal(active.length, 6);
        assert.ok(active.every((u: any) => u.max_hp === 30 && u.hp <= 30), "all deployed infantry use 30 hp");
        assert.ok(active.every((u: any) => u.faction !== 'blue' && u.kind !== 'tank'));
        assert.equal(world.control.green, 'lm');
        assert.equal(world.control.red, 'game_ai');
        assert.ok(world.squad_behavior.squads['green-squad'].order_id);
        verified = true; break;
      }
      if (state.status === 'done') break;
    }
    assert.ok(verified, 'human squad must execute and release opening gate in real Godot');
    sessions.stop(id); await sessions.wait(id);
  } finally { await sessions.close(); }
});

test('dual Harness 1v1 waits for both faction receipts', {
  skip: process.env.DESKFRONT_LIVE_TEST !== '1', timeout: 90000,
}, async () => {
  const backend = createMockSystemOne();
  const sessions = createSessionService({ registry: createDefaultRegistry(), runtimes: createDefaultRuntimeRegistry(), backend,
    backends: { names: ['mock'], defaultName: 'mock', create: () => backend }, logDir: 'output/deskfront-human-duel-test' });
  try {
    const id = sessions.start('deskfront', { backend: 'mock', variant: 'duel-headless',
      gameOptions: { modelFaction: 'green', behavior: 'human_squad', opponent: 'harness' }, runtime: { maxRequests: 20, durationMs: 70000 } }).matchId;
    let verified = false;
    for (let i = 0; i < 280; i++) {
      await new Promise(r => setTimeout(r, 250));
      const state = sessions.state(id);
      assert.notEqual(state.outcome, 'error', state.error);
      const world = state.latest?.observation as any;
      const game = (state.payload as any)?.game;
      if (world?.demo?.phase === 'battle' && Number(world.time) > .5 && !world.paused) {
        assert.equal(world.squad_behavior.enabled, true);
        assert.equal(game.lm.controller, 'human_squad');
        assert.equal(game.lm.squad.source, 'local_rules_baseline');
        assert.ok(game.lm.run_accepted_orders >= 1, 'battle must wait for Godot acceptance');
        assert.deepEqual(world.demo.participants, ['green', 'red']);
        const active = world.units.filter((u: any) => (u.deployment_phase ?? 'active') === 'active');
        assert.equal(active.length, 6);
        assert.ok(active.every((u: any) => u.max_hp === 30 && u.hp <= 30), "all deployed infantry use 30 hp");
        assert.ok(active.every((u: any) => u.faction !== 'blue' && u.kind !== 'tank'));
        assert.equal(world.control.green, 'lm');
        assert.equal(world.control.red, 'lm');
        assert.ok(game.harnessSides.green.run_accepted_orders >= 1);
        assert.ok(game.harnessSides.red.run_accepted_orders >= 1);
        assert.ok(world.squad_behavior.squads['red-squad'].order_id);
        assert.equal(game.nativeLM ?? null, null);
        assert.ok(world.squad_behavior.squads['green-squad'].order_id);
        verified = true; break;
      }
      if (state.status === 'done') break;
    }
    assert.ok(verified, 'human squad must execute and release opening gate in real Godot');
    sessions.stop(id); await sessions.wait(id);
  } finally { await sessions.close(); }
});
