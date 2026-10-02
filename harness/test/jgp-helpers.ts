import { PROTOCOL_VERSION, type Action, type Capabilities, type EntityState, type GameAdapter, type WorldState } from '../src/jgp/protocol.js';

export function entity(partial: Partial<EntityState> & { id: string }): EntityState {
  return {
    kind: 'wolf',
    faction: 'enemy',
    pos: { x: 0, y: 0 },
    vel: { x: 0, y: 0 },
    hp: 30,
    maxHp: 30,
    ...partial,
  };
}

export function player(pos: { x: number; y: number }, hp = 100): EntityState {
  return entity({ id: 'player', kind: 'player', faction: 'player', pos, hp, maxHp: 100 });
}

export function world(entities: EntityState[], tick = 1): WorldState {
  return {
    protocolVersion: PROTOCOL_VERSION,
    tick,
    timeMs: tick * 50,
    bounds: { w: 40, h: 20 },
    entities,
    events: [],
  };
}

/** Adapter that plays back a fixed world and records executed actions. */
export function fixedAdapter(w: WorldState, capsOverride: Partial<Capabilities> = {}): GameAdapter & { executed: Action[][] } {
  const executed: Action[][] = [];
  return {
    executed,
    capabilities: () => ({
      protocolVersion: PROTOCOL_VERSION,
      game: 'conformance',
      tickRateHz: 20,
      maxActionsPerTick: 64,
      features: [],
      ...capsOverride,
    }),
    getState: () => w,
    execute(actions) {
      executed.push(actions);
    },
  };
}
