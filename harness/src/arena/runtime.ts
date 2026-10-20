import type { SystemOne } from '../systemone/types.js';
import type { SessionConfig } from './session-config.js';
import type { GameOption } from './plugin.js';

export interface RuntimeSnapshot {
  status: 'running' | 'done';
  outcome: string | null;
  observation: unknown;
  payload?: unknown;
  error?: string;
}
export interface RuntimeSession {
  snapshot(): RuntimeSnapshot;
  input?(body: Record<string, unknown>): void;
  action?(body: Record<string, unknown>): void;
  history(): unknown[];
  stop(): void;
  completion: Promise<void>;
}
export interface RuntimePlugin {
  options?: Record<string, GameOption>;
  maxSessions?: number;
  id: string;
  name: string;
  description: string;
  page?: string;
  variants: { id: string; name: string }[];
  capabilities: { human: boolean; ai: boolean; benchmark: boolean; seed: boolean };
  start(context: { id: string; logDir: string; createBackend(name?: string): SystemOne; backendName?: string }, config: SessionConfig): RuntimeSession;
}

export function createRuntimeRegistry(plugins: RuntimePlugin[] = []) {
  const entries = new Map<string, RuntimePlugin>();
  const registry = {
    register(plugin: RuntimePlugin) {
      if (!/^[\w-]+$/.test(plugin.id) || entries.has(plugin.id)) throw new Error(`Invalid/duplicate runtime: ${plugin.id}`);
      entries.set(plugin.id, plugin);
    },
    get: (id: string) => entries.get(id),
    list: () => [...entries.values()],
  };
  plugins.forEach(plugin => registry.register(plugin));
  return registry;
}
export type RuntimeRegistry = ReturnType<typeof createRuntimeRegistry>;
