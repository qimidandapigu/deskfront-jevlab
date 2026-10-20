import { readFile } from 'node:fs/promises';
import { dirname, extname, resolve, sep } from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { anniePage } from '../deskfront/annie-page.js';
const root = resolve(fileURLToPath(new URL('../deskfront/annie-assets/', import.meta.url)));
// Use the same resolution as the running Harness. In exported workspaces Node
// can use an ancestor's dependencies; a hard-coded local node_modules cannot.
const require = createRequire(import.meta.url);
const libraries = {
  three: resolve(dirname(require.resolve('three')), '..'),
  vrm: dirname(require.resolve('@pixiv/three-vrm')),
};
export function createAnnieRoutes(deps: {
  matches: { get(id: string): { gameId?: string; kind?: string } | undefined };
  host: { snapshot(id: string): unknown; setEnabled(id: string, enabled: boolean): unknown };
  audio(id: string, entryId: string): Buffer | undefined;
}) {
  return async (req: IncomingMessage, res: ServerResponse, url: URL, send: (code: number, body: string | Buffer, type?: string) => void) => {
    if (req.method === 'GET' && url.pathname === '/runtime/deskfront/annie') { send(200, anniePage(), 'text/html; charset=utf-8'); return true; }
    const asset = /^\/vendor\/open-annie\/(.+)$/.exec(url.pathname);
    const library = /^\/vendor\/annie-lib\/(three|vrm)\/(.+)$/.exec(url.pathname);
    if (asset || library) {
      if (req.method !== 'GET') { send(405, ''); return true; }
      const base = asset ? root : libraries[library![1] as keyof typeof libraries];
      const path = resolve(base, decodeURIComponent(asset?.[1] ?? library![2]!));
      const types: Record<string, string> = { '.js': 'text/javascript; charset=utf-8', '.json': 'application/json', '.vrm': 'model/gltf-binary', '.md': 'text/plain; charset=utf-8' };
      if (!path.startsWith(base + sep) || !types[extname(path)]) { send(404, ''); return true; }
      try { const bytes = await readFile(path); res.setHeader('Cache-Control', 'public, max-age=3600'); send(200, bytes, types[extname(path)]); }
      catch { send(404, ''); }
      return true;
    }
    const api = /^\/api\/deskfront\/annie\/([\w-]+)\/(state|start|stop|audio\/([\w-]+))$/.exec(url.pathname);
    if (!api) return false;
    const id = api[1]!, action = api[2]!;
    const match = deps.matches.get(id);
    if (match?.gameId !== 'deskfront') { send(404, '{}', 'application/json'); return true; }
    res.setHeader('Cache-Control', 'no-store');
    if (req.headers.origin && req.headers.origin !== `http://${req.headers.host}`) { send(403, '{}', 'application/json'); return true; }
    if (req.method === 'GET' && action === 'state') { send(200, JSON.stringify(deps.host.snapshot(id)), 'application/json'); return true; }
    if (req.method === 'GET' && api[3]) {
      const audio = deps.audio(id, api[3]); send(audio ? 200 : 404, audio ?? '', 'audio/mpeg'); return true;
    }
    if (req.method === 'POST' && ['start', 'stop'].includes(action)) {
      if (req.headers['content-type'] !== 'application/json') { send(415, '{}', 'application/json'); return true; }
      if (action === 'start' && match.kind !== 'ai') { send(409, '{"error":"AI spectator required"}', 'application/json'); return true; }
      send(200, JSON.stringify(deps.host.setEnabled(id, action === 'start')), 'application/json'); return true;
    }
    send(405, '{}', 'application/json'); return true;
  };
}
