export const BRIDGE_PROTOCOL = 'quickplay-bridge/v1' as const;
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Fields = { [key: string]: Json };
export type Position = [number, number, number];
export interface Context {
  instanceId: string; runId: string; revision: number; tick: number; gameTime: number;
}
export type Capability = 'observe' | 'map' | 'query' | 'events' | 'control' | 'intents' | 'expressions' | 'commentary' | 'danmaku';
export interface GameInfo {
  protocol: typeof BRIDGE_PROTOCOL; gameId: string; buildVersion: string;
  extensions?: string[];
  coordinates: { unit: string; upAxis: 'x' | 'y' | 'z' };
  capabilities: Capability[]; actions: { id: string; parameters: Fields }[];
  queryKinds: string[]; emotions: string[]; controlScopes: ('team' | 'squad')[];
}
export interface Observation {
  context: Context;
  perspective: { teamId: string | null; visibility: 'team' | 'spectator' };
  actors: { id: string; teamId: string; position: Position; hp: number; maxHp: number; actionCapabilities: string[]; data?: Fields }[];
  squads: { id: string; teamId: string; actorIds: string[]; data?: Fields }[];
  objectives: { id: string; kind: string; status: string; position?: Position; data?: Fields }[];
  data: Fields;
}
export interface MapView { context: Context; regions: Fields[]; obstacles: Fields[]; data: Fields }
export interface SpatialQuery { id: string; context: Context; kind: string; actorIds: string[]; parameters: Fields }
export interface QueryResult { id: string; context: Context; candidates: Fields[]; expiresAtGameTime: number; data: Fields }
/** Cursors are opaque, scoped to a stream. A gap requires resynchronization. */
export interface GameEvent { id: string; context: Context; kind: string; actorIds: string[]; data: Fields }
export interface EventPage { items: GameEvent[]; nextCursor: string; gap: boolean }
export interface ControlScope { kind: 'team' | 'squad'; id: string }
export interface ControlRequest { id: string; context: Context; ownerId: string; scope: ControlScope; leaseSeconds: number }
/** active is legal only after the engine has confirmed handover. */
export interface ControlLease {
  leaseId: string; context: Context; ownerId: string; scope: ControlScope; epoch: number;
  expiresAtRealTime: number; status: 'pending' | 'active' | 'released' | 'expired' | 'rejected'; reason?: string;
}
export interface LeaseChange { leaseId: string; context: Context; epoch: number; leaseSeconds?: number }
export interface Intent {
  id: string; context: Context; leaseId: string; controlEpoch: number; orderVersion: number;
  actorIds: string[]; intent: { kind: string; parameters: Fields }; expiresAtGameTime: number;
}
export type ExecutionStatus = 'queued' | 'accepted' | 'executing' | 'suspended' | 'completed' | 'failed' | 'rejected' | 'cancelled';
export interface ExecutionReceipt { id: string; context: Context; status: ExecutionStatus; reason?: string; data?: Fields }
export interface CancelIntent { id: string; context: Context; leaseId: string; controlEpoch: number }
export interface Presentation {
  id: string; context: Context; expiresAtGameTime: number;
}
export interface ExpressionBatch extends Presentation {
  expressions: { actorId: string; emotion: string; intensity: number; holdSeconds: number }[];
}
export interface Commentary extends Presentation { text: string; audioResourceId?: string }
export interface Danmaku extends Presentation { items: { text: string; styleId?: string }[] }
export interface PresentationReceipt {
  id: string; context: Context; status: 'queued' | 'started' | 'displayed' | 'completed' | 'dropped' | 'failed'; reason?: string;
}
