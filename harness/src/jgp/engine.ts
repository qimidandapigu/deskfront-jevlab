import type { Action, Capabilities, EntityAnnotation, EntityState, GameAdapter, SwarmOrder, Vec2, WorldState } from "./protocol.js";
import { isAction } from "./protocol.js";
import type { JevAnswers, JevClient, JevUsage } from "./jev-types.js";
import { createContextBuilder, type TrimmedState } from "./context.js";
import { boidsSteer, fallbackAction, norm, withBoids, DEFAULT_RULES, type RulesConfig } from "./rules.js";
import { createMemory, type Memory } from "./memory.js";
import type { Strategist } from "./strategist.js";
import type { DecisionLogger, DecisionRecord } from "./logger.js";

export interface EngineConfig {
  /** per-enemy decision rate when near the player (Hz). */
  decisionHz: number;
  /** decision rate for enemies far from the player (interest management). */
  farDecisionHz: number;
  /** distance beyond which an enemy counts as "far". */
  farDistance: number;
  /** swarm brain rate (Hz). */
  swarmHz: number;
  /** minimum time an action is kept before switching (ms). */
  minActionHoldMs: number;
  /** @deprecated Ignored; valid choices execute at every confidence. */
  confidenceThreshold: number;
  /** @deprecated 兼容旧配置，不再使用置信度阈值。 */
  highRiskThreshold: number;
  /** action 题的分级声明：高风险动作 / 安全默认动作 / 允许弃权（与内置线 Question 语义一致）。 */
  actionGate?: { highRisk?: string[]; safeAction?: string; allowOther?: boolean };
  visionRange: number;
  rules: RulesConfig;
}

export const DEFAULT_ENGINE_CONFIG: EngineConfig = {
  decisionHz: 3,
  farDecisionHz: 1,
  farDistance: 20,
  swarmHz: 0.7,
  minActionHoldMs: 500,
  confidenceThreshold: 0.6,
  highRiskThreshold: 0.85,
  visionRange: 15,
  rules: DEFAULT_RULES,
};

export interface EngineDeps {
  adapter: GameAdapter;
  jev: JevClient;
  strategist: Strategist;
  logger: DecisionLogger;
  config?: Partial<EngineConfig>;
  now?: () => number;
  memory?: Memory;
}

interface EnemyRuntime {
  lastDecisionMs: number;
  lastAction: Action | null;
  lastActionChangedMs: number;
  lastSignature: string;
  aware: boolean;
  morale: number;
}

const ACTION_CHOICES = ["chase", "attack", "flee", "hold", "patrol", "flank"] as const;
type ChoiceName = (typeof ACTION_CHOICES)[number];

function d2(a: Vec2, b: Vec2): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

