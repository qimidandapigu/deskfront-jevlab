/** Game-specific facts, never pretend these are portable generic observations. */
import type { Context, ControlLease, Fields } from './contracts.js';
import { GameClient } from './client.js';
import { type GameTransport } from './transport.js';
export type DeskfrontTeam = 'green' | 'red';
export declare const DESKFRONT_FORCES_EXTENSION: "deskfront-forces/v1";
export interface DeskfrontForceSlot {
    slot_id: string;
    kind: 'infantry' | 'tank';
    weapon?: 'rifle' | 'smg' | 'rocket';
}
/** Exact slots, including crew. No engine-side hidden additions are authorized. */
export interface DeskfrontForceManifest {
    schema: typeof DESKFRONT_FORCES_EXTENSION;
    enemies: DeskfrontForceSlot[];
    reinforcements: DeskfrontForceSlot[];
    captives?: DeskfrontForceSlot[];
    equipment: {
        slot_id: string;
        kind: 'mortar';
        crew_slot_ids: string[];
    }[];
}
export interface DeskfrontSnapshot {
    context: Context;
    perspective: DeskfrontTeam | 'spectator';
    state: Fields;
}
export interface DeskfrontCommand {
    id: string;
    context: Context;
    teamId: DeskfrontTeam;
    leaseId: string;
    controlEpoch: number;
    command: Fields & {
        action: 'squad_order' | 'soldier_order' | 'unit_emotion' | 'grow_world' | 'preview_world' | 'pause' | 'sidebar';
    };
}
export interface NativeAcknowledgement {
    id: string;
    accepted: boolean;
    message: string;
    tick: number;
}
export declare class DeskfrontClient {
    private readonly transport;
    readonly game: GameClient;
    constructor(transport: GameTransport);
    static http(url: string): DeskfrontClient;
    observe(team?: DeskfrontTeam, signal?: AbortSignal): Promise<DeskfrontSnapshot>;
    spectate(signal?: AbortSignal): Promise<DeskfrontSnapshot>;
    acquire(context: Context, team: DeskfrontTeam, ownerId: string, worldControl?: boolean): Promise<ControlLease>;
    renew(context: Context, team: DeskfrontTeam, lease: ControlLease): Promise<ControlLease>;
    release(context: Context, team: DeskfrontTeam, lease: ControlLease): Promise<ControlLease>;
    submit(command: DeskfrontCommand, signal?: AbortSignal): Promise<NativeAcknowledgement>;
    candidates(context: Context, team: DeskfrontTeam, actorId: string, proposals: Fields[], id?: `${string}-${string}-${string}-${string}-${string}`): Promise<Fields>;
    getCandidates(id: string, team: DeskfrontTeam): Promise<Fields>;
    topology(context: Context, team: DeskfrontTeam, actorId: string): Promise<Fields>;
}
