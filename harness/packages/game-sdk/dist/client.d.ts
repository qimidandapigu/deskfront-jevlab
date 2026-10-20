import { type GameInfo, type Observation, type MapView, type SpatialQuery, type QueryResult, type EventPage, type ControlRequest, type ControlLease, type LeaseChange, type Intent, type ExecutionReceipt, type CancelIntent, type ExpressionBatch, type Commentary, type Danmaku, type PresentationReceipt } from './contracts.js';
import { type GameTransport } from './transport.js';
/** No model calls, simulation state or control ownership lives in the SDK. */
export declare class GameClient {
    private readonly transport;
    constructor(transport: GameTransport);
    static http(url: string, options?: {
        token?: string;
        timeoutMs?: number;
    }): GameClient;
    getInfo(signal?: AbortSignal): Promise<GameInfo>;
    observe(signal?: AbortSignal): Promise<Observation>;
    getMap(signal?: AbortSignal): Promise<MapView>;
    query(query: SpatialQuery, signal?: AbortSignal): Promise<QueryResult>;
    listEvents(cursor?: string, signal?: AbortSignal): Promise<EventPage>;
    /** Returns pages so gaps and resume cursors cannot be lost by flattening. */
    events(options?: {
        cursor?: string;
        pollMs?: number;
        signal?: AbortSignal;
    }): AsyncGenerator<EventPage>;
    acquireControl(request: ControlRequest, signal?: AbortSignal): Promise<ControlLease>;
    getControl(leaseId: string, signal?: AbortSignal): Promise<ControlLease>;
    renewControl(request: LeaseChange, signal?: AbortSignal): Promise<ControlLease>;
    releaseControl(request: LeaseChange, signal?: AbortSignal): Promise<ControlLease>;
    submitIntent(intent: Intent, signal?: AbortSignal): Promise<ExecutionReceipt>;
    cancelIntent(request: CancelIntent, signal?: AbortSignal): Promise<ExecutionReceipt>;
    getReceipt(id: string, signal?: AbortSignal): Promise<ExecutionReceipt>;
    waitForReceipt(id: string, options?: {
        timeoutMs?: number;
        pollMs?: number;
        signal?: AbortSignal;
    }): Promise<ExecutionReceipt>;
    setExpressions(batch: ExpressionBatch, signal?: AbortSignal): Promise<PresentationReceipt>;
    playCommentary(line: Commentary, signal?: AbortSignal): Promise<PresentationReceipt>;
    showDanmaku(batch: Danmaku, signal?: AbortSignal): Promise<PresentationReceipt>;
    getPresentationReceipt(id: string, signal?: AbortSignal): Promise<PresentationReceipt>;
}
