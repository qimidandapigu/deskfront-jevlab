import type { TurnBasedGame, RealtimeGame } from './plugin.js';
import type { Answers, AppliedAction, EffectSnapshot } from './decision.js';
import type { AssistancePolicy } from './assistance.js';

export type GameOutcome = 'won' | 'lost' | 'draw';
export interface MinimalView {
  observation: unknown;
  /** Engine-native commands and their meanings; no model-specific question construction. */
  actions: Record<string, string>;
  outcome: GameOutcome | null;
  /** Optional. Missing effect evidence stays unknown, never fabricated as progress. */
  effect?: EffectSnapshot;
}
export interface MinimalReceipt<S> {
  state: S;
  accepted: boolean;
  reason?: string;
}
export interface MinimalAdapter<S> {
  id: string;
  instructions: string;
  initial(): S;
  inspect(state: S): MinimalView;
  execute(state: S, action: string): MinimalReceipt<S>;
  assistance?: AssistancePolicy<S>;
}
export interface MinimalState<S> {
  world: S;
  tick: number;
  receipt: AppliedAction;
}

function common<S>(adapter: MinimalAdapter<S>) {
  const inspect = (s: MinimalState<S>) => adapter.inspect(s.world);
  return {
    id: adapter.id,
    initialState: (): MinimalState<S> => ({ world: adapter.initial(), tick: 0, receipt: { command: null } }),
    observe: (s: MinimalState<S>) => ({ state: inspect(s).observation, controller: 'minimal',
      assistance: adapter.assistance?.tools.map(tool => tool.id) ?? [] }),
    questions: (s: MinimalState<S>) => ({ action: { type: 'choice' as const, instructions: adapter.instructions, criteria: inspect(s).actions } }),
    isTerminal: (s: MinimalState<S>) => inspect(s).outcome !== null,
    outcome: (s: MinimalState<S>) => inspect(s).outcome,
    decision: {
      capture: (s: MinimalState<S>) => inspect(s).effect ?? { progress: null, position: null },
      describe: (s: MinimalState<S>) => s.receipt,
      ...(adapter.assistance ? { assistance: { tools: adapter.assistance.tools,
        ports: (s: MinimalState<S>) => adapter.assistance!.ports(s.world) } } : {}),
    },
  };
}
function execute<S>(adapter: MinimalAdapter<S>, s: MinimalState<S>, answers: Answers): MinimalState<S> {
  const selected = answers.action;
  if (selected?.type !== 'choice' || !Object.hasOwn(adapter.inspect(s.world).actions, selected.choice)) {
    return { ...s, receipt: { command: null, disposition: 'rejected', reason: 'invalid-command' } };
  }
  const result = adapter.execute(s.world, selected.choice);
  return { ...s, world: result.state, receipt: { command: selected.choice,
    disposition: result.accepted ? 'accepted' : 'rejected', reason: result.reason } };
}

/** Four bindings: initial state, observation/action declaration/result, and execution. */
export function createMinimalTurnGame<S>(adapter: MinimalAdapter<S>): TurnBasedGame<MinimalState<S>> {
  return { ...common(adapter),
    renderText: s => JSON.stringify(adapter.inspect(s.world).observation),
    act: (s, answers) => {
      const next = execute(adapter, s, answers);
      return { state: next, feedback: next.receipt.disposition === 'rejected' ? next.receipt.reason ?? 'engine-rejected' : null };
    },
  };
}

export interface MinimalRealtimeAdapter<S> extends MinimalAdapter<S> {
  tickMs: number;
  /** A finite lease is required; engine commands cannot stay pressed indefinitely. */
  actionTicks: number;
  step(state: S): S;
  release(state: S): S;
  /** Respawn/phase identity, when applicable. */
  contextKey?(state: S): string;
}
export function createMinimalRealtimeGame<S>(adapter: MinimalRealtimeAdapter<S>): RealtimeGame<MinimalState<S>> {
  if (!Number.isFinite(adapter.tickMs) || adapter.tickMs <= 0 || !Number.isSafeInteger(adapter.actionTicks) || adapter.actionTicks < 1)
    throw new Error('tickMs and actionTicks must be positive (actionTicks integer)');
  const base = common(adapter);
  return { ...base, tickMs: adapter.tickMs, decisionMs: adapter.tickMs,
    step: s => {
      const expired = s.receipt.expiresAt !== undefined && s.tick >= s.receipt.expiresAt;
      const world = expired ? adapter.release(s.world) : s.world;
      return { ...s, world: adapter.step(world), tick: s.tick + 1,
        ...(expired ? { receipt: { command: null, disposition: 'retained' as const } } : {}) };
    },
    act: (s, answers) => {
      const next = execute(adapter, s, answers);
      return next.receipt.disposition === 'accepted'
        ? { ...next, receipt: { ...next.receipt, expiresAt: s.tick + adapter.actionTicks } }
        : { ...next, world: adapter.release(next.world) };
    },
    decision: { ...base.decision,
      contextKey: s => adapter.contextKey?.(s.world) ?? '',
      schedule: { ready: s => s.receipt.expiresAt === undefined || s.tick >= s.receipt.expiresAt },
      release: s => ({ ...s, world: adapter.release(s.world), receipt: { command: null, disposition: 'retained' } }),
    },
  };
}
