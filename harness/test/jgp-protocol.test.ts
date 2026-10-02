import { test } from 'node:test';
import assert from 'node:assert/strict';
import { assertCapabilities, assertWorldState, isAction, isGameMessage, isHarnessMessage, isWorldState } from '../src/jgp/protocol.js';
import { entity, player, world } from './jgp-helpers.js';

test('protocol guards: accepts a valid WorldState', () => {
  const w = world([player({ x: 5, y: 5 }), entity({ id: 'wolf-0', pos: { x: 1, y: 1 } })]);
  assert.equal(isWorldState(w), true);
  assert.equal(assertWorldState(w), w);
});

test('protocol guards: rejects malformed payloads', () => {
  assert.equal(isWorldState(null), false);
  assert.equal(isWorldState({}), false);
  assert.equal(isWorldState({ protocolVersion: 'v2' }), false);
  assert.equal(isWorldState({ ...world([]), entities: [{ id: 1 }] }), false);
  assert.throws(() => assertWorldState({}));
  assert.throws(() => assertCapabilities({}));
});

test('protocol guards: validates actions', () => {
  assert.equal(isAction({ entityId: 'w', type: 'move', dir: { x: 1, y: 0 } }), true);
  assert.equal(isAction({ entityId: 'w', type: 'dance' }), false);
  assert.equal(isAction({ type: 'move' }), false);
});

test('protocol guards: message envelopes', () => {
  const w = world([player({ x: 5, y: 5 })]);
  assert.equal(isGameMessage({ type: 'hello', capabilities: { protocolVersion: 'v1', game: 'g', tickRateHz: 20, maxActionsPerTick: 8, features: [] } }), true);
  assert.equal(isGameMessage({ type: 'state', state: w }), true);
  assert.equal(isGameMessage({ type: 'actions', actions: [] }), false);
  assert.equal(isHarnessMessage({ type: 'hello_ack', protocolVersion: 'v1' }), true);
  assert.equal(isHarnessMessage({ type: 'actions', tick: 1, actions: [{ entityId: 'w', type: 'hold' }] }), true);
  // actions 帧可携带 entities 回写（aware/morale/swarmOrder）
  assert.equal(isHarnessMessage({ type: 'actions', tick: 1, actions: [], entities: [{ id: 'w', aware: true, morale: 0.5, swarmOrder: { type: 'flank', issuedAtTick: 1 } }] }), true);
  assert.equal(isHarnessMessage({ type: 'actions', tick: 1, actions: [], entities: [{ aware: true }] }), false);
  assert.equal(isHarnessMessage({ type: 'actions', tick: 1, actions: [], entities: [{ id: 'w', morale: 'high' }] }), false);
  assert.equal(isHarnessMessage({ type: 'error', message: 'x' }), true);
  assert.equal(isHarnessMessage({ type: 'hello' }), false);
});
