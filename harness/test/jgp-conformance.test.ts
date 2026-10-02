import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { Action, EntityAnnotation } from '../src/jgp/protocol.js';
import type { JevAnswers, JevClient } from '../src/jgp/jev-types.js';
import { createEngine } from '../src/jgp/engine.js';
import { createFakeJevClient, type FakeJevOptions } from '../src/jgp/jev-fake.js';
import { createMemoryLogger } from '../src/jgp/logger.js';
import { createDisabledStrategist, DEFAULT_MISSION } from '../src/jgp/strategist.js';
import { entity, fixedAdapter, player, world } from './jgp-helpers.js';

function makeEngine(w: ReturnType<typeof world>, jevOpts: FakeJevOptions = {}, now: () => number = () => 1_000_000) {
  const adapter = fixedAdapter(w);
  const logger = createMemoryLogger();
  const jev = createFakeJevClient(jevOpts);
  const engine = createEngine({ adapter, jev, strategist: createDisabledStrategist({ now }), logger, now });
  return { engine, adapter, logger, jev };
}

function actionOf(actions: Action[], id: string): Action | undefined {
  return actions.find((a) => a.entityId === id);
}

test('scenario 单挑: a wolf with the player in sight moves toward the player', async () => {
  const p = player({ x: 20, y: 10 });
  const wolf = entity({ id: 'wolf-0', pos: { x: 10, y: 10 } });
  const { engine, adapter } = makeEngine(world([p, wolf]));
  const actions = await engine.step(world([p, wolf]));
  const a = actionOf(actions, 'wolf-0');
  assert.ok(a);
  assert.equal(a.type, 'move');
  assert.equal(a.targetId, 'player');
  assert.ok((a.dir?.x ?? 0) > 0); // toward +x
  assert.equal(adapter.executed.length, 1);
});

test('scenario 追击: a wolf adjacent to the player attacks', async () => {
  const p = player({ x: 10, y: 10 });
  const wolf = entity({ id: 'wolf-0', pos: { x: 11, y: 10 } });
  const { engine } = makeEngine(world([p, wolf]));
  const actions = await engine.step(world([p, wolf]));
  assert.equal(actionOf(actions, 'wolf-0')?.type, 'attack');
});

test('scenario 被围: all adjacent wolves attack; far ones close in', async () => {
  const p = player({ x: 20, y: 10 });
  const wolves = [
    entity({ id: 'w-a', pos: { x: 21, y: 10 } }),
    entity({ id: 'w-b', pos: { x: 19, y: 10 } }),
    entity({ id: 'w-c', pos: { x: 20, y: 11 } }),
    entity({ id: 'w-far', pos: { x: 30, y: 10 } }),
  ];
  const { engine } = makeEngine(world([p, ...wolves]));
  const actions = await engine.step(world([p, ...wolves]));
  assert.equal(actionOf(actions, 'w-a')?.type, 'attack');
  assert.equal(actionOf(actions, 'w-b')?.type, 'attack');
  assert.equal(actionOf(actions, 'w-c')?.type, 'attack');
  const far = actionOf(actions, 'w-far');
  assert.equal(far?.type, 'move');
  assert.ok((far?.dir?.x ?? 0) < 0); // toward player at -x
});

test('scenario 残血: a critically hurt wolf flees from the player', async () => {
  const p = player({ x: 20, y: 10 });
  const wolf = entity({ id: 'wolf-0', pos: { x: 18, y: 10 }, hp: 5, maxHp: 30 });
  const { engine } = makeEngine(world([p, wolf]));
  const actions = await engine.step(world([p, wolf]));
  const a = actionOf(actions, 'wolf-0');
  assert.equal(a?.type, 'flee');
  assert.ok((a?.dir?.x ?? 0) < 0); // away from player
});

