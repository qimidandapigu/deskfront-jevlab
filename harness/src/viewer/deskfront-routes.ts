import type { IncomingMessage, ServerResponse } from 'node:http';

type Send = (status: number, body: string | Buffer, type?: string) => void;
type MatchLookup = { get(id: string): { gameId?: string } | undefined };
type DanmakuService = {
  snapshot(id: string): unknown;
  configure(id: string, enabled: boolean, density?: unknown): unknown;
};
type CommentaryService = {
  snapshot(id: string): unknown;
  setEnabled(id: string, enabled: boolean, volume?: unknown): unknown;
  volume(id: string, volume: number): unknown;
};

export interface DeskfrontOverlayRoutes {
  matches: MatchLookup;
  danmaku: DanmakuService;
  commentary: CommentaryService;
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', chunk => { data += chunk; });
    req.on('end', () => resolve(data));
    req.on('error', reject);
  });
}

/** Handles the two Deskfront spectator overlays without owning match lifecycle. */
export function createDeskfrontOverlayRoutes(deps: DeskfrontOverlayRoutes) {
  return async function handleDeskfrontOverlay(
    req: IncomingMessage,
    res: ServerResponse,
    url: URL,
    send: Send,
  ): Promise<boolean> {
    const danmakuRoute = /^\/api\/deskfront\/danmaku\/([\w-]+)\/(state|start|stop)$/.exec(url.pathname);
    if (danmakuRoute) {
      const [, matchId, action] = danmakuRoute;
      if (deps.matches.get(matchId!)?.gameId !== 'deskfront') { send(404, '{}', 'application/json'); return true; }
      res.setHeader('Cache-Control', 'no-store');
      if (req.headers.origin && req.headers.origin !== `http://${req.headers.host}`) { send(403, '{}', 'application/json'); return true; }
      if (req.method === 'GET' && action === 'state') { send(200, JSON.stringify(deps.danmaku.snapshot(matchId!)), 'application/json'); return true; }
      if (req.method === 'POST' && action !== 'state') {
        if (req.headers['content-type'] !== 'application/json') { send(415, '{}', 'application/json'); return true; }
        const body = JSON.parse((await readBody(req)) || '{}') as { density?: unknown };
        if (body.density !== undefined && !['low', 'normal'].includes(String(body.density))) { send(400, '{}', 'application/json'); return true; }
        send(200, JSON.stringify(deps.danmaku.configure(matchId!, action === 'start', body.density)), 'application/json');
        return true;
      }
      send(405, '{}', 'application/json');
      return true;
    }

    const commentaryRoute = /^\/api\/deskfront\/commentary\/([\w-]+)\/(start|state|stop|volume)$/.exec(url.pathname);
    if (commentaryRoute) {
      const [, matchId, action] = commentaryRoute;
      if (deps.matches.get(matchId!)?.gameId !== 'deskfront') { send(404, JSON.stringify({ error: 'Deskfront session not found' }), 'application/json'); return true; }
      res.setHeader('Cache-Control', 'no-store');
      // A remote page cannot cause billed speech generation in the local viewer.
      if (req.headers.origin && req.headers.origin !== `http://${req.headers.host}`) { send(403, '{}', 'application/json'); return true; }
      if (req.method === 'GET' && action === 'state') { send(200, JSON.stringify(deps.commentary.snapshot(matchId!)), 'application/json'); return true; }
      if (req.method === 'POST' && ['start', 'stop', 'volume'].includes(action!)) {
        if (req.headers['content-type'] !== 'application/json') { send(415, '{}', 'application/json'); return true; }
        const body = JSON.parse((await readBody(req)) || '{}') as { volume?: unknown };
        if (body.volume !== undefined && (typeof body.volume !== 'number' || !Number.isFinite(body.volume))) { send(400, '{}', 'application/json'); return true; }
        const result = action === 'volume'
          ? deps.commentary.volume(matchId!, typeof body.volume === 'number' ? body.volume : .75)
          : deps.commentary.setEnabled(matchId!, action === 'start', body.volume);
        send(200, JSON.stringify(result), 'application/json');
        return true;
      }
      send(405, '{}', 'application/json');
      return true;
    }
    return false;
  };
}
