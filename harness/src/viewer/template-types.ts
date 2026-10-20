import type { BackendSource, MatchState } from '../arena/sessions.js';
import type { GameRegistry } from '../arena/registry.js';
import type { ModelsConfig } from '../config.js';

export interface ExternalCatalogEntry {
  id: string; name: string; description: string;
  variants: Array<{ id: string; name: string; [key: string]: unknown }>;
  options: Record<string, unknown>;
  capabilities: { ai?: boolean; human?: boolean; seed?: boolean; [key: string]: unknown };
}

export interface HomeTemplateContext {
  registry: GameRegistry;
  catalog: Array<{ id: string; name: string; description?: string; page?: string; mode: string; capabilities: { human?: boolean; [key: string]: unknown }; [key: string]: unknown }>;
  matches: ReadonlyMap<string, MatchState>;
  config?: { get(): ModelsConfig };
  backends?: BackendSource;
  url: URL;
}

