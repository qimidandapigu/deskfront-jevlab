/** Two real JEV paths, mirrored sides, same engine and bounded per-side budget. */
import { readFileSync, mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { createSessionService } from '../arena/sessions.js';
import { createDefaultRegistry } from '../games/index.js';
import { createDefaultRuntimeRegistry } from '../games/runtimes.js';
import { loadEnvironment, loadModelsConfig, createConfiguredBackend } from '../config.js';

loadEnvironment();
const root = process.env.DESKFRONT_ROOT
  ? resolve(process.env.DESKFRONT_ROOT)
  : [resolve('..'), resolve('../deskfront-jevlab')]
    .find(candidate => existsSync(resolve(candidate, 'project.godot')))
  ?? resolve('../deskfront-jevlab');
const nativeEnv = readFileSync(resolve(root, '.env'), 'utf8');
const model = /^TYPESAFE_MODEL=(.+)$/m.exec(nativeEnv)?.[1]?.trim();
if (!model) throw new Error('Native JEV model missing');
const saved = loadModelsConfig(process.env);
if (saved.jev.provider !== 'typesafe' || !saved.jev.apiKey) throw new Error('Harness TypeSafe JEV is not configured');
const config = { ...saved, jev: { ...saved.jev, model } };
const before = execFileSync('git', ['diff', '--', '*.gd', '*.py', '*.json', '*.js', '*.html'], { cwd: root });
const logDir = resolve('output', 'deskfront-jev-comparison-' + new Date().toISOString().replace(/[:.]/g, '-'));
mkdirSync(logDir, { recursive: true });
const backend = createConfiguredBackend('jev', process.env, config);
const sessions = createSessionService({ registry: createDefaultRegistry(), runtimes: createDefaultRuntimeRegistry(), backend,
  backends: { names: ['jev'], defaultName: 'jev', create: () => createConfiguredBackend('jev', process.env, config) }, logDir });
const results: unknown[] = [];
console.log(JSON.stringify({ logDir, model, rounds: 2, requestsPerSide: 100 }));
try {
  for (const modelFaction of ['green', 'red']) {
    const id = sessions.start('deskfront', { variant: 'duel', backend: 'jev',
      gameOptions: { modelFaction, opponent: 'native_jev' },
      runtime: { durationMs: 180000, maxRequests: 100, requestTimeoutMs: 10000 } }).matchId;
    console.log(JSON.stringify({ started: id, harnessFaction: modelFaction }));
    await sessions.wait(id);
    const result = sessions.state(id);
    const world = result.latest?.observation as { winner?: string; time?: number; units?: { faction: string; hp: number; deployment_phase: string }[] };
    const payload = result.payload as { game?: { lm?: unknown; nativeLM?: unknown } };
    const row = { id, harnessFaction: modelFaction, outcome: result.outcome, error: result.error,
      winner: world?.winner, seconds: world?.time,
      winnerController: world?.winner === modelFaction ? 'harness' : world?.winner === 'draw' ? 'draw' : world?.winner ? 'native' : 'unfinished',
      survivors: world?.units?.filter(u => u.hp > 0 && u.deployment_phase === 'active').map(u => ({ faction: u.faction, hp: u.hp })),
      harness: payload.game?.lm, native: payload.game?.nativeLM };
    results.push(row);
    writeFileSync(resolve(logDir, 'report.json'), JSON.stringify({ model, results }, null, 2));
    console.log(JSON.stringify({ ...row, harness: undefined, native: undefined }));
    if (result.outcome === 'error') throw new Error(result.error ?? 'Match failed');
  }
} finally {
  await sessions.close();
  const after = execFileSync('git', ['diff', '--', '*.gd', '*.py', '*.json', '*.js', '*.html'], { cwd: root });
  if (!before.equals(after)) throw new Error('Game source changed during comparison');
}
