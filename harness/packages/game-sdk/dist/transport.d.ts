export interface GameTransport {
    request<T>(method: 'GET' | 'POST', path: string, body?: unknown, signal?: AbortSignal): Promise<T>;
}
export declare class BridgeError extends Error {
    readonly code: string;
    readonly status?: number | undefined;
    constructor(code: string, message: string, status?: number | undefined);
}
/** HTTP timeout does not cancel game execution; commands are never retried here. */
export declare class HttpTransport implements GameTransport {
    private readonly options;
    private readonly baseUrl;
    constructor(baseUrl: string, options?: {
        token?: string;
        timeoutMs?: number;
    });
    request<T>(method: 'GET' | 'POST', path: string, body?: unknown, signal?: AbortSignal): Promise<T>;
}
