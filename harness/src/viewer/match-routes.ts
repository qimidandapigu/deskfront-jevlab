import type { IncomingMessage, ServerResponse } from 'node:http';
import { SessionError, type createSessionService } from '../arena/sessions.js';
import { readBody, sendJson, type SendResponse } from './http.js';

type SessionService = ReturnType<typeof createSessionService>;

/** The session API is deliberately thin: the session service remains the state authority. */
export async function handleMatchRoute(
  req: IncomingMessage,
  _res: ServerResponse,
  url: URL,
  sessions: SessionService,
  send: SendResponse,
): Promise<boolean> {
  const route = /^\/api\/match\/([\w-]+)(?:\/(input|action|stop|state|history))?$/.exec(url.pathname);
  if (!route) return false;
  const [, id, operation] = route;
  const post = req.method === 'POST';
  let body: Record<string, unknown> = {};
  if (post) {
    try { body = JSON.parse((await readBody(req)) || '{}'); }
    catch { throw new SessionError(400, 'Invalid JSON'); }
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw new SessionError(400, 'Request body must be an object');
  }
  let result: unknown;
  if (!operation && post) result = sessions.start(id!, body);
  else if (operation === 'input' && post) result = sessions.input(id!, body);
  else if (operation === 'action' && post) result = sessions.action(id!, body);
  else if (operation === 'stop' && post) result = sessions.stop(id!);
  else if (operation === 'state' && req.method === 'GET') result = sessions.state(id!, url.searchParams.get('compact') === '1');
  else if (operation === 'history' && req.method === 'GET') result = sessions.history(id!);
  else { send(405, 'Method not allowed', 'text/plain'); return true; }
  sendJson(send, 200, result);
  return true;
}
