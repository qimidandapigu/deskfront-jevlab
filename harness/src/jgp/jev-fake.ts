import type { JevClient, JevQuestions, JevResponse } from "./jev-types.js";
import type { TrimmedState } from "./context.js";

export interface FakeJevOptions {
  /** 0..1 probability of throwing (simulated outage). */
  failRate?: number;
  /** Force every answer's confidence below this value (simulated uncertainty). */
  forceConfidenceBelow?: number;
  /** Simulated latency, ms. */
  latencyMs?: number;
  now?: () => number;
}

function isTrimmed(v: unknown): v is TrimmedState {
  if (typeof v !== "object" || v === null) return false;
  const o = v as Record<string, unknown>;
  return typeof o.self === "object" && o.self !== null && typeof o.mission === "string";
}

interface SwarmState {
  swarm: true;
  avgHpFrac: number;
  minDistToPlayer: number | null;
}

interface HeuristicAnswer {
  choice?: string;
  noul?: boolean;
  score?: number;
  confidence: number;
}

function isSwarmState(v: unknown): v is SwarmState {
  if (typeof v !== "object" || v === null) return false;
  const o = v as Record<string, unknown>;
  return o.swarm === true && typeof o.avgHpFrac === "number";
}

function swarmHeuristic(state: SwarmState): HeuristicAnswer {
  if (state.avgHpFrac < 0.35) return { choice: "retreat", confidence: 0.85 };
  if (state.minDistToPlayer !== null && state.minDistToPlayer > 5) return { choice: "flank", confidence: 0.8 };
  return { choice: "focus_fire", confidence: 0.85 };
}

/**
 * Offline deterministic Jev: heuristic answers derived from the trimmed
 * state, with injectable failure / low-confidence modes for tests and
 * key-less demos.
 */
export function createFakeJevClient(opts: FakeJevOptions = {}): JevClient & { callCount: () => number } {
  const now = opts.now ?? Date.now;
  let calls = 0;
  let flip = 0; // deterministic pseudo-randomness for failRate

  function heuristic(state: TrimmedState, name: string): HeuristicAnswer {
    const hpFrac = state.self.hp / state.self.maxHp;
    const p = state.player;
    if (name === "action") {
      let c: string;
      if (hpFrac <= 0.3 && p) c = "flee";
      else if (p && p.dist <= 9) c = "attack";
      else if (p) c = state.self.swarmOrder?.type === "flank" ? "flank" : "chase";
      else c = "patrol";
      return { choice: c, confidence: 0.85 };
    }
    if (name === "aware") {
      return { noul: p !== null && p.dist <= 12, confidence: 0.9 };
    }
    if (name === "morale") {
      const healthyAllies = state.allies.filter((a) => a.hpFrac > 0.5).length;
      const s = hpFrac > 0.5 && (healthyAllies >= 2 || (p && p.dist < 6)) ? 2 : hpFrac > 0.3 ? 1 : 0;
      return { score: s, confidence: 0.8 };
    }
    return { choice: "hold", confidence: 0.5 };
  }

  return {
    callCount: () => calls,
    async systemOne(request): Promise<JevResponse> {
      calls += 1;
      const t0 = now();
      if (opts.failRate && opts.failRate > 0) {
        flip = (flip + 1) % 1000;
        if (flip / 1000 < opts.failRate) throw new Error("fake jev: injected failure");
      }
      const state = isTrimmed(request.state) ? request.state : null;
      const swarm = isSwarmState(request.state) ? request.state : null;
      const answers: JevResponse["answers"] = {};
      const questions: JevQuestions = request.questions;
      for (const name of Object.keys(questions)) {
        const base =
          name === "tactic" && swarm
            ? swarmHeuristic(swarm)
            : state
              ? heuristic(state, name)
              : { choice: "hold", confidence: 0.5 };
        let confidence = base.confidence;
        if (opts.forceConfidenceBelow !== undefined && confidence >= opts.forceConfidenceBelow) {
          confidence = Math.max(0, opts.forceConfidenceBelow - 0.1);
        }
        const a: { choice?: string; noul?: boolean; score?: number; confidence: number; probabilities?: Record<string, number> } = {
          confidence,
        };
        if (base.choice !== undefined) {
          a.choice = base.choice;
          a.probabilities = { [base.choice]: confidence };
        }
        if (base.noul !== undefined) a.noul = base.noul;
        if (base.score !== undefined) a.score = base.score;
        answers[name] = a;
      }
      return { answers, latencyMs: (opts.latencyMs ?? 0) + (now() - t0), model: "fake-jev" };
    },
    dispose() {},
  };
}
