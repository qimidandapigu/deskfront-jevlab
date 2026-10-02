import { test } from 'node:test';
import assert from 'node:assert/strict';
import { starterLevel, actor, progress, validateActions } from '../src/games/jump/engine.js';
import { generateCandidates } from '../src/games/jump/candidates.js';

test('出生点生成 5–10 个候选，主候选在首且实测不摔死', () => {
  const level = starterLevel();
  const cands = generateCandidates(level, actor(level.spawn), progress());
  assert.ok(cands.length >= 5 && cands.length <= 10, `n=${cands.length}`);
  assert.equal(cands[0]!.id, 'cand-0');
  assert.equal(cands[0]!.dead, false);
  for (const c of cands) {
    assert.ok(c.actions.length >= 1 && c.actions.length <= 12);
    assert.ok(c.actions.reduce((n, a) => n + a.frames, 0) <= 360);
    assert.doesNotThrow(() => validateActions(c.actions, 360));
    assert.ok(c.summary.length > 0);
  }
});

test('候选纯函数：同状态两次生成完全一致', () => {
  const level = starterLevel();
  const a = actor(level.spawn), p = progress();
  assert.deepEqual(generateCandidates(level, a, p), generateCandidates(level, a, p));
});

test('接近终点时主候选直接 won', () => {
  const level = starterLevel();
  const nearDone = { coins: [0, 1, 2], key: true, switchOn: true, won: false };
  // 门后平台上，终点 (1088,400)
  const cands = generateCandidates(level, actor({ x: 1000, y: 400 }), nearDone);
  assert.equal(cands[0]!.won, true);
});

test('扰动变体与主候选动作不同且都合法', () => {
  const level = starterLevel();
  const cands = generateCandidates(level, actor(level.spawn), progress());
  const main = JSON.stringify(cands[0]!.actions);
  const variants = cands.slice(1);
  assert.ok(variants.length >= 4);
  assert.ok(variants.some(c => JSON.stringify(c.actions) !== main));
});

test('summary 格式：中文方向+跳+帧数', () => {
  const level = starterLevel();
  const cands = generateCandidates(level, actor(level.spawn), progress());
  assert.match(cands[0]!.summary, /[左右停]/);
  assert.match(cands[0]!.summary, /帧/);
});

test('回归：单段无跳主候选（纯走路到终点）也补齐到 ≥5 个候选', () => {
  const level = starterLevel();
  const nearDone = { coins: [0, 1, 2], key: true, switchOn: true, won: false };
  // searchRoute 解为单段 [{move:1,jump:false,frames:5}]：扰动为零个，
  // 填充大多去重，修复前只剩 3 个候选
  const cands = generateCandidates(level, actor({ x: 1050, y: 400 }), nearDone);
  assert.ok(cands.length >= 5 && cands.length <= 10, `n=${cands.length}`);
  assert.equal(cands[0]!.id, 'cand-0');
  for (const c of cands) assert.doesNotThrow(() => validateActions(c.actions, 360));
});

test('防御分支：searchRoute 无解时退化为固定探测集且非空', () => {
  const level = starterLevel();
  // 已死亡的 actor：搜索无法扩展任何节点，searchRoute 必然无解
  const dead = { ...actor(level.spawn), dead: true };
  const cands = generateCandidates(level, dead, progress());
  assert.ok(cands.length >= 1, '候选列表恒非空');
  assert.equal(cands[0]!.id, 'cand-0');
  for (const c of cands) {
    assert.doesNotThrow(() => validateActions(c.actions, 360));
    assert.ok(c.summary.length > 0);
  }
});
