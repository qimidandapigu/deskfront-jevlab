import { createRequestManager, selectQuestions, type RequestPolicy } from '../systemone/request.js';
import { setTimeout as sleep } from 'node:timers/promises';
import type { Answer, ModelResponse, SystemOne, TokenUsage } from '../systemone/types.js';
import type { RealtimeGame } from './plugin.js';
import { DEFAULT_CONFIDENCE_THRESHOLD, DEFAULT_HIGH_RISK_THRESHOLD } from './confidence.js';
import { assistDecision } from './assistance.js';
import { decisionTrigger, createEffectTracker, invalidChoice, prepareDecision, withDecisionFeedback, type DecisionFeedback, type DecisionHooks, type EffectSnapshot, type ExecutionRecord, type FeedbackRecord } from './decision.js';

export interface RealtimeRecord {
  game: string; frame: number; observation: unknown;
  answers: Record<string, Answer>; ms: number;
  request?: Omit<ModelResponse, 'answers'>;
  execution?: ExecutionRecord;
  hesitation?: boolean;
  capped?: { question: string; from: string; to: string };
  /** Legacy diagnostic: high risk without a configured safe action is NOT intercepted. */
  blocked?: { question: string; choice: string };
  abstained?: boolean;
  usage?: TokenUsage;
  error?: string;
  failureCount?: number;
}
export interface RealtimeOptions<S = unknown> {
  requests?: RequestPolicy;
  decisionMs?: number; maxFailures?: number; maxTicks?: number;
  tickSleepMs?: number;
  onTick?: (state: S, frame: number) => void;
  /** @deprecated Ignored: model latency never pauses simulation. */
  pauseWhileDeciding?: boolean;
  shouldAbort?: () => boolean;
  confidenceThreshold?: number; highRiskThreshold?: number;
  /** Maximum observation age in game time; defaults to game hook or 1500 ms. */
  maxDecisionAgeMs?: number;
  onUpdate?: (record: RealtimeRecord, snapshot: { done: boolean; outcome: string | null }) => void;
  rivalBackend?: SystemOne;
  onRivalUpdate?: (record: RealtimeRecord) => void;
  onFeedback?: (record: FeedbackRecord) => void;
  /** Lifecycle cancellations are separate from model-response callbacks. */
  onDiscard?: (record: RealtimeRecord) => void;
}
export interface RealtimeSummary {
  outcome: 'won' | 'lost' | 'draw' | 'finished' | 'void' | 'tick-limit' | 'aborted' | 'request-budget';
  ticks: number; decisions: number; skipped: number; failures: number;
  finalObservation?: unknown;
}

