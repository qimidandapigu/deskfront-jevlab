import { createRuntimeRegistry } from '../arena/runtime.js';
import { endlessRuntime } from './soldiers/endless-runtime.js';
import { jgpDemoRuntime } from '../jgp/runtime.js';
import { createDeskfrontRuntime } from '../deskfront/runtime.js';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { loadRegisteredGames } from '../external/manifests.js';

/** Non-JEP games use the same catalog and session lifecycle through runtime adapters. */
export function createBuiltinRuntimeRegistry(env: NodeJS.ProcessEnv = process.env) {
  const registry = createRuntimeRegistry([endlessRuntime, jgpDemoRuntime]);
  // Support both the standalone checkout (`quickplay-harness` next to
  // `deskfront-jevlab`) and the bundled checkout (`deskfront-jevlab/harness`).
  // An explicit DESKFRONT_ROOT always wins; otherwise choose the first
  // nearby directory that actually contains project.godot.
  const root = env.DESKFRONT_ROOT
    ? resolve(env.DESKFRONT_ROOT)
    : [resolve('..'), resolve('../deskfront-jevlab')]
      .find(candidate => existsSync(resolve(candidate, 'project.godot')))
      ?? resolve('../deskfront-jevlab');
  if (existsSync(resolve(root, 'project.godot'))) {
    const bundled = resolve(root, '../.artifacts/godot-4.5.1/Godot_v4.5.1-stable_win64_console.exe');
    registry.register(createDeskfrontRuntime({ root, python: env.PYTHON_BIN ?? 'python',
      godot: env.GODOT_BIN ?? (process.platform === 'win32' && existsSync(bundled) ? bundled : 'godot') }));
  }
  return registry;
}

export function createDefaultRuntimeRegistry(env: NodeJS.ProcessEnv = process.env) {
  const registry = createBuiltinRuntimeRegistry(env);
  loadRegisteredGames(registry, env.QUICKPLAY_GAMES_CONFIG ?? 'games.local.json');
  return registry;
}
