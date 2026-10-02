import { createRequestManager, selectQuestions, type RequestPolicy } from '../systemone/request.js';
import type { Answer, ModelResponse, SystemOne, TokenUsage } from '../systemone/types.js';
import type { TurnBasedGame, TurnResult } from './plugin.js';
import { DEFAULT_CONFIDENCE_THRESHOLD, DEFAULT_HIGH_RISK_THRESHOLD } from './confidence.js';
import { assistDecision } from './assistance.js';
import { createDecisionHistory, createEffectTracker, prepareDecision, withDecisionFeedback, type DecisionFeedback, type ExecutionRecord } from './decision.js';

export interface TurnRecord {
  request?: Omit<ModelResponse, 'answers'>;
  execution?: ExecutionRecord;
  game: string;
  turn: number;
  observation: unknown;
  /** 动作后的显示状态；observation 保留决策前输入，供审计和模型日志使用。 */
  resultObservation?: unknown;
  answers: Record<string, Answer>;
  feedback: string | null;
  ms: number;
  /** 主 choice 答案置信度低于阈值（capped 模式，动作照常执行，概率完整保留）。 */
  hesitation?: boolean;
  /** 低置信度的高风险动作被降级为安全默认动作。 */
  capped?: { question: string; from: string; to: string };
  /** 低置信度的高风险动作无安全默认，只打标不拦。 */
  blocked?: { question: string; choice: string };
  /** 后端返回保留键 "other" 弃权。 */
  abstained?: boolean;
  usage?: TokenUsage;
}

export interface RunOptions {
  requests?: RequestPolicy;
  signal?: AbortSignal;
  maxTurns?: number;
  maxInvalid?: number;
  now?: () => number;
  /** 每回合记录后的间隔毫秒（观战节奏用），默认 0。 */
  turnDelayMs?: number;
  /** 同一局面重复达到此次数即判死循环结束（默认 3，0 关闭）。 */
  maxRepeats?: number;
  /** 每回合开始前检查，返回 true 则中止对局（outcome: aborted）。 */
  shouldAbort?: () => boolean;
  /** 按 TurnResult.playMs 等待动作动画播完再进入下一回合（观战节奏用，默认 false）。 */
  playMsPacing?: boolean;
  /** @deprecated 兼容旧配置，不再按概率过滤。 */
  confidenceThreshold?: number;
  /** @deprecated 兼容旧配置，不再按概率过滤。 */
  highRiskThreshold?: number;
  onUpdate?: (record: TurnRecord, snapshot: { done: boolean; outcome: string | null; finalObservation?: unknown }) => void;
}

export interface RunSummary {
  outcome: 'won' | 'lost' | 'draw' | 'invalid-limit' | 'turn-limit' | 'loop' | 'aborted' | 'request-budget';
  turns: number;
  invalidCount: number;
}

