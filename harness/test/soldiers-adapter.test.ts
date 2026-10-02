import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRealtimeMatch } from '../src/arena/realtime.js';
import { createSoldiersGame } from '../src/games/soldiers/adapter.js';
import { newFirefight, stepFirefight, hasLos, SOLDIERS, firingRoute } from '../src/games/soldiers/engine.js';
import { createDefaultRegistry } from '../src/games/index.js';
import type { Answer, SystemOne } from '../src/systemone/types.js';

const shootBackend: SystemOne = {
  ask: async (_state, questions) => Object.fromEntries(Object.entries(questions).map(([name, q]) => {
    const choice = name === 'movement' ? 'advance' : name === 'weapon' ? 'shoot' : name === 'duration' ? 'long' : q.type === 'choice' ? Object.keys(q.criteria)[0]! : '';
    return [name, { type: 'choice', choice, probabilities: { [choice]: 1 }, confidence: 1 }];
  })) as Record<string, Answer>,
};

test('soldiers: 已注册进默认注册表', () => {
  const ids = createDefaultRegistry().list().map(g => g.id);
  assert.ok(ids.includes('soldiers'));
});

test('AI uses independent movement, weapon, target and duration choices', () => {
  const game = createSoldiersGame(), state = game.initialState();
  const qs = game.questions(state);
  assert.deepEqual(Object.keys(qs), ['movement', 'weapon', 'target', 'duration', 'ally-1_movement', 'ally-1_weapon', 'ally-1_target', 'ally-1_duration']);
  assert.ok(Object.values(qs).every(q => q.type === 'choice'));
  state.game.enemies[1]!.hp = 0;
  const target = game.questions(state).target;
  assert.ok(target?.type === 'choice');
  assert.deepEqual(Object.keys(target.criteria), ['enemy-0']);
});

test('observe 含双方位置、沙袋、视线状态', () => {
  const game = createSoldiersGame();
  const obs = game.observe(game.initialState()) as {
    player: { hp: number }; enemies: Array<{ distToPlayer: number; canSeePlayer: boolean }>;
    sandbags: unknown[]; enemiesAlive: number;
  };
  assert.equal(obs.player.hp, SOLDIERS.playerHp);
  assert.equal(obs.enemiesAlive, SOLDIERS.enemyCount);
  assert.ok(obs.sandbags.length > 0);
  assert.ok(obs.enemies.every(e => typeof e.distToPlayer === 'number' && typeof e.canSeePlayer === 'boolean'));
});

test('act 写入指令，非法 choice 保持原指令', () => {
  const game = createSoldiersGame();
  const s0 = game.initialState();
  const s1 = game.act(s0, { action: { type: 'choice', choice: 'flank', probabilities: { flank: 1 }, confidence: 1 } });
  assert.equal(s1.game.command, 'flank');
  const s2 = game.act(s1, { action: { type: 'choice', choice: 'fly', probabilities: { fly: 1 }, confidence: 1 } });
  assert.equal(s2.game.command, 'flank');
});

test('act 识别真人 control 输入（观测站自己玩），idle 回到据守', () => {
  const game = createSoldiersGame();
  const s0 = game.initialState();
  const s1 = game.act(s0, { control: { type: 'choice', choice: 'advance', probabilities: { advance: 1 }, confidence: 1 } });
  assert.equal(s1.game.command, 'advance');
  const s2 = game.act(s1, { control: { type: 'choice', choice: 'fly', probabilities: { fly: 1 }, confidence: 1 } });
  assert.equal(s2.game.command, 'advance');
  const s3 = game.act(s2, { control: { type: 'choice', choice: 'idle', probabilities: { idle: 1 }, confidence: 1 } });
  assert.equal(s3.game.command, 'hold');
});

test('engine: 沙袋挡视线，挪开即通', () => {
  const f = newFirefight(1);
  const bag = f.sandbags[5]!;
  // 隔着一个沙格对望：被挡
  assert.equal(hasLos(f, bag.x - 2, bag.y, bag.x + 2, bag.y), false);
  // 上方无遮挡：通
  assert.equal(hasLos(f, bag.x - 2, bag.y - 3 < 0 ? 0 : bag.y - 3, bag.x + 2, 0), true);
});

test('真人左右侧移方向固定且相反，不随时间自动反向', () => {
  for (const tick of [0, 40, 80]) {
    for (const [command, sign] of [['flankLeft', -1], ['flankRight', 1]] as const) {
      const game = createSoldiersGame();
      const state = game.initialState();
      state.game.tick = tick;
      state.game.sandbags = [];
      const x = state.game.player.x;
      game.act(state, { control: { type: 'choice', choice: command, probabilities: { [command]: 1 }, confidence: 1 } });
      game.step(state);
      assert.equal(Math.sign(state.game.player.x - x), sign);
    }
  }
});

