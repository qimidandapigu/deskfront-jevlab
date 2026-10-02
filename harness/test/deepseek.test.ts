import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  createDeepSeekSystemOne, InvalidAnswerError, ProviderUnavailableError,
} from '../src/systemone/deepseek.js';
import type { Question } from '../src/systemone/types.js';

interface CapturedRequest { url: unknown; body: Record<string, unknown>; }

function fakeFetch(payloads: unknown[], captured: CapturedRequest[], status = 200): typeof fetch {
  return (async (url: unknown, init: { body?: unknown }) => {
    captured.push({ url, body: JSON.parse(String(init?.body)) });
    const payload = payloads.length > 1 ? payloads.shift() : payloads[0];
    return new Response(JSON.stringify(payload), { status });
  }) as unknown as typeof fetch;
}

function chatResponse(topLogprobs: [string, number][]): unknown {
  return {
    choices: [{
      message: { content: topLogprobs[0]?.[0] ?? '' },
      logprobs: {
        content: [{
          token: topLogprobs[0]?.[0] ?? '',
          logprob: topLogprobs[0]?.[1] ?? -20,
          top_logprobs: topLogprobs.map(([token, logprob]) => ({ token, logprob, bytes: null })),
        }],
      },
    }],
  };
}

const CHOICE: Question = {
  type: 'choice', instructions: '选下一步', criteria: { U: '向上', D: '向下', L: '向左' },
};

test('commentary JSON can use its own system role without changing tactical defaults', async () => {
  const captured: CapturedRequest[] = [];
  const backend = createDeepSeekSystemOne({ apiKey: 'test', fetchImpl: fakeFetch([
    { choices: [{ message: { content: '{"text":"实际战况"}' } }] },
  ], captured) });
  await backend.ask({}, { commentary: { type: 'json', instructions: '生成解说', systemInstructions: '只播报真实战况，不指挥部队', maxOutputTokens: 240 } });
  assert.equal((captured[0]!.body.messages as { content: string }[])[0]!.content, '只播报真实战况，不指挥部队');
  assert.equal(captured[0]!.body.max_tokens, 240);
  await backend.ask({}, { plan: { type: 'json', instructions: '生成计划' } });
  assert.match((captured[1]!.body.messages as { content: string }[])[0]!.content, /战术指挥官/);
  assert.equal(captured[1]!.body.max_tokens, 2200);
});

test('generated plan uses JSON completion, not logprob choice scoring', async () => {
  const captured: CapturedRequest[]=[];
  const backend=createDeepSeekSystemOne({apiKey:'test',fetchImpl:fakeFetch([{model:'test-model',choices:[{finish_reason:'stop',message:{content:'{"intent":"hold","tasks":{}}'}}],usage:{prompt_tokens:4,completion_tokens:12,total_tokens:16}}],captured)});
  const result=await backend.request!({}, {plan:{type:'json',instructions:'生成计划'}});
  assert.deepEqual(result.answers.plan,{type:'json',value:{intent:'hold',tasks:{}}});
  assert.equal(captured[0]!.body.logprobs,undefined);
  assert.equal(captured[0]!.body.max_tokens,2200);
  assert.equal(result.usage?.totalTokens,16);
});

test('JSON analyst response reports safe transport timing, request size, finish reason and reasoning tokens', async () => {
  const captured: CapturedRequest[] = [];
  const secret = 'never-log-this-api-key';
  const prompt = 'PRIVATE_TACTICAL_PROMPT_机密';
  const payload = { model: 'provider-model', choices: [{ finish_reason: 'stop', message: { content: '{"intent":"hold"}' } }],
    usage: { prompt_tokens: 200, completion_tokens: 30, total_tokens: 230, completion_tokens_details: { reasoning_tokens: 7 } } };
  const backend = createDeepSeekSystemOne({ apiKey: secret, fetchImpl: fakeFetch([payload], captured) });
  const result = await backend.request!({ private: prompt }, { plan: { type: 'json', instructions: 'decide' } });
  assert.equal(result.usage?.reasoningTokens, 7);
  assert.equal(result.diagnostics?.length, 1);
  const diagnostic = result.diagnostics![0]!;
  assert.equal(diagnostic.provider, 'api.deepseek.com');
  assert.equal(diagnostic.requestBytes, Buffer.byteLength(JSON.stringify(captured[0]!.body), 'utf8'));
  assert.equal(diagnostic.finishReason, 'stop');
  assert.ok(diagnostic.headersElapsedMs >= 0);
  assert.ok(diagnostic.bodyElapsedMs >= diagnostic.headersElapsedMs);
  const safe = JSON.stringify(result.diagnostics);
  assert.ok(!safe.includes(secret));
  assert.ok(!safe.includes(prompt));
  assert.ok(!safe.includes('Authorization'));
});

