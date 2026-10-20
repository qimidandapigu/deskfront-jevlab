import type { Answer, Question } from '../systemone/types.js';

export const DEFAULT_CONFIDENCE_THRESHOLD = 0.6;
export const DEFAULT_HIGH_RISK_THRESHOLD = 0.85;

export interface GateResult {
  /** Legacy field; probability thresholds no longer affect execution. */
  hesitation: boolean;
  /** Legacy log field; no longer emitted. */
  capped?: { question: string; from: string; to: string };
  /** Legacy log field; no longer emitted. */
  blocked?: { question: string; choice: string };
  /** 后端返回 other；已用实际候选解决弃权。 */
  abstained?: { question: string };
  /** 只有题目完全没有真实候选时才跳过。 */
  skipAct: boolean;
}

/** Confidence is diagnostic only. An abstention still resolves to a concrete option. */
export function gateAnswers(
  questions: Record<string, Question>,
  answers: Record<string, Answer>,
  _thresholds: { confidence: number; highRisk: number },
): GateResult {
  const result: GateResult = { hesitation: false, skipAct: false };
  for (const [name, q] of Object.entries(questions)) {
    if (q.type !== 'choice') continue;
    const a = answers[name];
    if (!a || a.type !== 'choice' || !q.allowOther || a.choice !== 'other') continue;
    result.abstained = { question: name };
    const choices = Object.keys(q.criteria).filter(key => key !== 'other');
    const selected = choices.sort((x, y) => (a.probabilities[y] ?? 0) - (a.probabilities[x] ?? 0))[0];
    const fallback = q.safeAction && choices.includes(q.safeAction) ? q.safeAction : selected;
    if (fallback) answers[name] = { ...a, choice: fallback };
    else result.skipAct = true; // No actual action exists in this question.
  }
  return result;
}
