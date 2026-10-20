import { responseBackend } from './request.js';
import { createHash } from 'node:crypto';
import type { Answer, JsonAnswerDiagnostic, ModelRequestDiagnostic, Question, SystemOne, TokenUsage } from './types.js';
import { confidenceFrom } from './types.js';
import { compileReportSchema, parseReportArguments, type ReportSchema } from './strict-report-schema.js';

export const EXPERIENCE_REPORT_TOOL = 'submit_experience_analysis';

export class ProviderUnavailableError extends Error {
  constructor(message: string) { super(message); this.name = 'ProviderUnavailableError'; }
}
export class InvalidAnswerError extends Error {
  constructor(message: string, readonly diagnostic?: JsonAnswerDiagnostic) { super(message); this.name = 'InvalidAnswerError'; }
}

/** Explicit error transport allowlist. Never spread arbitrary provider errors. */
export function jsonAnswerErrorDiagnostic(error: unknown): JsonAnswerDiagnostic | undefined {
  if (!(error instanceof InvalidAnswerError) || !error.diagnostic) return undefined;
  const d = error.diagnostic;
  return { schema: d.schema, kind: d.kind, provider: d.provider, requestBytes: d.requestBytes,
    ...(d.outputMode ? { outputMode: d.outputMode, responseSchemaSha256: d.responseSchemaSha256, providerSchemaSha256: d.providerSchemaSha256 } : {}),
    headersElapsedMs: d.headersElapsedMs, bodyElapsedMs: d.bodyElapsedMs,
    ...(d.upstreamProvider === undefined ? {} : { upstreamProvider: d.upstreamProvider }),
    ...(d.finishReason === undefined ? {} : { finishReason: d.finishReason }),
    requestedModel: d.requestedModel, ...(d.resolvedModel === undefined ? {} : { resolvedModel: d.resolvedModel }),
    responseBytes: d.responseBytes, responseSha256: d.responseSha256, contentType: d.contentType,
    ...(d.contentChars === undefined ? {} : { contentChars: d.contentChars }),
    ...(d.contentBytes === undefined ? {} : { contentBytes: d.contentBytes }),
    ...(d.contentSha256 === undefined ? {} : { contentSha256: d.contentSha256 }),
    ...(d.trimmedChars === undefined ? {} : { trimmedChars: d.trimmedChars }),
    hasMessage: d.hasMessage, hasToolCalls: d.hasToolCalls, hasRefusal: d.hasRefusal, fencedContent: d.fencedContent,
    ...(d.usage === undefined ? {} : { usage: { promptTokens: d.usage.promptTokens, completionTokens: d.usage.completionTokens,
      totalTokens: d.usage.totalTokens, reasoningTokens: d.usage.reasoningTokens } }),
    ...(d.contentPreview === undefined ? {} : { contentPreview: { prefix: d.contentPreview.prefix,
      suffix: d.contentPreview.suffix, truncated: d.contentPreview.truncated } }),
    ...(d.jsonSyntax === undefined ? {} : { jsonSyntax: { unclosedContainers: d.jsonSyntax.unclosedContainers,
      unterminatedString: d.jsonSyntax.unterminatedString, trailingEscape: d.jsonSyntax.trailingEscape,
      unexpectedClose: d.jsonSyntax.unexpectedClose, trailingContent: d.jsonSyntax.trailingContent } }) };
}

function safeDiagnosticText(content: string, apiKey: string): string {
  return (apiKey ? content.split(apiKey).join('[credential redacted]') : content)
    .replace(/\b(?:sk-[A-Za-z0-9_-]{8,}|apikey_[A-Za-z0-9_-]{12,})\b/g, '[credential redacted]')
    .replace(/\bBearer\s+[A-Za-z0-9._-]+/gi, 'Bearer [credential redacted]');
}

function answerPreview(content: string, apiKey: string): NonNullable<JsonAnswerDiagnostic['contentPreview']> {
  const safe = safeDiagnosticText(content, apiKey);
  return { prefix: safe.slice(0, 320), suffix: safe.length > 320 ? safe.slice(-160) : '', truncated: safe.length > 480 };
}

