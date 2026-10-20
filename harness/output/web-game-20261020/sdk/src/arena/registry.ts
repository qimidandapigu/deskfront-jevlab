import type { GamePlugin } from './plugin.js';

export interface GameRegistry {
  register(plugin: GamePlugin): void;
  get(id: string): GamePlugin;
  list(): GamePlugin[];
}

/** JEP v1 §5：注册表由宿主显式创建，实例间互不影响。 */
export function createGameRegistry(): GameRegistry {
  const plugins = new Map<string, GamePlugin>();
  return {
    register(plugin) {
      if (plugins.has(plugin.id)) throw new Error(`游戏重复注册: ${plugin.id}`);
      plugins.set(plugin.id, plugin);
    },
    get(id) {
      const plugin = plugins.get(id);
      if (!plugin) throw new Error(`未注册的游戏: ${id}`);
      return plugin;
    },
    list() {
      return [...plugins.values()];
    },
  };
}
