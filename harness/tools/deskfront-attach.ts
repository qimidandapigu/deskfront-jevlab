/** Attach the shared complete Harness to a separately running game EXE. */
import { createRuntimeRegistry } from '../src/arena/runtime.js';
import { createAttachedDeskfrontRuntime } from '../src/deskfront/attached_runtime.js';
import { runDeskfrontSession } from '../src/deskfront/session-launch.js';
const flags = new Map<string, string>();
for (let i = 2; i < process.argv.length; i += 2) {
  const key = process.argv[i]!, value = process.argv[i + 1];
  if (!['--game', '--connection', '--seconds', '--requests', '--port', '--backend', '--spectator', '--report', '--exit-on-finish', '--levels', '--level-generator', '--config', '--env-file', '--annie', '--demo-rules', '--board-settings', '--headless'].includes(key) || !value) throw Error('Unknown/missing attachment option: ' + key);
  flags.set(key, value);
}

const levels = flags.get('--levels') ?? 'local';
if (flags.has('--game') && flags.has('--connection')) throw Error('Choose --game for a new game or --connection for an existing game');
if (!['local','ai'].includes(levels)) throw Error('--levels must be local or ai');
await runDeskfrontSession(flags, {
  runtimes: createRuntimeRegistry([createAttachedDeskfrontRuntime(process.env.PYTHON_BIN ?? 'python')]),
  variant: 'attached', levels: levels as 'local' | 'ai',
});