export function createEngine(deps: EngineDeps) {
  const cfg: EngineConfig = { ...DEFAULT_ENGINE_CONFIG, ...deps.config };
  const now = deps.now ?? Date.now;
  const memory = deps.memory ?? createMemory();
  const ctxBuilder = createContextBuilder({ visionRange: cfg.visionRange, maxAllies: 5 });
  const runtime = new Map<string, EnemyRuntime>();
  let swarmOrder: SwarmOrder = { type: "focus_fire", targetId: "player", issuedAtTick: 0 };
  let lastSwarmMs = -Infinity;
  let disposed = false;
  let caps: Capabilities | null = null;
  let capsLoaded = false;

  /** capabilities 只在首次需要时拉取；握手未就绪等失败场景按无上限处理。 */
  async function maxActionsPerTick(): Promise<number | null> {
    if (!capsLoaded) {
      capsLoaded = true;
      try { caps = await deps.adapter.capabilities(); } catch { caps = null; }
    }
    return caps?.maxActionsPerTick ?? null;
  }

  function rt(id: string): EnemyRuntime {
    let r = runtime.get(id);
    if (!r) {
      r = { lastDecisionMs: -Infinity, lastAction: null, lastActionChangedMs: -Infinity, lastSignature: "", aware: false, morale: 1 };
      runtime.set(id, r);
    }
    return r;
  }

  /** Significant-change signature: bucketed, so jitter doesn't retrigger decisions. */
  function signature(state: TrimmedState, self: EntityState): string {
    const p = state.player;
    return [
      p ? `${Math.round(p.dist / 2)}:${Math.round(p.hpFrac * 4)}` : "nop",
      Math.round((self.hp / self.maxHp) * 4),
      swarmOrder.type,
      state.allies.length,
    ].join("|");
  }

  async function runSwarmBrain(world: WorldState, enemies: EntityState[], player: EntityState | undefined): Promise<void> {
    const t = now();
    if (t - lastSwarmMs < 1000 / cfg.swarmHz) return;
    lastSwarmMs = t;
    const alive = enemies.filter((e) => e.hp > 0);
    const avgHpFrac = alive.length ? alive.reduce((s, e) => s + e.hp / e.maxHp, 0) / alive.length : 0;
    const minDist = player && alive.length ? Math.min(...alive.map((e) => d2(e.pos, player.pos))) : null;
    const state = {
      swarm: true as const,
      tick: world.tick,
      mission: deps.strategist.current().mission,
      soldiers: alive.length,
      avgHpFrac: Math.round(avgHpFrac * 100) / 100,
      playerHpFrac: player ? Math.round((player.hp / player.maxHp) * 100) / 100 : null,
      minDistToPlayer: minDist !== null ? Math.round(minDist * 10) / 10 : null,
    };
    const t0 = now();
    try {
      const res = await deps.jev.systemOne({
        state,
        questions: {
          tactic: {
            type: "choice",
            instructions: "Pick the squad tactic for the next seconds.",
            criteria: {
              focus_fire: "everyone concentrates fire on the player",
              spread: "spread out to avoid focused fire",
              flank: "split and maneuver for firing angles from two sides",
              retreat: "break contact and regroup away from the player",
            },
          },
        },
      });
      const a = res.answers.tactic;
      const valid = ["focus_fire", "spread", "flank", "retreat"] as const;
      const picked = a?.choice && (valid as readonly string[]).includes(a.choice) ? (a.choice as SwarmOrder["type"]) : null;
      swarmOrder = {
        type: picked ?? heuristicSwarm(avgHpFrac, minDist),
        targetId: player?.id,
        issuedAtTick: world.tick,
      };
      deps.logger.log({
        tick: world.tick, timeMs: world.timeMs, entity: "swarm", state,
        jev: { answers: res.answers, model: res.model, latencyMs: res.latencyMs, ...(res.usage ? { usage: res.usage } : {}) },
        action: null, fallback: swarmOrder.type !== picked, latencyMs: now() - t0,
      });
    } catch {
      swarmOrder = { type: heuristicSwarm(avgHpFrac, minDist), targetId: player?.id, issuedAtTick: world.tick };
      deps.logger.log({
        tick: world.tick, timeMs: world.timeMs, entity: "swarm", state,
        jev: null, action: null, fallback: true, fallbackReason: "jev_error", latencyMs: now() - t0,
      });
    }
  }

  function heuristicSwarm(avgHpFrac: number, minDist: number | null): SwarmOrder["type"] {
    if (avgHpFrac < 0.35) return "retreat";
    if (minDist !== null && minDist > 5) return "flank";
    return "focus_fire";
  }

  function mapChoice(choice: ChoiceName, self: EntityState, player: EntityState | undefined, steer: Vec2): Action {
    const toPlayer = player ? norm({ x: player.pos.x - self.pos.x, y: player.pos.y - self.pos.y }) : { x: 0, y: 0 };
    switch (choice) {
      case "attack":
        return player
          ? d2(self.pos, player.pos) <= cfg.rules.attackRange
            ? { entityId: self.id, type: "attack", targetId: player.id }
            : { entityId: self.id, type: "move", dir: withBoids(toPlayer, steer), targetId: player.id, speed: 1 }
          : { entityId: self.id, type: "hold" };
      case "chase":
        return player
          ? { entityId: self.id, type: "move", dir: withBoids(toPlayer, steer), targetId: player.id, speed: 1 }
          : { entityId: self.id, type: "patrol", dir: steer, speed: 0.4 };
      case "flank": {
        // approach the player from a perpendicular side, picked deterministically per id
        const h = [...self.id].reduce((s, c) => s + c.charCodeAt(0), 0);
        const side = h % 2 === 0 ? 1 : -1;
        const perp = { x: -toPlayer.y * side, y: toPlayer.x * side };
        const dir = norm({ x: toPlayer.x * 0.5 + perp.x, y: toPlayer.y * 0.5 + perp.y });
        return player
          ? { entityId: self.id, type: "move", dir: withBoids(dir, steer), targetId: player.id, speed: 1 }
          : { entityId: self.id, type: "patrol", dir: steer, speed: 0.4 };
      }
      case "flee":
        return player
          ? { entityId: self.id, type: "flee", dir: norm({ x: self.pos.x - player.pos.x, y: self.pos.y - player.pos.y }), speed: 1 }
          : { entityId: self.id, type: "hold" };
      case "patrol": {
        const h = [...self.id].reduce((s, c) => s + c.charCodeAt(0), 0);
        const ang = (h % 360) * (Math.PI / 180);
        return { entityId: self.id, type: "patrol", dir: withBoids({ x: Math.cos(ang), y: Math.sin(ang) }, steer), speed: 0.4 };
      }
      case "hold":
        return { entityId: self.id, type: "hold" };
    }
  }

  /** Enforce the swarm order by biasing low-level choices. */
  function applySwarmOrder(choice: ChoiceName, self: EntityState, player: EntityState | undefined): ChoiceName {
    if (!player) return choice;
    switch (swarmOrder.type) {
      case "retreat":
        return "flee";
      case "spread":
        return choice === "attack" ? choice : "patrol";
      case "flank":
        return choice === "attack" || choice === "chase" ? "flank" : choice;
      case "focus_fire":
        return choice;
    }
  }

  async function decideEnemy(world: WorldState, self: EntityState, allies: EntityState[], player: EntityState | undefined): Promise<Action | null> {
    const r = rt(self.id);
    const t = now();
    const steer = boidsSteer(self, allies, cfg.rules);
    const far = !player || d2(self.pos, player.pos) > cfg.farDistance;
    const rate = far ? cfg.farDecisionHz : cfg.decisionHz;

    // throttle: reuse previous action when not due
    if (t - r.lastDecisionMs < 1000 / rate) {
      return r.lastAction;
    }

    const ctx = ctxBuilder.build({
      world,
      self: { ...self, morale: r.morale, swarmOrder },
      mission: deps.strategist.current().mission,
      lastEvents: memory.recentEvents(self.id),
    });

    // event-driven throttling: no significant change → keep previous action
    const sig = signature(ctx, self);
    if (sig === r.lastSignature && r.lastAction) {
      r.lastDecisionMs = t;
      return r.lastAction;
    }
    r.lastSignature = sig;
    r.lastDecisionMs = t;

    const t0 = now();
    let action: Action;
    let fallback = false;
    let blocked = false;
    let fallbackReason: DecisionRecord["fallbackReason"];
    let jevLog: { answers: JevAnswers; model: string; latencyMs: number; usage?: JevUsage } | null = null;

    try {
      const res = await deps.jev.systemOne({
        state: ctx,
        questions: {
          action: {
            type: "choice",
            instructions: "You are a toy soldier in a squad engaging the player with rifles. Pick your immediate action.",
            criteria: {
              chase: "advance toward the player",
              attack: "shoot when in range and line of sight",
              flee: "fall back (low hp / pinned down)",
              hold: "hold position",
              patrol: "move between cover, stay alert",
              flank: "maneuver to a firing angle from the side",
            },
            ...(cfg.actionGate?.highRisk ? { highRisk: cfg.actionGate.highRisk } : {}),
            ...(cfg.actionGate?.safeAction ? { safeAction: cfg.actionGate.safeAction } : {}),
            ...(cfg.actionGate?.allowOther ? { allowOther: true } : {}),
          },
          aware: { type: "noul", instructions: "Have you noticed the player?" },
          morale: { type: "score", instructions: "Your fighting spirit.", criteria: ["broken", "shaken", "eager"] },
        },
      });
      jevLog = { answers: res.answers, model: res.model, latencyMs: res.latencyMs, ...(res.usage ? { usage: res.usage } : {}) };
      const a = res.answers.action;
      const awareAns = res.answers.aware;
      const moraleAns = res.answers.morale;
      if (typeof awareAns?.noul === 'boolean') r.aware = awareAns.noul;
      if (moraleAns?.score !== undefined && Number.isFinite(moraleAns.score)) r.morale = moraleAns.score / 2;

      // Valid model choices execute regardless of probability or confidence.
      const raw = a?.choice;
      const choice = raw && (ACTION_CHOICES as readonly string[]).includes(raw) ? raw as ChoiceName : null;
      if (choice) {
        action = mapChoice(applySwarmOrder(choice, self, player), self, player, steer);
      } else {
        fallback = true;
        fallbackReason = raw === 'other' ? 'abstained' : 'invalid';
        const safe = cfg.actionGate?.safeAction;
        action = safe && (ACTION_CHOICES as readonly string[]).includes(safe)
          ? mapChoice(applySwarmOrder(safe as ChoiceName, self, player), self, player, steer)
          : fallbackAction(self, world, cfg.rules, steer).action;
      }
    } catch {
      fallback = true;
      fallbackReason = "jev_error";
      action = fallbackAction(self, world, cfg.rules, steer).action;
    }

    // minimum action hold time (anti-jitter), except when the new action is an attack
    if (
      r.lastAction &&
      action.type !== "attack" &&
      action.type !== r.lastAction.type &&
      t - r.lastActionChangedMs < cfg.minActionHoldMs
    ) {
      deps.logger.log({
        tick: world.tick, timeMs: world.timeMs, entity: self.id, state: ctx,
        jev: jevLog, action: r.lastAction, fallback: true, fallbackReason: "held", latencyMs: now() - t0,
      });
      return r.lastAction;
    }

    if (!r.lastAction || action.type !== r.lastAction.type) {
      r.lastActionChangedMs = t;
    }
    r.lastAction = action;

    deps.logger.log({
      tick: world.tick, timeMs: world.timeMs, entity: self.id, state: ctx,
      jev: jevLog, action, fallback, fallbackReason, ...(blocked ? { blocked: true } : {}), latencyMs: now() - t0,
    });
    return action;
  }

  /** One synchronous decision pass over a world snapshot. Exported for tests. */
  async function step(world: WorldState): Promise<Action[]> {
    memory.observe(world);
    const player = world.entities.find((e) => e.faction === "player" && e.hp > 0);
    const enemies = world.entities.filter((e) => e.faction === "enemy" && e.hp > 0);
    const alliesOf = (self: EntityState) => enemies.filter((e) => e.id !== self.id);

    await runSwarmBrain(world, enemies, player);

    const actions = await Promise.all(enemies.map((e) => decideEnemy(world, e, alliesOf(e), player)));
    // 出站校验（对应内置线的合法性校验理念）：形状非法的 action 丢弃，
    // 并强制执行游戏在 capabilities 里声明的 maxActionsPerTick 上限
    const raw: unknown[] = actions.filter((a) => a !== null);
    const valid: Action[] = [];
    const dropped: { entity: string; reason: "invalid" | "over_limit" }[] = [];
    for (const a of raw) {
      if (isAction(a)) {
        valid.push(a);
      } else {
        const id = typeof a === "object" && a !== null && "entityId" in a ? String((a as { entityId: unknown }).entityId) : "engine";
        dropped.push({ entity: id, reason: "invalid" });
      }
    }
    const cap = await maxActionsPerTick();
    let out = valid;
    if (cap !== null && valid.length > cap) {
      out = valid.slice(0, cap);
      for (const a of valid.slice(cap)) dropped.push({ entity: a.entityId, reason: "over_limit" });
    }
    for (const d of dropped) {
      deps.logger.log({
        tick: world.tick, timeMs: world.timeMs, entity: d.entity, state: null,
        jev: null, action: null, fallback: true, fallbackReason: d.reason, latencyMs: 0,
      });
    }

    // reflect harness-computed fields back for the game to consume:
    // 进程内接法直接写回实体；stdio 等传输接法靠 annotations 随 actions 帧下发
    const annotations: EntityAnnotation[] = enemies.map((e) => {
      const r = rt(e.id);
      e.aware = r.aware;
      e.morale = r.morale;
      e.swarmOrder = swarmOrder;
      return { id: e.id, aware: r.aware, morale: r.morale, swarmOrder };
    });
    await deps.adapter.execute(out, annotations);
    return out;
  }

  /** Pull one snapshot from the adapter and decide. */
  async function tick(): Promise<Action[]> {
    return step(await deps.adapter.getState());
  }

  /** Run the tick loop until dispose(). */
  function run(opts: { tickHz?: number; onTick?: (world: WorldState, actions: Action[]) => void; onError?: (error: unknown) => void } = {}) {
    const tickHz = opts.tickHz ?? 20;
    let running = true;
    let busy = false;
    const timer = setInterval(() => {
      if (!running || busy) return;
      busy = true;
      void (async () => {
        try {
          const world = await deps.adapter.getState();
          const actions = await step(world);
          opts.onTick?.(world, actions);
        } catch (e) {
          // adapter failure (e.g. game process exited): stop the loop
          running = false;
          clearInterval(timer);
          opts.onError?.(e);
        } finally {
          busy = false;
        }
      })();
    }, 1000 / tickHz);
    return {
      stop() {
        running = false;
        clearInterval(timer);
      },
    };
  }

  return {
    step,
    tick,
    run,
    currentSwarmOrder: () => swarmOrder,
    moraleOf: (id: string) => rt(id).morale,
    awareOf: (id: string) => rt(id).aware,
    dispose() {
      if (disposed) return;
      disposed = true;
      runtime.clear();
      memory.dispose();
      ctxBuilder.dispose();
    },
  };
}

export type Engine = ReturnType<typeof createEngine>;
