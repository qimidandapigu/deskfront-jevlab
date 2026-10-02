import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdirSync, appendFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createRequestManager } from '../systemone/request.js';
import { invalidAnswers } from '../systemone/validation.js';
import type { RuntimePlugin } from '../arena/runtime.js';
import { GAME_PROTOCOL, validateQuestions, type GameMessage, type HarnessMessage } from './protocol.js';
import type { GameOption } from '../arena/plugin.js';

export interface ExternalGameManifest {
  /** Trusted host routing, never credentials or arbitrary backend selection from a game. */
  decisionRoles?: Record<string, string>;
  options?: Record<string, GameOption>;
  protocol: typeof GAME_PROTOCOL;
  id: string; name: string; description: string;
  command: string[]; cwd?: string; env?: Record<string, string>;
  variants?: { id: string; name: string }[];
  capabilities: { human: boolean; ai: boolean; seed: boolean };
  maxSessions?: number;
  startupTimeoutMs?: number;
}

/** The only process/model/session implementation required by new external games. */
export function createExternalGameRuntime(manifest: ExternalGameManifest): RuntimePlugin {
  if (manifest.protocol !== GAME_PROTOCOL || typeof manifest.id !== 'string' || !/^[\w-]+$/.test(manifest.id) || !Array.isArray(manifest.command) || !manifest.command.length || manifest.command.some(s => typeof s !== 'string' || !s)) throw new Error('Invalid external game manifest');
  return {
    id: manifest.id, name: manifest.name, description: manifest.description, variants: manifest.variants ?? [],
    options: manifest.options, maxSessions: manifest.maxSessions, capabilities: { ...manifest.capabilities, benchmark: false },
    start(context, config) {
      if (config.runtime?.maxTurns !== undefined || config.runtime?.maxTicks !== undefined || config.runtime?.decisionMs !== undefined) throw new Error('External games use durationMs and request budgets; engine limits belong in game options');
      const requests = createRequestManager(context.createBackend(config.backend), { timeoutMs: config.runtime?.requestTimeoutMs ?? 10000, maxRequests: config.runtime?.maxRequests ?? 100 });
      const roleRequests = new Map<string, ReturnType<typeof createRequestManager>>();
      let totalRequests = 0;
      const folder = resolve(context.logDir, context.id); mkdirSync(folder, { recursive: true });
      const logPath = resolve(context.logDir, `${context.id}.jsonl`);
      const log = (record: unknown) => appendFileSync(logPath, JSON.stringify(record) + '\n');
      const records: Record<string, unknown>[] = [];
      const remember = (record: Record<string, unknown>) => { records.push(record); if (records.length > 2000) records.shift(); log(record); };
      let active = true, ready = false, observation: unknown = null, payload: unknown = null;
      let outcome: string | null = null, error: string | undefined, pending = 0;
      const ids = new Set<string>();
      // Games receive launch settings and responses, never the provider credentials.
      const env: NodeJS.ProcessEnv = {};
      for (const [key, value] of Object.entries(process.env)) if (/^(path|pathext|systemroot|windir|home|userprofile|temp|tmp|appdata|localappdata|programdata|comspec|lang|lc_.*|display|wayland_display)$/i.test(key)) env[key] = value;
      Object.assign(env, manifest.env, { PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', QUICKPLAY_OUTPUT_DIR: folder });
      const child = spawn(manifest.command[0]!, manifest.command.slice(1), { cwd: manifest.cwd, env, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
      let complete!: () => void;
      const completion = new Promise<void>(r => { complete = r; });
      let startup: NodeJS.Timeout | undefined, duration: NodeJS.Timeout | undefined, force: NodeJS.Timeout | undefined;
      const send = (message: HarnessMessage) => { if (child.stdin?.writable) child.stdin.write(JSON.stringify(message) + '\n'); };
      child.stdin?.on('error', () => {});
      function finish(reason: string, cause?: unknown) {
        if (!active) return;
        active = false; outcome = reason;
        if (cause) error = cause instanceof Error ? cause.message : String(cause);
        if (startup) clearTimeout(startup); if (duration) clearTimeout(duration);
        requests.cancel('external-' + reason);
        for (const manager of roleRequests.values()) manager.cancel('external-' + reason);
        send({ type: 'stop' }); child.stdin?.end();
        force = setTimeout(() => {
          if (process.platform === 'win32' && child.pid) spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
          else child.kill();
        }, 4000);
        force.unref();
      }
      child.once('error', cause => finish('error', cause));
      child.once('close', code => {
        if (active) finish('error', new Error(`Game exited without an end message: ${code}`));
        if (force) clearTimeout(force);
        log({ type: 'outcome', game: manifest.id, outcome, error, config, requests: totalRequests });
        complete();
      });
      child.stderr?.on('data', data => appendFileSync(resolve(folder, 'host.log'), data));
      const lines = createInterface({ input: child.stdout! });
      lines.on('line', line => {
        if (!active) return;
        try {
          if (line.length > 2_000_000) throw new Error('Game message too large');
          const message = JSON.parse(line) as GameMessage;
          if (!message || typeof message !== 'object') throw new Error('Invalid game message');
          if (message.type === 'ready') {
            if (ready || message.protocol !== GAME_PROTOCOL) throw new Error('Protocol handshake mismatch');
            ready = true; clearTimeout(startup); return;
          }
          if (!ready) throw new Error('Game must acknowledge the protocol before sending data');
          if (message.type === 'state') { observation = message.observation; payload = message.payload ?? null; return; }
          if (message.type === 'end') {
            if (typeof message.outcome !== 'string' || !message.outcome || message.error !== undefined && typeof message.error !== 'string') throw new Error('Invalid end message');
            finish(message.outcome, message.error); return;
          }
          if (message.type === 'record') {
            if (!message.record || typeof message.record !== 'object' || Array.isArray(message.record)) throw new Error('Invalid record');
            remember({ type: 'game-record', game: manifest.id, record: message.record }); return;
          }
          if (message.type !== 'request') throw new Error('Unknown game message type');
          if (typeof message.id !== 'string' || !message.id || message.id.length > 128 || ids.has(message.id)) throw new Error('Invalid or duplicate request id');
          validateQuestions(message.questions);
          if (message.role !== undefined && (typeof message.role !== 'string' || !Object.hasOwn(manifest.decisionRoles ?? {}, message.role))) throw new Error('Unknown decision role');
          if (pending >= 16 || ids.size >= 10000) { send({ type: 'response', id: message.id, error: 'request_capacity_exceeded' }); return; }
          if (totalRequests >= (config.runtime?.maxRequests ?? 100)) {
            send({ type: 'response', id: message.id, error: 'request-budget' });
            if (manifest.id === 'deskfront') {
              remember({ type: 'request-budget-exhausted', game: manifest.id, requests: totalRequests });
              finish('request-budget');
            }
            return;
          }
          let manager = requests;
          if (message.role) {
            // Keep live tactical commands bounded: a plan arriving after the
            // squad has crossed the map is no longer useful. Experience
            // analysis is deliberately allowed its longer analyst budget and
            // runs independently of the combat command route.
            const roleBackend = manifest.decisionRoles![message.role];
            const configuredTimeout = config.runtime?.requestTimeoutMs ?? 10000;
            const timeoutMs = message.role === 'commander'
              ? Math.min(configuredTimeout, 18000)
              : roleBackend === 'analyst'
                ? Math.min(configuredTimeout, 35000)
                : configuredTimeout;
            if (!roleRequests.has(message.role)) roleRequests.set(message.role, createRequestManager(context.createBackend(config.backend === 'mock' ? 'mock' : roleBackend), { timeoutMs }));
            manager = roleRequests.get(message.role)!;
          }
          totalRequests++;
          ids.add(message.id); pending++;
          const requestedAt = performance.now();
          void manager.request(message.state, message.questions).then(response => {
            const invalid = invalidAnswers(message.questions, response.answers); if (invalid) throw new Error(invalid);
            if (!active) return;
            remember({ type: 'decision', game: manifest.id, id: message.id, role: message.role ?? 'executor', response,
              execution: { schema: 'quickplay-execution-v1', id: message.id, status: 'pending', rawAnswers: response.answers, executedAnswers: null, action: null, reason: 'awaiting-engine-receipt' } });
            send({ type: 'response', id: message.id, response });
          }).catch(cause => {
            if (!active) return;
            const reason = cause instanceof Error ? cause.message : String(cause);
            remember({ type: 'decision-error', game: manifest.id, id: message.id, role: message.role ?? 'executor', error: reason,
              elapsedMs: Math.max(0, Math.round(performance.now() - requestedAt)) });
            send({ type: 'response', id: message.id, error: reason });
          }).finally(() => { pending--; });
        } catch (cause) { finish('error', cause); }
      });
      startup = setTimeout(() => finish('error', new Error('Game handshake timed out')), manifest.startupTimeoutMs ?? 10000);
      if (config.runtime?.durationMs) duration = setTimeout(() => finish('time-limit'), config.runtime.durationMs);
      send({ type: 'start', protocol: GAME_PROTOCOL, sessionId: context.id, config });
      return {
        completion, stop: () => finish('aborted'), history: () => structuredClone(records),
        snapshot: () => ({ status: active ? 'running' : 'done', outcome, error, observation,
          payload: { phase: ready ? 'ready' : 'starting', game: payload, requests: totalRequests, logPath } }),
        ...(manifest.capabilities.human ? { input(body: Record<string, unknown>) { send({ type: 'input', body }); }, action(body: Record<string, unknown>) { send({ type: 'action', body }); } } : {}),
      };
    },
  };
}
