import { createRequestManager, responseBackend } from '../systemone/request.js';
import { createHash } from 'node:crypto';
import type { GamePlugin, RealtimeGame, TurnBasedGame } from './plugin.js';
import type { SystemOne, TokenUsage } from '../systemone/types.js';
import { runTurnGame, type TurnRecord } from './runner.js';
import { runRealtimeGame, type RealtimeRecord } from './realtime.js';
import type { FeedbackRecord } from './decision.js';
import { prepareGame } from './session-config.js';

export interface BenchmarkOptions {
  plugins: GamePlugin[];
  backends: string[];
  createBackend(name: string): SystemOne;
  seeds?: number[]; repeats?: number; variant?: string;
  maxTurns?: number; maxTicks?: number; maxRequests?: number; requestTimeoutMs?: number;
  /** Accelerated scheduling is only valid for synchronous offline baselines. */
  offline?: (backend: string) => boolean;
  prices?: Record<string, { inputPerMillion: number; outputPerMillion: number }>;
  onRecord?: (runId: string, record: TurnRecord | RealtimeRecord | FeedbackRecord) => void;
}
export interface BenchmarkRun {
  id: string; game: string; variant: string | null; backend: string; seed: number; repetition: number;
  timing: 'offline-accelerated' | 'realtime'; outcome: string; success: boolean;
  wallMs: number; gameMs: number | null; turns: number | null; requests: number;
  applied: number; invalid: number; discarded: number; errors: number;
  noProgress: number; feedbackCount: number; meanLatencyMs: number | null; p95LatencyMs: number | null;
  usage: TokenUsage; usageComplete: boolean; pendingAtEnd: number; estimatedCostUsd: number | null;
  provenance?: { initialStateSha256: string; controller: string; requestedModels: string[]; resolvedModels: string[] };
  error?: string;
}

