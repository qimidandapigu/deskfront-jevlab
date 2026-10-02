import type { ModelResponse, Question, SystemOne, TokenUsage } from './types.js';

export interface RequestPolicy { timeoutMs?: number; maxRequests?: number; diagnostics?: boolean }
export function selectQuestions(questions: Record<string, Question>, diagnostics = false) {
  if (diagnostics || !Object.values(questions).some(q => q.purpose === 'display')) return questions;
  return Object.fromEntries(Object.entries(questions).filter(([, q]) => q.purpose !== 'display'));
}

/** Compatibility for callers using ask; production consumers use request's atomic result. */
export function responseBackend(request: NonNullable<SystemOne['request']>): SystemOne {
  let lastUsage: TokenUsage | undefined;
  return { request, get lastUsage() { return lastUsage; }, async ask(state, questions) {
    const result = await request(state, questions); lastUsage = result.usage; return result.answers;
  } };
}

/** Shared request lifetime for matches, benchmarks, generation and external bridges.
 * Cancellation frees the caller immediately even for legacy providers ignoring signals.
 * No implicit manager retry; budgets count logical requests (providers may fan out).
 */
export function createRequestManager(backend: SystemOne, policy: RequestPolicy = {}) {
  const active = new Set<AbortController>();
  let count = 0;
  const timeoutMs = policy.timeoutMs ?? 10_000;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error('invalid-request-timeout');
  if (policy.maxRequests !== undefined && (!Number.isSafeInteger(policy.maxRequests) || policy.maxRequests < 1)) throw new Error('invalid-request-budget');
  return {
    get count() { return count; },
    get pending() { return active.size; },
    cancel(reason = 'request-cancelled') { for (const controller of active) controller.abort(new Error(reason)); },
    async request(state: unknown, questions: Record<string, Question>, options: { signal?: AbortSignal; shouldAbort?: () => boolean } = {}): Promise<ModelResponse> {
      options.signal?.throwIfAborted();
      if (count >= (policy.maxRequests ?? Infinity)) throw new Error('request-budget');
      count++;
      const controller = new AbortController(); active.add(controller);
      const abort = () => controller.abort(options.signal?.reason ?? new Error('request-cancelled'));
      options.signal?.addEventListener('abort', abort, { once: true });
      const timer = setTimeout(() => controller.abort(new Error('request-timeout')), timeoutMs);
      const poll = options.shouldAbort ? setInterval(() => { if (options.shouldAbort?.()) controller.abort(new Error('request-aborted')); }, 25) : undefined;
      let rejectAbort: () => void = () => {};
      const cancelled = new Promise<never>((_, reject) => {
        rejectAbort = () => reject(controller.signal.reason);
        controller.signal.addEventListener('abort', rejectAbort, { once: true });
      });
      try {
        const qs = selectQuestions(questions, policy.diagnostics);
        const result = await Promise.race([
          backend.request ? backend.request(state, qs, { signal: controller.signal })
            : backend.ask(state, qs).then(answers => ({ answers, usageComplete: false })),
          cancelled,
        ]);
        controller.signal.throwIfAborted();
        // Legacy lastUsage is deliberately not read: it is unsafe under concurrency.
        return structuredClone(result);
      } finally {
        clearTimeout(timer); if (poll) clearInterval(poll); active.delete(controller);
        options.signal?.removeEventListener('abort', abort);
        controller.signal.removeEventListener('abort', rejectAbort);
      }
    },
  };
}