test('confidence fallback: low-confidence Jev answers execute without probability filtering', async () => {
  const p = player({ x: 20, y: 10 });
  const wolf = entity({ id: 'wolf-0', pos: { x: 10, y: 10 } });
  const { engine, logger } = makeEngine(world([p, wolf]), { forceConfidenceBelow: 0.5 });
  const actions = await engine.step(world([p, wolf]));
  const a = actionOf(actions, 'wolf-0');
  assert.equal(a?.type, 'move'); // rules: chase
  const rec = logger.records.find((r) => r.entity === 'wolf-0');
  assert.equal(rec?.fallback, false);
  assert.equal(rec?.fallbackReason, undefined);
  assert.ok((rec?.jev?.answers['action']?.confidence ?? 1) < 0.6);
});

test('confidence fallback: Jev errors fall back to rules too', async () => {
  const p = player({ x: 20, y: 10 });
  const wolf = entity({ id: 'wolf-0', pos: { x: 21, y: 10 } });
  const { engine, logger } = makeEngine(world([p, wolf]), { failRate: 1 });
  const actions = await engine.step(world([p, wolf]));
  assert.equal(actionOf(actions, 'wolf-0')?.type, 'attack'); // adjacent → rules attack
  const rec = logger.records.find((r) => r.entity === 'wolf-0');
  assert.equal(rec?.fallback, true);
  assert.equal(rec?.fallbackReason, 'jev_error');
});

test('throttling: reuses the previous action when state has not changed significantly', async () => {
  const p = player({ x: 20, y: 10 });
  const wolf = entity({ id: 'wolf-0', pos: { x: 10, y: 10 } });
  let t = 1_000_000;
  const now = () => t;
  const { engine, jev } = makeEngine(world([p, wolf]), {}, now);
  await engine.step(world([p, wolf], 1));
  const callsAfterFirst = jev.callCount();
  t += 1000; // past decision interval, same state
  await engine.step(world([p, wolf], 2));
  assert.equal(jev.callCount(), callsAfterFirst); // no new per-enemy call
});

test('throttling: respects the minimum action hold time (500ms) against jitter', async () => {
  const p = player({ x: 20, y: 10 });
  const wolf = entity({ id: 'wolf-0', pos: { x: 10, y: 10 }, hp: 30 });
  let t = 1_000_000;
  const now = () => t;
  const { engine } = makeEngine(world([p, wolf]), {}, now);
  const first = await engine.step(world([p, wolf], 1));
  assert.equal(actionOf(first, 'wolf-0')?.type, 'move');
  // 100ms later the wolf is suddenly critical → would flee, but hold time applies
  t += 100;
  const hurt = entity({ id: 'wolf-0', pos: { x: 10, y: 10 }, hp: 5, maxHp: 30 });
  const second = await engine.step(world([p, hurt], 2));
  assert.equal(actionOf(second, 'wolf-0')?.type, 'move');
  // after the hold window, the flee goes through
  t += 1000;
  const third = await engine.step(world([p, hurt], 3));
  assert.equal(actionOf(third, 'wolf-0')?.type, 'flee');
});

test('throttling: interest management — far enemies decide less often than near ones', async () => {
  const p = player({ x: 20, y: 10 });
  const near = entity({ id: 'near', pos: { x: 15, y: 10 } });
  const far = entity({ id: 'far', pos: { x: 39, y: 19 } }); // > farDistance
  let t = 1_000_000;
  const now = () => t;
  const { engine, logger } = makeEngine(world([p, near, far]), {}, now);
  // change positions slightly each step to defeat the unchanged-state cache
  for (let i = 0; i < 6; i++) {
    const n = entity({ id: 'near', pos: { x: 15 - i * 2, y: 10 } }); // big moves: signature changes every step
    const f = entity({ id: 'far', pos: { x: 39, y: 19 - i * 0.3 } });
    await engine.step(world([p, n, f], i + 1));
    t += 400; // 2.5 steps/sec → near (3Hz) due almost every step, far (1Hz) rarely
  }
  const nearDecisions = logger.records.filter((r) => r.entity === 'near' && !r.fallbackReason?.match(/throttled|reused/)).length;
  const farDecisions = logger.records.filter((r) => r.entity === 'far' && !r.fallbackReason?.match(/throttled|reused/)).length;
  assert.ok(nearDecisions > farDecisions);
  assert.ok(nearDecisions >= 4);
  assert.ok(farDecisions <= 3);
});