test('2v2 时间到双方仍存活则平局', () => {
  const game = createSoldiersGame();
  const state = game.initialState();
  state.game.tick = SOLDIERS.limitTicks - 1;
  game.step(state);
  assert.equal(game.isTerminal(state), true);
  assert.equal(game.outcome?.(state), 'draw');
  assert.ok(state.game.events.includes('时间到，未能清除全部敌兵'));
});

test('engine: 射程内互相射击可分出胜负', async () => {
  const game = createSoldiersGame();
  const match = createRealtimeMatch(game, shootBackend, { decisionMs: 200, maxTicks: 5000 });
  for (let i = 0; i < 5000 && match.summary.outcome === 'finished'; i++) await match.tick();
  assert.equal(game.isTerminal(match.state), true);
  assert.ok(match.summary.decisions > 0);
  const obs = game.observe(match.state) as { status: string; winner: string | null };
  assert.equal(obs.status, 'done');
  assert.ok(obs.winner === 'player' || obs.winner === 'enemy');
});

test('engine: 掩体后的玩家不会被正面敌人打掉血', () => {
  const f = newFirefight(7);
  f.sandbags = [{ x: f.player.x, y: f.player.y - 2 }];
  f.enemyCommands = ["shoot", "hold"];
  // Construct cover explicitly; spawn geometry is no longer the old solo fortress.
  f.enemies.forEach(e => { e.hp = 0; });
  const e = f.enemies[0]!;
  e.hp = e.maxHp;
  e.x = f.player.x; e.y = f.player.y - 3.4;
  assert.equal(hasLos(f, e.x, e.y, f.player.x, f.player.y), false);
  const hpBefore = f.player.hp;
  for (let i = 0; i < 60; i++) stepFirefight(f);
  assert.equal(f.player.hp, hpBefore);
});

test('direct control moves in world axes and allows diagonal movement while firing', () => {
  const game = createSoldiersGame(), s = game.initialState();
  s.game.sandbags = [];
  const p = s.game.player;
  s.game.enemies.forEach((e, i) => { e.x = p.x + 4; e.y = p.y - 2; if (i) e.hp = 0; });
  const x = p.x, y = p.y;
  game.act(s, { control: { type: 'choice', choice: 'north_east_shoot', probabilities: { north_east_shoot: 1 }, confidence: 1 } });
  game.step(s);
  assert.ok(p.x > x && p.y < y);
  assert.ok(Math.abs(Math.hypot(p.x - x, p.y - y) - SOLDIERS.playerSpeed) < 1e-6);
  assert.equal(p.ammo, SOLDIERS.magazine);
  assert.equal(p.aim, SOLDIERS.aimTicks);
  assert.equal(s.game.enemies[0]!.hp, SOLDIERS.enemyHp);
});

test('enemy telegraphs a fixed aim point and moving out dodges the shot', () => {
  for (const dodge of [false, true]) {
    const f = newFirefight(); f.sandbags = [];
    f.player.x = 20; f.player.y = 15;
    f.enemies.forEach((e, i) => { e.x = 20; e.y = 10; if (i) e.hp = 0; });
    stepFirefight(f);
    assert.equal(f.player.hp, SOLDIERS.playerHp);
    assert.equal(f.enemies[0]!.aim, SOLDIERS.aimTicks);
    if (dodge) f.command = 'east';
    for (let i = 0; i < SOLDIERS.aimTicks; i++) stepFirefight(f);
    assert.equal(f.player.hp, SOLDIERS.playerHp - (dodge ? 0 : SOLDIERS.enemyDamage));
    assert.ok(f.tracers.some(t => t.id.endsWith('enemy-0') && t.hit === !dodge));
  }
});

test('reload blocks firing, refills only after its duration, and still permits movement', () => {
  const f = newFirefight(); f.sandbags = [];
  f.enemies.forEach((e, i) => { e.x = f.player.x; e.y = f.player.y - 5; if (i) e.hp = 0; });
  f.enemyCommands = ['hold', 'hold', 'hold'];
  f.player.ammo = 0; f.command = 'shoot'; stepFirefight(f);
  assert.equal(f.player.reload, SOLDIERS.reloadTicks);
  assert.equal(f.enemies[0]!.hp, SOLDIERS.enemyHp);
  f.command = 'east_shoot';
  const x = f.player.x;
  stepFirefight(f);
  assert.ok(f.player.x > x);
  assert.equal(f.enemies[0]!.hp, SOLDIERS.enemyHp);
  f.command = 'hold';
  for (let i = 1; i < SOLDIERS.reloadTicks; i++) stepFirefight(f);
  assert.equal(f.player.ammo, SOLDIERS.magazine);
  assert.equal(f.player.reload, 0);
});

