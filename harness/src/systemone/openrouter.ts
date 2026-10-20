import { progressiveBackend } from './request.js';
import type { ChoiceResponse, EntryType, NoulResponse, ScoreResponse } from '@typesafe-ai/sdk';
import type { Answer, Question, SystemOne, TokenUsage } from './types.js';
import { toAnswer, toSdkQuestion } from './jev.js';
import { createProxiedFetch } from './http.js';

interface DecisionsResponse {
  model?: string;
  answers?: Record<string, ChoiceResponse | ScoreResponse | NoulResponse>;
  usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number };
}

/**
 * Jev 经 OpenRouter 接入：decisions 模型不走 chat/completions，
 * 而是 POST {baseURL}/api/alpha/decisions，应答形状与 TypeSafe /v1/systemone 相同。
 * 环境变量：OPENROUTER_API_KEY（必需）/ OPENROUTER_BASE_URL / OPENROUTER_MODEL。
 */
export function createOpenRouterSystemOne(env: NodeJS.ProcessEnv = process.env): SystemOne {
  const apiKey = env['OPENROUTER_API_KEY'];
  if (!apiKey) {
    throw new Error('SYSTEMONE_BACKEND=openrouter 需要配置 OPENROUTER_API_KEY（另支持 OPENROUTER_BASE_URL / OPENROUTER_MODEL）');
  }
  const baseURL = (env['OPENROUTER_BASE_URL'] ?? 'https://openrouter.ai').replace(/\/+$/, '');
  const model = env['OPENROUTER_MODEL'] ?? 'typesafe/jev-1.13';
  const fetchImpl = createProxiedFetch(env);

  return progressiveBackend(async (state, questions, options) => {
      const sdkQuestions: Record<string, unknown> = {};
      for (const [name, q] of Object.entries(questions)) sdkQuestions[name] = toSdkQuestion(q);
      const response = await fetchImpl(`${baseURL}/api/alpha/decisions`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify({ model, state, questions: sdkQuestions }),
        signal: options?.signal ?? AbortSignal.timeout(15000),
      });
      if (!response.ok) throw new Error(`OpenRouter decisions 请求失败（HTTP ${response.status}）`);
      const result = (await response.json()) as DecisionsResponse;
      if (!result.answers) throw new Error('OpenRouter decisions 应答缺少 answers 字段');
      const usage = result.usage
        ? { promptTokens: result.usage.prompt_tokens, completionTokens: result.usage.completion_tokens, totalTokens: result.usage.total_tokens }
        : undefined;
      const answers: Record<string, Answer> = {};
      for (const [name, raw] of Object.entries(result.answers)) answers[name] = toAnswer(raw);
      return { answers, usage, requestedModel: model, resolvedModel: result.model, usageComplete: !!usage };
  });
}