export async function runBenchmark(options: BenchmarkOptions): Promise<BenchmarkRun[]> {
  const runs: BenchmarkRun[] = [];
  const maxRequests = options.maxRequests ?? 40;
  if (!Number.isInteger(maxRequests) || maxRequests < 1) throw new Error('maxRequests must be a positive integer');
  for (const plugin of options.plugins) for (const seed of options.seeds ?? [42])
    for (let repetition = 1; repetition <= (options.repeats ?? 1); repetition++) for (const name of options.backends) {
      const variant = options.variant ?? plugin.variants?.[0]?.id;
      if (variant && plugin.variants && !plugin.variants.some(v => v.id === variant)) throw new Error(`Unknown ${plugin.id} variant: ${variant}`);
      const id = `${plugin.id}-${variant ?? 'default'}-${name}-${seed}-${repetition}`;
      const started = Date.now();
      let model: SystemOne;
      const latencies: number[] = [];
      const offline = options.offline?.(name) ?? name === 'mock';
      const run: BenchmarkRun = { id, game: plugin.id, variant: variant ?? null, backend: name, seed, repetition,
        timing: offline ? 'offline-accelerated' : 'realtime', outcome: 'error', success: false,
        wallMs: 0, gameMs: null, turns: null, requests: 0, applied: 0, invalid: 0, discarded: 0, errors: 0,
        noProgress: 0, feedbackCount: 0, meanLatencyMs: null, p95LatencyMs: null,
        usage: { promptTokens: 0, completionTokens: 0, totalTokens: 0 }, usageComplete: true, pendingAtEnd: 0, estimatedCostUsd: null };
      let closed = false, pending = 0;
      const feedback = (record: FeedbackRecord) => {
        run.feedbackCount++;
        if (record.feedback.status === 'unchanged' && record.feedback.moved === false) run.noProgress++;
        options.onRecord?.(id, record);
      };
      const record = (r: TurnRecord | RealtimeRecord) => {
        const e = r.execution;
        if (e?.status === 'applied') run.applied++;
        if (e?.status === 'rejected') run.invalid++;
        if (e?.status === 'discarded') run.discarded++;
        if (e?.status === 'error') run.errors++;
        if (e?.feedback) {
          run.feedbackCount++;
          if (e.feedback.status === 'unchanged' && e.feedback.moved === false) run.noProgress++;
        }
        options.onRecord?.(id, r);
      };
      try {
        model = options.createBackend(name);
        const manager = createRequestManager(model, { maxRequests, timeoutMs: options.requestTimeoutMs ?? 10_000 });
        const requestedModels = new Set<string>(), resolvedModels = new Set<string>();
        const bounded = responseBackend(async (state, questions, requestOptions) => {
          pending++;
          const at = Date.now();
          try {
            const pendingResponse = manager.request(state, questions, requestOptions);
            run.requests = manager.count;
            const response = await pendingResponse;
            if (!closed) {
              if (response.requestedModel) requestedModels.add(response.requestedModel);
              if (response.resolvedModel) resolvedModels.add(response.resolvedModel);
              if (!offline && (response.usageComplete === false || response.usage?.promptTokens === undefined || response.usage.completionTokens === undefined)) run.usageComplete = false;
              for (const key of ['promptTokens', 'completionTokens', 'totalTokens'] as const) run.usage[key]! += response.usage?.[key] ?? 0;
            }
            return response;
          } catch (error) {
            if (!closed) run.usageComplete = offline;
            throw error;
          } finally {
            if (!closed) run.requests = manager.count;
            pending--;
            if (!closed) latencies.push(Date.now() - at);
          }
        });
        const prepared = prepareGame(plugin, { variant, seed, backend: name, runtime: {
          maxRequests, requestTimeoutMs: (options.requestTimeoutMs ?? 10_000) + 100,
          ...(plugin.mode === 'turn' ? { maxTurns: Math.min(options.maxTurns ?? 60, maxRequests) } : { maxTicks: options.maxTicks ?? 300 }),
        } });
        const game = prepared.game;
        const initial = game.initialState();
        const initialObservation = game.observe(initial, { turn: 0, recent: [], feedback: null });
        run.provenance = { initialStateSha256: createHash('sha256').update(JSON.stringify(initial)).digest('hex'),
          controller: (initialObservation as { controller?: string }).controller ?? 'game-adapter', requestedModels: [], resolvedModels: [] };
        if (plugin.mode === 'turn') {
          const result = await runTurnGame(game as TurnBasedGame<unknown>, bounded, { ...prepared.runnerOptions, onUpdate: record });
          run.outcome = result.outcome; run.turns = result.turns;
          if (run.outcome === 'turn-limit' && run.requests >= maxRequests) run.outcome = 'request-budget';
        } else {
          const realtime = game as RealtimeGame<unknown>;
          const result = await runRealtimeGame(realtime, bounded, { ...prepared.runnerOptions,
            ...(offline ? { tickSleepMs: 0 } : {}), onUpdate: record, onFeedback: feedback, onDiscard: record,
            shouldAbort: () => run.requests >= maxRequests && pending === 0 });
          run.outcome = result.outcome; run.gameMs = result.ticks * realtime.tickMs;
        }
        run.provenance.requestedModels = [...requestedModels]; run.provenance.resolvedModels = [...resolvedModels];
        if (run.outcome === 'aborted' && run.requests >= maxRequests) run.outcome = 'request-budget';
      } catch (error) {
        run.outcome = 'error'; if (run.errors === 0) run.errors++; run.usageComplete = offline;
        run.error = (error instanceof Error ? error.message : String(error)).replace(/Bearer\s+\S+/gi, 'Bearer [redacted]').replace(/\bsk-[\w-]+/g, '[redacted]').slice(0, 500);
      }
      closed = true; run.pendingAtEnd = pending;
      if (pending > 0 && !offline) run.usageComplete = false;
      run.wallMs = Date.now() - started; run.success = run.outcome === 'won';
      latencies.sort((a, b) => a - b);
      if (latencies.length) { run.meanLatencyMs = latencies.reduce((a, b) => a + b, 0) / latencies.length; run.p95LatencyMs = latencies[Math.ceil(latencies.length * .95) - 1]!; }
      const price = options.prices?.[name];
      run.estimatedCostUsd = offline ? 0 : price && run.usageComplete
        ? (run.usage.promptTokens! * price.inputPerMillion + run.usage.completionTokens! * price.outputPerMillion) / 1_000_000 : null;
      runs.push(run);
    }
  return runs;
}

export function summarizeBenchmark(runs: BenchmarkRun[]) {
  const groups = new Map<string, BenchmarkRun[]>();
  for (const run of runs) {
    const key = `${run.game}/${run.variant ?? 'default'}/${run.backend}`;
    groups.set(key, [...(groups.get(key) ?? []), run]);
  }
  return [...groups].map(([scenario, rows]) => ({ scenario, runs: rows.length,
    successRate: rows.filter(r => r.success).length / rows.length,
    invalidActions: rows.reduce((n, r) => n + r.invalid, 0), discardedReplies: rows.reduce((n, r) => n + r.discarded, 0),
    meanRequests: rows.reduce((n, r) => n + r.requests, 0) / rows.length,
    meanCostUsd: rows.every(r => r.estimatedCostUsd !== null) ? rows.reduce((n, r) => n + r.estimatedCostUsd!, 0) / rows.length : null,
  }));
}
