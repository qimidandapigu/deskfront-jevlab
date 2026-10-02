/**
 * JevClient abstraction. core depends only on this interface (DI);
 * two implementations: real (@typesafe-ai/sdk) and fake (offline).
 */

export interface JevChoiceQuestion {
  type: "choice";
  instructions?: unknown;
  criteria: Record<string, unknown>;
  /** 允许后端返回保留键 "other" 弃权：有 safeAction 时替换执行，否则本 tick 不动作。 */
  allowOther?: boolean;
  /** 兼容旧配置，不再按置信度降级或打标。 */
  highRisk?: string[];
  /** 弃权时的默认动作；不因低置信度替换正常选择。 */
  safeAction?: string;
}
export interface JevNoulQuestion {
  type: "noul";
  instructions?: unknown;
  criteria?: { true?: unknown; false?: unknown } | null;
}
export interface JevScoreQuestion {
  type: "score";
  instructions?: unknown;
  criteria: unknown[];
}
export type JevQuestion = JevChoiceQuestion | JevNoulQuestion | JevScoreQuestion;
export type JevQuestions = Record<string, JevQuestion>;

export interface JevAnswer {
  /** Set for choice questions. */
  choice?: string;
  /** Set for noul questions. */
  noul?: boolean;
  /** Set for score questions. */
  score?: number;
  confidence: number;
  probabilities?: Record<string, number>;
}
export type JevAnswers = Record<string, JevAnswer>;

export interface JevUsage {
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
}

export interface JevResponse {
  answers: JevAnswers;
  latencyMs: number;
  model: string;
  usage?: JevUsage;
}

export interface JevClient {
  systemOne(request: { state: unknown; questions: JevQuestions }): Promise<JevResponse>;
  dispose(): void;
}

export interface JevClientDeps {
  now?: () => number;
}
