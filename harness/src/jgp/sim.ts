import {
  PROTOCOL_VERSION,
  type Action,
  type Capabilities,
  type EntityState,
  type GameAdapter,
  type GameEvent,
  type Vec2,
  type WorldState,
} from "./protocol.js";

export interface SimConfig {
  width: number;
  height: number;
  soldierCount: number;
  /** soldier tiles/tick at speed 1. */
  soldierSpeed: number;
  playerSpeed: number;
  /** rifle range in tiles. */
  rifleRange: number;
  rifleDamage: number;
  /** ticks between shots for one soldier. */
  fireCooldownTicks: number;
  playerMaxHp: number;
  soldierMaxHp: number;
  /** how many ticks a tracer stays on screen. */
  tracerTicks: number;
  seed: number;
}

export const DEFAULT_SIM: SimConfig = {
  width: 40,
  height: 20,
  soldierCount: 3,
  soldierSpeed: 0.3,
  playerSpeed: 0.5,
  rifleRange: 9,
  rifleDamage: 7,
  fireCooldownTicks: 12,
  playerMaxHp: 100,
  soldierMaxHp: 30,
  tracerTicks: 6,
  seed: 42,
};

/** A fired bullet's trajectory segment, kept for a few ticks for rendering. */
export interface Tracer {
  from: Vec2;
  to: Vec2;
  hit: boolean;
  tick: number;
}

export interface SimAdapter extends GameAdapter {
  world(): WorldState;
  step(): WorldState;
  tracers(): Tracer[];
  dispose(): void;
}

/** Tiny deterministic PRNG (mulberry32). */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function cellOf(p: Vec2): string {
  return `${Math.round(p.x)},${Math.round(p.y)}`;
}

/**
 * Rifle hit chance: decays with distance, penalized while the target moves.
 * Shared with the soldiers plugin game (src/games/soldiers).
 */
export function rifleHitChance(dist: number, range: number, targetMoving: boolean): number {
  return Math.max(0.05, 0.9 - (dist / range) * 0.5 - (targetMoving ? 0.2 : 0));
}

/**
 * Line of sight on a grid: sample the segment a→b; blocked if it crosses any
 * cell in `blocked` (a Set of "rx,ry" rounded-cell keys). Shared with the
 * soldiers plugin game.
 */
export function segmentClear(a: Vec2, b: Vec2, blocked: ReadonlySet<string>): boolean {
  const d = Math.hypot(b.x - a.x, b.y - a.y);
  const steps = Math.max(1, Math.ceil(d / 0.4));
  for (let i = 1; i < steps; i++) {
    const t = i / steps;
    const x = a.x + (b.x - a.x) * t;
    const y = a.y + (b.y - a.y) * t;
    if (blocked.has(`${Math.round(x)},${Math.round(y)}`)) return false;
  }
  return true;
}

/**
 * Simulated tabletop firefight: grid world, 1 scripted toy soldier (player)
 * ducking behind a sandbag arc, N enemy toy soldiers with rifles advancing
 * from the far corners. Sandbags block movement and line of sight.
 * Implements GameAdapter — the engine cannot tell it apart from a real game.
 */
