import { progressiveBackend } from './request.js';
import {
  TypeSafeClient,
  type ChoiceResponse,
  type EntryType,
  type NoulResponse,
  type Questions as SdkQuestions,
  type ScoreResponse,
} from '@typesafe-ai/sdk';
import type { Answer, Question, SystemOne, TokenUsage } from './types.js';
import { createProxiedFetch } from './http.js';

export interface JevOptions {
  apiKey?: string;
  baseURL?: string;
  model?: string;
}

/** 把本项目的 score levels（{"0": "...", "1": "..."}）映射为 SDK 的有序 rubric 数组。 */
export function toSdkQuestion(q: Question): SdkQuestions[string] {
  if (q.type === 'json') throw new Error('JEV 执行接口不支持生成 JSON 计划；请使用 DeepSeek 指挥角色');
  if (q.type === 'choice') {
    return { type: 'choice', instructions: q.instructions, criteria: q.criteria };
  }
  if (q.type === 'score') {
    const keys = Object.keys(q.levels);
    if (keys.length < 2) throw new Error(`score 问题至少需要两级（收到 ${keys.length} 个）`);
    const sorted = keys
      .map(k => ({ k, n: Number(k) }))
      .sort((a, b) => a.n - b.n);
    if (!sorted.every(({ n }, i) => Number.isFinite(n) && n === i)) {
      throw new Error(`score levels 的 key 必须是从 0 开始的连续数字（收到 ${keys.join(', ')}）`);
    }
    return {
      type: 'score',
      instructions: q.instructions,
      criteria: sorted.map(({ k }) => q.levels[k]!) as [string, string, ...string[]],
    };
  }
  return { type: 'noul', instructions: q.instructions };
}

/** 把 SDK 的应答映射回 src 的 Answer 形状（noul 为 0..1，score 概率以等级 key 索引）。 */
export function toAnswer(raw: ChoiceResponse | ScoreResponse | NoulResponse): Answer {
  if (raw.type === 'choice') {
    return { type: 'choice', choice: raw.choice, probabilities: { ...raw.probabilities }, confidence: raw.confidence };
  }
  if (raw.type === 'score') {
    const probabilities: Record<string, number> = {};
    for (const [k, v] of Object.entries(raw.probabilities)) probabilities[k] = v;
    return { type: 'score', score: raw.score, probabilities, confidence: raw.confidence };
  }
  return { type: 'noul', noul: raw.noul };
}

/**
 * Jev（TypeSafe System One）真实后端：走官方 @typesafe-ai/sdk 的
 * client.systemOne({ state, questions })。环境变量：
 * TYPESAFE_API_KEY（必需）/ TYPESAFE_BASE_URL / TYPESAFE_DEFAULT_MODEL。
 */
export function createJevSystemOne(env: NodeJS.ProcessEnv = process.env): SystemOne {
  const apiKey = env['TYPESAFE_API_KEY'];
  if (!apiKey) {
    throw new Error('SYSTEMONE_BACKEND=jev 需要配置 TYPESAFE_API_KEY（另支持 TYPESAFE_BASE_URL / TYPESAFE_DEFAULT_MODEL）');
  }
  const client = new TypeSafeClient({
    apiKey,
    ...(env['TYPESAFE_BASE_URL'] ? { baseURL: env['TYPESAFE_BASE_URL'] } : {}),
    defaultModel: env['TYPESAFE_DEFAULT_MODEL'] ?? 'jev-latest',
    logLevel: 'warn',
    // The realtime runner owns the per-session deadline. Keep the SDK's
    // transport deadline at least as long as that outer budget; the previous
    // fixed 10s timeout aborted live squad decisions even when the session
    // explicitly allowed 30s, leaving the engine on a completed old order.
    // TYPESAFE_TIMEOUT_MS is an optional process-level override for other
    // callers; retries remain disabled so a late answer cannot duplicate an
    // already accepted command.
    timeout: (() => {
      const value = Number(env['TYPESAFE_TIMEOUT_MS'] ?? 30000);
      return Number.isFinite(value) && value >= 1000 ? Math.min(120000, Math.floor(value)) : 30000;
    })(),
    retry: { maxRetries: 0 },
    fetch: createProxiedFetch(env),
  });
  return progressiveBackend(async (state, questions, options) => {
      const sdkQuestions: SdkQuestions = {};
      for (const [name, q] of Object.entries(questions)) sdkQuestions[name] = toSdkQuestion(q);
      const result = await client.systemOne({ state: state as EntryType, questions: sdkQuestions }, options);
      const usage = { promptTokens: result.usage.input_tokens, completionTokens: result.usage.output_tokens, totalTokens: result.usage.input_tokens + result.usage.output_tokens };
      const answers: Record<string, Answer> = {};
      for (const [name, raw] of Object.entries(result.answers)) answers[name] = toAnswer(raw);
      return { answers, usage, usageComplete: true, requestedModel: env['TYPESAFE_DEFAULT_MODEL'] ?? 'jev-latest', resolvedModel: result.model };
  });
}
