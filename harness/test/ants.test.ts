import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createState, command, moveTo, transform, step, validPose, LEVELS, ROUTES, algorithmActions } from '../src/games/ants/engine.js';

test('click targets persist, stop at arrival, and are replaced or cancelled per ant', () => {
  const s = createState(1);
  const p = transform(LEVELS[0]!.grips[0]!, s.pose);
  moveTo(s, 0, { x: p.x + 160, y: p.y });
  for (let i = 0; i < 150; i++) step(s);
  assert.ok(s.ants[0]!.target, 'target does not expire at four seconds');
  assert.equal(s.ants[1]!.target, undefined);
  const arrived = transform(LEVELS[0]!.grips[0]!, s.pose);
  moveTo(s, 0, arrived); step(s);
  assert.equal(s.ants[0]!.target, undefined);
  assert.deepEqual(s.ants[0]!.force, { x: 0, y: 0 });
  moveTo(s, 0, { x: 200, y: 200 }); command(s, 0, 'stop');
  assert.equal(s.ants[0]!.target, undefined);
  assert.throws(() => moveTo(s, 0, { x: NaN, y: 100 }));
  assert.throws(() => moveTo(s, 0, { x: 1000, y: 100 }));
  const team = createState(1);
  LEVELS[0]!.grips.forEach((g, i) => { const q = transform(g, team.pose); moveTo(team, i, { x: q.x + 80, y: q.y }); });
  for (let i = 0; i < 300; i++) step(team);
  assert.ok(team.pose.x > 270 && team.pose.x < 285);
  assert.ok(team.ants.every(a => !a.target));
});
import { createServer } from 'node:http';
import { createAntHandler } from '../src/games/ants/server.js';

test('one slow ant does not block other ants from asking again', async () => {
  const counts = Array(6).fill(0); let instance = 0;
  const handler = createAntHandler({ names: ['jev'], defaultName: 'jev', create() {
    const ant = instance++;
    return { async ask() { return {}; }, async request() {
      counts[ant]++;
      if (ant === 5) await new Promise(() => {});
      return { answers: { force: { type: 'choice' as const, choice: 'stop', probabilities: { stop: 1 }, confidence: 1 } } };
    } };
  } });
  const server = createServer((req, res) => { void handler.handle(req, res, new URL(req.url!, 'http://localhost')); });
  await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
  try {
    await fetch(`http://127.0.0.1:${(server.address() as { port: number }).port}/api/ants/start`, { method: 'POST', body: JSON.stringify({ mode: 'jev', level: 1 }) });
    for (let i = 0; i < 100 && counts[0] < 2; i++) await new Promise(r => setTimeout(r, 20));
    assert.ok(counts[0] >= 2); assert.equal(counts[5], 1);
  } finally { handler.close(); await new Promise<void>(r => server.close(() => r())); }
});

test('ant API uses six independent model instances, records usage and rejects human overrides', async () => {
  let instances = 0; const observed: number[] = [];
  const handler = createAntHandler({ names: ['jev'], defaultName: 'jev', create() {
    instances++;
    return { async ask() { return {}; }, async request(state: unknown) {
      observed.push((state as { ant: number }).ant);
      return { answers: { force: { type: 'choice' as const, choice: 'east', probabilities: { east: 1 }, confidence: 1 } }, usage: { totalTokens: 10 } };
    } };
  } });
  const server = createServer((req, res) => { void handler.handle(req, res, new URL(req.url!, 'http://localhost')); });
  await new Promise<void>(r => server.listen(0, '127.0.0.1', r));
  const port = (server.address() as { port: number }).port, base = `http://127.0.0.1:${port}/api/ants/`;
  const post = (path: string, body: unknown) => fetch(base + path, { method: 'POST', body: JSON.stringify(body) });
  try {
    assert.equal((await post('start', { level: 4 })).status, 400);
    const { id } = await (await post('start', { level: 1, mode: 'jev' })).json() as { id: string };
    for (let i = 0; i < 50 && observed.length < 6; i++) await new Promise(r => setTimeout(r, 10));
    assert.equal(instances, 6); assert.deepEqual(observed.sort(), [1, 2, 3, 4, 5, 6]);
    assert.equal((await post(id + '/input', { ant: 0, action: 'west' })).status, 400);
    const history = await (await fetch(base + id + '/history')).json() as { tokens: number; records: unknown[] };
    assert.equal(history.tokens, 60); assert.equal(history.records.length, 6);
    const stopped = await (await post(id + '/stop', {})).json() as { state: { done: boolean; ants: { action: string }[] } };
    assert.equal(stopped.state.done, true); assert.ok(stopped.state.ants.every(a => a.action === 'stop'));
  } finally { handler.close(); await new Promise<void>(r => server.close(() => r())); }
});

test('ant forces combine, expire, and opposing endpoint forces rotate the load', () => {
  const s = createState(1); s.pose.angle = 0;
  command(s, 0, 'north'); command(s, 3, 'south');
  step(s);
  assert.ok(s.pose.angle > 0); assert.equal(s.pose.x, 200); assert.equal(s.pose.y, 280);
  for (let i = 0; i < 130; i++) step(s);
  assert.ok(s.ants.every(a => a.action === 'stop'));
  assert.throws(() => command(s, 6, 'north'));
  assert.throws(() => command(s, 0, 'teleport'));
});

test('walls block oversized loads and all six forces cannot tunnel through walls', () => {
  const s = createState(2);
  for (let i = 0; i < 300; i++) { s.ants.forEach((_, n) => command(s, n, 'east')); step(s); assert.ok(validPose(LEVELS[1]!, s.pose)); }
  assert.ok(s.pose.x < 510); assert.ok(s.blocked > 0); assert.equal(s.won, false);
});

for (let level = 1; level <= 3; level++) test(`level ${level} is solvable with actual six-ant forces`, () => {
  const s = createState(level), route = ROUTES[level - 1]!; let index = 0;
  assert.ok(validPose(LEVELS[level - 1]!, s.pose));
  for (let frame = 0; frame < 5401 && !s.done; frame++) {
    const target = route[index]!;
    if (Math.hypot(target.x - s.pose.x, target.y - s.pose.y) < 5 && Math.abs(Math.atan2(Math.sin(target.angle - s.pose.angle), Math.cos(target.angle - s.pose.angle))) < .15 && index < route.length - 1) index++;
    algorithmActions(s, route[index]!).forEach((a, i) => command(s, i, a, 1)); step(s);
    assert.ok(validPose(LEVELS[level - 1]!, s.pose));
  }
  assert.ok(s.won, JSON.stringify({ level, pose: s.pose, time: s.time, index }));
});
