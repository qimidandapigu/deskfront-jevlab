/** Start a player binary and attach immediately, before its offline fallback window. */
import { spawn } from 'node:child_process';
import { existsSync, statSync } from 'node:fs';
import { mkdir, mkdtemp, readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

/** Explicit launch override; attaching to an existing world cannot change its roster. */
export function resolveBoardSettings(path?: string, connection?: string, newGame = true): string | undefined {
  if (path === undefined) return undefined;
  if (connection || !newGame) throw Error('--board-settings requires a new game; use --game instead of attaching to an existing game');
  const file = resolve(path);
  if (!existsSync(file) || !statSync(file).isFile()) throw Error('Board settings file missing: ' + file);
  return file;
}

export function releaseArguments(folder: string, boardSettings?: string, headless = false): string[] {
  return ['--seconds', '0', '--wait-for-harness', '--output', folder,
    ...(headless ? ['--headless'] : []),
    ...(boardSettings ? ['--board-settings', boardSettings] : [])];
}

export interface OwnedHeadlessRelease {
  pid: number; connection: string; stop(): Promise<void>;
}

export async function startDeskfrontRelease(executable: string, options: {
  boardSettings?: string; headless?: boolean;
  signal?: AbortSignal;
  onHeadlessStarted?(owned: OwnedHeadlessRelease): void;
  onStarted?(pid:number):void;
} = {}): Promise<string> {
  const game = resolve(executable);
  if (!existsSync(game)) throw Error('Game executable missing: ' + game);
  const boardSettings = resolveBoardSettings(options.boardSettings);
  const outputRoot = resolve('output');
  await mkdir(outputRoot, { recursive: true });
  const folder = await mkdtemp(resolve(outputRoot, 'deskfront-exe-session-'));
  const connection = resolve(folder, 'connection.json');
  options.signal?.throwIfAborted();
  const child = spawn(game, releaseArguments(folder, boardSettings, options.headless),
    { windowsHide: true, stdio: 'ignore' });
  if (child.pid) options.onStarted?.(child.pid);
  let failure: Error | undefined;
  child.on('error', error => { failure = error; });
  // Visual games remain player-owned. Only an explicitly launched headless
  // process is owned by this bounded test session, including its engine child.
  if (!options.headless) child.unref();
  let stopping: Promise<void> | undefined;
  const stop = (): Promise<void> => stopping ??= (async () => {
    if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
    if (process.platform === 'win32') {
      await new Promise<void>((done, reject) => {
        const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
        killer.once('error', reject);
        killer.once('close', code => code === 0 || child.exitCode !== null ? done() : reject(Error('Could not stop owned headless game: ' + child.pid)));
      });
    } else child.kill('SIGTERM');
  })();
  try {
  if (options.headless && child.pid) options.onHeadlessStarted?.({ pid: child.pid, connection, stop });
  options.signal?.throwIfAborted();
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    options.signal?.throwIfAborted();
    if (failure) throw failure;
    if (child.exitCode !== null) throw Error('Game exited before attachment: ' + child.exitCode);
    let row: Record<string, unknown> | undefined;
    try { row = JSON.parse(await readFile(connection, 'utf8')); } catch { /* Initial or partial write. */ }
    options.signal?.throwIfAborted();
    if (row?.status === 'running') return connection;
    if (row?.status === 'closed') throw Error('Game closed before attachment');
    await new Promise(r => setTimeout(r, 100));
  }
  throw Error('Game did not become ready within 20 seconds; see ' + resolve(folder, 'game.log'));
  } catch (error) {
    if (options.headless) await stop();
    throw error;
  }
}
