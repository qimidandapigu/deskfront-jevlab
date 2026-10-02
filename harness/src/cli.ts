import { createDefaultRuntimeRegistry, createBuiltinRuntimeRegistry } from './games/runtimes.js';
import { createJgpRuntime } from './jgp/runtime.js';
import type { RuntimeRegistry } from './arena/runtime.js';
import { registerGameManifest } from './external/manifests.js';
import { createDefaultRegistry } from './games/index.js';
import { createSessionService } from './arena/sessions.js';
import type { SessionConfig } from './arena/session-config.js';
import { loadEnvironment, createConfiguredBackend, defaultBackendName } from './config.js';
import type { RealtimeGame, TurnBasedGame } from './arena/plugin.js';


/** CLI and HTTP share exactly the same session lifecycle. */
async function play(args: string[]): Promise<void> {
  const gameId = args[0] && !args[0].startsWith('--') ? args.shift()! : 'sokoban';
  const config: SessionConfig = { backend: defaultBackendName(), runtime: {} };
  const runtimeFlags = { 'max-turns': 'maxTurns', 'max-ticks': 'maxTicks', 'max-requests': 'maxRequests', 'timeout-ms': 'requestTimeoutMs', 'decision-ms': 'decisionMs', 'duration-ms': 'durationMs' } as const;
  for (let i = 0; i < args.length; i += 2) {
    const key = args[i]!.replace(/^--/, ''), value = args[i + 1];
    if (!args[i]!.startsWith('--') || !value) throw new Error(`Missing CLI argument: ${args[i]}`);
    if (key === 'variant' || key === 'backend' || key === 'rival') config[key] = value;
    else if (key === 'options') config.gameOptions = JSON.parse(value) as Record<string, unknown>;
    else if (key === 'seed') config.seed = Number(value);
    else if (Object.hasOwn(runtimeFlags, key)) config.runtime![runtimeFlags[key as keyof typeof runtimeFlags]] = Number(value);
    else throw new Error(`Unknown CLI argument: ${key}`);
  }
  await executeSession(gameId, config);
}

async function executeSession(gameId: string, config: SessionConfig, runtimes: RuntimeRegistry = createDefaultRuntimeRegistry()): Promise<void> {
  const registry = createDefaultRegistry();
  const sessions = createSessionService({ registry, runtimes, backend: createConfiguredBackend('mock'),
    backends: { names: ['mock', 'jev', 'deepseek', 'openrouter'], defaultName: config.backend, create: name => createConfiguredBackend(name) },
    startDelayMs: 0, turnDelayMs: 0 });
  let id: string | undefined;
  const stop = () => { if (id) sessions.stop(id); };
  process.on('SIGINT', stop);
  try {
    id = sessions.start(gameId, config).matchId;
    const result = await sessions.wait(id);
    console.log(JSON.stringify({ matchId: id, ...result }, null, 2));
    console.log(`决策日志: logs/${id}.jsonl`);
    if (result.outcome === 'error') process.exitCode = 1;
  } finally { process.removeListener('SIGINT', stop); await sessions.close(); }
}

/** 不开对局、不调 API：打印某游戏 initialState 下 observe() + questions() 的完整 JSON。 */
function inspect(gameId: string, variant?: string): void {
  const registry = createDefaultRegistry();
  const plugin = registry.get(gameId);
  const game = plugin.create(variant);
  const state = game.initialState();
  const observation = plugin.mode === 'turn'
    ? (game as TurnBasedGame<unknown>).observe(state, { turn: 0, recent: [], feedback: null })
    : (game as RealtimeGame<unknown>).observe(state);
  console.log(JSON.stringify({ observe: observation, questions: game.questions(state) }, null, 2));
}

/**
 * 外部游戏（JGP stdio）：spawn 子进程，hello 握手后跑决策循环。
 * 用法: tsx src/cli.ts run -- <command...>
 * JEV_RUN_SECONDS 可限定运行时长（默认无限，子进程退出或 Ctrl+C 结束）。
 */
async function run(command: string[]): Promise<void> {
  const runtimes = createDefaultRuntimeRegistry();
  runtimes.register(createJgpRuntime({ id: 'external', name: 'External JGP game', command }));
  const seconds = Number(process.env.JEV_RUN_SECONDS ?? 0);
  if (!Number.isFinite(seconds) || seconds < 0) throw new Error('JEV_RUN_SECONDS must be non-negative');
  await executeSession('external', { backend: process.env.JEV_BACKEND ?? defaultBackendName(),
    ...(seconds > 0 ? { runtime: { durationMs: Math.max(1, Math.round(seconds * 1000)) } } : {}) }, runtimes);

}

async function main(): Promise<void> {
  loadEnvironment();
  const [cmd, ...rest] = process.argv.slice(2);
  if (cmd === 'register') {
    if (rest.length !== 1) throw new Error('Usage: jev register <game.json>');
    const reservedIds = [...createDefaultRegistry().list(), ...createBuiltinRuntimeRegistry().list()].map(game => game.id);
    console.log(`Registered: ${registerGameManifest(rest[0]!, process.env.QUICKPLAY_GAMES_CONFIG ?? 'games.local.json', reservedIds)}`);
    return;
  }
  if (cmd === 'list') {
    const registry = createDefaultRegistry();
    const service = createSessionService({ registry, runtimes: createDefaultRuntimeRegistry(), backend: createConfiguredBackend('mock') });
    try { console.log(JSON.stringify(service.catalog(), null, 2)); } finally { await service.close(); }
    return;
  }
  if (cmd === 'run') {
    const command = rest[0] === '--' ? rest.slice(1) : rest;
    if (command.length === 0) {
      console.error('用法: tsx src/cli.ts run -- <command...>');
      process.exitCode = 1;
      return;
    }
    await run(command);
    return;
  }
  if (cmd === 'inspect') {
    const [gameId, variant] = rest;
    if (!gameId) {
      console.error('用法: tsx src/cli.ts inspect <game> [variant]');
      process.exitCode = 1;
      return;
    }
    inspect(gameId, variant);
    return;
  }
  if (cmd && cmd !== 'play') {
    console.error(`未知子命令: ${cmd}（可用: play, run, inspect, list, register）`);
    process.exitCode = 1;
    return;
  }
  await play(rest);
}

main().catch(error => { console.error(error); process.exitCode = 1; });
