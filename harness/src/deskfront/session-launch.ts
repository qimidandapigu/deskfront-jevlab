/** Shared session/spectator lifecycle for source and binary Deskfront. No game ownership. */
import { loadEnvironment, createConfiguredBackend, defaultBackendName, type ModelsConfig } from '../config.js';
import { createGameRegistry } from '../arena/registry.js';
import type { RuntimeRegistry } from '../arena/runtime.js';
import { startViewer } from '../viewer/server.js';
import { writeFile, mkdir, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { startNativeAnnie } from './annie-native.js';
import { resolveBoardSettings, startDeskfrontRelease, type OwnedHeadlessRelease } from './release-launch.js';
import type { ChildProcess } from 'node:child_process';

export function nativeSpectatorPid(game: Record<string, any> | undefined): number | undefined {
  const pid = Number(game?.enginePid);
  return game?.engineLive !== false && Number.isSafeInteger(pid) && pid > 0 ? pid : undefined;
}
/** Fixed opening beats are opt-in; AI generation and legal choices stay enabled. */
export function demoRuleOptions(value: string | undefined): Record<string, boolean> {
  if (value !== undefined && value !== 'true' && value !== 'false') throw Error('--demo-rules must be true or false');
  return { openingRescueRule: value === 'true', secondStageTankRule: value === 'true' };
}
/** Explicit EXE-only mode; a connection cannot turn an existing game headless. */
export function headlessSessionOptions(flags: Map<string, string>) {
  const value = flags.get('--headless');
  if (value !== undefined && value !== 'true' && value !== 'false') throw Error('--headless must be true or false');
  const headless = value === 'true';
  if (headless && (!flags.has('--game') || flags.has('--connection'))) throw Error('--headless requires --game for a new owned game');
  return { headless, spectator: !headless && flags.get('--spectator') !== 'false',
    annie: !headless && flags.get('--annie') !== 'false',
    exitOnFinish: headless || flags.get('--exit-on-finish') === 'true' };
}
export function headlessTerminalReason(game: Record<string, any> | undefined): string | undefined {
  if (game?.awaitingRestart === true || game?.world?.world_growth?.mission?.status === 'failed'
      || game?.world_growth?.mission?.status === 'failed') return 'mission_failed';
  return undefined;
}
export async function runDeskfrontSession(flags: Map<string, string>, launch: {
  runtimes: RuntimeRegistry; variant: 'attached' | 'infinite'; levels: 'local' | 'ai';
  gameOptions?: Record<string, unknown>;
}) {
loadEnvironment(flags.get('--env-file') ?? '.env');
const modelConfig = flags.has('--config') ? JSON.parse(await readFile(resolve(flags.get('--config')!), 'utf8')) as ModelsConfig : undefined;
const backend = flags.get('--backend') ?? modelConfig?.defaultModel ?? defaultBackendName();
const levels = launch.levels;
const demoRules = demoRuleOptions(flags.get('--demo-rules'));
const presentation = headlessSessionOptions(flags);
const boardSettings = resolveBoardSettings(flags.get('--board-settings'), flags.get('--connection'), launch.variant === 'infinite' || flags.has('--game'));
if (!['local', 'ai'].includes(levels)) throw Error('--levels must be local or ai');
if (launch.variant === 'attached' && levels === 'ai' && !flags.has('--level-generator')) throw Error('AI levels require --level-generator <private provider.py>');
if (levels === 'local' && flags.has('--level-generator')) throw Error('Private generator requires explicit --levels ai');
const seconds = Number(flags.get('--seconds') ?? 180), requests = Number(flags.get('--requests') ?? 300);
if (!Number.isFinite(seconds) || seconds < 1 || !Number.isInteger(requests) || requests < 1) throw Error('Invalid seconds/requests');
const server = await startViewer({ port: Number(flags.get('--port') ?? 3807), startDelayMs: 0,
  registry: createGameRegistry(), runtimes: launch.runtimes, backend: createConfiguredBackend('mock'),
  backends: { names: ['mock', 'jev', 'deepseek'], defaultName: backend, create: name => createConfiguredBackend(name, process.env, modelConfig) } });
const url = 'http://127.0.0.1:' + server.port;
const post = async (path: string, body: object) => {
  const response = await fetch(url + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const value = await response.json() as Record<string, any>;
  if (!response.ok) throw Error(value.error ?? 'HTTP ' + response.status);
  return value;
};
let closed = false;
const launchAbort = new AbortController();
let nativeAnnie: ChildProcess | undefined;
let ownedHeadless: OwnedHeadlessRelease | undefined;
let report: Record<string, unknown> | undefined;
let launchedGamePid:number|undefined;
const saveReport = async () => {
  if (report && flags.has('--report')) {
    const file = resolve(flags.get('--report')!); await mkdir(resolve(file, '..'), { recursive: true });
    await writeFile(file, JSON.stringify(report, null, 2));
  }
};
let closing: Promise<void> | undefined;
const close = (reason = 'session_finished'): Promise<void> => closing ??= (async () => { closed = true; nativeAnnie?.kill();
  launchAbort.abort(Error(reason));
  if (presentation.headless && report && reason.startsWith('interrupted:')) report.result ??= {
    status: 'interrupted', reason, finishedAt: new Date().toISOString(),
  };
  const lifecycle: Record<string, unknown> = { reason, ownedGamePid: ownedHeadless?.pid, startedAt: new Date().toISOString() };
  try { await server.close(); } finally {
    try { await ownedHeadless?.stop(); lifecycle.ownedProcessStop = 'completed'; }
    catch (error) { lifecycle.ownedProcessStop = 'error'; lifecycle.error = error instanceof Error ? error.message : String(error); throw error; }
    finally {
      lifecycle.finishedAt = new Date().toISOString();
      if (presentation.headless) {
        if (report) { report.lifecycle = lifecycle; await saveReport(); }
        if (ownedHeadless) await writeFile(resolve(ownedHeadless.connection, '..', 'headless-lifecycle.json'), JSON.stringify(lifecycle, null, 2));
      }
    }
  }
})();
process.once('SIGINT', () => void close('interrupted:SIGINT').catch(error => console.error(error)));
process.once('SIGTERM', () => void close('interrupted:SIGTERM').catch(error => console.error(error)));
try {
  // Prepare the server first, then launch and attach in one operation. A manual
  // gap between two terminal commands can exceed the game's 30-second grace.
  const connection = flags.has('--game') ? await startDeskfrontRelease(flags.get('--game')!, {
    boardSettings, headless: presentation.headless, signal: launchAbort.signal,
    onStarted: pid => { launchedGamePid=pid; },
    onHeadlessStarted: owned => { ownedHeadless = owned; },
  }) : flags.get('--connection');
  if (closed) { await closing; return; }
  const start = await post('/api/match/deskfront', { backend, variant: launch.variant, mode: 'ai',
    gameOptions: { ...launch.gameOptions, ...demoRules, ...(boardSettings && launch.variant === 'infinite' ? { boardSettingsPath: boardSettings } : {}), ...(connection ? { connectionFile: resolve(connection) } : {}), attachedWorldGeneration: levels === 'ai',
      ...(launch.variant === 'attached' && levels === 'ai' ? { levelGeneratorModule: resolve(flags.get('--level-generator')!) } : {}) },
    runtime: { durationMs: seconds * 1000, maxRequests: requests, requestTimeoutMs: 30000 } });
  const id = start.matchId as string;
  let presentationWritten = false;
  const writePresentation = async (folder: string) => {
    await writeFile(resolve(folder, 'presentation.json'), JSON.stringify({
      directorUrl: url + '/api/deskfront/director/' + id,
      directorPage: url + '/runtime/deskfront/director?session=' + id,
      runtimeStatusUrl: url + '/api/deskfront/runtime-status/' + id,
    }));
    presentationWritten = true;
  };
  // Read-only native panels share the existing director projection, not a
  // second interpretation of generation logs. This file contains no secrets.
  if (connection && launch.variant === 'attached') {
    await writePresentation(resolve(connection, '..'));
  }
  report = { ...(launchedGamePid?{launchedGamePid}:{}), matchId: id, url: url + '/runtime/deskfront?session=' + id, mode: launch.variant === 'attached' ? 'attached-exe' : 'source-full', backend, levels, demoRules: demoRules.openingRescueRule,
    ...(presentation.headless ? { headless: true, ownedGamePid: ownedHeadless?.pid, spectator: false, annie: false, exitOnFinish: true } : {}),
    ...(boardSettings ? { boardSettings } : {}), ...(connection ? { connection: resolve(connection) } : {}) };
  await saveReport();
  console.log(JSON.stringify(report));
  let enabled = false;
  let terminalReason: string | undefined;
  while (!closed) {
    await new Promise(r => setTimeout(r, 500));
    if (closed) break;
    const response = await fetch(url + '/api/match/' + id + '/state?compact=1');
    const state = await response.json() as Record<string, any>;
    const game = state.payload?.game ?? state.payload;
    if (!presentationWritten && launch.variant === 'infinite' && typeof game?.engineRoot === 'string') {
      await writePresentation(resolve(game.engineRoot, '..'));
    }
    if (presentation.headless && !terminalReason && state.status !== 'done') {
      terminalReason = headlessTerminalReason(game);
      if (terminalReason) {
        report.headlessTerminal = { reason: terminalReason, observedAt: new Date().toISOString(), game,
          observation: state.finalObservation ?? state.latest?.observation };
        await post('/api/match/' + id + '/stop', {});
      }
    }
    if (!enabled && nativeSpectatorPid(game) && presentation.spectator && backend !== 'mock') {
      await post('/api/deskfront/commentary/' + id + '/start', {});
      await post('/api/deskfront/danmaku/' + id + '/start', { density: 'low' });
      if (presentation.annie) {
        try { nativeAnnie = await startNativeAnnie(Number(game.enginePid), url + '/runtime/deskfront/annie?session=' + id + '&embedded=1', resolve('logs','annie',id));
          nativeAnnie.on('error', error => console.error('Annie host: ' + error.message)); }
        catch(error){ console.error('Annie host: '+(error instanceof Error?error.message:String(error))); }
      }
      enabled = true;
    }
    if (state.status === 'done') {
      console.log(JSON.stringify({ matchId: id, outcome: state.outcome, error: state.error,
        commentary: await (await fetch(url + '/api/deskfront/commentary/' + id + '/state')).json(),
        danmaku: await (await fetch(url + '/api/deskfront/danmaku/' + id + '/state')).json() }));
      if (presentation.headless) {
        report.result = { status: state.status, outcome: state.outcome, error: state.error,
          terminalReason: terminalReason ?? 'session_finished', finishedAt: new Date().toISOString(), game,
          observation: state.finalObservation ?? state.latest?.observation };
        await saveReport();
      }
      if (presentation.exitOnFinish) await close();
      else break;
    }
  }
} catch (error) {
  if (presentation.headless && report) {
    report.result ??= { status: 'error', error: error instanceof Error ? error.message : String(error), finishedAt: new Date().toISOString() };
    await saveReport();
  }
  await close('session_error'); throw error;
}

}
