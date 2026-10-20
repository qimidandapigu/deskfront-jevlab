import type { IncomingMessage, ServerResponse } from 'node:http';
import { extname, resolve, dirname, sep } from 'node:path';
import { readFile } from 'node:fs/promises';
import type { GameRegistry } from '../arena/registry.js';
import { sendJson, type SendResponse } from './http.js';

export interface StaticRouteContext {
  registry: GameRegistry;
  kaplayUmd: string;
}

/** Static game assets are isolated here so the main server does not own path/security details. */
export async function handleStaticRoute(
  req: IncomingMessage,
  _res: ServerResponse,
  url: URL,
  context: StaticRouteContext,
  send: SendResponse,
): Promise<boolean> {
  if (req.method === 'GET' && url.pathname === '/vendor/kaplay.js') {
    send(200, await readFile(context.kaplayUmd), 'text/javascript; charset=utf-8');
    return true;
  }
  const clientJs = /^\/client\/([\w-]+)\.js$/.exec(url.pathname);
  if (req.method === 'GET' && clientJs) {
    const plugin = context.registry.get(clientJs[1]!);
    send(200, await readFile(plugin.clientScript, 'utf8'), 'text/javascript; charset=utf-8');
    return true;
  }
  const asset = /^\/assets\/([\w-]+)\/(.+)$/.exec(url.pathname);
  if (req.method === 'GET' && asset) {
    const plugin = context.registry.get(asset[1]!);
    const base = dirname(plugin.clientScript);
    const file = resolve(base, decodeURIComponent(asset[2]!));
    if (file !== base && !file.startsWith(base + sep)) { send(404, 'not found', 'text/plain'); return true; }
    const types: Record<string, string> = { '.png': 'image/png', '.jpg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp' };
    const type = types[extname(file).toLowerCase()];
    if (!type) { send(404, 'not found', 'text/plain'); return true; }
    send(200, await readFile(file), type);
    return true;
  }
  return false;
}