export function createRealtimeMatch<S>(game: RealtimeGame<S>, backend: SystemOne, options: RealtimeOptions<S> = {}) {
  const decisionMs = options.decisionMs ?? game.decisionMs ?? 200;
  const thresholds = { confidence: options.confidenceThreshold ?? DEFAULT_CONFIDENCE_THRESHOLD, highRisk: options.highRiskThreshold ?? DEFAULT_HIGH_RISK_THRESHOLD };
  let state = game.initialState(), frame = 0, done = false, sequence = 0;
  const summary: RealtimeSummary = { outcome: 'finished', ticks: 0, decisions: 0, skipped: 0, failures: 0 };
  const makeSide = (name: 'self' | 'rival', model: SystemOne, hooks: DecisionHooks<S> | undefined) => ({
    name, model: createRequestManager(model, options.requests), hooks, lastEvent: undefined as string | undefined, pending: false, enabled: true, epoch: 0, nextAt: decisionMs, failures: 0,
    lastMs: null as number | null, latest: undefined as DecisionFeedback | undefined,
    track: createEffectTracker(), active: undefined as { record: ExecutionRecord; before?: EffectSnapshot } | undefined,
    request: undefined as { id: string; at: number; observation: unknown; started: number; cancelled: boolean; controller: AbortController } | undefined,
  });
  const self = makeSide('self', backend, game.decision);
  const rival = game.rival && options.rivalBackend ? makeSide('rival', options.rivalBackend, game.rival.decision) : null;
  if (rival) state = game.rival!.act(state, {});
  type Side = typeof self;
  const sides = rival ? [self, rival] : [self];
  const observe = (side: Side) => side.name === 'self' ? game.observe(state) : game.rival!.observe(state);
  const questions = (side: Side) => side.name === 'self' ? game.questions(state) : game.rival!.questions?.(state) ?? game.questions(state);
  const settle = (side: Side, reason: string, after = side.hooks?.capture(state)) => {
    if (!side.active) return;
    const { record, before } = side.active;
    side.latest = side.track(record.id, before, after, frame, reason);
    // Separate immutable event: JSONL consumers cannot observe later object mutations.
    options.onFeedback?.({ type: 'feedback', game: game.id, side: side.name, feedback: side.latest });
    side.active = undefined;
  };
  const cancel = (side: Side, reason: string) => {
    const request = side.request;
    if (!request || request.cancelled) return;
    request.cancelled = true; request.controller.abort(new Error(reason));
    side.request = undefined; side.pending = false;
    options.onDiscard?.({ game: game.id, frame, observation: request.observation, answers: {}, ms: Date.now() - request.started,
      execution: { schema: 'quickplay-execution-v1', id: request.id, side: side.name, requestedAt: request.at, resolvedAt: frame, status: 'discarded', rawAnswers: {}, executedAnswers: null, action: null, reason } });
  };
  const release = (side: Side) => { if (side.hooks?.release) state = side.hooks.release(state); };
  const finish = (outcome: RealtimeSummary['outcome']) => {
    if (done) return;
    done = true; summary.outcome = outcome;
    for (const side of sides) { settle(side, outcome); cancel(side, outcome); release(side); }
  };
  const dispatch = async (side: Side, trigger: string) => {
    side.pending = true;
    const epoch = side.epoch;
    const context = side.hooks?.contextKey?.(state);
    const currentEffect = side.active ? side.track(side.active.record.id, side.active.before, side.hooks?.capture(state), frame, 'in-progress', false) : side.latest;
    const rawObservation = withDecisionFeedback(observe(side), currentEffect);
    const observation = structuredClone(side.lastMs !== null && rawObservation !== null && typeof rawObservation === 'object'
      ? { ...rawObservation, timing: { lastDecisionMs: side.lastMs } } : rawObservation);
    const qs = structuredClone(selectQuestions(questions(side), options.requests?.diagnostics));
    const request = { id: `${game.id}:${side.name}:${++sequence}`, at: frame, observation, started: Date.now(), cancelled: false, controller: new AbortController() };
    side.request = request;
    const publish = (record: RealtimeRecord) => side.name === 'self'
      ? options.onUpdate?.(record, { done, outcome: done ? summary.outcome : null }) : options.onRivalUpdate?.(record);
    try {
      const response = await side.model.request(observation, qs, { signal: request.controller.signal });
      const raw = response.answers;
      if (done || request.cancelled || epoch !== side.epoch || !side.enabled) return;
      const ms = Date.now() - request.started;
      const usage = response.usage;
      const prepared = prepareDecision(qs, raw, thresholds);
      const ageMs = (frame - request.at) * game.tickMs;
      const ageReason = options.maxDecisionAgeMs !== undefined
        ? (ageMs > options.maxDecisionAgeMs ? 'observation-expired' : null)
        : side.hooks?.validateResponse && !prepared.skip ? side.hooks.validateResponse(state, prepared.answers, ageMs)
        : ageMs > (side.hooks?.maxAgeMs ?? 1500) ? 'observation-expired' : null;
      const stale = ageReason ?? (side.hooks?.contextKey?.(state) !== context ? 'context-changed'
        : !prepared.skip && invalidChoice(selectQuestions(questions(side), options.requests?.diagnostics), prepared.answers) ? 'candidates-changed' : null);
      const execution: ExecutionRecord = { schema: 'quickplay-execution-v1', id: request.id, side: side.name, requestedAt: request.at, resolvedAt: frame,
        validation: { ageMs, live: !!side.hooks?.validateResponse && options.maxDecisionAgeMs === undefined && !prepared.skip },
        trigger, status: stale ? 'discarded' : prepared.status, rawAnswers: raw, executedAnswers: null, action: null, reason: stale ?? prepared.reason };
      if (!stale && !prepared.skip) {
        const before = side.hooks?.capture(state);
        const recovery = side.hooks?.recover?.(state, prepared.answers, currentEffect);
        if (recovery) {
          const checked = prepareDecision(qs, recovery.answers, thresholds);
          if (!checked.skip) { prepared.answers = checked.answers; execution.reason = recovery.reason; }
        }
        const assisted = assistDecision(side.hooks?.assistance, state,
          selectQuestions(questions(side), options.requests?.diagnostics), prepared.answers, currentEffect);
        prepared.answers = assisted.answers;
        if (assisted.trace.length) execution.assistance = assisted.trace;
        state = side.name === 'self' ? game.act(state, prepared.answers) : game.rival!.act(state, prepared.answers);
        execution.executedAnswers = structuredClone(prepared.answers);
        execution.action = structuredClone(side.hooks?.describe(state, prepared.answers) ?? { command: prepared.answers });
        execution.reason = execution.action.reason ?? execution.reason;
        const disposition = execution.action.disposition ?? 'accepted';
        if (disposition === 'accepted') {
          settle(side, 'superseded', before);
          side.active = { record: execution, before };
          if (side.name === 'self') summary.decisions++;
        } else {
          execution.status = disposition === 'retained' ? 'skipped' : 'rejected';
          execution.executedAnswers = null;
        }
      } else {
        if (!stale) { settle(side, prepared.reason ?? 'skipped'); release(side); }
        side.latest = side.track(execution.id, undefined, undefined, frame, stale ?? prepared.reason ?? 'skipped');
        execution.feedback = side.latest;
      }
      side.failures = 0; side.lastMs = ms;
      const gate = prepared.gate;
      publish({ game: game.id, frame, observation, answers: raw, execution, ms, request: { usage: response.usage, usageComplete: response.usageComplete, requestedModel: response.requestedModel, resolvedModel: response.resolvedModel },
        ...(gate.hesitation ? { hesitation: true } : {}), ...(gate.capped ? { capped: gate.capped } : {}),
        ...(gate.blocked ? { blocked: gate.blocked } : {}), ...(gate.abstained ? { abstained: true } : {}), ...(usage ? { usage } : {}) });
    } catch (error) {
      if (done || request.cancelled || epoch !== side.epoch) return;
      side.failures++; summary.failures++;
      const message = (error instanceof Error ? `${error.name}: ${error.message}` : String(error))
        .replace(/Bearer\s+\S+/gi, 'Bearer [redacted]').replace(/\bsk-[\w-]+/g, '[redacted]').slice(0, 500);
      settle(side, 'model-error'); release(side);
      const execution: ExecutionRecord = { schema: 'quickplay-execution-v1', id: request.id, side: side.name, requestedAt: request.at, resolvedAt: frame, status: 'error', rawAnswers: {}, executedAnswers: null, action: null, reason: message };
      // The response is already accounted for; finish must not also cancel it.
      side.request = undefined; side.pending = false;
      if (side.failures >= (options.maxFailures ?? 3)) finish('void');
      publish({ game: game.id, frame, observation, answers: {}, ms: Date.now() - request.started, error: message, failureCount: side.failures, execution });
    } finally {
      if (side.request === request) { side.request = undefined; side.pending = false; }
    }
  };
  const tick = async (waitForDecision = true): Promise<void> => {
    if (done) return;
    if (game.isTerminal(state)) { finish(game.outcome?.(state) ?? 'finished'); return; }
    for (const side of sides) {
      const expiry = side.active ? side.hooks?.describe(state, side.active.record.executedAnswers ?? {}).expiresAt ?? side.active.record.action?.expiresAt : undefined;
      if (expiry !== undefined && frame >= expiry) { settle(side, 'expired'); release(side); }
    }
    state = game.step(state); frame++; summary.ticks = frame;
    options.onTick?.(state, frame);
    if (game.isTerminal(state)) { finish(game.outcome?.(state) ?? 'finished'); return; }
    if (frame >= (options.maxTicks ?? 10_000)) { finish('tick-limit'); return; }
    const elapsed = frame * game.tickMs;
    let selfResponse: Promise<void> | undefined;
    for (const side of sides) {
      if (!side.enabled) continue;
      const trigger = decisionTrigger(side.hooks, state, elapsed, side.nextAt - decisionMs, decisionMs,
        side.lastEvent, side.name === 'self' ? game.decisionReady?.(state) : undefined)
        ?? (side.hooks?.schedule?.prefetch?.(state, side.lastMs ?? decisionMs) ? 'prefetch' : null);
      if (!trigger) continue;
      if (side.pending) { if (side.name === 'self') summary.skipped++; continue; }
      if (side.model.count >= (options.requests?.maxRequests ?? Infinity)) { finish('request-budget'); break; }
      // A side without controlled living units has no questions and needs no request.
      if (!Object.keys(questions(side)).length) continue;
      side.nextAt = elapsed + decisionMs;
      side.lastEvent = side.hooks?.schedule?.eventKey?.(state);
      if (trigger === 'completed') settle(side, 'completed');
      const response = dispatch(side, trigger);
      if (side.name === 'self') selfResponse = response;
    }
    if (waitForDecision) await selfResponse;
  };
  return {
    tick, stop: () => finish('aborted'),
    /** Invalidate in-flight replies before manual/external control is applied. */
    setControl(sideName: 'self' | 'rival', enabled: boolean) {
      const side = sideName === 'self' ? self : rival;
      if (!side || done || side.enabled === enabled) return;
      side.enabled = enabled; side.epoch++; cancel(side, 'control-changed'); settle(side, 'control-changed'); release(side);
    },
    startHumanCompanion(model: boolean) { if (game.humanCompanion) state = game.humanCompanion.start(state, model); },
    applyExternal(answers: Record<string, Answer>, sideName: 'self' | 'rival' = 'self', preserveModel = false) {
      if (done) return;
      const side = sideName === 'self' ? self : rival;
      const context = side?.hooks?.contextKey?.(state);
      if (!preserveModel) this.setControl(sideName, false);
      state = sideName === 'self' ? game.act(state, answers) : game.rival?.act(state, answers) ?? state;
      if (preserveModel && side && context !== side.hooks?.contextKey?.(state)) {
        side.epoch++; cancel(side, 'context-changed'); settle(side, 'context-changed');
      }
    },
    get done() { return done; }, get state() { return state; }, get summary() { return summary; },
  };
}

export async function runRealtimeGame<S>(game: RealtimeGame<S>, backend: SystemOne, options: RealtimeOptions<S> = {}): Promise<RealtimeSummary> {
  const match = createRealtimeMatch(game, backend, options);
  let error: unknown = null;
  while (!match.done) {
    if (options.shouldAbort?.()) { match.stop(); break; }
    void match.tick().catch((e: unknown) => { error ??= e; match.stop(); });
    await sleep(options.tickSleepMs ?? game.tickMs);
  }
  if (error) throw error;
  try { match.summary.finalObservation = game.observe(match.state); } catch { /* Do not hide outcome. */ }
  return match.summary;
}