test('auto aim chooses a visible enemy rather than a nearer enemy behind cover', () => {
  const f = newFirefight(); f.player.x = 10; f.player.y = 10;
  f.sandbags = [{ x: 10, y: 8 }];
  f.enemies[0]!.x = 10; f.enemies[0]!.y = 6;
  f.enemies[1]!.x = 16; f.enemies[1]!.y = 10;
  f.enemyCommands = ['hold', 'hold', 'hold'];
  f.command = 'shoot';
  for (let i = 0; i <= SOLDIERS.aimTicks; i++) stepFirefight(f);
  assert.equal(f.enemies[0]!.hp, SOLDIERS.enemyHp);
  assert.equal(f.enemies[1]!.hp, SOLDIERS.enemyHp - SOLDIERS.playerDamage);
});

function choices(values: Record<string, string>): Record<string, Answer> {
  return Object.fromEntries(Object.entries(values).map(([key, choice]) => [key, { type: 'choice', choice, probabilities: { [choice]: 1 }, confidence: 1 }]));
}

test('recorded sandbag stalemate: repeated hold/shoot is recovered without crossing cover', () => {
  const game = createSoldiersGame(), s = game.initialState(), f = s.game;
  Object.assign(f.player, { hp:96, x:20, y:15 }); f.enemies[0]!.hp = 0;
  f.sandbags = [18,19,20,21,22].map(x=>({x,y:13}));
  Object.assign(f.enemies[1]!, { x: 20, y: 11.5 });
  f.enemyCommands = ['hold', 'hold', 'hold'];
  const answers = choices({ movement: 'hold', weapon: 'shoot', target: 'enemy-1', duration: 'short' });
  assert.equal(hasLos(f, 20, 15, 20, 11.5), false);
  for (let i = 0; i < 4; i++) {
    game.act(s, answers);
    if (i < 3) for (let n = 0; n < 4; n++) game.step(s);
  }
  assert.equal(f.order!.movement, 'reposition');
  assert.ok(f.order!.recovery);
  for (let i = 0; i < 100 && f.enemies[1]!.hp === SOLDIERS.enemyHp; i++) {
    game.step(s);
    assert.ok(!f.sandbags.some(b => b.x === Math.round(f.player.x) && b.y === Math.round(f.player.y)));
  }
  assert.ok(f.enemies[1]!.hp < SOLDIERS.enemyHp, 'must actually open a firing angle and deal damage');
  assert.equal(answers.movement!.type === 'choice' && answers.movement!.choice, 'hold', 'raw model answer stays intact');
});

test('rival recovery survives early player decisions and opens a firing angle', () => {
  const game = createSoldiersGame(), s = game.initialState(), f = s.game;
  f.enemies[0]!.hp = 0;
  Object.assign(f.player,{x:20,y:15}); f.sandbags = [18,19,20,21,22].map(x=>({x,y:13}));
  Object.assign(f.enemies[1]!, { x: 20, y: 11.5 });
  const answers = choices({ 'enemy-1_movement': 'hold', 'enemy-1_weapon': 'shoot', 'enemy-1_target': 'player', 'enemy-1_duration': 'short' });
  for (let i = 0; i < 4; i++) { game.rival!.act(s, answers); for (let n = 0; n < 4; n++) game.step(s); }
  const recovery = f.enemyOrders[1];
  assert.equal(recovery?.movement, 'reposition');
  game.rival!.act(s, answers);
  assert.equal(f.enemyOrders[1], recovery);
  for (let i = 0; i < 100 && f.player.hp === 100; i++) game.step(s);
  assert.ok(f.player.hp < 100);
});

