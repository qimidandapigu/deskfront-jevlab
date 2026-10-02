/**
 * Strategist ("command brain") interface. v1 ships DISABLED:
 * no DeepSeek, just a static default directive injected into the
 * context builder's `mission` field via the directive store.
 */

export interface Directive {
  mission: string;
  issuedAtMs: number;
  source: "strategist" | "default";
}

export interface Strategist {
  /** Current standing directive. Cheap, synchronous read. */
  current(): Directive;
  dispose(): void;
}

export const DEFAULT_MISSION = "Focus fire on the player; stay near the pack.";

export function createDisabledStrategist(deps: { now?: () => number } = {}): Strategist {
  const now = deps.now ?? Date.now;
  const directive: Directive = { mission: DEFAULT_MISSION, issuedAtMs: now(), source: "default" };
  return {
    current: () => directive,
    dispose() {},
  };
}
