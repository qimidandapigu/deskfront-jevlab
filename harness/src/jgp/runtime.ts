import { mkdirSync, appendFileSync } from 'node:fs';
import type { RuntimePlugin } from '../arena/runtime.js';
import type { GameAdapter, WorldState } from './protocol.js';
import { createEngine } from './engine.js';
import { createSystemOneJevClient } from './jev-real.js';
import { createDisabledStrategist } from './strategist.js';
import { executionAudit, type DecisionRecord } from './logger.js';
import { createStdioAdapter } from './stdio.js';
import { createSimAdapter } from './sim.js';
import { DEFAULT_RULES } from './rules.js';

interface ManagedAdapter extends GameAdapter {
  ready?(): Promise<void>;
  exitCode?(): number | null;
  dispose(): void;
}

/** Commands are registered by the host, never accepted from a browser request. */
export function createJgpRuntime(options: { id: string; name: string; command?: string[]; adapter?: () => ManagedAdapter }): RuntimePlugin {
  return {
    id: options.id, name: options.name, description: 'JGP 协议游戏：公共模型配置、会话管理和执行审计。',
    variants: [], capabilities: { human: false, ai: true, benchmark: false, seed: false },
    start(context, config) {
      for (const key of ['maxTurns', 'decisionMs'] as const) if (config.runtime?.[key] !== undefined) throw new Error(`JGP does not support ${key}`);
      const backend = context.createBackend(config.backend);
      const jev = createSystemOneJevClient(backend, { model: config.backend ?? context.backendName,
        requests: { timeoutMs: config.runtime?.requestTimeoutMs ?? 10000 } });
      const adapter = options.adapter?.() ?? createStdioAdapter(options.command!);
      const strategist = createDisabledStrategist();
      mkdirSync(context.logDir, { recursive: true });
      const logPath = `${context.logDir}/${context.id}.jsonl`;
      const records: DecisionRecord[] = [];
      let world: WorldState | null = null, active = true, outcome: string | null = null, error: string | undefined;
      let requests = 0, loop: ReturnType<ReturnType<typeof createEngine>['run']> | undefined;
      let complete!: () => void;
      const completion = new Promise<void>(resolve => { complete = resolve; });
      let startup: NodeJS.Timeout | undefined, duration: NodeJS.Timeout | undefined;
      const engine = createEngine({ adapter, strategist,
        jev: {
          async systemOne(request) {
            if (!active) throw new Error('Session stopped');
            if (requests >= (config.runtime?.maxRequests ?? Infinity)) { finish('request-budget'); throw new Error('Request budget exhausted'); }
            requests++; return jev.systemOne(request);
          },
          dispose: () => jev.dispose(),
        },
        logger: {
          log(record) {
            if (!active) return;
            const audited = { ...record, execution: executionAudit(record) };
            records.push(audited); if (records.length > 2000) records.shift();
            appendFileSync(logPath, JSON.stringify(audited) + '\n');
          }, path: () => logPath, dispose() {},
        },
        config: { actionGate: { highRisk: ['attack'], safeAction: 'hold', allowOther: true }, rules: { ...DEFAULT_RULES, attackRange: 9 } },
      });
      function finish(reason: string, cause?: unknown) {
        if (!active) return;
        active = false; outcome = reason;
        if (cause) error = cause instanceof Error ? cause.message : String(cause);
        if (startup) clearTimeout(startup); if (duration) clearTimeout(duration);
        loop?.stop(); engine.dispose(); jev.dispose(); strategist.dispose(); adapter.dispose();
        appendFileSync(logPath, JSON.stringify({ type: 'outcome', game: options.id, outcome, error, requests, config }) + '\n');
        complete();
      }
      startup = setTimeout(() => finish('error', new Error('JGP handshake timed out')), config.runtime?.requestTimeoutMs ?? 10000);
      void Promise.resolve().then(() => adapter.ready?.()).then(async () => {
        if (!active) return;
        const caps = await adapter.capabilities();
        if (!active) return;
        clearTimeout(startup);
        loop = engine.run({ tickHz: caps.tickRateHz,
          onTick(next) {
            if (!active) return;
            world = structuredClone(next);
            if (config.runtime?.maxTicks && next.tick >= config.runtime.maxTicks) finish('tick-limit');
          },
          onError(cause) { finish(adapter.exitCode?.() === 0 ? 'finished' : 'error', adapter.exitCode?.() === 0 ? undefined : cause); },
        });
      }).catch(cause => finish('error', cause));
      if (config.runtime?.durationMs) duration = setTimeout(() => finish('time-limit'), config.runtime.durationMs);
      return {
        completion, stop: () => finish('aborted'), history: () => structuredClone(records),
        snapshot: () => ({ status: active ? 'running' : 'done', outcome, observation: world, payload: { requests, logPath }, error }),
      };
    },
  };
}

export const jgpDemoRuntime = createJgpRuntime({ id: 'jgp-demo', name: 'JGP 玩具兵演示', adapter: () => createSimAdapter() });
