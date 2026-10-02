import { createGameRegistry, type GameRegistry } from '../arena/registry.js';
import { sokobanPlugin } from './sokoban/index.js';
import { boxingPlugin } from './boxing/index.js';
import { jumpPlugin } from './jump/index.js';
import { soldiersPlugin } from './soldiers/index.js';

/** JEP v1 §5 便捷入口：返回已注册全部内置游戏的注册表实例。 */
export function createDefaultRegistry(): GameRegistry {
  const registry = createGameRegistry();
  registry.register(sokobanPlugin);
  registry.register(boxingPlugin);
  registry.register(jumpPlugin);
  registry.register(soldiersPlugin);
  return registry;
}