function jsonSyntax(text: string): NonNullable<JsonAnswerDiagnostic['jsonSyntax']> {
  const stack: string[] = [];
  let quoted = false, escape = false, unexpectedClose = false, ended = false, trailingContent = false;
  for (const char of text) {
    if (ended && !/\s/.test(char)) trailingContent = true;
    if (quoted) {
      if (escape) escape = false;
      else if (char === '\\') escape = true;
      else if (char === '"') quoted = false;
    } else if (char === '"') quoted = true;
    else if (char === '{' || char === '[') stack.push(char);
    else if (char === '}' || char === ']') {
      if (stack.pop() !== (char === '}' ? '{' : '[')) unexpectedClose = true;
      if (!stack.length) ended = true;
    }
  }
  return { unclosedContainers: stack.length, unterminatedString: quoted, trailingEscape: escape, unexpectedClose, trailingContent };
}

function jsonAnswer(bodyText: string, transport: ModelRequestDiagnostic, requestedModel: string, apiKey: string, strict?: ReportSchema):
  { value: Record<string, unknown>; body: Record<string, unknown> } {
  const sha = (text: string) => createHash('sha256').update(text, 'utf8').digest('hex');
  let body: unknown;
  let kind: JsonAnswerDiagnostic['kind'] = 'invalid_response_json';
  let first: Record<string, unknown> | undefined, message: Record<string, unknown> | undefined, content: unknown, parsedText: string | undefined;
  const record = (v: unknown): Record<string, unknown> | undefined => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : undefined;
  const fail = (text: string): never => {
    const envelope = record(body);
    const trimmed = typeof content === 'string' ? content.trim() : undefined;
    const usage = usageFrom(body);
    throw new InvalidAnswerError(text, { ...transport, schema: 'quickplay-json-answer-error/v1', kind,
      requestedModel: safeDiagnosticText(requestedModel, apiKey).slice(0, 160),
      ...(typeof envelope?.model === 'string' ? { resolvedModel: safeDiagnosticText(envelope.model, apiKey).slice(0, 160) } : {}),
      ...(typeof first?.finish_reason === 'string' ? { finishReason: safeDiagnosticText(first.finish_reason, apiKey).slice(0, 80) } : {}),
      ...(typeof envelope?.provider === 'string' ? { upstreamProvider: safeDiagnosticText(envelope.provider, apiKey).slice(0, 160) } : {}),
      responseBytes: Buffer.byteLength(bodyText, 'utf8'), responseSha256: sha(bodyText),
      contentType: content === null ? 'null' : Array.isArray(content) ? 'array' : typeof content,
      ...(typeof content === 'string' ? { contentChars: content.length, contentBytes: Buffer.byteLength(content, 'utf8'),
        contentSha256: sha(content), trimmedChars: trimmed!.length, contentPreview: answerPreview(content, apiKey) } : {}),
      hasMessage: !!message, hasToolCalls: Array.isArray(message?.tool_calls) && message.tool_calls.length > 0,
      hasRefusal: typeof message?.refusal === 'string' && message.refusal.length > 0,
      fencedContent: typeof trimmed === 'string' && trimmed.startsWith('```'), ...(usage ? { usage } : {}),
      ...(kind === 'malformed_content' && parsedText !== undefined ? { jsonSyntax: jsonSyntax(parsedText) } : {}) });
  };
  try { body = JSON.parse(bodyText); } catch { fail('模型响应正文不是合法 JSON'); }
  const envelope = record(body);
  first = record(Array.isArray(envelope?.choices) ? envelope.choices[0] : undefined);
  message = record(first?.message); content = message?.content;
  if (strict) {
    if (typeof envelope?.id !== 'string' || !envelope.id || typeof envelope.model !== 'string' || !envelope.model ||
        !Array.isArray(envelope.choices) || envelope.choices.length !== 1 || !first || first.index !== 0) {
      kind = 'strict_tool_contract'; fail('严格体验报告须恰好一个完整响应');
    }
    const choice = first!;
    if (choice.finish_reason === 'length') { kind = 'truncated_content'; fail('严格体验报告输出被截断'); }
    if (!message || message.role !== 'assistant') { kind = 'missing_message'; fail('严格体验报告缺少 assistant 消息'); }
    const reportMessage = message!;
    if (reportMessage.refusal !== undefined && reportMessage.refusal !== null && reportMessage.refusal !== '') { kind = 'refused_content'; fail('模型拒绝输出严格体验报告'); }
    if (choice.finish_reason !== 'tool_calls') { kind = 'unsupported_finish_reason'; fail('严格体验报告未以工具参数完整结束'); }
    const calls = reportMessage.tool_calls;
    if (!Array.isArray(calls) || calls.length !== 1 || !Object.hasOwn(reportMessage, 'content') ||
        !(content === null || typeof content === 'string' && !content.trim())) {
      kind = 'strict_tool_contract'; fail('严格体验报告须仅返回一个指定报告工具');
    }
    const call = record((calls as unknown[])[0]), fn = record(call?.function);
    if (!call || call.type !== 'function' || typeof call.id !== 'string' || !call.id ||
        !fn || fn.name !== EXPERIENCE_REPORT_TOOL || typeof fn.arguments !== 'string') {
      kind = 'strict_tool_contract'; fail('严格体验报告工具名称或参数不合法');
    }
    const args = fn!.arguments as string;
    content = args; parsedText = args;
    let value: Record<string, unknown>;
    try { value = parseReportArguments(args); }
    catch { kind = 'malformed_content'; fail('严格体验报告参数不是完整且唯一键的 JSON 对象'); }
    const violation = strict.check(value!);
    if (violation) { kind = 'strict_schema_mismatch'; fail('严格体验报告不符合声明结构：' + violation.slice(0, 160)); }
    return { value: value!, body: envelope! };
  }
  if (first?.finish_reason === 'length') { kind = 'truncated_content'; fail('指挥计划输出被截断'); }
  if (typeof message?.refusal === 'string' && message.refusal.length > 0) { kind = 'refused_content'; fail('模型拒绝输出 JSON 计划'); }
  if (Array.isArray(message?.tool_calls) && message.tool_calls.length > 0) { kind = 'tool_call_content'; fail('JSON 计划意外返回工具调用'); }
  if (first?.finish_reason !== undefined && first.finish_reason !== null && first.finish_reason !== 'stop') {
    kind = 'unsupported_finish_reason'; fail('JSON 计划未正常结束');
  }
  if (!message) { kind = 'missing_message'; fail('JSON 计划缺少模型消息'); }
  if (typeof content !== 'string') { kind = 'unexpected_content_type'; fail('JSON 计划正文必须是文本'); }
  let text = (content as string).trim();
  if (!text) { kind = 'empty_content'; fail('JSON 计划正文为空'); }
  // One complete fence is presentation only; no arbitrary brace extraction,
  // prefix/suffix prose, syntax repair, or incomplete-result acceptance.
  const fence = /^```(?:json)?[\t ]*\r?\n([\s\S]*?)\r?\n```$/i.exec(text);
  if (fence) text = fence[1]!.trim();
  parsedText = text;
  let value: unknown;
  try { value = JSON.parse(text); } catch { kind = 'malformed_content'; fail('指挥计划不是合法 JSON'); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) { kind = 'non_object_content'; fail('指挥计划必须是对象'); }
  return { value: value as Record<string, unknown>, body: envelope! };
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
      if (question.responseMode !== undefined && question.responseMode !== 'strict_tool') throw new InvalidAnswerError('未知 JSON 输出模式');
      if (question.responseSchema !== undefined && question.responseMode !== 'strict_tool') throw new InvalidAnswerError('严格报告 schema 必须显式启用 strict_tool');
      const strictMode = question.responseMode === 'strict_tool';
      const local = ['127.0.0.1', 'localhost'].includes(url.hostname);
      if (strictMode && (!options.analysis || provider !== 'api.deepseek.com' && !local)) throw new InvalidAnswerError('严格体验报告仅支持官方 DeepSeek 分析线路');
      let strict: ReportSchema | undefined;
      if (strictMode) {
        try { strict = compileReportSchema(question.responseSchema); }
        catch (error) { throw new InvalidAnswerError(error instanceof Error ? error.message : 'invalid-strict-report-schema'); }
        if (Object.keys(options.extraBody ?? {}).some(key => ['stop', 'tools', 'tool_choice'].includes(key))) throw new InvalidAnswerError('严格体验报告不接受额外停止符或工具配置');
        if (question.maxOutputTokens !== undefined && (!Number.isFinite(question.maxOutputTokens) || question.maxOutputTokens < 64 || question.maxOutputTokens > 2200)) throw new InvalidAnswerError('严格体验报告输出预算不合法');
      }
      const timeout = AbortSignal.timeout(timeoutMs);
      const { temperature: configuredTemperature, ...extraBody } = options.extraBody ?? {};
      const temperature = Object.hasOwn(options.extraBody ?? {}, 'temperature') ? configuredTemperature : .4;
      const strictFields = new Set(['response_format', 'stream', 'n']);
      const extensions = strictMode ? Object.fromEntries(Object.entries(extraBody).filter(([key]) => !strictFields.has(key))) : extraBody;
      const requestBody = JSON.stringify({ ...extensions, model, messages: [
        { role: 'system', content: question.systemInstructions ?? '你是战术指挥官。根据当前真实战况自主制定可执行计划，只输出一个 JSON 对象。不得把尚未执行的动作当作事实。' },
        { role: 'user', content: JSON.stringify({ state, instructions: question.instructions }) },
      ], ...(question.maxOutputTokens !== undefined ? { max_tokens: Math.max(64, Math.min(2200, Math.floor(question.maxOutputTokens))) }
        : strictMode ? { max_tokens: 1800 } : options.analysis ? {} : { max_tokens: 2200 }), ...(temperature == null ? {} : { temperature }),
        ...(strict ? { thinking: { type: 'disabled' }, stream: false, n: 1,
          tools: [{ type: 'function', function: { name: EXPERIENCE_REPORT_TOOL, strict: true,
            description: '提交本次完整体验分析报告的数据；不执行游戏动作。', parameters: strict.providerSchema } }],
          tool_choice: { type: 'function', function: { name: EXPERIENCE_REPORT_TOOL } } }
          : { response_format: { type: 'json_object' } }) });
      const requestUrl = new URL(url);
      if (strict) { requestUrl.pathname = '/beta/chat/completions'; requestUrl.search = ''; requestUrl.hash = ''; }
      const started = performance.now();
      const response = await fetchImpl(requestUrl, {
        method: 'POST', redirect: 'manual', signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${options.apiKey}` },
        body: requestBody,
      });
      const headersAt = performance.now();
      if (!response.ok) throw new ProviderUnavailableError(strict ? `严格体验报告接口不可用（HTTP ${response.status}）；未回退普通 JSON` : `模型服务暂时不可用（HTTP ${response.status}）`);
      const bodyText = await response.text();
      const bodyAt = performance.now();
      const outputDiagnostic = strict ? { outputMode: 'strict_tool' as const, responseSchemaSha256: strict.responseSchemaSha256, providerSchemaSha256: strict.providerSchemaSha256 } : {};
      const parsed = jsonAnswer(bodyText, { ...diagnostic(provider, requestBody, started, headersAt, bodyAt, undefined), ...outputDiagnostic }, model, options.apiKey, strict);
      const body = parsed.body as { choices?: { finish_reason?: string }[]; model?: string; provider?: string };
      const value = parsed.value;
      const usage = usageFrom(body);
      return { answer: { type: 'json', value: value as Record<string, unknown> }, usage, usageComplete: !!usage, resolvedModel: body.model,
        diagnostic: { ...diagnostic(provider, requestBody, started, headersAt, bodyAt, body.choices?.[0]?.finish_reason, body.provider), ...outputDiagnostic } };
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
        Object.entries(questions).map(async ([key, question]) => {
          const result = await askQuestion(state, question, requestOptions?.signal);
          requestOptions?.onAnswer?.(key, result.answer);
          return [key, result] as const;
        }),
      );
      const usage = entries.reduce<TokenUsage | undefined>((acc, [, r]) => mergeUsage(acc, r.usage), undefined);
      const models = [...new Set(entries.map(([, r]) => r.resolvedModel))];
      return { resolvedModel: models.length === 1 ? models[0] : undefined, answers: Object.fromEntries(entries.map(([key, r]) => [key, r.answer])), usage, requestedModel: model, usageComplete: entries.every(([, r]) => r.usageComplete),
        diagnostics: entries.map(([, r]) => r.diagnostic) };
  });
}