export function createSimAdapter(config: Partial<SimConfig> = {}): SimAdapter {
  const cfg: SimConfig = { ...DEFAULT_SIM, ...config };
  const rand = rng(cfg.seed);
  let tick = 0;
  let pendingEvents: GameEvent[] = [];
  let tracers: Tracer[] = [];

  // Player base: an arc of sandbags near the bottom center of the table.
  const base: Vec2 = { x: Math.round(cfg.width / 2), y: cfg.height - 5 };

  const sandbags: EntityState[] = [];
  function addSandbag(x: number, y: number): void {
    const rx = Math.round(x);
    const ry = Math.round(y);
    if (rx < 0 || ry < 0 || rx >= cfg.width || ry >= cfg.height) return;
    if (sandbags.some((s) => Math.round(s.pos.x) === rx && Math.round(s.pos.y) === ry)) return;
    sandbags.push({
      id: `sandbag-${sandbags.length}`, kind: "sandbag", faction: "neutral",
      pos: { x: rx, y: ry }, vel: { x: 0, y: 0 }, hp: 1, maxHp: 1,
    });
  }
  // arc in front of the player base, opening toward the player (facing up-field)
  for (let deg = -70; deg <= 70; deg += 14) {
    const a = (deg * Math.PI) / 180;
    addSandbag(base.x + Math.sin(a) * 4.2, base.y - Math.cos(a) * 2.6);
  }
  // two mid-field cover segments (short angled lines), leaving a center lane
  for (let i = 0; i < 4; i++) {
    addSandbag(cfg.width * 0.22 + i * 0.9, cfg.height * 0.45 - i * 0.5);
    addSandbag(cfg.width * 0.78 - i * 0.9, cfg.height * 0.45 - i * 0.5);
  }
  const sandbagCells = new Set(sandbags.map((s) => cellOf(s.pos)));

  const player: EntityState = {
    id: "player", kind: "soldier", faction: "player",
    pos: { ...base }, vel: { x: 0, y: 0 },
    hp: cfg.playerMaxHp, maxHp: cfg.playerMaxHp,
  };

  // Enemy squad spawns along the far edge corners.
  const spawnSpots: Vec2[] = [
    { x: 2, y: 1 },
    { x: cfg.width - 3, y: 1 },
    { x: Math.round(cfg.width / 2), y: 1 },
    { x: 2, y: Math.round(cfg.height / 3) },
    { x: cfg.width - 3, y: Math.round(cfg.height / 3) },
  ];
  const soldiers: EntityState[] = [];
  for (let i = 0; i < cfg.soldierCount; i++) {
    const spot = spawnSpots[i % spawnSpots.length] ?? { x: 2 + i, y: 1 };
    soldiers.push({
      id: `soldier-${i}`, kind: "soldier", faction: "enemy",
      pos: { x: spot.x + rand(), y: spot.y + rand() * 0.5 }, vel: { x: 0, y: 0 },
      hp: cfg.soldierMaxHp, maxHp: cfg.soldierMaxHp,
    });
  }
  const lastFired = new Map<string, number>();

  function snapshot(): WorldState {
    const events = pendingEvents;
    pendingEvents = [];
    return {
      protocolVersion: PROTOCOL_VERSION,
      tick,
      timeMs: tick * 50,
      bounds: { w: cfg.width, h: cfg.height },
      entities: [player, ...soldiers, ...sandbags].map((e) => ({ ...e, pos: { ...e.pos }, vel: { ...e.vel } })),
      events,
    };
  }

  /** Clamp to bounds, refuse sandbag cells, slide along walls when blocked. */
  function moveEntity(e: EntityState, nx: number, ny: number): void {
    nx = Math.min(Math.max(nx, 0), cfg.width - 1);
    ny = Math.min(Math.max(ny, 0), cfg.height - 1);
    const blocked = (x: number, y: number): boolean => sandbagCells.has(`${Math.round(x)},${Math.round(y)}`);
    if (!blocked(nx, ny)) {
      e.pos = { x: nx, y: ny };
    } else if (!blocked(nx, e.pos.y)) {
      e.pos = { x: nx, y: e.pos.y };
    } else if (!blocked(e.pos.x, ny)) {
      e.pos = { x: e.pos.x, y: ny };
    }
  }

  /** Line of sight: sample the segment; blocked if it crosses a sandbag cell. */
  function hasLineOfSight(a: Vec2, b: Vec2): boolean {
    return segmentClear(a, b, sandbagCells);
  }

  /** Scripted player soldier: hugs the sandbag arc, shuffling and peeking. */
  function movePlayer(): void {
    if (player.hp <= 0) {
      pendingEvents.push({ tick, type: "death", entityId: player.id, message: "player died, respawning" });
      player.hp = player.maxHp;
      player.pos = { ...base };
      return;
    }
    const t = tick / 20;
    // small shuffle behind the wall, with an occasional peek over the top
    const peek = Math.sin(t * 0.7) > 0.75 ? -1.6 : 0;
    const nx = base.x + 1.8 * Math.sin(t * 1.3);
    const ny = base.y + 0.8 * Math.sin(t * 2.1) + peek;
    player.vel = { x: nx - player.pos.x, y: ny - player.pos.y };
    moveEntity(player, nx, ny);
  }

  function fireRifle(s: EntityState): void {
    const d = Math.hypot(player.pos.x - s.pos.x, player.pos.y - s.pos.y);
    if (d > cfg.rifleRange) return;
    if (!hasLineOfSight(s.pos, player.pos)) return;
    // hit chance: decays with distance, penalized while the target is moving
    const targetMoving = Math.hypot(player.vel.x, player.vel.y) > 0.05;
    const pHit = rifleHitChance(d, cfg.rifleRange, targetMoving);
    const hit = rand() < pHit;
    tracers.push({ from: { ...s.pos }, to: { ...player.pos }, hit, tick });
    if (tracers.length > 64) tracers = tracers.slice(-64);
    pendingEvents.push({
      tick, type: "shot", entityId: s.id,
      message: `${s.id} fires at player (dist ${d.toFixed(1)}${hit ? ", hit" : ", miss"})`,
    });
    if (hit) {
      player.hp = Math.max(0, player.hp - cfg.rifleDamage);
      pendingEvents.push({
        tick, type: "hit", entityId: player.id,
        message: `${s.id} hit player (${player.hp} hp)`,
      });
      pendingEvents.push({
        tick, type: "damage", entityId: player.id,
        message: `player takes ${cfg.rifleDamage} damage (${player.hp} hp)`,
      });
    }
  }

  function applyActions(actions: Action[]): void {
    for (const a of actions) {
      const s = soldiers.find((x) => x.id === a.entityId);
      if (!s || s.hp <= 0) continue;
      const speed = (a.speed ?? 1) * cfg.soldierSpeed;
      switch (a.type) {
        case "move":
        case "flee":
        case "patrol": {
          if (a.dir) {
            s.vel = { x: a.dir.x * speed, y: a.dir.y * speed };
            moveEntity(s, s.pos.x + s.vel.x, s.pos.y + s.vel.y);
          }
          break;
        }
        case "attack": {
          if (a.targetId !== player.id || player.hp <= 0) break;
          const last = lastFired.get(s.id) ?? -Infinity;
          if (tick - last < cfg.fireCooldownTicks) break;
          lastFired.set(s.id, tick);
          fireRifle(s);
          break;
        }
        case "hold":
          s.vel = { x: 0, y: 0 };
          break;
      }
    }
  }

  return {
    capabilities(): Capabilities {
      return {
        protocolVersion: PROTOCOL_VERSION,
        game: "jev-sim",
        tickRateHz: 20,
        maxActionsPerTick: 64,
        features: ["grid", "hp", "events", "cover", "projectiles"],
      };
    },
    getState: () => snapshot(),
    execute(actions, entities) {
      applyActions(actions);
      // 消费 harness 回写（与 stdio 接法的 entities 字段同一通道）
      if (entities) {
        for (const ann of entities) {
          const s = soldiers.find((x) => x.id === ann.id);
          if (!s) continue;
          s.aware = ann.aware;
          s.morale = ann.morale;
          s.swarmOrder = ann.swarmOrder;
        }
      }
      movePlayer();
      tick += 1;
      tracers = tracers.filter((t) => tick - t.tick < cfg.tracerTicks);
    },
    world: () => snapshot(),
    step() {
      movePlayer();
      tick += 1;
      tracers = tracers.filter((t) => tick - t.tick < cfg.tracerTicks);
      return snapshot();
    },
    tracers: () => tracers.map((t) => ({ ...t, from: { ...t.from }, to: { ...t.to } })),
    dispose() {},
  };
}

