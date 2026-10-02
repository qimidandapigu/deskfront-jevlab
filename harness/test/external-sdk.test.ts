import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { tmpdir } from 'node:os';
import { createSessionService } from '../src/arena/sessions.js';
import { createDefaultRegistry } from '../src/games/index.js';
import { createRuntimeRegistry } from '../src/arena/runtime.js';
import { createMockSystemOne } from '../src/systemone/mock.js';
import { createExternalGameRuntime } from '../src/external/runtime.js';
import { loadGameManifest, loadRegisteredGames, registerGameManifest } from '../src/external/manifests.js';
import { GAME_PROTOCOL } from '../src/external/protocol.js';

test('a manifest and Python SDK game join the catalog and run without changing host code', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'quickplay-sdk-'));
  const config = join(dir, 'games.local.json');
  assert.equal(registerGameManifest('examples/counter/game.json', config), 'counter-demo');
  registerGameManifest('examples/counter/game.json', config);
  assert.equal(JSON.parse(readFileSync(config, 'utf8')).manifests.length, 1);
  const runtimes = createRuntimeRegistry(); loadRegisteredGames(runtimes, config);
  const service = createSessionService({ registry: createDefaultRegistry(), runtimes, backend: createMockSystemOne(), logDir: dir });
  try {
    assert.equal(service.catalog().find(g => g.id === 'counter-demo')?.options.target?.default, 4);
    assert.throws(() => service.start('counter-demo', { gameOptions: { target: 1000 } }));
    assert.throws(() => service.start('counter-demo', { gameOptions: { typo: 1 } }));
    const id = service.start('counter-demo', { gameOptions: { target: 3 } }).matchId;
    const state = await service.wait(id);
    assert.equal(state.outcome, 'won', state.error);
    assert.deepEqual(state.latest?.observation, { position: 3, target: 3 });
    const records = service.history(id).history as { type: string; execution?: { status: string }; record?: { execution?: { status: string } } }[];
    assert.equal(records.filter(r => r.type === 'decision').length, 3);
    assert.ok(records.filter(r => r.type === 'decision').every(r => r.execution?.status === 'pending'));
    assert.equal(records.filter(r => r.record?.execution?.status === 'applied').length, 3);
  } finally { await service.close(); rmSync(dir, { recursive: true, force: true }); }
});

test('JavaScript SDK uses the identical protocol and cannot see provider credentials', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'quickplay-js-sdk-'));
  const prior = process.env.OPENAI_API_KEY;
  process.env.OPENAI_API_KEY = 'test-secret-must-not-reach-game';
  const sdk = pathToFileURL(resolve('sdk/javascript/quickplay.mjs')).href;
  const script = `import {Game} from ${JSON.stringify(sdk)}; const game=await Game.connect();
    const r=await game.ask({},{move:{type:'choice',instructions:'Go',criteria:{go:'Go'}}});
    game.publish({choice:r.answers.move.choice,credentialVisible:!!process.env.OPENAI_API_KEY});game.finish('won');`;
  const runtimes = createRuntimeRegistry([createExternalGameRuntime({ protocol: GAME_PROTOCOL, id: 'js-sdk', name: 'JS SDK', description: 'Test',
    command: [process.execPath, '--input-type=module', '-e', script], capabilities: { human: false, ai: true, seed: false } })]);
  const service = createSessionService({ registry: createDefaultRegistry(), runtimes, backend: createMockSystemOne(), logDir: dir });
  try {
    const result = await service.wait(service.start('js-sdk').matchId);
    assert.equal(result.outcome, 'won');
    assert.deepEqual(result.latest?.observation, { choice: 'go', credentialVisible: false });
  } finally {
    if (prior === undefined) delete process.env.OPENAI_API_KEY; else process.env.OPENAI_API_KEY = prior;
    await service.close(); rmSync(dir, { recursive: true, force: true });
  }
});

test('protocol mismatch fails before any model call and closes the owned child', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'quickplay-protocol-'));
  let calls = 0;
  const script = `const r=require('node:readline').createInterface({input:process.stdin});r.on('line',l=>{const m=JSON.parse(l);if(m.type==='start')console.log(JSON.stringify({type:'ready',protocol:'wrong'}));if(m.type==='stop')process.exit(0);});`;
  const runtimes = createRuntimeRegistry([createExternalGameRuntime({ protocol: GAME_PROTOCOL, id: 'bad', name: 'Bad', description: 'Test',
    command: [process.execPath, '-e', script], capabilities: { human: false, ai: true, seed: false } })]);
  const service = createSessionService({ registry: createDefaultRegistry(), runtimes, backend: { ask: async () => { calls++; return {}; } }, logDir: dir });
  try {
    const state = await service.wait(service.start('bad').matchId);
    assert.equal(state.outcome, 'error'); assert.match(state.error!, /handshake mismatch/); assert.equal(calls, 0);
  } finally { await service.close(); rmSync(dir, { recursive: true, force: true }); }
});

test('stop cancels a pending SDK model request and prevents late records', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'quickplay-stop-sdk-'));
  let entered = false;
  const sdk = pathToFileURL(resolve('sdk/javascript/quickplay.mjs')).href;
  const script = `import {Game} from ${JSON.stringify(sdk)};const game=await Game.connect();try{await game.ask({},{x:{type:'choice',instructions:'Go',criteria:{go:'Go'}}});}catch{}`;
  const runtimes = createRuntimeRegistry([createExternalGameRuntime({ protocol: GAME_PROTOCOL, id: 'waiting', name: 'Waiting', description: 'Test',
    command: [process.execPath, '--input-type=module', '-e', script], capabilities: { human: false, ai: true, seed: false } })]);
  const service = createSessionService({ registry: createDefaultRegistry(), runtimes, logDir: dir,
    backend: { ask: () => { entered = true; return new Promise(() => {}); } } });
  try {
    const id = service.start('waiting').matchId;
    for (let i = 0; i < 100 && !entered; i++) await new Promise(r => setTimeout(r, 10));
    assert.ok(entered); service.stop(id);
    assert.equal((await service.wait(id)).outcome, 'aborted');
    const records = readFileSync(join(dir, `${id}.jsonl`), 'utf8').trim().split('\n').map(line => JSON.parse(line));
    assert.equal(records.length, 1); assert.equal(records[0].type, 'outcome');
  } finally { await service.close(); rmSync(dir, { recursive: true, force: true }); }
});

test('manifests reject unsupported protocols and conflicting game IDs', () => {
  const dir = mkdtempSync(join(tmpdir(), 'quickplay-manifest-'));
  try {
    const original = JSON.parse(readFileSync('examples/counter/game.json', 'utf8'));
    const other = join(dir, 'other.json'); writeFileSync(other, JSON.stringify({ ...original, protocol: 'unknown' }));
    assert.throws(() => loadGameManifest(other));
    writeFileSync(other, JSON.stringify(original));
    const config = join(dir, 'games.local.json');
    registerGameManifest('examples/counter/game.json', config);
    assert.throws(() => registerGameManifest(other, config), /Duplicate game id/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
