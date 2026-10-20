import { ProxyAgent, fetch as undiciFetch, type RequestInit as UndiciRequestInit } from 'undici';

const LOCAL_HOSTS = new Set(['127.0.0.1', 'localhost', '::1']);

// 同一代理地址复用一个 ProxyAgent（连接池），避免每次创建后端都泄漏一个 agent
const agents = new Map<string, ProxyAgent>();

/**
 * 本机 fake-ip/系统代理环境下 Node fetch 直连 openrouter.ai 会超时。
 * 配置了 HTTPS_PROXY/HTTP_PROXY 时返回经代理的 fetch；本机回环地址始终直连。
 */
export function createProxiedFetch(env: NodeJS.ProcessEnv): typeof fetch {
  const proxy = env['HTTPS_PROXY'] ?? env['https_proxy'] ?? env['HTTP_PROXY'] ?? env['http_proxy'];
  if (!proxy) return fetch;
  let agent = agents.get(proxy);
  if (!agent) {
    agent = new ProxyAgent(proxy);
    agents.set(proxy, agent);
  }
  return ((url: string | URL, init?: RequestInit) => {
    const hostname = new URL(String(url)).hostname;
    if (LOCAL_HOSTS.has(hostname)) return fetch(url, init);
    return undiciFetch(String(url), { ...init, dispatcher: agent } as UndiciRequestInit) as unknown as Promise<Response>;
  }) as typeof fetch;
}
