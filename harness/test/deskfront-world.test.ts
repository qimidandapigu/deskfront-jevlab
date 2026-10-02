import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { createSessionService } from '../src/arena/sessions.js';
import { createDefaultRegistry } from '../src/games/index.js';
import { createDefaultRuntimeRegistry } from '../src/games/runtimes.js';
import { createConfiguredBackend, loadEnvironment, loadModelsConfig } from '../src/config.js';

test('world director: shared roles, player evidence, freshness, budget and completion boundary', () => {
  execFileSync(process.env.PYTHON_BIN ?? 'python', ['-X', 'utf8', 'test/deskfront_opening_execution_checks.py'], { stdio: 'pipe' });
  for (const suite of ['checks', 'design_checks', 'pipeline_checks', 'context_checks']) {
    execFileSync(process.env.PYTHON_BIN ?? 'python', ['-X', 'utf8', `test/deskfront_world_${suite}.py`], { stdio: 'pipe' });
  }
});

test('world generation: shared roles produce real Godot completion receipts', {
  skip: process.env.DESKFRONT_WORLD_TEST !== '1', timeout: 100000,
}, async () => {
  loadEnvironment();
  const model = process.env.DESKFRONT_WORLD_REAL === '1' ? 'jev' : 'mock';
  const config = loadModelsConfig(process.env);
  const logDir = resolve('output', `world-${model}-${Date.now()}`);
  mkdirSync(logDir, { recursive: true });
  const create = (name: string) => createConfiguredBackend(name, process.env, config);
  const sessions = createSessionService({ registry: createDefaultRegistry(), runtimes: createDefaultRuntimeRegistry(),
    backend: create(model), backends: { names: ['jev', 'deepseek', 'mock'], defaultName: model, create }, logDir });
  console.log(`World test artifacts: ${logDir}`);
  try {
    const id = sessions.start('deskfront', { backend: model, variant: 'infinite-headless', gameOptions: { greenController: 'local' },
      runtime: { maxRequests: 8, requestTimeoutMs: 30000, durationMs: 85000 } }).matchId;
    let completed = false;
    let firstRun: string | undefined;
    let firstRight: number | undefined;
    let flankMoved = false;
    const starts = new Map<string, number[]>();
    for (let i = 0; i < 330; i++) {
      await new Promise(r => setTimeout(r, 250));
      const state = sessions.state(id);
      assert.notEqual(state.outcome, 'error', state.error);
      const world = state.latest?.observation as { run_id?: string; bounds?: number[]; shots?: number; units?: { id: string; position: number[]; order_mode: string; last_shot_at: number }[]; world_growth?: { revision: number; completed: { spawned: string[] }[]; unit_roles: Record<string, { role: string }> } } | undefined;
      if (world?.run_id) {
        firstRun ??= world.run_id;
        firstRight ??= world.bounds?.[2];
        assert.equal(world.run_id, firstRun, 'Generation must preserve the battle, not reload it');
      }
      const rows = sessions.history(id).history as { record?: { type?: string; status?: string; receipt?: { accepted?: boolean } } }[];
      for (const u of world?.units ?? []) {
        const role = world?.world_growth?.unit_roles?.[u.id]?.role;
        if (role !== '侧翼突击') continue;
        if (!starts.has(u.id)) starts.set(u.id, u.position);
        const p = starts.get(u.id)!;
        if (Math.hypot(u.position[0]!-p[0]!, u.position[1]!-p[1]!) > .35) flankMoved = true;
      }
      const supportFired = world?.units?.some(u => world.world_growth?.unit_roles?.[u.id]?.role === '正面掩护' && u.last_shot_at >= 0);
      const prepared = world?.world_growth?.completed?.some(r => r.spawned.length === 3);
      if (prepared && flankMoved && supportFired && (world?.shots ?? 0) > 0 && rows.some(r => r.record?.type === 'world-receipt' && r.record.status === 'completed' && r.record.receipt?.accepted)) {
        assert.ok(world!.bounds![2]! > firstRight!);
        completed = true;
        break;
      }
      if (state.status === 'done') break;
    }
    const state = sessions.state(id);
    const history = sessions.history(id).history as { type?: string; role?: string; response?: { resolvedModel?: string } }[];
    writeFileSync(resolve(logDir, 'report.json'), JSON.stringify({ completed, state, decisions: history.filter(r => r.type === 'decision') }, null, 2));
    assert.ok(completed, 'Require complete three-defender scene, actual flanking movement and actual shots; see report.json');
    const roles = new Set(history.filter(r => r.type === 'decision').map(r => r.role));
    assert.ok(roles.has('experience_analyst') && roles.has('executor'), 'World analysis and generation routes must execute');
    sessions.stop(id); await sessions.wait(id);
    const owned = (state.payload as { game: { enginePid: number; hostPid: number } }).game;
    for (const pid of [owned.enginePid, owned.hostPid]) assert.throws(() => process.kill(pid, 0), 'Owned processes exit after stop');
  } finally { await sessions.close(); }
});
