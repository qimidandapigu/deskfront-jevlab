import { responseBackend } from './request.js';
import type { Answer, ModelRequestDiagnostic, Question, SystemOne, TokenUsage } from './types.js';
import { confidenceFrom } from './types.js';

export class ProviderUnavailableError extends Error {
  constructor(message: string) { super(message); this.name = 'ProviderUnavailableError'; }
}
export class InvalidAnswerError extends Error {
  constructor(message: string) { super(message); this.name = 'InvalidAnswerError'; }
}

export interface DeepSeekOptions {
  analysis?: boolean;
  apiKey: string;
  chatUrl?: string;
  model?: string;
  timeoutMs?: number;
  topLogprobs?: number;
  fetchImpl?: typeof fetch;
  /** 合并进请求体的供应商扩展字段（如火山的 thinking 开关） */
  extraBody?: Record<string, unknown>;
}

/** DeepSeek top_logprobs 上限为 20，单题选项不能超过这个数。 */
const MAX_OPTIONS = 20;
const LABELS = 'ABCDEFGHIJKLMNOPQRST'.split('');

const SYSTEM_PROMPT = [
  '你是一个决策模型。根据 state 和 question 选出最佳选项。',
  '只输出所选选项的字母编号（例如 A），不要输出任何其他字符。',
].join('\n');

interface Labeled {
  question: Question;
  /** 每个候选对应的单 token 字母编号 */
  labels: string[];
  /** 每个候选的原始 key（noul 为 'true' | 'false'） */
  keys: string[];
}

function labelQuestion(question: Question): Labeled {
  if (question.type === 'json') throw new InvalidAnswerError('JSON 计划不能使用选项打分');
  const keys = question.type === 'noul'
    ? ['true', 'false']
    : Object.keys(question.type === 'choice' ? question.criteria : question.levels);
  if (keys.length === 0) throw new InvalidAnswerError('问题没有候选选项');
  if (keys.length > MAX_OPTIONS) {
    throw new InvalidAnswerError(`logprobs 模式单题最多 ${MAX_OPTIONS} 个选项（收到 ${keys.length} 个）`);
  }
  return { question, labels: keys.map((_, i) => LABELS[i]!), keys };
}

function userContent(state: unknown, labeled: Labeled): string {
  const q = labeled.question;
  if (q.type === 'json') throw new InvalidAnswerError('JSON 计划不能使用选项打分');
  const options: Record<string, string> = {};
  if (q.type === 'noul') {
    options['A'] = '陈述为真';
    options['B'] = '陈述为假';
  } else {
    const source = q.type === 'choice' ? q.criteria : q.levels;
    labeled.keys.forEach((key, i) => { options[labeled.labels[i]!] = `${key}: ${source[key]}`; });
  }
  return JSON.stringify({ state, question: { type: q.type, instructions: q.instructions, options } })
    // 引导模型首 token 即输出字母，保证 logprobs 决策位稳定（健谈的模型否则会先写分析）
    + '\n\n直接输出答案字母：';
}

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new InvalidAnswerError('模型返回结构不是对象');
  }
  return value as Record<string, unknown>;
}