test('response body timing includes delayed download after headers', async () => {
  const payload = JSON.stringify({ choices: [{ finish_reason: 'stop', message: { content: '{"intent":"hold"}' } }] });
  const slowFetch = (async () => {
    await new Promise(resolve => setTimeout(resolve, 12));
    return new Response(new ReadableStream<Uint8Array>({
      start(controller) { setTimeout(() => { controller.enqueue(new TextEncoder().encode(payload)); controller.close(); }, 20); },
    }));
  }) as typeof fetch;
  const backend = createDeepSeekSystemOne({ apiKey: 'test', fetchImpl: slowFetch });
  const result = await backend.request!({}, { plan: { type: 'json', instructions: 'decide' } });
  const timing = result.diagnostics![0]!;
  assert.ok(timing.headersElapsedMs >= 8, `headers ${timing.headersElapsedMs}ms`);
  assert.ok(timing.bodyElapsedMs - timing.headersElapsedMs >= 12, `body ${timing.bodyElapsedMs}ms, headers ${timing.headersElapsedMs}ms`);
});

test('generated plan rejects truncated JSON instead of installing partial tasks', async () => {
  const backend=createDeepSeekSystemOne({apiKey:'test',fetchImpl:fakeFetch([{choices:[{finish_reason:'length',message:{content:'{}'}}]}],[])});
  await assert.rejects(backend.ask({}, {plan:{type:'json',instructions:'生成计划'}}),InvalidAnswerError);
});

test('request returns provider model and usage together; aliases are not invented resolutions', async () => {
  const payload = { ...(chatResponse([['A', -.1], ['B', -3]]) as object), model: 'provider-build-42', usage: { prompt_tokens: 8, completion_tokens: 1, total_tokens: 9 } };
  const backend = createDeepSeekSystemOne({ apiKey: 'test', model: 'configured-alias', fetchImpl: fakeFetch([payload], []) });
  const response = await backend.request!({}, { action: CHOICE });
  assert.equal(response.requestedModel, 'configured-alias'); assert.equal(response.resolvedModel, 'provider-build-42');
  assert.equal(response.usage?.totalTokens, 9); assert.equal(response.usageComplete, true);
});

test('choice: 从 top_logprobs 归一化出真实分布，choice 为 argmax', async () => {
  const captured: CapturedRequest[] = [];
  const backend = createDeepSeekSystemOne({
    apiKey: 'k', fetchImpl: fakeFetch([chatResponse([['A', -0.05], ['B', -2.5], ['C', -4]])], captured),
  });
  const answers = await backend.ask({ board: 'x' }, { action: CHOICE });
  const action = answers['action'];
  assert.ok(action && action.type === 'choice');
  assert.equal(action.choice, 'U');
  const sum = Object.values(action.probabilities).reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(sum - 1) < 1e-9);
  assert.ok(action.probabilities['U']! > 0.8, `U 概率应 > 0.8，实际 ${action.probabilities['U']}`);
  assert.ok(action.confidence > 0.5);
});

test('choice: 请求体走 logprobs 路线（logprobs/top_logprobs/temperature=1，无 json_object）', async () => {
  const captured: CapturedRequest[] = [];
  const backend = createDeepSeekSystemOne({
    apiKey: 'k', fetchImpl: fakeFetch([chatResponse([['A', -0.1], ['B', -3]])], captured),
  });
  await backend.ask({}, { m: { type: 'choice', instructions: 'x', criteria: { a: '甲', b: '乙' } } });
  const body = captured[0]!.body;
  assert.equal(body['logprobs'], true);
  assert.equal(body['top_logprobs'], 20);
  assert.equal(body['temperature'], 1);
  assert.equal(body['top_p'], 1);
  assert.equal(body['response_format'], undefined);
  assert.ok(Number(body['max_tokens']) <= 16);
});

test('choice: 候选字母带空白和引号的 token 也能匹配', async () => {
  const backend = createDeepSeekSystemOne({
    apiKey: 'k', fetchImpl: fakeFetch([chatResponse([[' "B"', -0.01], [' A ', -3]])], []),
  });
  const answers = await backend.ask({}, { m: { type: 'choice', instructions: 'x', criteria: { a: '甲', b: '乙' } } });
  const m = answers['m'];
  assert.ok(m && m.type === 'choice');
  assert.equal(m.choice, 'b');
  assert.ok(m.probabilities['b']! > 0.9);
});

test('noul: 真/假两候选归一化后为真的概率', async () => {
  const backend = createDeepSeekSystemOne({
    apiKey: 'k', fetchImpl: fakeFetch([chatResponse([['A', -0.2], ['B', -1.5]])], []),
  });
  const answers = await backend.ask({}, { stuck: { type: 'noul', instructions: '是否卡死' } });
  const stuck = answers['stuck'];
  assert.ok(stuck && stuck.type === 'noul');
  const expected = Math.exp(-0.2) / (Math.exp(-0.2) + Math.exp(-1.5));
  assert.ok(Math.abs(stuck.noul - expected) < 1e-9);
});