test('swarm brain: broadcasts a swarm order into enemy state and logs the swarm decision', async () => {
  const p = player({ x: 20, y: 10 });
  const wolves = [entity({ id: 'w-0', pos: { x: 5, y: 5 } }), entity({ id: 'w-1', pos: { x: 6, y: 5 } })];
  const w = world([p, ...wolves]);
  const { engine, logger } = makeEngine(w);
  await engine.step(w);
  const order = engine.currentSwarmOrder();
  assert.ok(['focus_fire', 'flank', 'spread', 'retreat'].includes(order.type));
  // reflected onto entities for the game to consume
  const w0 = w.entities.find((e) => e.id === 'w-0');
  assert.equal(w0?.swarmOrder?.type, order.type);
  const swarmRec = logger.records.find((r) => r.entity === 'swarm');
  assert.ok(swarmRec);
  // the disabled strategist's default mission reaches the per-enemy context
  const rec = logger.records.find((r) => r.entity === 'w-0');
  assert.equal((rec?.state as { mission?: string } | undefined)?.mission, DEFAULT_MISSION);
});

test('swarm brain: orders a retreat when the pack is critically hurt (fake heuristic)', async () => {
  const p = player({ x: 20, y: 10 });
  const wolves = [
    entity({ id: 'w-0', pos: { x: 5, y: 5 }, hp: 5 }),
    entity({ id: 'w-1', pos: { x: 6, y: 5 }, hp: 6 }),
  ];
  const { engine } = makeEngine(world([p, ...wolves]));
  await engine.step(world([p, ...wolves]));
  assert.equal(engine.currentSwarmOrder().type, 'retreat');
});

function stubJev(answers: JevAnswers): JevClient {
  return {
    async systemOne() { return { answers, latencyMs: 0, model: 'stub' }; },
    dispose() {},
  };
}

test('writeback: execute 携带逐实体 aware/morale/swarmOrder 注解', async () => {
  const p = player({ x: 20, y: 10 });
  const wolf = entity({ id: 'wolf-0', pos: { x: 10, y: 10 } });
  const w = world([p, wolf]);
  const calls: { actions: Action[]; entities?: EntityAnnotation[] }[] = [];
  const base = fixedAdapter(w);
  const adapter = { ...base, execute(actions: Action[], entities?: EntityAnnotation[]) { calls.push({ actions, entities }); } };
  const engine = createEngine({
    adapter, jev: createFakeJevClient({}),
    strategist: createDisabledStrategist({ now: () => 1_000_000 }),
    logger: createMemoryLogger(), now: () => 1_000_000,
  });
  await engine.step(w);
  const ann = calls[0]?.entities?.find((e) => e.id === 'wolf-0');
  assert.ok(ann);
  assert.equal(typeof ann.aware, 'boolean');
  assert.equal(typeof ann.morale, 'number');
  assert.equal(ann.swarmOrder?.type, engine.currentSwarmOrder().type);
});

test('action gate: 高风险低置信度仍执行原动作', async () => {
  const p = player({ x: 10, y: 10 });
  const wolf = entity({ id: 'wolf-0', pos: { x: 11, y: 10 } });
  const logger = createMemoryLogger();
  const engine = createEngine({
    adapter: fixedAdapter(world([p, wolf])), logger,
    jev: stubJev({ action: { choice: 'attack', confidence: 0.7 } }),
    strategist: createDisabledStrategist({ now: () => 1_000_000 }),
    now: () => 1_000_000,
    config: { actionGate: { highRisk: ['attack'], safeAction: 'hold' } },
  });
  const actions = await engine.step(world([p, wolf]));
  assert.equal(actionOf(actions, 'wolf-0')?.type, 'attack'); // No confidence gate
  const rec = logger.records.find((r) => r.entity === 'wolf-0');
  assert.equal(rec?.fallback, false);
  assert.equal(rec?.fallbackReason, undefined);
});

