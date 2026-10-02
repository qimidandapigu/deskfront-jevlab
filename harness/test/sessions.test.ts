import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createSessionService } from '../src/arena/sessions.js';
import { createDefaultRegistry } from '../src/games/index.js';
import { createDefaultRuntimeRegistry } from '../src/games/runtimes.js';
import { createMockSystemOne } from '../src/systemone/mock.js';
import { createJgpRuntime } from '../src/jgp/runtime.js';
import { startViewer } from '../src/viewer/server.js';
import { Script } from 'node:vm';

function fixture() {
  const logDir = mkdtempSync(join(tmpdir(), 'quickplay-session-'));
  const runtimes = createDefaultRuntimeRegistry();
  const sessions = createSessionService({ registry: createDefaultRegistry(), runtimes, backend: createMockSystemOne(),
    backends: { names: ['mock'], defaultName: 'mock', create: () => createMockSystemOne() },
    logDir, startDelayMs: 0, turnDelayMs: 0, tickSleepMs: 0 });
  return { sessions, runtimes, logDir, async close() { await sessions.close(); rmSync(logDir, { recursive: true, force: true }); } };
}

test('shared service runs every built-in game and captures its exact launch settings', async () => {
  const f = fixture();
  try {
    for (const game of ['sokoban', 'boxing', 'jump', 'soldiers']) {
      const config = { backend: 'mock', runtime: game === 'sokoban' ? { maxTurns: 2 } : { maxTicks: 3 } };
      const id = f.sessions.start(game, config).matchId;
      config.runtime.maxTicks = 999;
      const state = await f.sessions.wait(id);
      assert.equal(state.status, 'done'); assert.notEqual(state.outcome, 'error');
      assert.equal(state.config?.runtime?.maxTicks, game === 'sokoban' ? undefined : 3);
      const records = readFileSync(join(f.logDir, `${id}.jsonl`), 'utf8').trim().split('\n').map(s => JSON.parse(s));
      assert.equal(records.at(-1).type, 'outcome');
      assert.equal(records.filter(r => r.type === 'outcome').length, 1);
    }
  } finally { await f.close(); }
});

test('bad config and unsupported controller combinations are rejected before starting', async () => {
  const f = fixture();
  try {
    for (const config of [null, [], { variant: 'missing' }, { backend: 'missing' }, { runtime: { maxTicks: -1 } }, { runtime: { typo: 2 } }, { rival: 'mock' }]) {
      assert.throws(() => f.sessions.start('sokoban', config as never));
    }
    assert.throws(() => f.sessions.start('boxing', { variant: 'practice-heavy', rival: 'mock' }));
    assert.throws(() => f.sessions.start('jgp-demo', { mode: 'human' }));
    assert.throws(() => f.sessions.start('jgp-demo', { seed: 42 }));
    assert.equal(f.sessions.matches.size, 0);
  } finally { await f.close(); }
});

test('endless uses the common session ID, input, history and idempotent stop', async () => {
  const f = fixture();
  try {
    const id = f.sessions.start('soldiers-endless', { mode: 'human', variant: 'random', seed: 73 }).matchId;
    f.sessions.input(id, { command: 'north', paused: true });
    const state = f.sessions.state(id);
    const payload = state.payload as { id: string; seed: number; paused: boolean };
    assert.equal(payload.id, id); assert.equal(payload.seed, 73); assert.equal(payload.paused, true);
    assert.deepEqual(f.sessions.history(id).history, []);
    f.sessions.stop(id); f.sessions.stop(id);
    assert.equal((await f.sessions.wait(id)).outcome, 'aborted');
    assert.throws(() => f.sessions.input(id, { command: 'north' }));
    const lines = readFileSync(join(f.logDir, `${id}.jsonl`), 'utf8').trim().split('\n');
    assert.equal(lines.length, 1);
  } finally { await f.close(); }
});

test('JGP demo obeys the session tick limit and retains pending execution audit', async () => {
  const f = fixture();
  try {
    const id = f.sessions.start('jgp-demo', { backend: 'mock', runtime: { maxTicks: 2 } }).matchId;
    const state = await f.sessions.wait(id);
    assert.equal(state.outcome, 'tick-limit');
    const records = f.sessions.history(id).history as { execution?: { status: string } }[];
    assert.ok(records.length);
    assert.ok(records.every(r => r.execution?.status !== 'applied'));
    const before = readFileSync(join(f.logDir, `${id}.jsonl`), 'utf8');
    f.sessions.stop(id);
    await new Promise(r => setTimeout(r, 80));
    assert.equal(readFileSync(join(f.logDir, `${id}.jsonl`), 'utf8'), before);
  } finally { await f.close(); }
});

