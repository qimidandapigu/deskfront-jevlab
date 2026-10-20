import { invalidAnswers } from '../systemone/validation.js';
import type { Answer, Question } from '../systemone/types.js';
import { gateAnswers } from './confidence.js';
import type { AssistancePolicy, AssistanceTrace } from './assistance.js';

export type Answers = Record<string, Answer>;
export interface EffectSnapshot { progress: number | null; position: string | null; }
export interface AppliedAction { command: unknown; expiresAt?: number; reason?: string; disposition?: 'accepted' | 'retained' | 'rejected'; }
/** Game-owned semantics; no physics, pathfinding or victory rules live in the runner. */
export interface DecisionHooks<S> {
  assistance?: AssistancePolicy<S>;
  capture(state: S): EffectSnapshot;
  describe(state: S, answers: Answers): AppliedAction;
  /** Changes on respawn / phase changes, not on every physics tick. */
  contextKey?(state: S): string;
  maxAgeMs?: number;
  /** Recheck a delayed action against live game semantics; null means still usable. */
  validateResponse?(state: S, answers: Answers, ageMs: number): string | null;
  release?(state: S): S;
  /** Game declares interruptible events and recovery semantics. */
  schedule?: { ready?(state: S): boolean | undefined; prefetch?(state: S, latencyMs: number): boolean; eventKey?(state: S): string; maxWaitMs?: number; canInterrupt?(state: S): boolean };
  recover?(state: S, answers: Answers, feedback: DecisionFeedback | undefined): { answers: Answers; reason: string } | null;
}
export interface DecisionFeedback {
  decisionId: string;
  status: 'progressed' | 'regressed' | 'unchanged' | 'unknown';
  progressDelta: number | null;
  moved: boolean | null;
  repeats: number;
  reason: string;
  at: number;
}
export interface ExecutionRecord {
  assistance?: AssistanceTrace[];
  schema?: 'quickplay-execution-v1';
  id: string;
  side: 'self' | 'rival';
  requestedAt: number;
  resolvedAt: number;
  status: 'pending' | 'applied' | 'rejected' | 'discarded' | 'skipped' | 'error';
  rawAnswers: Answers;
  executedAnswers: Answers | null;
  action: AppliedAction | null;
  reason: string | null;
  feedback?: DecisionFeedback;
  trigger?: string;
  validation?: { ageMs: number; live: boolean };
}

/** One scheduler for both sides. A game may protect an uninterruptible action. */
export function decisionTrigger<S>(hooks: DecisionHooks<S> | undefined, state: S, elapsed: number,
  lastAt: number, interval: number, lastEvent: string | undefined, legacyReady?: boolean): string | null {
  const policy = hooks?.schedule;
  const ready = policy?.ready?.(state) ?? legacyReady;
  if (ready) return 'completed';
  const interruptible = policy?.canInterrupt?.(state) ?? ready !== false;
  if (interruptible && lastEvent !== undefined && policy?.eventKey?.(state) !== lastEvent) return 'event-changed';
  if (interruptible && elapsed - lastAt >= (policy?.maxWaitMs ?? interval) && (ready !== false || policy?.maxWaitMs !== undefined)) return 'max-wait';
  return null;
}

/** Shared bounded visit history; each game supplies a semantic position key. */
export function createDecisionHistory(limit = 128) {
  const visits = new Map<string, number>();
  return {
    count: (key: string) => visits.get(key) ?? 0,
    visit(key: string) {
      const count = (visits.get(key) ?? 0) + 1;
      visits.delete(key); visits.set(key, count);
      if (visits.size > limit) visits.delete(visits.keys().next().value!);
      return count;
    },
  };
}
export interface FeedbackRecord { type: 'feedback'; game: string; side: 'self' | 'rival'; feedback: DecisionFeedback; }

export const repeatedWithoutProgress = (previous: number, unchanged: boolean) => unchanged ? previous + 1 : 0;

export function invalidChoice(questions: Record<string, Question>, answers: Answers): string | null {
  for (const [key, q] of Object.entries(questions)) {
    if (q.type !== 'choice') continue;
    const a = answers[key];
    if (!a || a.type !== 'choice' || !Object.hasOwn(q.criteria, a.choice) && !(q.allowOther && a.choice === 'other')) return `invalid-choice:${key}:${a?.type === 'choice' ? a.choice : 'missing'}`;
  }
  return null;
}

export function prepareDecision(questions: Record<string, Question>, raw: Answers, thresholds: { confidence: number; highRisk: number }) {
  // Never let an unsolicited answer activate a human-only control channel.
  const answers = structuredClone(Object.fromEntries(Object.keys(questions).filter(key => raw && Object.hasOwn(raw, key)).map(key => [key, raw[key]!])));
  const invalid = invalidAnswers(questions, answers);
  const gate = invalid ? { hesitation: false, skipAct: true } : gateAnswers(questions, answers, thresholds);
  const reason = invalid ?? (gate.skipAct ? 'abstained' : gate.capped ? 'confidence-safe-action' : gate.abstained ? 'abstention-resolved-to-action' : null);
  // Validate the safe action too: misconfigured fallbacks must never reach the engine.
  const fallbackInvalid = invalidChoice(questions, answers);
  return { answers, gate, reason: invalid ?? fallbackInvalid ?? reason, skip: !!invalid || !!fallbackInvalid || gate.skipAct,
    status: invalid || fallbackInvalid ? 'rejected' as const : gate.skipAct ? 'skipped' as const : 'applied' as const };
}

export function createEffectTracker() {
  let repeats = 0;
  return (id: string, before: EffectSnapshot | undefined, after: EffectSnapshot | undefined, at: number, reason: string, commit = true): DecisionFeedback => {
    const delta = before?.progress != null && after?.progress != null ? after.progress - before.progress : null;
    const moved = before?.position != null && after?.position != null ? before.position !== after.position : null;
    const status = delta === null ? 'unknown' : delta > 0 ? 'progressed' : delta < 0 ? 'regressed' : 'unchanged';
    const nextRepeats = repeatedWithoutProgress(repeats, status === 'unchanged' && !moved);
    if (commit) repeats = nextRepeats;
    return { decisionId: id, status, progressDelta: delta, moved, repeats: nextRepeats, reason, at };
  };
}

export function withDecisionFeedback(observation: unknown, feedback?: DecisionFeedback): unknown {
  return feedback && observation !== null && typeof observation === 'object'
    ? { ...observation, decisionFeedback: feedback } : observation;
}
