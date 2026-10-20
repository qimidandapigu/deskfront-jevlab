import { createRuntimeRegistry } from '../arena/runtime.js';
import { createAttachedDeskfrontRuntime } from '../deskfront/attached_runtime.js';
export function createBuiltinRuntimeRegistry(env: NodeJS.ProcessEnv = process.env) {
  return createRuntimeRegistry([createAttachedDeskfrontRuntime(env.PYTHON_BIN ?? 'python')]);
}
export const createDefaultRuntimeRegistry = createBuiltinRuntimeRegistry;