test('endless snapshots the selected backend at creation and cancels pending generation on stop', async () => {
  const logDir = mkdtempSync(join(tmpdir(), 'quickplay-endless-'));
  let selected = '', calls = 0;
  const sessions = createSessionService({ registry: createDefaultRegistry(), runtimes: createDefaultRuntimeRegistry(), backend: createMockSystemOne(), logDir,
    backends: { names: ['custom'], create(name) { selected = name; return { ask: () => { calls++; return new Promise(() => {}); } }; } } });
  const id = sessions.start('soldiers-endless', { mode: 'human', backend: 'custom' }).matchId;
  const input = setInterval(() => sessions.input(id, { command: 'hold' }), 100);
  try {
    assert.equal(selected, 'custom');
    for (let i = 0; i < 100 && !calls; i++) await new Promise(r => setTimeout(r, 50));
    assert.equal(calls, 1);
    clearInterval(input); sessions.stop(id);
    const before = readFileSync(join(logDir, `${id}.jsonl`), 'utf8');
    await new Promise(r => setTimeout(r, 60));
    assert.equal(readFileSync(join(logDir, `${id}.jsonl`), 'utf8'), before);
    assert.equal((await sessions.wait(id)).outcome, 'aborted');
  } finally { clearInterval(input); await sessions.close(); rmSync(logDir, { recursive: true, force: true }); }
});

test('JGP handshake timeout disposes the adapter and closes the session', async () => {
  const f = fixture(); let disposed = 0;
  f.runtimes.register(createJgpRuntime({ id: 'hung', name: 'Hung', adapter: () => ({
    ready: () => new Promise<void>(() => {}), capabilities() { throw new Error('Not ready'); },
    getState: async () => { throw new Error('Not ready'); }, execute() {}, dispose() { disposed++; },
  }) }));
  try {
    const id = f.sessions.start('hung', { runtime: { requestTimeoutMs: 20 } }).matchId;
    const result = await f.sessions.wait(id);
    assert.equal(result.outcome, 'error'); assert.match(result.error!, /handshake timed out/);
    assert.equal(disposed, 1);
  } finally { await f.close(); }
});

test('external child process handshake, exit and cleanup run through the common service', async () => {
  const f = fixture();
  const script = `const r=require('node:readline').createInterface({input:process.stdin});
    const send=x=>process.stdout.write(JSON.stringify(x)+'\\n');
    r.on('line',line=>{const m=JSON.parse(line);if(m.type==='hello_ack')send({type:'state',state:{protocolVersion:'v1',tick:1,timeMs:50,bounds:{w:10,h:10},entities:[],events:[]}});if(m.type==='actions')process.exit(0);});
    send({type:'hello',capabilities:{protocolVersion:'v1',game:'stub',tickRateHz:20,maxActionsPerTick:64,features:[]}});`;
  f.runtimes.register(createJgpRuntime({ id: 'child', name: 'Child', command: [process.execPath, '-e', script] }));
  try {
    const id = f.sessions.start('child', { runtime: { durationMs: 3000 } }).matchId;
    const state = await f.sessions.wait(id);
    assert.equal(state.outcome, 'finished');
    assert.equal((state.latest?.observation as { tick: number }).tick, 1);
  } finally { await f.close(); }
});

test('web catalog and common session endpoints include endless and JGP; invalid JSON cannot start a game', async () => {
  const logDir = mkdtempSync(join(tmpdir(), 'quickplay-catalog-'));
  const viewer = await startViewer({ backend: createMockSystemOne(), registry: createDefaultRegistry(), runtimes: createDefaultRuntimeRegistry({ DESKFRONT_ROOT: join(logDir, 'missing') }), port: 0, logDir, startDelayMs: 0 });
  const base = `http://127.0.0.1:${viewer.port}`;
  try {
    const catalog = await (await fetch(base + '/api/games')).json() as { id: string }[];
    assert.deepEqual(catalog.map(g => g.id).sort(), ['boxing', 'jgp-demo', 'jump', 'sokoban', 'soldiers', 'soldiers-endless']);
    const bad = await fetch(base + '/api/match/sokoban', { method: 'POST', body: '{' });
    assert.equal(bad.status, 400);
    const opened = await fetch(base + '/api/match/soldiers-endless', { method: 'POST', body: JSON.stringify({ mode: 'human', variant: 'random' }) });
    assert.equal(opened.status, 200);
    const { matchId } = await opened.json() as { matchId: string };
    assert.equal((await fetch(base + `/api/match/${matchId}/stop`, { method: 'POST' })).status, 200);
    const stopped = await (await fetch(base + `/api/match/${matchId}/state`)).json() as { status: string };
    assert.equal(stopped.status, 'done');
    const page = await fetch(base + '/runtime/jgp-demo');
    assert.equal(page.status, 200);
    const html = await page.text();
    for (const script of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new Script(script[1]!);
  } finally { await viewer.close(); rmSync(logDir, { recursive: true, force: true }); }
});
