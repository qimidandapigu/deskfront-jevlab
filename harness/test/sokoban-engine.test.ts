import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parse, move, won, renderRows } from '../src/games/sokoban/engine.js';

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

test('parse: 合法地图解析出玩家/箱子/目标', () => {
  const s = parse(ROWS);
  assert.equal(s.width, 8);
  assert.equal(s.boxes.length, 1);
  assert.equal(s.goals.length, 1);
  assert.ok(s.goals.length >= 1 && s.boxes.length === s.goals.length);
});

test('parse: 边缘不封闭抛错', () => {
  assert.throws(() => parse(['########', '#     @ #', '# .$   #', '#      #', '#      #', '#      #', '#      #', '########']));
});

test('move: 向上推箱到目标即胜利', () => {
  const s = parse(ROWS);
  const r = move(s, 'U'); // @ 从 (4,4) 到 (4,3)？玩家在第 4 行(x=2)：直接向上推箱
  assert.ok(r.moved && r.pushed);
  assert.ok(won(r.state));
});

test('move: 撞墙不动', () => {
  const s = parse(ROWS);
  const r = move(s, 'L');
  assert.ok(r.moved); // (2,4) 左边是空地，可以走
  const r2 = move(r.state, 'L');
  assert.ok(!r2.moved); // 再左是墙
  assert.equal(r2.state, r.state);
});

test('renderRows 往返一致', () => {
  const s = parse(ROWS);
  assert.deepEqual(renderRows(s), ROWS);
});
