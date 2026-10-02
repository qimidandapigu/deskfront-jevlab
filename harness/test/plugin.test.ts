import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createGameRegistry } from '../src/arena/registry.js';
import { createDefaultRegistry } from '../src/games/index.js';
import { sokobanPlugin } from '../src/games/sokoban/index.js';
import { runTurnGame } from '../src/arena/runner.js';
import { createMockSystemOne } from '../src/systemone/mock.js';
import type { TurnBasedGame } from '../src/arena/plugin.js';

test('注册表：推箱子已注册，可取可玩', async () => {
  const registry = createDefaultRegistry();
  assert.ok(registry.list().some(g => g.id === 'sokoban' && g.name === '推箱子' && g.mode === 'turn'));
  const plugin = registry.get('sokoban');
  assert.equal(plugin.mode, 'turn');
  const game = plugin.create() as TurnBasedGame<{ player: number }>;
  const summary = await runTurnGame(game, createMockSystemOne(), { maxTurns: 10 });
  assert.equal(summary.outcome, 'won', '默认入门关卡可以离线完整通关');
});

test('注册表：未知 id 抛错', () => {
  const registry = createDefaultRegistry();
  assert.throws(() => registry.get('mahjong'), /未注册/);
});

test('注册表：重复 id 抛错且实例间隔离（JEP §2/§5）', () => {
  const a = createGameRegistry();
  a.register(sokobanPlugin);
  assert.throws(() => a.register(sokobanPlugin), /重复注册/);
  // 另一个注册表实例不受 a 影响
  const b = createGameRegistry();
  assert.doesNotThrow(() => b.register(sokobanPlugin));
  assert.equal(b.list().length, 1);
});
