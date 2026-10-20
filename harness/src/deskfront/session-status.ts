/** Narrow runtime facts for native presentation; this does not assert control ownership. */
const outcomes = ['time-limit', 'request-budget', 'aborted', 'error', 'game-closed', 'finished', 'won', 'lost'] as const;
export interface DeskfrontSessionStatus {
  schemaVersion: 1;
  sessionId: string;
  status: 'running' | 'done';
  outcome: typeof outcomes[number] | 'unknown' | null;
  requests: number | null;
  requestLimit: number | null;
  durationMs: number | null;
  runId: string | null;
  errorCategory: 'runtime-error' | null;
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}
function count(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
}
function duration(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}
function runId(value: unknown): string | null {
  return typeof value === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$/.test(value) ? value : null;
}

export function deskfrontSessionStatus(sessionId: string, snapshot: unknown): DeskfrontSessionStatus | null {
  const state = record(snapshot);
  if (state.status !== 'running' && state.status !== 'done') return null;
  const payload = record(state.payload), runtime = record(record(state.config).runtime);
  const latest = record(record(state.latest).observation), final = record(state.finalObservation);
  const observation = record(state.observation);
  const outcome = state.status === 'running' ? null
    : outcomes.find(value => value === state.outcome) ?? 'unknown';
  return {
    schemaVersion: 1, sessionId, status: state.status, outcome,
    requests: count(payload.requests), requestLimit: count(runtime.maxRequests),
    durationMs: duration(runtime.durationMs),
    runId: runId(latest.run_id) ?? runId(final.run_id) ?? runId(observation.run_id),
    // Never relay raw exceptions, provider responses or configuration to the game.
    errorCategory: outcome === 'error' ? 'runtime-error' : null,
  };
}
