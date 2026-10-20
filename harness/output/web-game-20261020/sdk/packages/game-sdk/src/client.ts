import { BRIDGE_PROTOCOL, type GameInfo, type Observation, type MapView, type SpatialQuery, type QueryResult, type EventPage, type ControlRequest, type ControlLease, type LeaseChange, type Intent, type ExecutionReceipt, type CancelIntent, type ExpressionBatch, type Commentary, type Danmaku, type PresentationReceipt } from './contracts.js';
import { BridgeError, HttpTransport, type GameTransport } from './transport.js';

const TERMINAL = new Set(['completed', 'failed', 'rejected', 'cancelled']);
function positive(value: number, name: string) {
  if (!Number.isFinite(value) || value <= 0) throw new BridgeError('invalid_interval', `${name} must be positive`);
}
function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(signal.reason); return; }
    const abort = () => { clearTimeout(timer); signal?.removeEventListener('abort', abort); reject(signal?.reason); };
    const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve(); }, ms);
    signal?.addEventListener('abort', abort, { once: true });
  });
}

/** No model calls, simulation state or control ownership lives in the SDK. */
export class GameClient {
  constructor(private readonly transport: GameTransport) {}
  static http(url: string, options?: { token?: string; timeoutMs?: number }): GameClient { return new GameClient(new HttpTransport(url, options)); }
  async getInfo(signal?: AbortSignal): Promise<GameInfo> {
    const info = await this.transport.request<GameInfo>('GET', '/v1/info', undefined, signal);
    if (info?.protocol !== BRIDGE_PROTOCOL) throw new BridgeError('protocol_mismatch', `Expected ${BRIDGE_PROTOCOL}`);
    return info;
  }
  observe(signal?: AbortSignal): Promise<Observation> { return this.transport.request('GET', '/v1/state', undefined, signal); }
  getMap(signal?: AbortSignal): Promise<MapView> { return this.transport.request('GET', '/v1/map', undefined, signal); }
  query(query: SpatialQuery, signal?: AbortSignal): Promise<QueryResult> { return this.transport.request('POST', '/v1/query', query, signal); }
  listEvents(cursor?: string, signal?: AbortSignal): Promise<EventPage> { return this.transport.request('GET', '/v1/events' + (cursor !== undefined ? `?cursor=${encodeURIComponent(cursor)}` : ''), undefined, signal); }
  /** Returns pages so gaps and resume cursors cannot be lost by flattening. */
  async *events(options: { cursor?: string; pollMs?: number; signal?: AbortSignal } = {}): AsyncGenerator<EventPage> {
    const pollMs = options.pollMs ?? 500;
    positive(pollMs, 'pollMs');
    let cursor = options.cursor;
    while (!options.signal?.aborted) {
      const page = await this.listEvents(cursor, options.signal);
      cursor = page.nextCursor;
      if (page.items.length || page.gap) yield page;
      await delay(pollMs, options.signal);
    }
  }
  acquireControl(request: ControlRequest, signal?: AbortSignal): Promise<ControlLease> { return this.transport.request('POST', '/v1/control/acquire', request, signal); }
  getControl(leaseId: string, signal?: AbortSignal): Promise<ControlLease> { return this.transport.request('GET', `/v1/control/${encodeURIComponent(leaseId)}`, undefined, signal); }
  renewControl(request: LeaseChange, signal?: AbortSignal): Promise<ControlLease> { return this.transport.request('POST', '/v1/control/renew', request, signal); }
  releaseControl(request: LeaseChange, signal?: AbortSignal): Promise<ControlLease> { return this.transport.request('POST', '/v1/control/release', request, signal); }
  submitIntent(intent: Intent, signal?: AbortSignal): Promise<ExecutionReceipt> { return this.transport.request('POST', '/v1/intents', intent, signal); }
  cancelIntent(request: CancelIntent, signal?: AbortSignal): Promise<ExecutionReceipt> { return this.transport.request('POST', '/v1/intents/cancel', request, signal); }
  getReceipt(id: string, signal?: AbortSignal): Promise<ExecutionReceipt> { return this.transport.request('GET', `/v1/receipts/${encodeURIComponent(id)}`, undefined, signal); }
  async waitForReceipt(id: string, options: { timeoutMs?: number; pollMs?: number; signal?: AbortSignal } = {}): Promise<ExecutionReceipt> {
    const timeoutMs = options.timeoutMs ?? 10000, pollMs = options.pollMs ?? 250;
    positive(timeoutMs, 'timeoutMs'); positive(pollMs, 'pollMs');
    const controller = new AbortController();
    const abort = () => controller.abort(options.signal?.reason);
    if (options.signal?.aborted) abort(); else options.signal?.addEventListener('abort', abort, { once: true });
    const timer = setTimeout(() => controller.abort(new BridgeError('receipt_timeout', 'No terminal receipt before deadline; command was not cancelled')), timeoutMs);
    try {
      while (true) {
        const receipt = await this.getReceipt(id, controller.signal);
        if (receipt.id !== id) throw new BridgeError('receipt_mismatch', 'Bridge returned a receipt for another command');
        if (TERMINAL.has(receipt.status)) return receipt;
        await delay(pollMs, controller.signal);
      }
    } finally { clearTimeout(timer); options.signal?.removeEventListener('abort', abort); }
  }
  setExpressions(batch: ExpressionBatch, signal?: AbortSignal): Promise<PresentationReceipt> { return this.transport.request('POST', '/v1/presentation/expressions', batch, signal); }
  playCommentary(line: Commentary, signal?: AbortSignal): Promise<PresentationReceipt> { return this.transport.request('POST', '/v1/presentation/commentary', line, signal); }
  showDanmaku(batch: Danmaku, signal?: AbortSignal): Promise<PresentationReceipt> { return this.transport.request('POST', '/v1/presentation/danmaku', batch, signal); }
  getPresentationReceipt(id: string, signal?: AbortSignal): Promise<PresentationReceipt> { return this.transport.request('GET', `/v1/presentation/receipts/${encodeURIComponent(id)}`, undefined, signal); }
}
