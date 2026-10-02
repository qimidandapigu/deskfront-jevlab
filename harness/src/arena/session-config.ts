import type { GamePlugin } from './plugin.js';

/** Serializable, credential-free launch configuration shared by every entry point. */
export interface SessionConfig {
  variant?: string;
  mode?: 'ai' | 'human';
  backend?: string;
  rival?: string;
  seed?: number;
  gameOptions?: Record<string, unknown>;
  runtime?: { maxTurns?: number; maxTicks?: number; maxRequests?: number; requestTimeoutMs?: number; decisionMs?: number; durationMs?: number };
}

function object(value: unknown, label: string): asserts value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} must be an object`);
}

export function normalizeSessionConfig(plugin: Pick<GamePlugin, 'id' | 'variants' | 'mode' | 'humanControls' | 'options'>, input: unknown): SessionConfig {
  object(input, 'Session config');
  const allowed = ['variant', 'mode', 'backend', 'rival', 'seed', 'runtime', 'gameOptions'];
  for (const key of Object.keys(input)) if (!allowed.includes(key)) throw new Error(`Unknown session option: ${key}`);
  for (const key of ['variant', 'backend', 'rival'] as const) {
    if (input[key] !== undefined && (typeof input[key] !== 'string' || !input[key])) throw new Error(`Invalid ${key}`);
  }
  if (input.mode !== undefined && input.mode !== 'human' && input.mode !== 'ai') throw new Error('Invalid mode');
  if (input.variant !== undefined && !plugin.variants?.some(v => v.id === input.variant)) throw new Error(`Unknown ${plugin.id} variant: ${input.variant}`);
  if (input.seed !== undefined && (!Number.isInteger(input.seed) || Number(input.seed) < 0 || Number(input.seed) > 0xffffffff)) throw new Error('seed must be uint32');
  if (input.mode === 'human' && plugin.mode === 'realtime' && !plugin.humanControls) throw new Error('This game does not support human controls');
  if (input.runtime !== undefined) {
    object(input.runtime, 'runtime');
    for (const [key, value] of Object.entries(input.runtime)) {
      if (!['maxTurns', 'maxTicks', 'maxRequests', 'requestTimeoutMs', 'decisionMs', 'durationMs'].includes(key)) throw new Error(`Unknown runtime option: ${key}`);
      if (!Number.isSafeInteger(value) || Number(value) < 1) throw new Error(`${key} must be a positive integer`);
    }
  }
  const supplied = input.gameOptions === undefined ? {} : input.gameOptions;
  object(supplied, 'gameOptions');
  const resolved: Record<string, unknown> = {};
  for (const key of Object.keys(supplied)) if (!Object.hasOwn(plugin.options ?? {}, key)) throw new Error(`Unknown game option: ${key}`);
  for (const [key, schema] of Object.entries(plugin.options ?? {})) {
    const value = supplied[key] === undefined ? schema.default : supplied[key];
    if (value === undefined) continue;
    const valid = schema.type === 'integer' ? Number.isSafeInteger(value) : typeof value === schema.type;
    if (!valid || typeof value === 'number' && (!Number.isFinite(value) || schema.min !== undefined && value < schema.min || schema.max !== undefined && value > schema.max)
      || schema.enum && !schema.enum.includes(value as string | number | boolean)) throw new Error(`Invalid game option: ${key}`);
    resolved[key] = value;
  }
  return { ...structuredClone(input), ...(Object.keys(resolved).length ? { gameOptions: resolved } : {}) } as SessionConfig;
}

export function prepareGame(plugin: GamePlugin, input: unknown = {}) {
  const config = normalizeSessionConfig(plugin, input);
  if (plugin.mode === 'turn' && (config.runtime?.maxTicks !== undefined || config.runtime?.decisionMs !== undefined)) throw new Error('Turn games do not support maxTicks/decisionMs');
  if (plugin.mode === 'realtime' && config.runtime?.maxTurns !== undefined) throw new Error('Realtime games do not support maxTurns');
  const game = plugin.create(config.variant, { seed: config.seed, gameOptions: config.gameOptions });
  if (config.rival && (plugin.mode !== 'realtime' || !('rival' in game) || !game.rival || plugin.variants?.find(v => v.id === config.variant)?.rival === false)) {
    throw new Error('This game/variant does not support a rival model');
  }
  const runtime = config.runtime ?? {};
  return { config, game, runnerOptions: {
    ...(runtime.maxTurns === undefined ? {} : { maxTurns: runtime.maxTurns }),
    ...(runtime.maxTicks === undefined ? {} : { maxTicks: runtime.maxTicks }),
    ...(runtime.decisionMs === undefined ? {} : { decisionMs: runtime.decisionMs }),
    requests: { timeoutMs: runtime.requestTimeoutMs ?? 10000, ...(runtime.maxRequests === undefined ? {} : { maxRequests: runtime.maxRequests }) },
    ...(plugin.gating?.confidence === undefined ? {} : { confidenceThreshold: plugin.gating.confidence }),
    ...(plugin.gating?.highRisk === undefined ? {} : { highRiskThreshold: plugin.gating.highRisk }),
  } };
}