export async function runTurnGame<S>(
  game: TurnBasedGame<S>, backend: SystemOne, options: RunOptions = {},
): Promise<RunSummary> {
  const requests = createRequestManager(backend, options.requests);
  const maxTurns = options.maxTurns ?? 200;
  const maxInvalid = options.maxInvalid ?? 3;
  const now = options.now ?? Date.now;
  const thresholds = {
    confidence: options.confidenceThreshold ?? DEFAULT_CONFIDENCE_THRESHOLD,
    highRisk: options.highRiskThreshold ?? DEFAULT_HIGH_RISK_THRESHOLD,
  };

  let state = game.initialState();
  const track = createEffectTracker();
  let lastEffect: DecisionFeedback | undefined;
  let feedback: string | null = null;
  let consecutiveInvalid = 0;
  let invalidCount = 0;
  const recent: string[] = [];
  const maxRepeats = options.maxRepeats ?? 3;
  const stateCounts = createDecisionHistory();
  const stateKey = (s: S) => game.decision?.capture(s).position ?? JSON.stringify(s);
  if (maxRepeats > 0) stateCounts.visit(stateKey(state));

  for (let turn = 1; turn <= maxTurns; turn++) {
    if (game.isTerminal(state)) return { outcome: game.outcome?.(state) ?? 'won', turns: turn - 1, invalidCount };
    if (requests.count >= (options.requests?.maxRequests ?? Infinity)) return { outcome: 'request-budget', turns: turn - 1, invalidCount };
    if (options.shouldAbort?.()) return { outcome: 'aborted', turns: turn - 1, invalidCount };
    const started = now();
    const observation = structuredClone(withDecisionFeedback(game.observe(state, { turn, recent: recent.slice(-5), feedback }), lastEffect));
    const questions = selectQuestions(game.questions(state), options.requests?.diagnostics);
    let usage: TokenUsage | undefined;
    let request: Omit<ModelResponse, 'answers'> | undefined;
    let rawAnswers: Record<string, Answer>;
    try {
      const response = await requests.request(observation, questions, { signal: options.signal, shouldAbort: options.shouldAbort });
      rawAnswers = response.answers; usage = response.usage;
      const { answers: _answers, ...metadata } = response; request = metadata;
    } catch (error) {
      const message = (error instanceof Error ? error.message : String(error)).replace(/Bearer\s+\S+/gi, 'Bearer [redacted]').replace(/\bsk-[\w-]+/g, '[redacted]').slice(0, 500);
      const execution: ExecutionRecord = { schema: 'quickplay-execution-v1', id: `${game.id}:self:${turn}`, side: 'self', requestedAt: turn, resolvedAt: turn,
        status: options.shouldAbort?.() || options.signal?.aborted ? 'discarded' : 'error', rawAnswers: {}, executedAnswers: null, action: null, reason: message };
      options.onUpdate?.({ game: game.id, turn, observation, answers: {}, execution, feedback: message, ms: now() - started }, { done: true, outcome: execution.status === 'discarded' ? 'aborted' : 'error' });
      if (execution.status === 'discarded') return { outcome: 'aborted', turns: turn - 1, invalidCount };
      throw new Error(message);
    }
    const prepared = prepareDecision(questions, rawAnswers, thresholds);
    const { answers, gate } = prepared;
    const execution: ExecutionRecord = { schema: 'quickplay-execution-v1', id: `${game.id}:self:${turn}`, side: 'self', requestedAt: turn, resolvedAt: turn,
      status: prepared.status, rawAnswers, executedAnswers: null, action: null, reason: prepared.reason };
    if (options.shouldAbort?.()) {
      execution.status = 'discarded'; execution.reason = 'aborted';
      options.onUpdate?.({ game: game.id, turn, observation, answers: rawAnswers, execution, feedback: null, ms: now() - started, ...(usage ? { usage } : {}) }, { done: true, outcome: 'aborted' });
      return { outcome: 'aborted', turns: turn - 1, invalidCount };
    }
    const before = game.decision?.capture(state);
    let result: TurnResult<S>;
    if (prepared.skip) {
      result = { state, feedback: prepared.status === 'rejected' ? prepared.reason : null };
    } else {
      const recovery = game.decision?.recover?.(state, answers, lastEffect);
      if (recovery) {
        const checked = prepareDecision(questions, recovery.answers, thresholds);
        if (!checked.skip) { Object.assign(answers, checked.answers); execution.reason = recovery.reason; }
      }
      const assisted = assistDecision(game.decision?.assistance, state, questions, answers, lastEffect);
      Object.assign(answers, assisted.answers);
      if (assisted.trace.length) execution.assistance = assisted.trace;
      result = game.act(state, answers);
      execution.executedAnswers = structuredClone(answers);
      execution.action = structuredClone(game.decision?.describe(result.state, answers) ?? { command: answers });
      execution.reason = execution.action.reason ?? execution.reason;
      if (result.feedback !== null) { execution.status = 'rejected'; execution.reason = result.feedback; execution.action = null; execution.executedAnswers = null; }
    }
    feedback = result.feedback;
    if (feedback === null) {
      consecutiveInvalid = 0;
      state = result.state;
      // recent 带上实际执行的动作，给无状态模型一点记忆，减少来回横跳
      const choice = Object.values(answers).find(a => a.type === 'choice');
      const actionLabel = choice && choice.type === 'choice' ? ` ${choice.choice}` : '';
      recent.push(`turn ${turn}:${actionLabel} ok`);
    } else {
      consecutiveInvalid++;
      invalidCount++;
      recent.push(`turn ${turn}: ${feedback}`);
    }
    lastEffect = track(execution.id, before, game.decision?.capture(state), turn, execution.reason ?? 'completed');
    execution.feedback = lastEffect;
    const record: TurnRecord = {
      game: game.id, turn, observation, answers, execution, feedback, request, ms: now() - started,
      ...(feedback === null && !prepared.skip
        ? { resultObservation: game.observe(state, { turn, recent: recent.slice(-5), feedback: null }) }
        : {}),
      ...(gate.hesitation ? { hesitation: true } : {}),
      ...(gate.capped ? { capped: gate.capped } : {}),
      ...(gate.blocked ? { blocked: gate.blocked } : {}),
      ...(gate.abstained ? { abstained: true } : {}),
      ...(usage ? { usage } : {}),
    };
    let done = false;
    let outcome: string | null = null;
    let repeatCount = 0;
    if (maxRepeats > 0 && feedback === null && !prepared.skip) {
      repeatCount = stateCounts.visit(stateKey(state));
    }
    if (game.isTerminal(state)) {
      done = true;
      outcome = game.outcome?.(state) ?? 'won';
    } else if (consecutiveInvalid >= maxInvalid) {
      done = true;
      outcome = 'invalid-limit';
    } else if (maxRepeats > 0 && repeatCount >= maxRepeats) {
      done = true;
      outcome = 'loop';
    } else if (turn === maxTurns) {
      done = true;
      outcome = 'turn-limit';
    }
    options.onUpdate?.(record, {
      done,
      outcome,
      // 终局时补上动作生效后的局面，供观测端渲染最终帧（record.observation 仍是决策前的）
      ...(done && feedback === null
        ? { finalObservation: record.resultObservation ?? observation }
        : {}),
    });
    if (done) return { outcome: outcome as RunSummary['outcome'], turns: turn, invalidCount };
    const delayMs = Math.max(options.turnDelayMs ?? 0, options.playMsPacing ? (result.playMs ?? 0) : 0);
    if (!done && delayMs > 0) await new Promise(r => setTimeout(r, delayMs));
  }
  return { outcome: game.isTerminal(state) ? game.outcome?.(state) ?? 'won' : 'turn-limit', turns: maxTurns, invalidCount };
}
