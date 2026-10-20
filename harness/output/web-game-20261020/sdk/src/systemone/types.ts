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
  | { type: 'json'; instructions: string; label?: string; systemInstructions?: string; maxOutputTokens?: number;
      /** Opt-in data-only experience report. Never executes a model tool. */
      responseMode?: 'strict_tool'; responseSchema?: Record<string, unknown> }
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
  outputMode?: 'strict_tool';
  responseSchemaSha256?: string;
  providerSchemaSha256?: string;
}

/** JSON answer failures, deliberately excluding request bodies, headers and reasoning. */
export interface JsonAnswerDiagnostic extends ModelRequestDiagnostic {
  schema: 'quickplay-json-answer-error/v1';
  kind: 'invalid_response_json' | 'missing_message' | 'unexpected_content_type' | 'empty_content' | 'truncated_content' | 'unsupported_finish_reason' | 'refused_content' | 'tool_call_content' | 'malformed_content' | 'non_object_content' | 'strict_tool_contract' | 'strict_schema_mismatch';
  requestedModel: string;
  resolvedModel?: string;
  responseBytes: number;
  responseSha256: string;
  contentType: string;
  contentChars?: number;
  contentBytes?: number;
  contentSha256?: string;
  trimmedChars?: number;
  hasMessage: boolean;
  hasToolCalls: boolean;
  hasRefusal: boolean;
  fencedContent: boolean;
  usage?: TokenUsage;
  /** Bounded final-answer excerpts with credential patterns removed. */
  contentPreview?: { prefix: string; suffix: string; truncated: boolean };
  /** Lexical shape only; never used to repair or accept a failed JSON answer. */
  jsonSyntax?: { unclosedContainers: number; unterminatedString: boolean; trailingEscape: boolean; unexpectedClose: boolean; trailingContent: boolean };
}

export interface SystemOne {
  request?(state: unknown, questions: Record<string, Question>, options?: ModelRequestOptions): Promise<ModelResponse>;
  ask(state: unknown, questions: Record<string, Question>): Promise<Record<string, Answer>>;
  /** 最近一次 ask 的 token 用量（mock 等本地后端可不提供）。 */
  readonly lastUsage?: TokenUsage;
}

/** Completed choices for display only; the final response remains atomic. */
export interface ModelRequestOptions {
  signal?: AbortSignal;
  onAnswer?: (key: string, answer: Answer) => void;
}

/** Metadata belongs to this response, never to another concurrent request. */
export interface ModelResponse {
  answers: Record<string, Answer>;
  usage?: TokenUsage;
  diagnostics?: ModelRequestDiagnostic[];
  requestedModel?: string;
  resolvedModel?: string;
  usageComplete?: boolean;
  /** Number of provider batches behind this logical request, when reported. */
  upstreamRequests?: number;
}

/** 1 - 归一化香农熵：分布越集中越接近 1，越均匀越接近 0。 */
export function confidenceFrom(probabilities: Record<string, number>): number {
  const entries = Object.values(probabilities).filter(p => p > 0);
  if (entries.length <= 1) return 1;
  const n = Object.keys(probabilities).length;
  const entropy = -entries.reduce((sum, p) => sum + p * Math.log(p), 0);
  return Math.max(0, Math.min(1, 1 - entropy / Math.log(n)));
}
