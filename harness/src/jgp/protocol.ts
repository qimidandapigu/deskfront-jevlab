/**
 * JGP (Jev Game Protocol) v1 — wire types + runtime guards.
 * No dependencies; games and harness both import from here.
 * See docs/protocol.md.
 */

export const PROTOCOL_VERSION = "v1" as const;
export type ProtocolVersion = typeof PROTOCOL_VERSION;

export interface Vec2 {
  x: number;
  y: number;
}

export type Faction = "player" | "enemy" | "neutral";

export interface SwarmOrder {
  type: "focus_fire" | "spread" | "flank" | "retreat";
  targetId?: string;
  issuedAtTick: number;
}

export interface EntityState {
  id: string;
  kind: string;
  faction: Faction;
  pos: Vec2;
  vel: Vec2;
  hp: number;
  maxHp: number;
  /** Whether this entity has noticed the player (set by harness, read by game). */
  aware?: boolean;
  /** 0..1 morale, set by harness decisions. */
  morale?: number;
  /** Latest order broadcast by the swarm brain. */
  swarmOrder?: SwarmOrder;
}

export interface GameEvent {
  tick: number;
  type: string;
  entityId?: string;
  message: string;
}

/** Harness 回写的逐实体输出（aware/morale/swarmOrder），随 actions 帧下发；游戏可忽略。 */
export interface EntityAnnotation {
  id: string;
  aware?: boolean;
  morale?: number;
  swarmOrder?: SwarmOrder;
}

export interface Bounds {
  w: number;
  h: number;
}

export interface WorldState {
  protocolVersion: ProtocolVersion;
  tick: number;
  timeMs: number;
  bounds: Bounds;
  entities: EntityState[];
  /** Events since the previous state snapshot. */
  events: GameEvent[];
}

export type ActionType = "move" | "attack" | "flee" | "hold" | "patrol";

export interface Action {
  entityId: string;
  type: ActionType;
  /** Unit-ish direction for move/flee/patrol. */
  dir?: Vec2;
  /** Target entity for attack/move. */
  targetId?: string;
  /** 0..1 speed multiplier. */
  speed?: number;
}

export interface Capabilities {
  protocolVersion: ProtocolVersion;
  game: string;
  tickRateHz: number;
  maxActionsPerTick: number;
  features: string[];
}

export interface GameAdapter {
  capabilities(): Capabilities | Promise<Capabilities>;
  getState(): WorldState | Promise<WorldState>;
  execute(actions: Action[], entities?: EntityAnnotation[]): void | Promise<void>;
}

// ---------- runtime guards (no `any`; narrow from unknown) ----------

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}
function isStr(v: unknown): v is string {
  return typeof v === "string";
}

export function isVec2(v: unknown): v is Vec2 {
  return isObj(v) && isNum(v.x) && isNum(v.y);
}

export function isSwarmOrder(v: unknown): v is SwarmOrder {
  if (!isObj(v) || !isNum(v.issuedAtTick)) return false;
  const t = v.type;
  return t === "focus_fire" || t === "spread" || t === "flank" || t === "retreat";
}

export function isEntityState(v: unknown): v is EntityState {
  if (!isObj(v)) return false;
  return (
    isStr(v.id) &&
    isStr(v.kind) &&
    (v.faction === "player" || v.faction === "enemy" || v.faction === "neutral") &&
    isVec2(v.pos) &&
    isVec2(v.vel) &&
    isNum(v.hp) &&
    isNum(v.maxHp) &&
    (v.aware === undefined || typeof v.aware === "boolean") &&
    (v.morale === undefined || isNum(v.morale)) &&
    (v.swarmOrder === undefined || isSwarmOrder(v.swarmOrder))
  );
}

export function isEntityAnnotation(v: unknown): v is EntityAnnotation {
  return (
    isObj(v) &&
    isStr(v.id) &&
    (v.aware === undefined || typeof v.aware === "boolean") &&
    (v.morale === undefined || isNum(v.morale)) &&
    (v.swarmOrder === undefined || isSwarmOrder(v.swarmOrder))
  );
}

export function isGameEvent(v: unknown): v is GameEvent {
  return isObj(v) && isNum(v.tick) && isStr(v.type) && isStr(v.message);
}

export function isWorldState(v: unknown): v is WorldState {
  if (!isObj(v)) return false;
  return (
    v.protocolVersion === PROTOCOL_VERSION &&
    isNum(v.tick) &&
    isNum(v.timeMs) &&
    isObj(v.bounds) &&
    isNum(v.bounds.w) &&
    isNum(v.bounds.h) &&
    Array.isArray(v.entities) &&
    v.entities.every(isEntityState) &&
    Array.isArray(v.events) &&
    v.events.every(isGameEvent)
  );
}

export function isAction(v: unknown): v is Action {
  if (!isObj(v)) return false;
  const t = v.type;
  return (
    isStr(v.entityId) &&
    (t === "move" || t === "attack" || t === "flee" || t === "hold" || t === "patrol") &&
    (v.dir === undefined || isVec2(v.dir)) &&
    (v.targetId === undefined || isStr(v.targetId)) &&
    (v.speed === undefined || isNum(v.speed))
  );
}

export function isCapabilities(v: unknown): v is Capabilities {
  if (!isObj(v)) return false;
  return (
    v.protocolVersion === PROTOCOL_VERSION &&
    isStr(v.game) &&
    isNum(v.tickRateHz) &&
    isNum(v.maxActionsPerTick) &&
    Array.isArray(v.features) &&
    v.features.every(isStr)
  );
}

export function assertWorldState(v: unknown): WorldState {
  if (!isWorldState(v)) throw new Error("invalid WorldState payload");
  return v;
}

export function assertCapabilities(v: unknown): Capabilities {
  if (!isCapabilities(v)) throw new Error("invalid Capabilities payload");
  return v;
}

// ---------- message envelope (v1, one JSON object per NDJSON line over stdio) ----------

/** game → harness */
export type GameMessage =
  | { type: "hello"; capabilities: Capabilities }
  | { type: "state"; state: WorldState };

/** harness → game */
export type HarnessMessage =
  | { type: "hello_ack"; protocolVersion: ProtocolVersion }
  | { type: "actions"; tick: number; actions: Action[]; entities?: EntityAnnotation[] }
  | { type: "error"; message: string };

export function isGameMessage(v: unknown): v is GameMessage {
  if (!isObj(v)) return false;
  if (v.type === "hello") return isCapabilities(v.capabilities);
  if (v.type === "state") return isWorldState(v.state);
  return false;
}

export function isHarnessMessage(v: unknown): v is HarnessMessage {
  if (!isObj(v)) return false;
  if (v.type === "hello_ack") return v.protocolVersion === PROTOCOL_VERSION;
  if (v.type === "actions") {
    return (
      isNum(v.tick) &&
      Array.isArray(v.actions) &&
      v.actions.every(isAction) &&
      (v.entities === undefined || (Array.isArray(v.entities) && v.entities.every(isEntityAnnotation)))
    );
  }
  if (v.type === "error") return isStr(v.message);
  return false;
}
