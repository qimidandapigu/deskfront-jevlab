import { createRequestManager, type RequestPolicy } from '../systemone/request.js';
import { invalidAnswers } from '../systemone/validation.js';
import { createJevSystemOne } from "../systemone/jev.js";
import type { Answer, Question, SystemOne } from "../systemone/types.js";
import type { JevAnswer, JevAnswers, JevClient, JevQuestions, JevResponse } from "./jev-types.js";

/** JGP 的 JevQuestions → 内置线 SystemOne 的 Question（分级字段透传）。 */
export function toQuestion(q: JevQuestions[string]): Question {
  const instructions = q.instructions == null ? "" : typeof q.instructions === "string" ? q.instructions : JSON.stringify(q.instructions);
  if (q.type === "choice") {
    const criteria: Record<string, string> = {};
    for (const [k, v] of Object.entries(q.criteria)) criteria[k] = typeof v === "string" ? v : JSON.stringify(v);
    return {
      type: "choice", instructions, criteria,
      ...(q.allowOther ? { allowOther: true } : {}),
      ...(q.highRisk ? { highRisk: q.highRisk } : {}),
      ...(q.safeAction ? { safeAction: q.safeAction } : {}),
    };
  }
  if (q.type === "score") {
    const levels: Record<string, string> = {};
    q.criteria.forEach((d, i) => { levels[String(i)] = typeof d === "string" ? d : JSON.stringify(d); });
    return { type: "score", instructions, levels };
  }
  return { type: "noul", instructions };
}

/** 内置线 Answer → JGP 的 JevAnswer；noul 的 confidence 缺失时按 max(p, 1-p) 合成兜底。 */
export function toJevAnswer(a: Answer): JevAnswer {
  if (a.type === 'json') throw new Error('JGP execution does not accept generated JSON plans');
  if (a.type === "choice") return { choice: a.choice, confidence: a.confidence, probabilities: a.probabilities };
  if (a.type === "score") return { score: a.score, confidence: a.confidence, probabilities: a.probabilities };
  return { noul: a.noul >= 0.5, confidence: a.confidence ?? Math.max(a.noul, 1 - a.noul) };
}

/**
 * 把任意内置线 SystemOne 后端包装成 JGP 的 JevClient：
 * mock / deepseek / openrouter / jev 因此都能驱动外部游戏，两条线共用同一套后端生态。
 */
export function createSystemOneJevClient(systemOne: SystemOne, deps: { now?: () => number; model?: string; requests?: RequestPolicy } = {}): JevClient {
  const now = deps.now ?? Date.now;
  const requests = createRequestManager(systemOne, deps.requests);
  let disposed = false;
  return {
    async systemOne(request): Promise<JevResponse> {
      if (disposed) throw new Error("client-disposed");
      const t0 = now();
      const questions: Record<string, Question> = {};
      for (const [name, q] of Object.entries(request.questions)) questions[name] = toQuestion(q);
      const response = await requests.request(request.state, questions);
      const raw = response.answers;
      const invalid = invalidAnswers(questions, raw);
      if (invalid) throw new Error(invalid);
      const answers: JevAnswers = {};
      for (const name of Object.keys(questions)) answers[name] = toJevAnswer(raw[name]!);
      return { answers, latencyMs: now() - t0, model: response.resolvedModel ?? response.requestedModel ?? deps.model ?? "systemone", ...(response.usage ? { usage: response.usage } : {}) };
    },
    dispose() { disposed = true; requests.cancel("client-disposed"); },
  };
}

/** Real Jev client for the JGP engine, built on the src/systemone SDK wrapper. */
export function createJevClient(deps: { env?: NodeJS.ProcessEnv; now?: () => number } = {}): JevClient {
  return createSystemOneJevClient(createJevSystemOne(deps.env ?? process.env), { ...(deps.now ? { now: deps.now } : {}), model: "jev" });
}
