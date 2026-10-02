import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parse, won } from '../src/games/sokoban/engine.js';
import { walkingPaths, pushPositionKey, reachablePushes, applyPush } from '../src/games/sokoban/pushes.js';

const ROWS = [
  '########',
  '#      #',
  '# .    #',
  '# $    #',
  '# @    #',
  '#      #',
  '#      #',
  '########',
];

test('walkingPaths: 箱子固定，走位绕箱而行', () => {
  const s = parse(ROWS);
  const paths = walkingPaths(s);
  // (2,4) 正上方是箱子，到 (2,2) 必须从左侧绕行
  assert.equal(paths.get(2 * 8 + 2), 'LUUR');
  // 箱子占据的格子不可走
  assert.ok(!paths.has(3 * 8 + 2));
});

test('pushPositionKey: 同一连通区域内走位等价，推箱后变化', () => {
  const s = parse(ROWS);
  const moved = { ...s, player: 5 * 8 + 5 };
  assert.equal(pushPositionKey(moved), pushPositionKey(s));
  const push = reachablePushes(s).find(o => o.id === 'push-A-U')!;
  assert.notEqual(pushPositionKey(applyPush(s, push)), pushPositionKey(s));
});

test('reachablePushes: 推到非目标死角标注 corner 与 deadlock', () => {
  const s = parse([
    '########',
    '# $@   #',
    '#      #',
    '#    . #',
    '#      #',
    '#      #',
    '#      #',
    '########',
  ]);
  const pushes = reachablePushes(s);
  const left = pushes.find(o => o.id === 'push-A-L')!;
  assert.deepEqual(left.boxTo, { x: 1, y: 1 });
  assert.equal(left.corner, true);
  assert.equal(left.deadlock, true);
  assert.ok(left.warning && left.warning.includes('不可能通关'));
});

test('reachablePushes: 双箱互斥——推上唯一可行目标点判 deadlock（非死角）', () => {
  // A 箱 (3,2) 推上第 1 行后被墙困住只能去 G1(1,1)，而 B 箱 (1,3) 贴左墙也只能去 G1
  const s = parse([
    '########',
    '#.     #',
    '#  $   #',
    '#$ @   #',
    '#      #',
    '#      #',
    '#    . #',
    '########',
  ]);
  const pushes = reachablePushes(s);
  const trap = pushes.find(o => o.id === 'push-A-U')!;
  assert.deepEqual(trap.boxTo, { x: 3, y: 1 });
  assert.equal(trap.deadlock, true);
  assert.equal(trap.corner, false); // 不是墙角，是目标点分配不上
  // B 箱向上推不互斥：A 箱还能去 G2(6,6)
  const safe = pushes.find(o => o.id === 'push-B-U')!;
  assert.equal(safe.deadlock, false);
});

test('reachablePushes: 候选含走位步数与动作串，可直接 applyPush 到终局', () => {
  const s = parse(ROWS);
  const push = reachablePushes(s).find(o => o.id === 'push-A-U')!;
  assert.equal(push.walkSteps, 0);
  assert.equal(push.actions, 'U');
  assert.equal(push.onGoal, true);
  const next = applyPush(s, push);
  assert.ok(won(next));
  // 需要走位的候选：actions = 走位路径 + 推
  const left = reachablePushes(s).find(o => o.id === 'push-A-L')!;
  assert.equal(left.walkSteps + 1, left.actions.length);
  const after = applyPush(s, left);
  assert.ok(after.boxes.includes(3 * 8 + 1));
});
