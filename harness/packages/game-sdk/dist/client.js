import { BRIDGE_PROTOCOL } from './contracts.js';
import { BridgeError, HttpTransport } from './transport.js';
const TERMINAL = new Set(['completed', 'failed', 'rejected', 'cancelled']);
function positive(value, name) {
    if (!Number.isFinite(value) || value <= 0)
        throw new BridgeError('invalid_interval', `${name} must be positive`);
}
function delay(ms, signal) {
    return new Promise((resolve, reject) => {
        if (signal?.aborted) {
            reject(signal.reason);
            return;
        }
        const abort = () => { clearTimeout(timer); signal?.removeEventListener('abort', abort); reject(signal?.reason); };
        const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve(); }, ms);
        signal?.addEventListener('abort', abort, { once: true });
    });
}
/** No model calls, simulation state or control ownership lives in the SDK. */
export class GameClient {
    transport;
    constructor(transport) {
        this.transport = transport;
    }
    static http(url, options) { return new GameClient(new HttpTransport(url, options)); }
    async getInfo(signal) {
        const info = await this.transport.request('GET', '/v1/info', undefined, signal);
        if (info?.protocol !== BRIDGE_PROTOCOL)
            throw new BridgeError('protocol_mismatch', `Expected ${BRIDGE_PROTOCOL}`);
        return info;
    }
    observe(signal) { return this.transport.request('GET', '/v1/state', undefined, signal); }
    getMap(signal) { return this.transport.request('GET', '/v1/map', undefined, signal); }
    query(query, signal) { return this.transport.request('POST', '/v1/query', query, signal); }
    listEvents(cursor, signal) { return this.transport.request('GET', '/v1/events' + (cursor !== undefined ? `?cursor=${encodeURIComponent(cursor)}` : ''), undefined, signal); }
    /** Returns pages so gaps and resume cursors cannot be lost by flattening. */
    async *events(options = {}) {
        const pollMs = options.pollMs ?? 500;
        positive(pollMs, 'pollMs');
        let cursor = options.cursor;
        while (!options.signal?.aborted) {
            const page = await this.listEvents(cursor, options.signal);
            cursor = page.nextCursor;
            if (page.items.length || page.gap)
                yield page;
            await delay(pollMs, options.signal);
        }
    }
    acquireControl(request, signal) { return this.transport.request('POST', '/v1/control/acquire', request, signal); }
    getControl(leaseId, signal) { return this.transport.request('GET', `/v1/control/${encodeURIComponent(leaseId)}`, undefined, signal); }
    renewControl(request, signal) { return this.transport.request('POST', '/v1/control/renew', request, signal); }
    releaseControl(request, signal) { return this.transport.request('POST', '/v1/control/release', request, signal); }
    submitIntent(intent, signal) { return this.transport.request('POST', '/v1/intents', intent, signal); }
    cancelIntent(request, signal) { return this.transport.request('POST', '/v1/intents/cancel', request, signal); }
    getReceipt(id, signal) { return this.transport.request('GET', `/v1/receipts/${encodeURIComponent(id)}`, undefined, signal); }
    async waitForReceipt(id, options = {}) {
        const timeoutMs = options.timeoutMs ?? 10000, pollMs = options.pollMs ?? 250;
        positive(timeoutMs, 'timeoutMs');
        positive(pollMs, 'pollMs');
        const controller = new AbortController();
        const abort = () => controller.abort(options.signal?.reason);
        if (options.signal?.aborted)
            abort();
        else
            options.signal?.addEventListener('abort', abort, { once: true });
        const timer = setTimeout(() => controller.abort(new BridgeError('receipt_timeout', 'No terminal receipt before deadline; command was not cancelled')), timeoutMs);
        try {
            while (true) {
                const receipt = await this.getReceipt(id, controller.signal);
                if (receipt.id !== id)
                    throw new BridgeError('receipt_mismatch', 'Bridge returned a receipt for another command');
                if (TERMINAL.has(receipt.status))
                    return receipt;
                await delay(pollMs, controller.signal);
            }
        }
        finally {
            clearTimeout(timer);
            options.signal?.removeEventListener('abort', abort);
        }
    }
    setExpressions(batch, signal) { return this.transport.request('POST', '/v1/presentation/expressions', batch, signal); }
    playCommentary(line, signal) { return this.transport.request('POST', '/v1/presentation/commentary', line, signal); }
    showDanmaku(batch, signal) { return this.transport.request('POST', '/v1/presentation/danmaku', batch, signal); }
    getPresentationReceipt(id, signal) { return this.transport.request('GET', `/v1/presentation/receipts/${encodeURIComponent(id)}`, undefined, signal); }
}
