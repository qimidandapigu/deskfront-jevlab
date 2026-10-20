export interface GameTransport {
  request<T>(method: 'GET' | 'POST', path: string, body?: unknown, signal?: AbortSignal): Promise<T>;
}
export class BridgeError extends Error {
  constructor(public readonly code: string, message: string, public readonly status?: number) { super(message); this.name = 'BridgeError'; }
}
/** HTTP timeout does not cancel game execution; commands are never retried here. */
export class HttpTransport implements GameTransport {
  private readonly baseUrl: string;
  constructor(baseUrl: string, private readonly options: { token?: string; timeoutMs?: number } = {}) {
    const url = new URL(baseUrl);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new BridgeError('invalid_url', 'Expected an HTTP service URL without credentials, query or fragment');
    this.baseUrl = url.href.replace(/\/$/, '');
    const timeout = options.timeoutMs ?? 5000;
    if (!Number.isFinite(timeout) || timeout <= 0) throw new BridgeError('invalid_timeout', 'timeoutMs must be positive');
  }
  async request<T>(method: 'GET' | 'POST', path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    const controller = new AbortController();
    const abort = () => controller.abort(signal?.reason);
    if (signal?.aborted) abort(); else signal?.addEventListener('abort', abort, { once: true });
    const timer = setTimeout(() => controller.abort(new BridgeError('request_timeout', 'No HTTP response before deadline; execution outcome is unknown')), this.options.timeoutMs ?? 5000);
    try {
      const response = await fetch(this.baseUrl + path, {
        method, signal: controller.signal,
        headers: { Accept: 'application/json', ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(this.options.token ? { Authorization: `Bearer ${this.options.token}` } : {}) },
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      });
      let result: unknown;
      try { result = await response.json(); }
      catch { throw new BridgeError('invalid_response', 'Bridge returned non-JSON data', response.status); }
      if (!response.ok) {
        const error = result as { code?: string; error?: string; message?: string } | null;
        throw new BridgeError(error?.code ?? error?.error ?? 'http_error', error?.message ?? 'Bridge rejected request', response.status);
      }
      return result as T;
    } catch (error) {
      if (controller.signal.aborted) throw controller.signal.reason;
      throw error;
    } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
  }
}
