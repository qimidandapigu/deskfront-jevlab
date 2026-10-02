import type { IncomingMessage, ServerResponse } from 'node:http';
import { readFile } from 'node:fs/promises';
import type { createSessionService } from '../../arena/sessions.js';

/** Compatibility routes only. All state/timers/models belong to the session service. */
export function createEndlessHandler(sessions: ReturnType<typeof createSessionService>) {
  return {
    async handle(req: IncomingMessage, res: ServerResponse, url: URL): Promise<boolean> {
      if (url.pathname === '/game/soldiers-endless') {
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end(await readFile(new URL('./endless.html', import.meta.url), 'utf8')); return true;
      }
      if (!url.pathname.startsWith('/api/endless/')) return false;
      const operation = url.pathname.slice('/api/endless/'.length);
      const send = (status: number, data: unknown) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(data)); };
      try {
        if (req.method !== (operation === 'state' ? 'GET' : 'POST')) { send(405, { error: 'Method not allowed' }); return true; }
        let raw = ''; for await (const chunk of req) { raw += chunk; if (raw.length > 4096) throw new Error('请求过大'); }
        const body = raw ? JSON.parse(raw) : {};
        if (operation === 'start') {
          const { matchId } = sessions.start('soldiers-endless', { mode: 'human', variant: body.mode === 'random' ? 'random' : 'model', seed: body.seed ?? 42, ...(body.backend ? { backend: body.backend } : {}) });
          send(200, sessions.state(matchId).payload); return true;
        }
        const id = url.searchParams.get('id') ?? '';
        if (sessions.state(id).gameId !== 'soldiers-endless') throw new Error('Unknown endless session');
        if (operation === 'stop') { sessions.stop(id); send(200, { ok: true }); return true; }
        if (operation === 'input') sessions.input(id, body);
        else if (operation === 'next') sessions.action(id, { choice: 'next' });
        else if (operation !== 'state') { send(404, { error: 'Unknown operation' }); return true; }
        send(200, sessions.state(id).payload);
      } catch (error) { send(400, { error: error instanceof Error ? error.message : String(error) }); }
      return true;
    },
  };
}
