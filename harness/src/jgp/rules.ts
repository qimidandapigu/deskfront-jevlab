import type { Action, EntityState, Vec2, WorldState } from "./protocol.js";

/** Local rule layer: Boids flocking + chase/flee/patrol fallback state machine. */

export interface RulesConfig {
  boidsRadius: number;
  separationWeight: number;
  alignmentWeight: number;
  cohesionWeight: number;
  /** hp fraction below which a unit flees. */
  fleeHpFrac: number;
  attackRange: number;
  visionRange: number;
}

export const DEFAULT_RULES: RulesConfig = {
  boidsRadius: 6,
  separationWeight: 1.5,
  alignmentWeight: 0.4,
  cohesionWeight: 0.3,
  fleeHpFrac: 0.3,
  attackRange: 1.6,
  visionRange: 15,
};

function len(v: Vec2): number {
  return Math.hypot(v.x, v.y);
}

export function norm(v: Vec2): Vec2 {
  const l = len(v);
  return l > 1e-6 ? { x: v.x / l, y: v.y / l } : { x: 0, y: 0 };
}

/** Boids steering for `self` among `allies`: separation + alignment + cohesion. */
export function boidsSteer(self: EntityState, allies: EntityState[], cfg: RulesConfig): Vec2 {
  const near = allies.filter((a) => len({ x: a.pos.x - self.pos.x, y: a.pos.y - self.pos.y }) <= cfg.boidsRadius);
  if (near.length === 0) return { x: 0, y: 0 };
  let sep = { x: 0, y: 0 };
  let ali = { x: 0, y: 0 };
  let coh = { x: 0, y: 0 };
  for (const a of near) {
    const dx = self.pos.x - a.pos.x;
    const dy = self.pos.y - a.pos.y;
    const d = Math.max(len({ x: dx, y: dy }), 1e-3);
    sep = { x: sep.x + dx / (d * d), y: sep.y + dy / (d * d) };
    ali = { x: ali.x + a.vel.x, y: ali.y + a.vel.y };
    coh = { x: coh.x + a.pos.x, y: coh.y + a.pos.y };
  }
  const n = near.length;
  ali = { x: ali.x / n - self.vel.x, y: ali.y / n - self.vel.y };
  coh = { x: coh.x / n - self.pos.x, y: coh.y / n - self.pos.y };
  return norm({
    x: sep.x * cfg.separationWeight + ali.x * cfg.alignmentWeight + coh.x * cfg.cohesionWeight,
    y: sep.y * cfg.separationWeight + ali.y * cfg.alignmentWeight + coh.y * cfg.cohesionWeight,
  });
}

/** Blend a desired heading with the boids steering vector. */
export function withBoids(desired: Vec2, steer: Vec2, boidsGain = 0.5): Vec2 {
  return norm({ x: desired.x + steer.x * boidsGain, y: desired.y + steer.y * boidsGain });
}

export type FallbackMode = "chase" | "flee" | "patrol";

/**
 * Deterministic local AI used when Jev is missing or unconfident.
 * State machine: low hp → flee; player visible & aware → chase/attack; else patrol.
 */
export function fallbackAction(
  self: EntityState,
  world: WorldState,
  cfg: RulesConfig,
  steer: Vec2,
): { action: Action; mode: FallbackMode } {
  const player = world.entities.find((e) => e.faction === "player" && e.hp > 0);
  const hpFrac = self.hp / self.maxHp;

  if (hpFrac <= cfg.fleeHpFrac && player) {
    const away = norm({ x: self.pos.x - player.pos.x, y: self.pos.y - player.pos.y });
    return { action: { entityId: self.id, type: "flee", dir: withBoids(away, steer, 0.2), speed: 1 }, mode: "flee" };
  }

  if (player) {
    const to = { x: player.pos.x - self.pos.x, y: player.pos.y - self.pos.y };
    const d = len(to);
    if (d <= cfg.attackRange) {
      return { action: { entityId: self.id, type: "attack", targetId: player.id }, mode: "chase" };
    }
    if (d <= cfg.visionRange) {
      return { action: { entityId: self.id, type: "move", dir: withBoids(norm(to), steer), targetId: player.id, speed: 1 }, mode: "chase" };
    }
  }

  // Deterministic patrol: slow circle derived from id hash + tick.
  const h = [...self.id].reduce((s, c) => s + c.charCodeAt(0), 0);
  const ang = (world.tick / 25 + h) % (Math.PI * 2);
  return {
    action: { entityId: self.id, type: "patrol", dir: withBoids({ x: Math.cos(ang), y: Math.sin(ang) }, steer), speed: 0.4 },
    mode: "patrol",
  };
}
