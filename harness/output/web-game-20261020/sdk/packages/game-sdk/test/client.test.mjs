import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { GameClient, BridgeError } from '../dist/index.js';
import { startReferenceService } from '../examples/reference-service.mjs';

async function fixture(t) {
  const ref = await startReferenceService(); t.after(() => ref.close());
  const game = GameClient.http(ref.url), observation = await game.observe();
  const lease = await game.acquireControl({ id: 'acquire', context: observation.context, ownerId: 'test-harness', scope: { kind: 'team', id: 'green' }, leaseSeconds: 5 });
  const intent = { id: 'move-1', context: observation.context, leaseId: lease.leaseId, controlEpoch: lease.epoch, orderVersion: 1, actorIds: ['actor-1'], intent: { kind: 'move', parameters: { x: .2 } }, expiresAtGameTime: 5 };
  return { ref, game, observation, lease, intent };
}

test('reference native algorithm runs without model or takeover', async t => {
  const ref = await startReferenceService(); t.after(() => ref.close()); const game = GameClient.http(ref.url);
  ref.step(); const obs = await game.observe();
  assert.equal(obs.data.controller, 'native'); assert.equal(obs.actors[0].position[0], .05);
  assert.equal((await game.getInfo()).protocol, 'quickplay-bridge/v1');
});

test('queued remains queued until environment actually executes', async t => {
  const { ref, game, intent } = await fixture(t);
  assert.equal((await game.submitIntent(intent)).status, 'queued');
  assert.equal((await game.getReceipt(intent.id)).status, 'queued');
  ref.step(); assert.equal((await game.getReceipt(intent.id)).status, 'executing');
  ref.step(); assert.equal((await game.waitForReceipt(intent.id)).status, 'completed');
  assert.equal((await game.observe()).actors[0].position[0], .2);
});

test('receipt timeout leaves the actual command active', async t => {
  const { ref, game, intent } = await fixture(t); await game.submitIntent(intent);
  await assert.rejects(game.waitForReceipt(intent.id, { timeoutMs: 25, pollMs: 5 }), error => error.code === 'receipt_timeout');
  assert.equal((await game.getReceipt(intent.id)).status, 'queued');
  ref.step(); ref.step(); assert.equal((await game.getReceipt(intent.id)).status, 'completed');
});

test('handover cancels prior motion, resumes native and rejects late commands', async t => {
  const { ref, game, lease, intent, observation } = await fixture(t); await game.submitIntent(intent);
  const released = await game.releaseControl({ leaseId: lease.leaseId, context: observation.context, epoch: lease.epoch });
  assert.equal(released.status, 'released'); assert.equal((await game.getReceipt(intent.id)).status, 'cancelled');
  await assert.rejects(game.submitIntent({ ...intent, id: 'late' }), error => error.code === 'stale_control_epoch');
  ref.step(); assert.equal((await game.observe()).data.controller, 'native');
});

test('lease expiry uses real time even when example simulation does not step', async t => {
  const { game, lease, observation } = await fixture(t);
  await game.renewControl({ leaseId: lease.leaseId, context: observation.context, epoch: lease.epoch, leaseSeconds: .01 });
  await new Promise(resolve => setTimeout(resolve, 25));
  assert.equal((await game.getControl(lease.leaseId)).status, 'expired');
  assert.equal((await game.observe()).data.controller, 'native');
});

test('new motion replaces rather than runs alongside old motion', async t => {
  const { ref, game, intent } = await fixture(t); await game.submitIntent(intent);
  await game.submitIntent({ ...intent, id: 'move-2', orderVersion: 2, intent: { kind: 'move', parameters: { x: .1 } } });
  assert.equal((await game.getReceipt(intent.id)).reason, 'replaced');
  ref.step(); assert.equal((await game.getReceipt('move-2')).status, 'completed');
});

test('SDK does not fill capabilities, query results or display receipts', async t => {
  const { game, observation } = await fixture(t);
  assert.ok(!(await game.getInfo()).capabilities.includes('expressions'));
  await assert.rejects(game.query({ id: 'q', context: observation.context, kind: 'cover', actorIds: ['actor-1'], parameters: {} }), error => error.code === 'unsupported_capability');
  await assert.rejects(game.setExpressions({ id: 'e', context: observation.context, expiresAtGameTime: 5, expressions: [{ actorId: 'actor-1', emotion: 'afraid', intensity: .8, holdSeconds: 20 }] }), error => error.code === 'unsupported_capability');
});

test('event cursor is incremental and reports evicted history', async t => {
  const { ref, game } = await fixture(t);
  const first = await game.listEvents(); assert.equal(first.items.length, 1);
  assert.equal((await game.listEvents(first.nextCursor)).items.length, 0);
  for (let i = 0; i < 40; i++) ref.emit('test-event');
  const gap = await game.listEvents(first.nextCursor); assert.equal(gap.gap, true); assert.equal(gap.items.length, 32);
  const stream = game.events({ cursor: first.nextCursor, pollMs: 5 });
  assert.equal((await stream.next()).value.gap, true); await stream.return();
});

test('SDK rejects wrong protocol and mismatched receipt IDs', async () => {
  const wrong = new GameClient({ request: async () => ({ protocol: 'old' }) });
  await assert.rejects(wrong.getInfo(), error => error.code === 'protocol_mismatch');
  const other = new GameClient({ request: async () => ({ id: 'other', status: 'completed' }) });
  await assert.rejects(other.waitForReceipt('original'), error => error.code === 'receipt_mismatch');
});

test('transport deadline interrupts a stalled response without a retry', async t => {
  let requests = 0;
  const server = createServer(() => { requests++; });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }));
  const game = GameClient.http(`http://127.0.0.1:${server.address().port}`, { timeoutMs: 50 });
  await assert.rejects(game.observe(), error => error instanceof BridgeError && error.code === 'request_timeout');
  assert.equal(requests, 1);
});

test('aborted event reader does not start a hidden poll', async () => {
  let requests = 0; const game = new GameClient({ request: async () => { requests++; return { items: [], nextCursor: '0', gap: false }; } });
  const abort = new AbortController(); abort.abort();
  const stream = game.events({ signal: abort.signal }); assert.equal((await stream.next()).done, true); assert.equal(requests, 0);
});