test('action gate: 高风险低置信度无 safeAction 时照常执行', async () => {
  const p = player({ x: 10, y: 10 });
  const wolf = entity({ id: 'wolf-0', pos: { x: 11, y: 10 } });
  const logger = createMemoryLogger();
  const engine = createEngine({
    adapter: fixedAdapter(world([p, wolf])), logger,
    jev: stubJev({ action: { choice: 'attack', confidence: 0.7 } }),
    strategist: createDisabledStrategist({ now: () => 1_000_000 }),
    now: () => 1_000_000,
    config: { actionGate: { highRisk: ['attack'] } },
  });
  const actions = await engine.step(world([p, wolf]));
  assert.equal(actionOf(actions, 'wolf-0')?.type, 'attack');
  const rec = logger.records.find((r) => r.entity === 'wolf-0');
  assert.equal(rec?.fallback, false);
  assert.equal(rec?.blocked, undefined);
  assert.equal(rec?.fallbackReason, undefined);
});

test('action gate: other 弃权有 safeAction 时替换执行（abstained）', async () => {
  const p = player({ x: 10, y: 10 });
  const wolf = entity({ id: 'wolf-0', pos: { x: 11, y: 10 } });
  const logger = createMemoryLogger();
  const engine = createEngine({
    adapter: fixedAdapter(world([p, wolf])), logger,
    jev: stubJev({ action: { choice: 'other', confidence: 0.95 } }),
    strategist: createDisabledStrategist({ now: () => 1_000_000 }),
    now: () => 1_000_000,
    config: { actionGate: { allowOther: true, safeAction: 'hold' } },
  });
  const actions = await engine.step(world([p, wolf]));
  assert.equal(actionOf(actions, 'wolf-0')?.type, 'hold');
  const rec = logger.records.find((r) => r.entity === 'wolf-0');
  assert.equal(rec?.fallback, true);
  assert.equal(rec?.fallbackReason, 'abstained');
});

test('action gate: other 弃权无 safeAction 时执行规则动作', async () => {
  const p = player({ x: 10, y: 10 });
  const wolf = entity({ id: 'wolf-0', pos: { x: 11, y: 10 } });
  const logger = createMemoryLogger();
  const engine = createEngine({
    adapter: fixedAdapter(world([p, wolf])), logger,
    jev: stubJev({ action: { choice: 'other', confidence: 0.95 } }),
    strategist: createDisabledStrategist({ now: () => 1_000_000 }),
    now: () => 1_000_000,
    config: { actionGate: { allowOther: true } },
  });
  const actions = await engine.step(world([p, wolf]));
  assert.equal(actionOf(actions, 'wolf-0')?.type, 'attack');
  const rec = logger.records.find((r) => r.entity === 'wolf-0');
  assert.equal(rec?.action?.type, 'attack');
  assert.equal(rec?.fallback, true);
  assert.equal(rec?.fallbackReason, 'abstained');
});

test('outbound validation: 超出 maxActionsPerTick 的 action 被丢弃并记录', async () => {
  const p = player({ x: 20, y: 10 });
  const wolves = [entity({ id: 'w-0', pos: { x: 10, y: 10 } }), entity({ id: 'w-1', pos: { x: 11, y: 10 } })];
  const w = world([p, ...wolves]);
  const adapter = fixedAdapter(w, { maxActionsPerTick: 1 });
  const logger = createMemoryLogger();
  const engine = createEngine({
    adapter, logger, jev: createFakeJevClient({}),
    strategist: createDisabledStrategist({ now: () => 1_000_000 }),
    now: () => 1_000_000,
  });
  const actions = await engine.step(w);
  assert.equal(actions.length, 1); // 两只狼都想动，但上限 1
  assert.equal(adapter.executed[0]?.length, 1);
  const drop = logger.records.find((r) => r.fallbackReason === 'over_limit');
  assert.ok(drop);
  assert.equal(drop.action, null);
});
