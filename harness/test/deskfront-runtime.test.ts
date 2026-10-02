import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { createSessionService } from '../src/arena/sessions.js';
import { createDefaultRegistry } from '../src/games/index.js';
import { createDefaultRuntimeRegistry } from '../src/games/runtimes.js';
import { createMockSystemOne } from '../src/systemone/mock.js';
import type { SystemOne } from '../src/systemone/types.js';
import { createDeskfrontRuntime } from '../src/deskfront/runtime.js';
import { deskfrontPage } from '../src/deskfront/page.js';

const configuredRoot = process.env.DESKFRONT_ROOT;
const deskfrontRoot = configuredRoot
  ? resolve(configuredRoot)
  : [resolve('..'), resolve('../deskfront-jevlab')]
    .find(candidate => existsSync(resolve(candidate, 'project.godot')))
  ?? resolve('../deskfront-jevlab');

test('Deskfront current catalog exposes one infinite product with tank enabled by default', () => {
  const manifest = createDeskfrontRuntime({ root: deskfrontRoot, python: 'python', godot: 'godot' });
  assert.deepEqual(manifest.variants?.map(variant => variant.id), ['infinite', 'infinite-headless']);
  assert.equal(manifest.options?.secondStageTankRule?.default, true);
  assert.equal(manifest.options?.secondStageTankShowcase?.default, false);
  assert.match(deskfrontPage(), /id="tank-rule" type="checkbox" checked/);
  assert.match(deskfrontPage(), /secondStageTankRule:\$\('tank-rule'\)\.checked/);
  assert.match(manifest.description ?? '', /无尽推进/);
});

test('Deskfront: live Godot state and engine acknowledgement through the shared local backend', {
  skip: process.env.DESKFRONT_LIVE_TEST !== '1', timeout: 60000,
}, async () => {
  const logDir = mkdtempSync(join(tmpdir(), 'quickplay-deskfront-'));
  const mock = createMockSystemOne();
  const backend: SystemOne = { async ask(state, questions) {
    const answers = await mock.ask(state, questions);
    const tactic = questions.tactic;
    if (tactic?.type === 'choice' && tactic.criteria.capture_flag) answers.tactic = { type: 'choice', choice: 'capture_flag', confidence: 1,
      probabilities: Object.fromEntries(Object.keys(tactic.criteria).map(key => [key, key === 'capture_flag' ? 1 : 0])) };
    return answers;
  } };
  const sessions = createSessionService({ registry: createDefaultRegistry(), runtimes: createDefaultRuntimeRegistry(), backend,
    backends: { names: ['mock'], defaultName: 'mock', create: () => backend }, logDir });
  let id: string | undefined;
  try {
    id = sessions.start('deskfront', { backend: 'mock', variant: 'headless', runtime: { maxRequests: 9, durationMs: 30000 } }).matchId;
    let accepted = false;
    for (let i = 0; i < 110; i++) {
      await new Promise(r => setTimeout(r, 250));
      const state = sessions.state(id);
      assert.notEqual(state.outcome, 'error', state.error);
      const rows = sessions.history(id).history as { record?: { receipt?: { accepted?: boolean } } }[];
      if (rows.some(r => r.record?.receipt?.accepted === true)) { accepted = true; break; }
      if (state.status === 'done') break;
    }
    const state = sessions.state(id);
    const world = state.latest?.observation as { tick: number; run_id: string; units: unknown[] };
    const owned = (state.payload as { game: { enginePid: number; hostPid: number } }).game;
    assert.ok(world?.tick > 0 && world.run_id && world.units.length > 0, 'Only real Godot snapshots count');
    assert.ok(accepted, 'At least one model-selected command must receive a Godot accepted receipt');
    sessions.stop(id); await sessions.wait(id);
    for (const pid of [owned.enginePid, owned.hostPid]) assert.throws(() => process.kill(pid, 0), 'Owned process must exit on stop');
    const records = readFileSync(join(logDir, `${id}.jsonl`), 'utf8').trim().split('\n').map(line => JSON.parse(line));
    assert.equal(records.at(-1).type, 'outcome');
    assert.equal(records.at(-1).outcome, 'aborted');
  } catch (error) {
    console.error(`Deskfront diagnostic artifacts: ${logDir}`);
    throw error;
  } finally {
    await sessions.close();
    if (id && sessions.state(id).outcome === 'aborted') rmSync(logDir, { recursive: true, force: true });
  }
});
