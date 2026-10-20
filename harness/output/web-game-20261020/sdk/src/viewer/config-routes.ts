import type { IncomingMessage, ServerResponse } from 'node:http';
import type { ModelsConfig } from '../config.js';
import { createProxiedFetch } from '../systemone/http.js';
import { readBody, sendJson, type SendResponse } from './http.js';

export interface ConfigRouteOptions {
  config?: {
    get(): ModelsConfig;
    save(next: ModelsConfig): void;
    test?(override: { target?: string; provider?: string; apiKey?: string; model?: string }): Promise<{ ok: boolean; ms?: number; error?: string }>;
  };
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Handles model configuration without coupling the main HTTP entry to provider details. */
export async function handleConfigRoute(
  req: IncomingMessage,
  _res: ServerResponse,
  url: URL,
  options: ConfigRouteOptions,
  send: SendResponse,
): Promise<boolean> {
  if (req.method === 'POST' && url.pathname === '/api/config') {
    if (!options.config) { sendJson(send, 404, { error: '配置功能未启用' }); return true; }
    try {
      const body = JSON.parse(await readBody(req)) as Partial<ModelsConfig>;
      const current = options.config.get();
      const mergeModel = <T extends { apiKey: string; provider: string }>(prev: T, next: Partial<T> | undefined, isolateProvider = false): T => ({
        ...prev,
        ...(isolateProvider && next?.provider && next.provider !== prev.provider ? { extraBody: undefined } : {}),
        ...(next ?? {}),
        // Slow-model credentials cannot cross provider boundaries on a blank-key save.
        apiKey: next?.apiKey ? next.apiKey
          : isolateProvider && next?.provider && next.provider !== prev.provider ? '' : prev.apiKey,
      });
      const next: ModelsConfig = {
        defaultModel: body.defaultModel === 'deepseek' ? 'deepseek' : 'jev',
        jev: mergeModel(current.jev, body.jev),
        deepseek: mergeModel(current.deepseek, body.deepseek, true),
        analyst: mergeModel(current.analyst ?? { provider: 'ark' as const, apiKey: '', model: '' }, body.analyst, true),
      };
      for (const profile of [next.deepseek, next.analyst]) {
        if (profile && !['deepseek', 'ark', 'openrouter'].includes(profile.provider)) {
          throw new Error('未知慢脑接入方式；请选择 deepseek、ark 或 openrouter');
        }
      }
      options.config.save(next);
      sendJson(send, 200, { ok: true });
    } catch (error) {
      sendJson(send, 400, { error: errorText(error) });
    }
    return true;
  }

  if (req.method === 'POST' && url.pathname === '/api/config/test') {
    if (!options.config?.test) { sendJson(send, 404, { error: '配置功能未启用' }); return true; }
    try {
      const body = JSON.parse(await readBody(req)) as { target?: string; provider?: string; apiKey?: string; model?: string };
      sendJson(send, 200, await options.config.test(body));
    } catch (error) {
      // Connection failures are part of the test result, not an HTTP failure.
      sendJson(send, 200, { ok: false, error: errorText(error) });
    }
    return true;
  }

  if (req.method === 'GET' && url.pathname === '/api/models/list') {
    if (!options.config) { sendJson(send, 404, { error: '配置功能未启用' }); return true; }
    const requested = url.searchParams.get('target');
    const target = requested === 'deepseek' || requested === 'analyst' ? requested : 'jev';
    const current = options.config.get()[target] ?? { provider: 'ark', apiKey: '', model: '' };
    const provider = url.searchParams.get('provider') ?? current.provider;
    const apiKey = url.searchParams.get('apiKey')
      || (provider === current.provider ? current.apiKey : '')
      || (provider === 'deepseek' ? process.env['DEEPSEEK_API_KEY'] : undefined);
    const bases: Record<string, string> = {
      typesafe: process.env['TYPESAFE_BASE_URL'] ?? 'https://api.typesafe.ai/v1',
      openrouter: 'https://openrouter.ai/api/v1',
      ark: 'https://ark.cn-beijing.volces.com/api/v3',
      deepseek: 'https://api.deepseek.com',
    };
    const base = Object.hasOwn(bases, provider) ? bases[provider] : undefined;
    if (!base) { sendJson(send, 200, { ok: false, error: `未知接入方式：${provider}` }); return true; }
    if (provider === 'deepseek' && !apiKey) {
      sendJson(send, 200, { ok: false, error: 'DeepSeek 官方接口需要配置 DEEPSEEK_API_KEY 或该配置档的 API Key' }); return true;
    }
    try {
      const r = await createProxiedFetch(process.env)(`${base}/models`, {
        headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
        signal: AbortSignal.timeout(15000),
      });
      if (!r.ok) { sendJson(send, 200, { ok: false, error: `服务商返回 HTTP ${r.status}` }); return true; }
      const data = await r.json() as { data?: { id?: string; name?: string }[]; models?: { id?: string; name?: string }[] };
      const all = (data.data ?? data.models ?? []).map(m => String(m.id ?? m.name ?? '')).filter(Boolean);
      // OpenRouter/方舟的全量列表很长：优先按卡片关键字过滤，滤不到再给全量
      const kw = target === 'jev' ? /jev|typesafe/i : /deepseek/i;
      const filtered = all.filter(id => kw.test(id));
      sendJson(send, 200, { ok: true, models: (filtered.length ? filtered : all).slice(0, 200), total: all.length });
    } catch (error) {
      sendJson(send, 200, { ok: false, error: errorText(error) });
    }
    return true;
  }

  return false;
}
