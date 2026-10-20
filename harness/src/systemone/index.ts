import type { SystemOne } from './types.js';
import { createMockSystemOne } from './mock.js';
import { createDeepSeekSystemOne } from './deepseek.js';
import { createJevSystemOne } from './jev.js';
import { createOpenRouterSystemOne } from './openrouter.js';
import { createProxiedFetch } from './http.js';

export { createPlanner } from './planner.js';

/** JEP v1 §4：后端接入只在此查表登记，禁止业务代码散落 env 分支。
 *  deepseek 走 logprobs 路线，与 Jev 同为 SystemOne 契约，可直接切换。 */
const backends: Record<string, (env: NodeJS.ProcessEnv) => SystemOne> = {
  mock: () => createMockSystemOne(),
  deepseek: env => {
    const chatUrl = env['MODEL_CHAT_URL'] ?? 'https://api.deepseek.com/chat/completions';
    const official = new URL(chatUrl).hostname === 'api.deepseek.com';
    const apiKey = env['MODEL_API_KEY'] || (official ? env['DEEPSEEK_API_KEY'] : undefined);
    if (!apiKey) throw new Error(official
      ? 'DeepSeek 官方接口需要配置 DEEPSEEK_API_KEY 或 MODEL_API_KEY'
      : '当前接入方式需要配置 MODEL_API_KEY；不会借用 DeepSeek 官方密钥');
    const configuredExtra = env['MODEL_EXTRA_BODY'] ? JSON.parse(env['MODEL_EXTRA_BODY']) as Record<string, unknown> : undefined;
    if (official && configuredExtra && ('provider' in configuredExtra || 'reasoning' in configuredExtra)) {
      throw new Error('DeepSeek 官方配置不能包含 OpenRouter provider/reasoning 参数');
    }
    return createDeepSeekSystemOne({
      apiKey,
      analysis: env['MODEL_ANALYSIS'] === '1',
      ...(env['MODEL_CHAT_URL'] ? { chatUrl: env['MODEL_CHAT_URL'] } : {}),
      ...(env['MODEL_NAME'] ? { model: env['MODEL_NAME'] } : official ? { model: 'deepseek-flash' } : {}),
      ...(official ? { extraBody: { thinking: { type: 'disabled' }, ...configuredExtra } }
        : configuredExtra ? { extraBody: configuredExtra } : {}),
      fetchImpl: createProxiedFetch(env),
    });
  },
  jev: env => createJevSystemOne(env),
  openrouter: env => createOpenRouterSystemOne(env),
};

export function createSystemOne(env: NodeJS.ProcessEnv): SystemOne {
  const name = env['SYSTEMONE_BACKEND'] ?? 'mock';
  const factory = backends[name];
  if (!factory) {
    throw new Error(`未知 SYSTEMONE_BACKEND: ${name}（可用: ${Object.keys(backends).join(', ')}）`);
  }
  return factory(env);
}

export type { Answer, Question, SystemOne } from './types.js';