test('score: 期望分值等于等级按概率加权', async () => {
  const backend = createDeepSeekSystemOne({
    apiKey: 'k', fetchImpl: fakeFetch([chatResponse([['A', 0], ['D', -20]])], []),
  });
  const answers = await backend.ask({}, {
    risk: { type: 'score', instructions: '风险', levels: { '0': '无', '3': '高' } },
  });
  const risk = answers['risk'];
  assert.ok(risk && risk.type === 'score');
  assert.ok(risk.score < 0.01, `score 应接近 0，实际 ${risk.score}`);
});

test('多问题：一次 ask 内并发，每题独立分布', async () => {
  const backend = createDeepSeekSystemOne({
    apiKey: 'k',
    fetchImpl: fakeFetch([chatResponse([['A', -0.1], ['B', -3]]), chatResponse([['B', -0.1], ['A', -3]])], []),
  });
  const answers = await backend.ask({}, { q1: CHOICE, q2: CHOICE });
  assert.equal(answers['q1']?.type === 'choice' && answers['q1'].choice, 'U');
  assert.equal(answers['q2']?.type === 'choice' && answers['q2'].choice, 'D');
});

test('无候选字母时重试一次后仍无效则抛 InvalidAnswerError', async () => {
  const captured: CapturedRequest[] = [];
  const backend = createDeepSeekSystemOne({
    apiKey: 'k', fetchImpl: fakeFetch([chatResponse([['好', -0.1], ['的', -0.2]])], captured),
  });
  await assert.rejects(backend.ask({}, { m: CHOICE }), InvalidAnswerError);
  assert.equal(captured.length, 2, '应该重试一次，共两次请求');
});

test('选项超过 20 个直接拒绝（top_logprobs 上限）', async () => {
  const criteria: Record<string, string> = {};
  for (let i = 0; i < 21; i++) criteria[`k${i}`] = `选项${i}`;
  const backend = createDeepSeekSystemOne({ apiKey: 'k', fetchImpl: fakeFetch([], []) });
  await assert.rejects(
    backend.ask({}, { m: { type: 'choice', instructions: 'x', criteria } }),
    /最多 20 个选项/,
  );
});

test('HTTP 错误抛 ProviderUnavailableError', async () => {
  const backend = createDeepSeekSystemOne({
    apiKey: 'k', fetchImpl: fakeFetch([{ error: 'x' }], [], 500),
  });
  await assert.rejects(backend.ask({}, { m: CHOICE }), ProviderUnavailableError);
});

test('地址校验：拒绝 http 非本机地址与带凭据地址', () => {
  assert.throws(
    () => createDeepSeekSystemOne({ apiKey: 'k', chatUrl: 'http://evil.example.com/v1' }),
    /HTTPS/,
  );
  assert.throws(
    () => createDeepSeekSystemOne({ apiKey: 'k', chatUrl: 'https://user:pass@api.deepseek.com/v1' }),
    /凭据/,
  );
});

test('超时抛 ProviderUnavailableError', async () => {
  const neverResolve: typeof fetch = ((_url: unknown, init: { signal?: AbortSignal }) =>
    new Promise<Response>((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(init.signal?.reason));
    })) as unknown as typeof fetch;
  const backend = createDeepSeekSystemOne({ apiKey: 'k', timeoutMs: 20, fetchImpl: neverResolve });
  await assert.rejects(backend.ask({}, { m: CHOICE }), /unavailable|超时|暂时不可用/i);
});

test('usage: 响应带 usage 时聚合进 lastUsage，缺失时为 undefined', async () => {
  const captured: CapturedRequest[] = [];
  const withUsage = {
    ...chatResponse([['A', -0.1], ['B', -3]]) as object,
    usage: { prompt_tokens: 100, completion_tokens: 2, total_tokens: 102 },
  };
  const backend = createDeepSeekSystemOne({
    apiKey: 'k', fetchImpl: fakeFetch([withUsage], captured),
  });
  await backend.ask({}, { m: { type: 'choice', instructions: 'x', criteria: { a: '甲', b: '乙' } } });
  assert.deepEqual(backend.lastUsage, { promptTokens: 100, completionTokens: 2, totalTokens: 102 });

  const plain = createDeepSeekSystemOne({
    apiKey: 'k', fetchImpl: fakeFetch([chatResponse([['A', -0.1], ['B', -3]])], captured),
  });
  await plain.ask({}, { m: { type: 'choice', instructions: 'x', criteria: { a: '甲', b: '乙' } } });
  assert.equal(plain.lastUsage, undefined);
});
