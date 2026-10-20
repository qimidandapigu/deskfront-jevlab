import type { ModelRequestOptions, ModelResponse, Question, SystemOne, TokenUsage } from './types.js';

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

/** Opt-in bounded fan-out for visual construction. Ordinary calls stay batched. */
export function progressiveBackend(request: NonNullable<SystemOne['request']>): SystemOne {
  return responseBackend(async (state, questions, options) => {
    if (!options?.onAnswer) return request(state, questions, options);
    const entries = Object.entries(questions);
    if (entries.length === 0) return request(state, questions, options);
    const size = Math.ceil(entries.length / 3);
    const controller = new AbortController();
    const signal = options.signal ? AbortSignal.any([options.signal, controller.signal]) : controller.signal;
    try {
      const groups = Array.from({ length: Math.ceil(entries.length / size) }, (_, i) => Object.fromEntries(entries.slice(i * size, (i + 1) * size)));
      const results = await Promise.all(groups.map(async group => {
        const result = await request(state, group, { signal });
        signal.throwIfAborted();
        for (const [key, answer] of Object.entries(result.answers)) options.onAnswer!(key, answer);
        return result;
      }));
      const usage: TokenUsage = {};
      for (const key of ['promptTokens', 'completionTokens', 'totalTokens', 'reasoningTokens'] as const) {
        if (results.every(r => r.usage?.[key] !== undefined)) usage[key] = results.reduce((n, r) => n + r.usage![key]!, 0);
      }
      const same = (key: 'requestedModel' | 'resolvedModel') => results.every(r => r[key] === results[0]?.[key]) ? results[0]?.[key] : undefined;
      return { answers: Object.assign({}, ...results.map(r => r.answers)), usage,
        usageComplete: results.every(r => r.usageComplete === true), requestedModel: same('requestedModel'), resolvedModel: same('resolvedModel'),
        diagnostics: results.flatMap(r => r.diagnostics ?? []), upstreamRequests: results.length };
    } catch (error) { controller.abort(error); throw error; }
  });
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
    async request(state: unknown, questions: Record<string, Question>, options: ModelRequestOptions & { shouldAbort?: () => boolean } = {}): Promise<ModelResponse> {
      options.signal?.throwIfAborted();
      if (count >= (policy.maxRequests ?? Infinity)) throw new Error('request-budget');
      count++;
      const controller = new AbortController(); active.add(controller);
      const abort = () => controller.abort(options.signal?.reason ?? new Error('request-cancelled'));
      options.signal?.addEventListener('abort', abort, { once: true });
      const timer = setTimeout(() => controller.abort(new Error('request-timeout')), timeoutMs);
      const poll = options.shouldAbort ? setInterval(() => { if (options.shouldAbort?.()) controller.abort(new Error('request-aborted')); }, 25) : undefined;
      let rejectAbort: () => void = () => {};
      let closed = false;
      const cancelled = new Promise<never>((_, reject) => {
        rejectAbort = () => reject(controller.signal.reason);
        controller.signal.addEventListener('abort', rejectAbort, { once: true });
      });
      try {
        const qs = selectQuestions(questions, policy.diagnostics);
        const result = await Promise.race([
          backend.request ? backend.request(state, qs, { signal: controller.signal, ...(options.onAnswer ? { onAnswer: (key, answer) => {
            if (!closed && !controller.signal.aborted) options.onAnswer!(key, structuredClone(answer));
          } } : {}) })
            : backend.ask(state, qs).then(answers => ({ answers, usageComplete: false })),
          cancelled,
        ]);
        controller.signal.throwIfAborted();
        // Legacy lastUsage is deliberately not read: it is unsafe under concurrency.
        return structuredClone(result);
      } finally {
        closed = true;
        clearTimeout(timer); if (poll) clearInterval(poll); active.delete(controller);
        options.signal?.removeEventListener('abort', abort);
        controller.signal.removeEventListener('abort', rejectAbort);
      }
    },
  };
}