/** 把模型输出的 token 归到某个候选字母上，容忍空白、引号、大小写。 */
function matchLabel(token: unknown, labels: string[]): string | null {
  if (typeof token !== 'string') return null;
  const cleaned = token.trim().replace(/^["'`]+|["'`]+$/g, '').toUpperCase();
  return cleaned.length === 1 && labels.includes(cleaned) ? cleaned : null;
}

/** 从头若干输出位置的 top_logprobs 提取候选分布并 softmax 归一化，key 为原始选项 key。
 *  健谈的模型（如火山 DeepSeek v4）首 token 可能不是字母：在前若干位置中取
 *  覆盖候选字母最多（并列取最早）的一个位置作为决策位。 */
function distributionFrom(body: unknown, labeled: Labeled): Record<string, number> {
  const choices = asRecord(body)['choices'];
  const first = Array.isArray(choices) ? asRecord(choices[0]) : asRecord(undefined);
  const logprobs = asRecord(first['logprobs']);
  const content = logprobs['content'];
  if (!Array.isArray(content) || content.length === 0) {
    throw new InvalidAnswerError('响应缺少 top_logprobs（模型端点需支持 logprobs）');
  }

  let best: Map<string, number> | null = null;
  for (const pos of content.slice(0, 12)) {
    const top = asRecord(pos)['top_logprobs'];
    if (!Array.isArray(top)) continue;
    const found = new Map<string, number>();
    for (const entry of top) {
      const record = asRecord(entry);
      const label = matchLabel(record['token'], labeled.labels);
      const logprob = record['logprob'];
      if (label === null || typeof logprob !== 'number' || !Number.isFinite(logprob) || logprob <= -9999) continue;
      if (!found.has(label) || logprob > found.get(label)!) found.set(label, logprob);
    }
    if (found.size === labeled.labels.length) { best = found; break; }
    if (!best || found.size > best.size) best = found;
  }
  if (!best || best.size === 0) throw new InvalidAnswerError('top_logprobs 中没有任何候选字母');

  const max = Math.max(...best.values());
  const weights = new Map([...best].map(([label, lp]) => [label, Math.exp(lp - max)]));
  const total = [...weights.values()].reduce((a, b) => a + b, 0);
  const probabilities: Record<string, number> = {};
  labeled.keys.forEach((key, i) => {
    probabilities[key] = (weights.get(labeled.labels[i]!) ?? 0) / total;
  });
  return probabilities;
}

function toAnswer(question: Question, probabilities: Record<string, number>): Answer {
  const keys = Object.keys(probabilities);
  const topKey = keys.reduce((best, key) => probabilities[key]! > probabilities[best]! ? key : best, keys[0]!);
  if (question.type === 'choice') {
    return { type: 'choice', choice: topKey, probabilities, confidence: confidenceFrom(probabilities) };
  }
  if (question.type === 'score') {
    const score = keys.reduce((sum, level) => sum + Number(level) * probabilities[level]!, 0);
    return { type: 'score', score, probabilities, confidence: confidenceFrom(probabilities) };
  }
  return { type: 'noul', noul: probabilities['true']!, confidence: confidenceFrom(probabilities) };
}

function usageFrom(body: unknown): TokenUsage | undefined {
  if (typeof body !== 'object' || body === null) return undefined;
  const u = (body as Record<string, unknown>)['usage'];
  if (typeof u !== 'object' || u === null) return undefined;
  const r = u as Record<string, unknown>;
  const prompt = typeof r['prompt_tokens'] === 'number' ? r['prompt_tokens'] : undefined;
  const completion = typeof r['completion_tokens'] === 'number' ? r['completion_tokens'] : undefined;
  const total = typeof r['total_tokens'] === 'number' ? r['total_tokens'] : undefined;
  const details = r['completion_tokens_details'];
  const detailRecord = typeof details === 'object' && details !== null ? details as Record<string, unknown> : undefined;
  const reportedReasoning = detailRecord?.['reasoning_tokens'] ?? r['reasoning_tokens'];
  const reasoning = typeof reportedReasoning === 'number' ? reportedReasoning : undefined;
  if (prompt === undefined && completion === undefined && total === undefined && reasoning === undefined) return undefined;
  return { promptTokens: prompt, completionTokens: completion, totalTokens: total,
    ...(reasoning === undefined ? {} : { reasoningTokens: reasoning }) };
}

function mergeUsage(a: TokenUsage | undefined, b: TokenUsage | undefined): TokenUsage | undefined {
  if (!a) return b;
  if (!b) return a;
  const sum = (x?: number, y?: number) => (x === undefined && y === undefined ? undefined : (x ?? 0) + (y ?? 0));
  return {
    promptTokens: sum(a.promptTokens, b.promptTokens),
    completionTokens: sum(a.completionTokens, b.completionTokens),
    totalTokens: sum(a.totalTokens, b.totalTokens),
    reasoningTokens: sum(a.reasoningTokens, b.reasoningTokens),
  };
}

function diagnostic(provider: string, requestBody: string, started: number, headersAt: number, bodyAt: number, finishReason: unknown, upstreamProvider?: unknown): ModelRequestDiagnostic {
  return { provider, requestBytes: Buffer.byteLength(requestBody, 'utf8'),
    headersElapsedMs: Math.max(0, Math.round(headersAt - started)),
    bodyElapsedMs: Math.max(0, Math.round(bodyAt - started)),
    ...(typeof upstreamProvider === 'string' ? { upstreamProvider } : {}),
    ...(typeof finishReason === 'string' ? { finishReason } : {}) };
}

export function createDeepSeekSystemOne(options: DeepSeekOptions): SystemOne {
  const url = new URL(options.chatUrl ?? 'https://api.deepseek.com/chat/completions');
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(url.hostname))) {
    throw new Error('模型地址必须使用 HTTPS（本机测试除外）');
  }
  if (url.username || url.password) throw new Error('模型地址不能包含凭据');
  const model = options.model ?? 'deepseek-chat';
  const provider = url.hostname;
  const timeoutMs = options.timeoutMs ?? (options.analysis ? 120000 : 30000);
  const topLogprobs = Math.min(options.topLogprobs ?? MAX_OPTIONS, MAX_OPTIONS);
  const fetchImpl = options.fetchImpl ?? fetch;

  async function call(state: unknown, labeled: Labeled, signal?: AbortSignal): Promise<{ probabilities: Record<string, number>; usage?: TokenUsage; resolvedModel?: string; diagnostic: ModelRequestDiagnostic }> {
    const timeout = new AbortController();
    const timer = setTimeout(() => timeout.abort(new ProviderUnavailableError('模型服务响应超时')), timeoutMs);
    try {
      const requestBody = JSON.stringify({
        model,
        messages: [
          { role: 'system', content: SYSTEM_PROMPT },
          { role: 'user', content: userContent(state, labeled) },
        ],
        max_tokens: 8,
        temperature: 1,
        top_p: 1,
        logprobs: true,
        top_logprobs: topLogprobs,
        ...options.extraBody,
      });
      const started = performance.now();
      const response = await fetchImpl(url, {
        method: 'POST', redirect: 'manual', signal: signal ? AbortSignal.any([signal, timeout.signal]) : timeout.signal,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${options.apiKey}` },
        body: requestBody,
      });
      const headersAt = performance.now();
      if (!response.ok) throw new ProviderUnavailableError(`模型服务暂时不可用（HTTP ${response.status}）`);
      const bodyText = await response.text();
      const bodyAt = performance.now();
      const body: unknown = JSON.parse(bodyText);
      const first = (body as { choices?: { finish_reason?: unknown }[] })?.choices?.[0];
      return { probabilities: distributionFrom(body, labeled), usage: usageFrom(body), resolvedModel: typeof (body as { model?: unknown })?.model === 'string' ? (body as { model: string }).model : undefined,
        diagnostic: diagnostic(provider, requestBody, started, headersAt, bodyAt, first?.finish_reason,
          (body as { provider?: unknown })?.provider) };
    } catch (error) {
      if (error instanceof InvalidAnswerError || error instanceof ProviderUnavailableError) throw error;
      if (error instanceof SyntaxError) throw new InvalidAnswerError('模型返回不是合法 JSON');
      throw new ProviderUnavailableError('模型服务暂时不可用');
    } finally {
      clearTimeout(timer);
    }
  }

  async function askQuestion(state: unknown, question: Question, signal?: AbortSignal): Promise<{ answer: Answer; usage?: TokenUsage; usageComplete: boolean; resolvedModel?: string; diagnostic: ModelRequestDiagnostic }> {
    if (question.type === 'json') {
      const timeout = AbortSignal.timeout(timeoutMs);
      const requestBody = JSON.stringify({ ...options.extraBody, model, messages: [
        { role: 'system', content: question.systemInstructions ?? '你是战术指挥官。根据当前真实战况自主制定可执行计划，只输出一个 JSON 对象。不得把尚未执行的动作当作事实。' },
        { role: 'user', content: JSON.stringify({ state, instructions: question.instructions }) },
      ], ...(question.maxOutputTokens !== undefined ? { max_tokens: Math.max(64, Math.min(2200, Math.floor(question.maxOutputTokens))) }
        : options.analysis ? {} : { max_tokens: 2200 }), temperature: .4, response_format: { type: 'json_object' } });
      const started = performance.now();
      const response = await fetchImpl(url, {
        method: 'POST', redirect: 'manual', signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${options.apiKey}` },
        body: requestBody,
      });
      const headersAt = performance.now();
      if (!response.ok) throw new ProviderUnavailableError(`模型服务暂时不可用（HTTP ${response.status}）`);
      const bodyText = await response.text();
      const bodyAt = performance.now();
      const body = JSON.parse(bodyText) as { choices?: { finish_reason?: string; message?: { content?: string } }[]; model?: string; provider?: string };
      if (body.choices?.[0]?.finish_reason === 'length') throw new InvalidAnswerError('指挥计划输出被截断');
      let value: unknown;
      try { value = JSON.parse(body.choices?.[0]?.message?.content ?? ''); } catch { throw new InvalidAnswerError('指挥计划不是合法 JSON'); }
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw new InvalidAnswerError('指挥计划必须是对象');
      const usage = usageFrom(body);
      return { answer: { type: 'json', value: value as Record<string, unknown> }, usage, usageComplete: !!usage, resolvedModel: body.model,
        diagnostic: diagnostic(provider, requestBody, started, headersAt, bodyAt, body.choices?.[0]?.finish_reason, body.provider) };
    }
    const labeled = labelQuestion(question);
    let result: { probabilities: Record<string, number>; usage?: TokenUsage; resolvedModel?: string; diagnostic: ModelRequestDiagnostic };
    let usageComplete = true;
    try {
      result = await call(state, labeled, signal);
    } catch (error) {
      if (!(error instanceof InvalidAnswerError)) throw error;
      signal?.throwIfAborted();
      usageComplete = false;
      result = await call(state, labeled, signal);
    }
    return { answer: toAnswer(question, result.probabilities), usage: result.usage, usageComplete: usageComplete && !!result.usage, resolvedModel: result.resolvedModel, diagnostic: result.diagnostic };
  }

  return responseBackend(async (state, questions, requestOptions) => {
      const entries = await Promise.all(
        Object.entries(questions).map(async ([key, question]) =>
          [key, await askQuestion(state, question, requestOptions?.signal)] as const),
      );
      const usage = entries.reduce<TokenUsage | undefined>((acc, [, r]) => mergeUsage(acc, r.usage), undefined);
      const models = [...new Set(entries.map(([, r]) => r.resolvedModel))];
      return { resolvedModel: models.length === 1 ? models[0] : undefined, answers: Object.fromEntries(entries.map(([key, r]) => [key, r.answer])), usage, requestedModel: model, usageComplete: entries.every(([, r]) => r.usageComplete),
        diagnostics: entries.map(([, r]) => r.diagnostic) };
  });
}
