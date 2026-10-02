import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  PHYSICS, starterLevel, actor, progress, step, validateActions, replayActions,
  verifyLevel, searchRoute, tileMap, validateLevel,
} from '../src/games/jump/engine.js';

test('水平移动：每帧 speed 像素，空中同速', () => {
  const level = starterLevel();
  const a = actor(level.spawn), p = progress();
  for (let i = 0; i < 10; i++) step(a, { move: 1, jump: false }, level, p);
  assert.ok(Math.abs(a.x - (level.spawn.x + PHYSICS.speed * 10)) < 1e-9, `x=${a.x}`);
  assert.equal(a.grounded, true);
});

test('跳跃：按住起跳、松开跳切、可落到高台', () => {
  const level = starterLevel();
  // spawn (64,400)，平台 {x:128,y:336,w:112} 高 64，可跳上
  const a = actor(level.spawn), p = progress();
  const { actor: end } = replayActions(level, a, p, validateActions([
    { move: 1, jump: false, frames: 20 },   // 助跑到 x=128
    { move: 1, jump: true, frames: 30 },    // 按住跳
    { move: 1, jump: false, frames: 30 },   // 松开继续飞/落地
  ], 360));
  assert.ok(!end.dead);
  assert.ok(end.x > level.spawn.x);
});

test('摔死：走出平台落入水中 y>470', () => {
  const level = starterLevel();
  // 平台 0 右边界 x=560，下一块在 x=624，中间 64px 空隙下方是水
  const { actor: end } = replayActions(level, actor({ x: 550, y: 400 }), progress(),
    validateActions([{ move: 1, jump: false, frames: 90 }], 360));
  assert.equal(end.dead, true);
});

test('未开门时门是墙，挡回角色', () => {
  const level = starterLevel();
  // door x=928，门未开；从门左边 900 持续向右走
  const { actor: end } = replayActions(level, actor({ x: 900, y: 400 }), progress(),
    validateActions([{ move: 1, jump: false, frames: 90 }], 360));
  assert.ok(end.x <= level.door.x - 14 + 0.01, `x=${end.x} 应被门挡住`);
  assert.equal(end.dead, false);
});

test('机关需要带钥匙且落地踩才开', () => {
  const level = starterLevel();
  const a = actor({ x: level.switch.x, y: 400 }), p = progress();
  step(a, { move: 0, jump: false }, level, p);
  assert.equal(p.switchOn, false, '无钥匙踩机关不应开');
  p.key = true;
  step(a, { move: 0, jump: false }, level, p);
  assert.equal(p.switchOn, true);
});

test('validateActions：段数/帧数上限与形状校验', () => {
  assert.throws(() => validateActions([]), /1–12/);
  assert.throws(() => validateActions(Array(13).fill({ move: 0, jump: false, frames: 1 })), /1–12/);
  assert.throws(() => validateActions([{ move: 2, jump: false, frames: 1 }]), /move/);
  assert.throws(() => validateActions([{ move: 0, jump: false, frames: 91 }]), /frames/);
  assert.throws(() => validateActions([{ move: 0, jump: false, frames: 90 }, { move: 0, jump: false, frames: 90 }], 100), /超过/);
  assert.equal(validateActions([{ move: -1, jump: true, frames: 30 }], 360).length, 1);
});

test('replayActions 确定性且不改输入；同输入同结果', () => {
  const level = starterLevel();
  const a0 = actor(level.spawn), p0 = progress();
  const actions = validateActions([{ move: 1, jump: false, frames: 60 }], 360);
  const r1 = replayActions(level, a0, p0, actions);
  const r2 = replayActions(level, a0, p0, actions);
  assert.deepEqual(r1, r2);
  assert.equal(a0.x, level.spawn.x, '输入 actor 不被修改');
  assert.equal(p0.coins.length, 0, '输入 progress 不被修改');
});

test('verifyLevel(starterLevel) 找到完整通关解', () => {
  const result = verifyLevel(starterLevel());
  assert.equal(result.verified, true, result.reason);
  assert.ok(result.actions && result.actions.length > 0);
  // 解回放后确实通关
  const level = starterLevel();
  const check = replayActions(level, actor(level.spawn), progress(), result.actions!);
  assert.equal(check.progress.won, true);
});

test('searchRoute 可从关卡中段的任意 actor/progress 起搜', () => {
  const level = starterLevel();
  // 已拿钥匙+机关+两枚金币，站在第二块地面上
  const mid = { ...progress(), key: true, switchOn: true, coins: [0, 1] };
  const result = searchRoute(level, actor({ x: 720, y: 336 }), mid);
  assert.equal(result.verified, true, result.reason);
  const check = replayActions(level, actor({ x: 720, y: 336 }), mid, result.actions!);
  assert.equal(check.progress.won, true);
});

test('tileMap 含图例与关键字符', () => {
  const level = starterLevel();
  const screen = tileMap(level, actor(level.spawn), progress());
  const all = screen.rows.join('\n');
  assert.ok(all.includes('#') && all.includes('~') && all.includes('k') && all.includes('s') && all.includes('D') && all.includes('G') && all.includes('@'));
  assert.ok(screen.legend.includes('地面'));
});

test('validateLevel 拒绝非法关卡', () => {
  assert.throws(() => validateLevel({ version: 1 }), /关卡格式/);
  assert.throws(() => validateLevel(null), /关卡格式/);
});
