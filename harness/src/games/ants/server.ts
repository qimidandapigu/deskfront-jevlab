import { readFile } from 'node:fs/promises';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { randomUUID } from 'node:crypto';
import type { BackendSource } from '../../arena/sessions.js';
import { createRequestManager } from '../../systemone/request.js';
import { antDecision } from './decision.js';
import { createState, command, moveTo, step, LEVELS, ROUTES, algorithmActions, DIRECTIONS, type State } from './engine.js';

type Manager = ReturnType<typeof createRequestManager>;
interface Session { id: string; state: State; mode: string; managers: Manager[]; busy: boolean; pending: boolean[]; nextAnt: number[]; statuses: string[]; route: number; lastSeen: number; next: number; requests: number; tokens: number; usageKnown: boolean; errors: number; messages: string[]; records: unknown[] }
export function createAntHandler(backends?: BackendSource) {
  const sessions = new Map<string, Session>();
  const stop = (s: Session) => { s.state.done = true; s.state.ants.forEach((_, i) => command(s.state, i, 'stop')); s.managers.forEach(m => m.cancel()); };
  const timer = setInterval(() => {
    for (const [id, s] of sessions) {
      if (Date.now() - s.lastSeen > 30_000) stop(s);
      if (Date.now() - s.lastSeen > 300_000) { sessions.delete(id); continue; }
      if (s.state.done) continue;
      if (s.mode === 'algorithm') {
        const route = ROUTES[s.state.level - 1]!, target = route[s.route]!;
        if (Math.hypot(target.x - s.state.pose.x, target.y - s.state.pose.y) < 5 && Math.abs(Math.atan2(Math.sin(target.angle - s.state.pose.angle), Math.cos(target.angle - s.state.pose.angle))) < .15 && s.route < route.length - 1) s.route++;
        algorithmActions(s.state, route[s.route]!).forEach((a, i) => command(s.state, i, a, 1));
      }
      step(s.state);
      if (s.state.done) { s.managers.forEach(m => m.cancel()); continue; }
      if (s.managers.length) {
        s.managers.forEach((manager, ant) => {
          if (s.pending[ant] || s.state.time < s.nextAnt[ant]! || manager.count >= 30) return;
          s.pending[ant] = true; s.busy = true;
          s.statuses[ant] = '等待模型回复';
          const observed = structuredClone(s.state), started = Date.now(); s.requests++;
          const decision = antDecision(observed, ant);
          void manager.request(decision.observation, decision.questions).then(response => {
            if (response.usage?.totalTokens === undefined) s.usageKnown = false; else s.tokens += response.usage.totalTokens;
            const record = { ant: ant + 1, time: s.state.time, ms: Date.now() - started, observation: decision.observation, response, executed: null as string | null };
            s.records.push(record);
            if (s.state.done) return;
            // A slow response to an unchanged scene is still useful. Reject geometric staleness.
            if (Math.hypot(s.state.pose.x - observed.pose.x, s.state.pose.y - observed.pose.y) > 65 || Math.abs(Math.atan2(Math.sin(s.state.pose.angle - observed.pose.angle), Math.cos(s.state.pose.angle - observed.pose.angle))) > .55) {
              s.statuses[ant] = '场景已变化，重新决策'; return;
            }
            const action = response.answers.force;
            if (!action || action.type !== 'choice' || !Object.hasOwn(DIRECTIONS, action.choice)) throw new Error('模型返回了无效拉力');
            command(s.state, ant, action.choice, 4); record.executed = action.choice;
            s.statuses[ant] = action.choice === 'stop' ? '模型选择松力' : `拉动 ${action.choice} · ${record.ms}ms`;
            s.messages.push(`${ant + 1}号：${s.statuses[ant]}`);
          }).catch(error => {
            s.usageKnown = false;
            const message = error instanceof Error ? error.message : String(error);
            s.records.push({ ant: ant + 1, time: s.state.time, ms: Date.now() - started, error: message, executed: null });
            if (!s.state.done) { s.errors++; s.statuses[ant] = message === 'request-timeout' ? '请求超时，将重试' : message; s.messages.push(`${ant + 1}号：${s.statuses[ant]}`); }
          }).finally(() => {
            s.pending[ant] = false; s.busy = s.pending.some(Boolean); s.nextAnt[ant] = s.state.time + 1;
            s.messages = s.messages.slice(-18);
            if (!s.state.done && !s.busy && s.managers.every(m => m.count >= 30)) { s.messages.push('已到请求上限，本局结束。'); stop(s); }
          });
        });
      }
    }
  }, 1000 / 30);
  timer.unref();
  return {
    close() { clearInterval(timer); sessions.forEach(stop); },
    async handle(req: IncomingMessage, res: ServerResponse, url: URL): Promise<boolean> {
      if (url.pathname !== '/ants' && !url.pathname.startsWith('/api/ants/')) return false;
      const send = (code: number, value: unknown) => { res.writeHead(code, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(value)); };
      try {
        if (url.pathname === '/ants' && req.method === 'GET') { res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); res.end(await readFile(new URL('./play.html', import.meta.url), 'utf8')); return true; }
        let body: Record<string, unknown> = {};
        if (req.method === 'POST') { let raw = ''; for await (const chunk of req) { raw += chunk; if (raw.length > 8192) throw new Error('请求太大'); } body = JSON.parse(raw || '{}'); }
        if (url.pathname === '/api/ants/start' && req.method === 'POST') {
          const mode = String(body.mode ?? 'human'), level = Number(body.level ?? 1);
          if (!['human', 'algorithm', 'jev', 'deepseek'].includes(mode) || !Number.isInteger(level) || level < 1 || level > 3) throw new Error('无效模式或关卡');
          if ([...sessions.values()].filter(s => !s.state.done).length >= 8) throw new Error('同时运行的对局过多');
          const managers = mode === 'jev' || mode === 'deepseek' ? Array.from({ length: 6 }, () => { if (!backends) throw new Error('模型后端未配置'); return createRequestManager(backends.create(mode), { timeoutMs: 12000, maxRequests: 30 }); }) : [];
          const id = randomUUID();
          sessions.set(id, { id, state: createState(level), mode, managers, busy: false, pending: Array(6).fill(false), nextAnt: Array(6).fill(0), statuses: Array(6).fill("准备决策"), route: 0, lastSeen: Date.now(), next: 0, requests: 0, tokens: 0, usageKnown: true, errors: 0, messages: [], records: [] });
          send(200, { id }); return true;
        }
        const match = /^\/api\/ants\/([\w-]+)\/(state|input|stop|history)$/.exec(url.pathname);
        if (!match) { send(404, { error: 'Unknown ant route' }); return true; }
        const s = sessions.get(match[1]!); if (!s) { send(404, { error: '对局已过期，请重新开始' }); return true; }
        s.lastSeen = Date.now(); const op = match[2];
        if ((op === 'state' || op === 'history') && req.method !== 'GET' || (op === 'input' || op === 'stop') && req.method !== 'POST') { send(405, { error: 'Method not allowed' }); return true; }
        if (op === 'stop') stop(s);
        if (op === 'input') {
          if (s.mode !== 'human' || s.state.done) throw new Error('当前对局不能接收手动操作');
          if (body.action === 'stopAll') s.state.ants.forEach((_, i) => command(s.state, i, 'stop'));
          else if (body.action === 'moveTo') {
            const target = body.target as { x: number; y: number };
            moveTo(s.state, Number(body.ant), target);
          }
          else command(s.state, Number(body.ant), String(body.action));
          s.records.push({ time: s.state.time, ant: body.ant, action: body.action, target: body.target, pose: { ...s.state.pose } });
        }
        if (op === 'history') send(200, { mode: s.mode, state: s.state, requests: s.requests, tokens: s.usageKnown ? s.tokens : null, cost: null, records: s.records });
        else send(200, { id: s.id, mode: s.mode, state: s.state, level: LEVELS[s.state.level - 1], requests: s.requests, tokens: s.usageKnown ? s.tokens : null, errors: s.errors, messages: s.messages.slice(-6), busy: s.busy, statuses: s.statuses });
      } catch (error) { send(400, { error: error instanceof Error ? error.message : String(error) }); }
      return true;
    },
  };
}
