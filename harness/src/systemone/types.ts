export type Question = { purpose?: 'action' | 'protection' | 'display' } & (
  | {
      type: 'choice'; instructions: string; criteria: Record<string, string>;
      /** 题目中文短名，观测站据此渲染（新游戏零前端改动）。 */
      label?: string;
      /** 允许后端返回保留键 "other" 表示弃权（runner 按安全默认处理，不算非法动作）。 */
      allowOther?: boolean;
      /** 兼容旧配置；不再按置信度降级或拦截。 */
      highRisk?: string[];
      /** 弃权时的默认动作；不因低置信度替换正常选择。 */
      safeAction?: string;
    }
  | { type: 'score'; instructions: string; levels: Record<string, string>; label?: string }
  | { type: 'json'; instructions: string; label?: string; systemInstructions?: string; maxOutputTokens?: number }
  | { type: 'noul'; instructions: string; label?: string });

export type Answer =
  | { type: 'json'; value: Record<string, unknown>; confidence?: never }
  | { type: 'choice'; choice: string; probabilities: Record<string, number>; confidence: number }
  | { type: 'score'; score: number; probabilities: Record<string, number>; confidence: number }
  | { type: 'noul'; noul: number; /** 对布尔判断本身的把握；缺省时消费方可按 max(noul, 1-noul) 合成。 */ confidence?: number };

/** 一次 ask 的 token 用量；后端能拿到才提供。 */
export interface TokenUsage {
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
  /** Provider-reported reasoning tokens within completionTokens, when available. */
  reasoningTokens?: number;
}

/** Safe transport metadata for one upstream HTTP call; never includes headers or prompt content. */
export interface ModelRequestDiagnostic {
  /** API hostname; not the OpenRouter downstream inference provider. */
  provider: string;
  /** OpenRouter's reported inference provider, if present in the response. */
  upstreamProvider?: string;
  requestBytes: number;
  /** Milliseconds from dispatch until response headers arrived. */
  headersElapsedMs: number;
  /** Milliseconds from dispatch until the complete response body was received. */
  bodyElapsedMs: number;
  finishReason?: string;
}

export interface SystemOne {
  request?(state: unknown, questions: Record<string, Question>, options?: { signal?: AbortSignal }): Promise<ModelResponse>;
  ask(state: unknown, questions: Record<string, Question>): Promise<Record<string, Answer>>;
  /** 最近一次 ask 的 token 用量（mock 等本地后端可不提供）。 */
  readonly lastUsage?: TokenUsage;
}

/** Metadata belongs to this response, never to another concurrent request. */
export interface ModelResponse {
  answers: Record<string, Answer>;
  usage?: TokenUsage;
  diagnostics?: ModelRequestDiagnostic[];
  requestedModel?: string;
  resolvedModel?: string;
  usageComplete?: boolean;
}

/** 1 - 归一化香农熵：分布越集中越接近 1，越均匀越接近 0。 */
export function confidenceFrom(probabilities: Record<string, number>): number {
  const entries = Object.values(probabilities).filter(p => p > 0);
  if (entries.length <= 1) return 1;
  const n = Object.keys(probabilities).length;
  const entropy = -entries.reduce((sum, p) => sum + p * Math.log(p), 0);
  return Math.max(0, Math.min(1, 1 - entropy / Math.log(n)));
}
