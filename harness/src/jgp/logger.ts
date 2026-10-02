import { appendFileSync } from "node:fs";
import type { Action } from "./protocol.js";
import type { JevAnswers, JevUsage } from "./jev-types.js";

/** One JSONL record per entity decision (or skip). */
export interface DecisionRecord {
  execution?: ReturnType<typeof executionAudit>;
  tick: number;
  timeMs: number;
  entity: string;
  state: unknown;
  jev: { answers: JevAnswers; model: string; latencyMs: number; usage?: JevUsage } | null;
  action: Action | null;
  fallback: boolean;
  fallbackReason?: "low_confidence" | "jev_error" | "held" | "throttled" | "reused" | "abstained" | "capped" | "invalid" | "over_limit";
  /** 高风险低置信但无 safeAction：打标不拦（action 照常执行，fallback 保持 false）。 */
  blocked?: boolean;
  latencyMs: number;
}

/** JGP emits commands to an external engine; delivery is not execution evidence. */
export function executionAudit(rec: DecisionRecord) {
  return { schema: 'quickplay-execution-v1', id: `jgp:${rec.tick}:${rec.entity}`, side: 'self', clock: 'engine-tick',
    requestedAt: rec.tick, resolvedAt: null,
    status: rec.action ? 'pending' : rec.fallbackReason === 'jev_error' ? 'error' : 'skipped',
    rawAnswers: rec.jev?.answers ?? {}, executedAnswers: null, action: null,
    proposedAction: rec.action, reason: rec.fallbackReason ?? (rec.action ? 'awaiting-engine-receipt' : null), feedback: null };
}

export interface DecisionLogger {
  log(rec: DecisionRecord): void;
  path(): string | null;
  dispose(): void;
}

export function createDecisionLogger(deps: { filePath?: string; alsoStdout?: boolean } = {}): DecisionLogger {
  const filePath = deps.filePath ?? null;
  return {
    log(rec) {
      const line = JSON.stringify({ ...rec, execution: executionAudit(rec) }) + "\n";
      if (filePath) appendFileSync(filePath, line, "utf8");
      if (deps.alsoStdout) process.stdout.write(line);
    },
    path: () => filePath,
    dispose() {},
  };
}

/** In-memory logger for tests. */
export function createMemoryLogger(): DecisionLogger & { records: DecisionRecord[] } {
  const records: DecisionRecord[] = [];
  return {
    records,
    log(rec) {
      records.push({ ...rec, execution: executionAudit(rec) });
    },
    path: () => null,
    dispose() {
      records.length = 0;
    },
  };
}