const ANSI = {
  reset: "\x1b[0m",
  green: "\x1b[32m",
  red: "\x1b[31m",
  yellow: "\x1b[33m",
  grey: "\x1b[90m",
};

/** ASCII renderer for the terminal demo, with ANSI colors and tracer fire. */
export function renderAscii(world: WorldState, tracers: Tracer[] = []): string {
  const { w, h } = world.bounds;
  const grid: string[][] = Array.from({ length: h }, () => Array.from({ length: w }, () => "."));
  const put = (x: number, y: number, ch: string): void => {
    const rx = Math.round(x);
    const ry = Math.round(y);
    if (rx < 0 || ry < 0 || rx >= w || ry >= h) return;
    const row = grid[ry];
    if (row) row[rx] = ch;
  };
  // sandbags
  for (const e of world.entities) {
    if (e.kind === "sandbag") put(e.pos.x, e.pos.y, `${ANSI.yellow}#${ANSI.reset}`);
  }
  // soldiers and player
  for (const e of world.entities) {
    if (e.faction === "player") {
      put(e.pos.x, e.pos.y, e.hp > 0 ? `${ANSI.green}@${ANSI.reset}` : `${ANSI.grey}x${ANSI.reset}`);
    } else if (e.faction === "enemy" && e.hp > 0) {
      put(e.pos.x, e.pos.y, `${ANSI.red}${e.swarmOrder?.type === "flank" ? "s" : "S"}${ANSI.reset}`);
    }
  }
  // bullet tracers on top: `*` along the line, `!` at a hit endpoint
  for (const tr of tracers) {
    const d = Math.hypot(tr.to.x - tr.from.x, tr.to.y - tr.from.y);
    const steps = Math.max(1, Math.ceil(d / 0.5));
    for (let i = 1; i < steps; i++) {
      const t = i / steps;
      put(tr.from.x + (tr.to.x - tr.from.x) * t, tr.from.y + (tr.to.y - tr.from.y) * t, `${ANSI.grey}*${ANSI.reset}`);
    }
    if (tr.hit) put(tr.to.x, tr.to.y, `${ANSI.red}!${ANSI.reset}`);
  }
  const player = world.entities.find((e) => e.faction === "player");
  const alive = world.entities.filter((e) => e.faction === "enemy" && e.hp > 0).length;
  const order = world.entities.find((e) => e.faction === "enemy" && e.hp > 0)?.swarmOrder?.type ?? "-";
  const header = `tick=${world.tick} player_hp=${player?.hp ?? "?"} enemies=${alive} order=${order}`;
  return header + "\n" + grid.map((r) => r.join("")).join("\n");
}
