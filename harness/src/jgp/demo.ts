import { createSessionService } from '../arena/sessions.js';
import { createDefaultRegistry } from '../games/index.js';
import { createDefaultRuntimeRegistry } from '../games/runtimes.js';
import { createConfiguredBackend, defaultBackendName, loadEnvironment } from '../config.js';
import { renderAscii } from './sim.js';
import type { WorldState } from './protocol.js';

loadEnvironment();
const seconds = Number(process.env.DEMO_SECONDS ?? 8);
if (!Number.isFinite(seconds) || seconds <= 0) throw new Error('DEMO_SECONDS must be positive');
const backend = process.env.JEV_BACKEND ?? defaultBackendName();
const sessions = createSessionService({ registry: createDefaultRegistry(), runtimes: createDefaultRuntimeRegistry(), backend: createConfiguredBackend('mock'),
  backends: { names: ['mock', 'jev', 'deepseek', 'openrouter'], defaultName: backend, create: name => createConfiguredBackend(name) } });
const { matchId } = sessions.start('jgp-demo', { backend, runtime: { durationMs: Math.max(1, Math.round(seconds * 1000)) } });
const stop = () => sessions.stop(matchId);
process.on('SIGINT', stop);
const display = setInterval(() => {
  const world = sessions.state(matchId).latest?.observation as WorldState | null;
  if (world) process.stdout.write('\x1b[2J\x1b[H' + renderAscii(world) + '\n');
}, 500);
try {
  const result = await sessions.wait(matchId);
  console.log(`demo ended: ${result.outcome}; logs/${matchId}.jsonl`);
  if (result.outcome === 'error') process.exitCode = 1;
} finally { clearInterval(display); process.removeListener('SIGINT', stop); await sessions.close(); }
