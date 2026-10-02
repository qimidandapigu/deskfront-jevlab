import { sourceProvenance } from './arena/provenance.js';
import { existsSync, mkdirSync, readdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createDefaultRegistry } from './games/index.js';
import { createConfiguredBackend } from './config.js';
import { createJsonlLogger } from './arena/logger.js';
import { runBenchmark, summarizeBenchmark } from './arena/benchmark.js';

const args = process.argv.slice(2);
const allowed = new Set(['games', 'backends', 'seeds', 'repeats', 'variant', 'max-turns', 'max-ticks', 'max-requests', 'timeout-ms', 'input-usd-per-million', 'output-usd-per-million', 'out']);
const flags: Record<string, string> = {};
for (let i = 0; i < args.length; i += 2) {
  const name = args[i]!.slice(2), value = args[i + 1];
  if (!args[i]!.startsWith('--') || !allowed.has(name) || !value || value.startsWith('--')) throw new Error(`Unknown or missing argument: ${args[i]}`);
  flags[name] = value;
}
function positive(name: string, fallback: number) {
  const n = Number(flags[name] ?? fallback);
  if (!Number.isSafeInteger(n) || n < 1) throw new Error(`--${name} must be a positive integer`);
  return n;
}
const backends = (flags.backends ?? 'mock').split(',');
if (backends.some(b => !['mock', 'jev', 'deepseek', 'openrouter'].includes(b))) throw new Error('Unknown backend');
// Default bench cannot accidentally use a paid backend from .env.
if (backends.some(b => b !== 'mock')) { try { process.loadEnvFile('.env'); } catch (e) { if ((e as NodeJS.ErrnoException).code !== 'ENOENT') throw e; } }
const registry = createDefaultRegistry();
const plugins = flags.games ? flags.games.split(',').map(id => registry.get(id)) : registry.list();
const seeds = (flags.seeds ?? '42').split(',').map(Number);
if (seeds.some(n => !Number.isSafeInteger(n) || n < 0 || n > 0xffffffff)) throw new Error('Seeds must be uint32 integers');
const out = resolve(flags.out ?? `output/bench-${Date.now()}`);
if (existsSync(out) && readdirSync(out).length) throw new Error('Output directory must be empty to avoid mixing runs');
mkdirSync(out, { recursive: true });
const logs = new Map<string, ReturnType<typeof createJsonlLogger>>();
const prices: Record<string, { inputPerMillion: number; outputPerMillion: number }> = {};
if (flags['input-usd-per-million'] !== undefined || flags['output-usd-per-million'] !== undefined) {
  const inputPerMillion = Number(flags['input-usd-per-million']), outputPerMillion = Number(flags['output-usd-per-million']);
  if (![inputPerMillion, outputPerMillion].every(n => Number.isFinite(n) && n >= 0)) throw new Error('Provide both non-negative token prices');
  if (backends.filter(b => b !== 'mock').length !== 1) throw new Error('Token prices require exactly one paid backend');
  prices[backends.find(b => b !== 'mock')!] = { inputPerMillion, outputPerMillion };
}
const options = { plugins, backends, seeds, repeats: positive('repeats', 1), variant: flags.variant,
  maxTurns: positive('max-turns', 60), maxTicks: positive('max-ticks', 300), maxRequests: positive('max-requests', 40), requestTimeoutMs: positive('timeout-ms', 10_000), prices,
  createBackend: (name: string) => createConfiguredBackend(name),
  onRecord: (id: string, record: Parameters<ReturnType<typeof createJsonlLogger>>[0]) => {
    let log = logs.get(id); if (!log) { log = createJsonlLogger(resolve(out, `${id}.jsonl`)); logs.set(id, log); }
    log(record);
  },
};
const runs = await runBenchmark(options);
for (const run of runs) options.onRecord(run.id, { type: 'outcome', game: run.game, outcome: run.outcome, benchmark: run });
const report = { schema: 'quickplay-benchmark-v2', provenance: sourceProvenance(), createdAt: new Date().toISOString(),
  settings: { seeds, repeats: options.repeats, maxTurns: options.maxTurns, maxTicks: options.maxTicks, maxRequests: options.maxRequests, requestTimeoutMs: options.requestTimeoutMs, prices },
  models: Object.fromEntries(backends.map(b => [b, b === 'mock' ? 'local-heuristic' : runs.find(r => r.backend === b && r.provenance?.requestedModels.length)?.provenance?.requestedModels[0] ?? null])),
  notes: ['Only soldiers currently consumes RNG seed; other games use deterministic fixed variants.', 'Jump uses assisted landing routes, not independent model key control.', 'requests counts SystemOne.ask calls, not provider HTTP calls (one ask may fan out).', 'Unknown token prices or incomplete usage produce null cost; failures remain in the denominator.', 'Offline accelerated timing is not comparable to paid realtime matches.'],
  summary: summarizeBenchmark(runs), runs };
writeFileSync(resolve(out, 'report.json'), JSON.stringify(report, null, 2) + '\n');
console.table(report.summary);
console.log(`Report: ${resolve(out, 'report.json')}`);
if (runs.some(r => r.outcome === 'error' || r.outcome === 'void')) process.exitCode = 1;
