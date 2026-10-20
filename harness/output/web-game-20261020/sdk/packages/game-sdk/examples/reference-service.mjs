// A small OPEN protocol reference environment, not the private Deskfront game.
import { createServer } from 'node:http';
import { BRIDGE_PROTOCOL } from '../dist/index.js';

export async function startReferenceService() {
  let tick = 0, position = 0, epoch = 0, lease = null, sequence = 0;
  const receipts = new Map(), commands = new Map(), events = [];
  const context = () => ({ instanceId: 'reference-instance', runId: 'reference-run', revision: 1, tick, gameTime: tick * .1 });
  function emit(kind, data = {}) {
    events.push({ sequence: ++sequence, id: `event-${sequence}`, context: context(), kind, actorIds: ['actor-1'], data });
    if (events.length > 32) events.shift();
  }
  function release(status) {
    lease = { ...lease, status }; epoch++;
    for (const [id, command] of commands) {
      receipts.set(id, { id, context: context(), status: 'cancelled', reason: 'control_released' }); commands.delete(id);
    }
    emit('control_released', { status });
  }
  function expire() { if (lease?.status === 'active' && Date.now() >= lease.expiresAtRealTime) release('expired'); }
  function step() {
    expire(); tick++;
    if (lease?.status !== 'active') { position = Math.min(1, position + .05); return; }
    for (const [id, command] of commands) {
      if (context().gameTime > command.expiresAtGameTime) {
        receipts.set(id, { id, context: context(), status: 'failed', reason: 'intent_expired' }); commands.delete(id); continue;
      }
      const goal = command.intent.parameters.x;
      position += Math.sign(goal - position) * Math.min(.1, Math.abs(goal - position));
      const done = Math.abs(goal - position) < .001;
      receipts.set(id, { id, context: context(), status: done ? 'completed' : 'executing' });
      if (done) { commands.delete(id); emit('intent_completed', { commandId: id }); }
    }
  }
  const info = {
    protocol: BRIDGE_PROTOCOL, gameId: 'reference-point', buildVersion: '1', coordinates: { unit: 'example-unit', upAxis: 'y' },
    capabilities: ['observe', 'map', 'events', 'control', 'intents'],
    actions: [{ id: 'move', parameters: { x: 'finite number' } }], queryKinds: [], emotions: [], controlScopes: ['team'],
  };
  const server = createServer(async (req, res) => {
    function send(code, value) { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(value)); }
    function fail(code, message, status = 409) { send(status, { code, message }); }
    try {
      expire();
      const url = new URL(req.url, 'http://127.0.0.1');
      if (req.method === 'GET') {
        if (url.pathname === '/v1/info') { send(200, info); return; }
        if (url.pathname === '/v1/state') {
          send(200, { context: context(), perspective: { teamId: 'green', visibility: 'team' }, actors: [{ id: 'actor-1', teamId: 'green', position: [position, 0, 0], hp: 30, maxHp: 30, actionCapabilities: ['move'] }], squads: [], objectives: [], data: { controller: lease?.status === 'active' ? 'external' : 'native' } }); return;
        }
        if (url.pathname === '/v1/map') { send(200, { context: context(), regions: [{ id: 'line', min: 0, max: 1 }], obstacles: [], data: {} }); return; }
        if (url.pathname === '/v1/events') {
          const cursor = Number(url.searchParams.get('cursor') ?? 0);
          if (!Number.isInteger(cursor) || cursor < 0 || cursor > sequence) { fail('invalid_cursor', 'Cursor does not belong to this stream', 400); return; }
          send(200, { items: events.filter(e => e.sequence > cursor).map(({ sequence: _, ...e }) => e), nextCursor: String(sequence), gap: cursor < sequence - events.length }); return;
        }
        if (url.pathname.startsWith('/v1/receipts/')) {
          const receipt = receipts.get(decodeURIComponent(url.pathname.slice('/v1/receipts/'.length)));
          if (!receipt) { fail('receipt_not_found', 'No retained receipt for ID', 404); return; }
          send(200, receipt); return;
        }
        if (url.pathname.startsWith('/v1/control/')) {
          if (!lease || decodeURIComponent(url.pathname.slice('/v1/control/'.length)) !== lease.leaseId) { fail('lease_not_found', 'No retained lease for ID', 404); return; }
          send(200, lease); return;
        }
        fail('not_found', 'Unknown route', 404); return;
      }
      if (req.method !== 'POST') { fail('method_not_allowed', 'Use GET or POST', 405); return; }
      let raw = ''; for await (const chunk of req) { raw += chunk; if (raw.length > 65536) { fail('body_too_large', 'Example limit exceeded', 413); return; } }
      const body = JSON.parse(raw);
      if (url.pathname === '/v1/query' || url.pathname.startsWith('/v1/presentation/')) { fail('unsupported_capability', 'Reference environment does not support this capability', 501); return; }
      if (body.context?.instanceId !== context().instanceId || body.context?.runId !== context().runId) { fail('stale_run', 'Command is for another instance or run'); return; }
      if (url.pathname === '/v1/control/acquire') {
        if (body.scope?.kind !== 'team' || body.scope?.id !== 'green' || typeof body.ownerId !== 'string' || !body.ownerId || !Number.isFinite(body.leaseSeconds) || body.leaseSeconds <= 0) { fail('invalid_control_request', 'Invalid scope, owner or duration', 400); return; }
        if (lease?.status === 'active') { fail('control_busy', 'Scope already controlled'); return; }
        lease = { leaseId: `lease-${++epoch}`, context: context(), ownerId: body.ownerId, scope: body.scope, epoch, expiresAtRealTime: Date.now() + body.leaseSeconds * 1000, status: 'active' };
        emit('control_acquired'); send(200, lease); return;
      }
      if (!lease || lease.status !== 'active' || body.leaseId !== lease.leaseId || (body.controlEpoch ?? body.epoch) !== lease.epoch) { fail('stale_control_epoch', 'Lease is not the active controller'); return; }
      if (url.pathname === '/v1/control/renew') {
        if (!Number.isFinite(body.leaseSeconds) || body.leaseSeconds <= 0) { fail('invalid_duration', 'Lease duration must be positive', 400); return; }
        lease = { ...lease, expiresAtRealTime: Date.now() + body.leaseSeconds * 1000 }; send(200, lease); return;
      }
      if (url.pathname === '/v1/control/release') { release('released'); send(200, lease); return; }
      if (url.pathname === '/v1/intents/cancel') {
        if (!commands.has(body.id)) { fail('intent_not_active', 'No active intent for ID'); return; }
        commands.delete(body.id); const result = { id: body.id, context: context(), status: 'cancelled' }; receipts.set(body.id, result); send(200, result); return;
      }
      if (url.pathname === '/v1/intents') {
        if (receipts.has(body.id)) { fail('duplicate_id', 'Use receipt lookup rather than repeat submission'); return; }
        if (body.actorIds?.length !== 1 || body.actorIds[0] !== 'actor-1') { fail('invalid_actor', 'Unknown actor', 400); return; }
        if (typeof body.id !== 'string' || !body.id || !Number.isInteger(body.orderVersion) || body.orderVersion < 0 || body.intent?.kind !== 'move' || !Number.isFinite(body.intent?.parameters?.x) || !Number.isFinite(body.expiresAtGameTime) || body.expiresAtGameTime <= context().gameTime) { fail('invalid_intent', 'Invalid or expired intent', 400); return; }
        // One ordinary motion for one actor: new version cancels the prior one.
        for (const [id, old] of commands) {
          if (body.orderVersion <= old.orderVersion) { fail('stale_order_version', 'Prior intent version still owns this actor'); return; }
          receipts.set(id, { id, context: context(), status: 'cancelled', reason: 'replaced' }); commands.delete(id);
        }
        if (receipts.size >= 256) receipts.delete(receipts.keys().next().value);
        commands.set(body.id, body); const result = { id: body.id, context: context(), status: 'queued' }; receipts.set(body.id, result); send(202, result); return;
      }
      fail('not_found', 'Unknown route', 404);
    } catch { if (!res.headersSent) fail('invalid_json', 'Malformed example request', 400); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return { url: `http://127.0.0.1:${server.address().port}`, step, emit, close: () => new Promise((resolve, reject) => { server.close(error => error ? reject(error) : resolve()); server.closeAllConnections(); }) };
}