test('clear shots and human hold are never forced into recovery; unreachable route is explicit', () => {
  const game = createSoldiersGame(), s = game.initialState(), f = s.game;
  Object.assign(f.player,{x:20,y:15});
  f.sandbags = []; Object.assign(f.enemies[0]!, { x: 20, y: 10 });
  for (let i = 0; i < 8; i++) game.act(s, choices({ movement: 'hold', weapon: 'shoot', target: 'enemy-0', duration: 'short' }));
  assert.equal(f.order!.movement, 'hold');
  game.act(s, choices({ control: 'idle' }));
  assert.equal(f.order, null); assert.equal(f.command, 'hold');
  f.sandbags = Array.from({ length: SOLDIERS.width }, (_, x) => ({ x, y: 12 }));
  assert.equal(firingRoute(f, f.player, f.enemies[0]!), null);
  game.act(s, choices({ movement: 'reposition', weapon: 'shoot', target: 'enemy-0', duration: 'short' }));
  assert.equal(f.order!.reason, 'no-route');
});
test('timed order moves and shoots together, then releases both movement and weapon', () => {
  const game = createSoldiersGame(), s = game.initialState(); s.game.sandbags = [];
  Object.assign(s.game.player,{x:20,y:15});
  s.game.enemies.forEach((e, i) => { e.x = 20; e.y = 10; if (i) e.hp = 0; });
  s.game.enemyCommands = ['hold', 'hold', 'hold'];
  game.act(s, choices({ movement: 'right', weapon: 'shoot', target: 'enemy-0', duration: 'short' }));
  const x = s.game.player.x;
  for (let i = 0; i < 4; i++) game.step(s);
  assert.notEqual(s.game.player.x, x);
  assert.equal(s.game.enemies[0]!.hp, SOLDIERS.enemyHp);
  const end = { x: s.game.player.x, y: s.game.player.y };
  for (let i = 0; i < 20; i++) game.step(s);
  assert.equal(s.game.player.x, end.x); assert.equal(s.game.player.y, end.y);
  assert.equal(s.game.enemies[0]!.hp, SOLDIERS.enemyHp - SOLDIERS.playerDamage);
  assert.equal(game.decisionReady?.(s), true);
});
test('invalid or dead-target orders do not overwrite a valid plan; collision ends movement early', () => {
  const game = createSoldiersGame(), s = game.initialState();
  game.act(s, choices({ movement: 'advance', weapon: 'cease', target: 'enemy-0', duration: 'long' }));
  const old = s.game.order;
  game.act(s, choices({ movement: 'fly', weapon: 'shoot', target: 'enemy-0', duration: 'forever' }));
  assert.equal(s.game.order, old);
  s.game.player.x = 0; s.game.player.y = 0; s.game.enemies[0]!.x = 5; s.game.enemies[0]!.y = 0;
  game.act(s, choices({ movement: 'retreat', weapon: 'cease', target: 'enemy-0', duration: 'long' }));
  game.step(s);
  assert.equal(s.game.order?.reason, 'blocked');
  s.game.enemies[0]!.hp = 0; game.step(s);
  assert.equal(s.game.order?.reason, 'target-gone');
});
test('rival receives independent timed orders per enemy', () => {
  const game = createSoldiersGame(), s = game.initialState(); s.game.sandbags = [];
  game.rival!.act(s, choices({ 'enemy-0_movement': 'advance', 'enemy-0_weapon': 'shoot', 'enemy-0_target': 'player', 'enemy-0_duration': 'normal' }));
  assert.equal(s.game.enemyOrders[0]?.expiresAt, 10);
  const e = s.game.enemies[0]!, x = e.x;
  game.step(s); assert.notEqual(e.x, x);
  for (let i = 0; i < 9; i++) game.step(s);
  const stop = e.x; game.step(s); assert.equal(e.x, stop);
});


test('both factions share health, movement, damage and cooldown', () => {
  assert.equal(SOLDIERS.playerHp, SOLDIERS.enemyHp);
  assert.equal(SOLDIERS.playerSpeed, SOLDIERS.enemySpeed);
  assert.equal(SOLDIERS.playerDamage, SOLDIERS.enemyDamage);
  assert.equal(SOLDIERS.playerFireTicks, SOLDIERS.fireCooldownTicks);
});

test('both factions require the same windup and can dodge the same locked shot', () => {
  for (const shooterSide of ['player', 'enemy'] as const) {
    for (const dodge of [false, true]) {
      const f = newFirefight(); f.sandbags = [];
      f.player.x = 20; f.player.y = 15;
      f.enemies.forEach((e, i) => { e.x = 20; e.y = 10; if (i) e.hp = 0; });
      f.command = shooterSide === 'player' ? 'shoot' : 'hold';
      f.enemyCommands = [shooterSide === 'enemy' ? 'shoot' : 'hold', 'hold', 'hold'];
      const shooter = shooterSide === 'player' ? f.player : f.enemies[0]!;
      const target = shooterSide === 'player' ? f.enemies[0]! : f.player;
      stepFirefight(f);
      assert.equal(target.hp, 100); assert.equal(shooter.aim, SOLDIERS.aimTicks);
      if (dodge) target.x += 2;
      for (let i = 0; i < SOLDIERS.aimTicks; i++) stepFirefight(f);
      assert.equal(target.hp, dodge ? 100 : 90);
      assert.equal(shooter.ammo, 5);
      assert.equal(shooter.cool, SOLDIERS.fireCooldownTicks);
    }
  }
});
