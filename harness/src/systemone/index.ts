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
    const apiKey = env['MODEL_API_KEY'];
    if (!apiKey) throw new Error('SYSTEMONE_BACKEND=deepseek 需要配置 MODEL_API_KEY');
    return createDeepSeekSystemOne({
      apiKey,
      analysis: env['MODEL_ANALYSIS'] === '1',
      ...(env['MODEL_CHAT_URL'] ? { chatUrl: env['MODEL_CHAT_URL'] } : {}),
      ...(env['MODEL_NAME'] ? { model: env['MODEL_NAME'] } : {}),
      ...(env['MODEL_EXTRA_BODY'] ? { extraBody: JSON.parse(env['MODEL_EXTRA_BODY']) as Record<string, unknown> } : {}),
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
