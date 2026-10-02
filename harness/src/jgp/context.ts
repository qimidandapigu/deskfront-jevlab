import type { EntityState, SwarmOrder, WorldState } from "./protocol.js";

/** State JSON fed to Jev for one enemy. Target: ~200–500 tokens. */
export interface TrimmedState {
  tick: number;
  mission: string;
  self: {
    id: string;
    kind: string;
    pos: { x: number; y: number };
    hp: number;
    maxHp: number;
    morale: number;
    swarmOrder: SwarmOrder | null;
  };
  player: {
    id: string;
    pos: { x: number; y: number };
    dist: number;
    hpFrac: number;
  } | null;
  allies: Array<{ id: string; dist: number; hpFrac: number }>;
  lastEvents: string[];
}

export interface ContextDeps {
  visionRange: number;
  maxAllies: number;
}

function dist(a: { x: number; y: number }, b: { x: number; y: number }): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

export function createContextBuilder(deps: ContextDeps) {
  function build(input: {
    world: WorldState;
    self: EntityState;
    mission: string;
    lastEvents: string[];
  }): TrimmedState {
    const { world, self } = input;
    const player = world.entities.find((e) => e.faction === "player" && e.hp > 0) ?? null;
    const visibleAllies = world.entities
      .filter((e) => e.faction === "enemy" && e.id !== self.id && e.hp > 0)
      .map((e) => ({ e, d: dist(e.pos, self.pos) }))
      .filter((x) => x.d <= deps.visionRange)
      .sort((a, b) => a.d - b.d)
      .slice(0, deps.maxAllies)
      .map((x) => ({ id: x.e.id, dist: Math.round(x.d * 10) / 10, hpFrac: Math.round((x.e.hp / x.e.maxHp) * 100) / 100 }));

    const playerVisible = player !== null && dist(player.pos, self.pos) <= deps.visionRange;

    return {
      tick: world.tick,
      mission: input.mission,
      self: {
        id: self.id,
        kind: self.kind,
        pos: { x: Math.round(self.pos.x * 10) / 10, y: Math.round(self.pos.y * 10) / 10 },
        hp: self.hp,
        maxHp: self.maxHp,
        morale: Math.round((self.morale ?? 1) * 100) / 100,
        swarmOrder: self.swarmOrder ?? null,
      },
      player: playerVisible && player
        ? {
            id: player.id,
            pos: { x: Math.round(player.pos.x), y: Math.round(player.pos.y) },
            dist: Math.round(dist(player.pos, self.pos) * 10) / 10,
            hpFrac: Math.round((player.hp / player.maxHp) * 100) / 100,
          }
        : null,
      allies: visibleAllies,
      lastEvents: input.lastEvents.slice(-5),
    };
  }

  return { build, dispose() {} };
}

export type ContextBuilder = ReturnType<typeof createContextBuilder>;
