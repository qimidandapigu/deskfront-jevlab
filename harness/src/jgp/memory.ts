import type { GameEvent, WorldState } from "./protocol.js";

/**
 * Memory: per-entity ring buffer of notable events + a rolling one-line summary.
 * v1 is fully rule-based (no LLM summarization).
 */

export interface MemoryConfig {
  ringSize: number;
  /** event types that must always be recorded. */
  alwaysRecord: string[];
}

export const DEFAULT_MEMORY: MemoryConfig = {
  ringSize: 8,
  alwaysRecord: ["damage", "death", "target_switch", "hp_change"],
};

export interface EntityMemory {
  events: string[];
  summary: string;
  lastHp: number | null;
  lastTarget: string | null;
}

export function createMemory(cfg: Partial<MemoryConfig> = {}) {
  const config: MemoryConfig = { ...DEFAULT_MEMORY, ...cfg };
  const store = new Map<string, EntityMemory>();

  function get(id: string): EntityMemory {
    let m = store.get(id);
    if (!m) {
      m = { events: [], summary: "no prior contact", lastHp: null, lastTarget: null };
      store.set(id, m);
    }
    return m;
  }

  function record(id: string, msg: string): void {
    const m = get(id);
    m.events.push(msg);
    if (m.events.length > config.ringSize) m.events.shift();
  }

  /** Ingest a world snapshot: record notable events, refresh summaries. */
  function observe(world: WorldState): void {
    for (const e of world.entities) {
      const m = get(e.id);
      if (m.lastHp !== null && e.hp < m.lastHp) {
        record(e.id, `t${world.tick} hp ${m.lastHp}->${e.hp}`);
      }
      if (m.lastHp !== null && m.lastHp > 0 && e.hp <= 0) {
        record(e.id, `t${world.tick} died`);
      }
      m.lastHp = e.hp;
      const hpFrac = Math.round((e.hp / e.maxHp) * 100);
      m.summary = `t${world.tick}: hp ${hpFrac}%, at (${Math.round(e.pos.x)},${Math.round(e.pos.y)})`;
    }
    for (const ev of world.events) {
      if (ev.entityId && (config.alwaysRecord.includes(ev.type) || isNotable(ev))) {
        record(ev.entityId, `t${ev.tick} ${ev.message}`);
      }
    }
  }

  function isNotable(ev: GameEvent): boolean {
    return /damage|death|target/i.test(ev.type);
  }

  function recentEvents(id: string): string[] {
    return get(id).events;
  }

  function summary(id: string): string {
    return get(id).summary;
  }

  return {
    observe,
    recentEvents,
    summary,
    dispose() {
      store.clear();
    },
  };
}

export type Memory = ReturnType<typeof createMemory>;
