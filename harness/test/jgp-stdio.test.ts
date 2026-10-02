import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setTimeout as sleep } from 'node:timers/promises';
import { createStdioAdapter } from '../src/jgp/stdio.js';

// 迷你游戏：收到 hello_ack 后推 state(1)，100ms 后再推 state(2)；
// 收到 actions 帧时自检：tick 必须是被处理那帧（1，而非最新到达的 2），
// 且携带 entities 回写。自检通过 exit 0，否则 exit 2。
const GAME_SCRIPT = `
const readline = require('node:readline');
const send = (m) => process.stdout.write(JSON.stringify(m) + '\\n');
const mk = (t) => ({ protocolVersion: 'v1', tick: t, timeMs: t * 50, bounds: { w: 10, h: 10 }, entities: [{ id: 'player', kind: 'player', faction: 'player', pos: { x: 1, y: 1 }, vel: { x: 0, y: 0 }, hp: 10, maxHp: 10 }], events: [] });
const lines = readline.createInterface({ input: process.stdin });
lines.on('line', (line) => {
  const msg = JSON.parse(line);
  if (msg.type === 'hello_ack') {
    send({ type: 'state', state: mk(1) });
    setTimeout(() => send({ type: 'state', state: mk(2) }), 100);
  }
  if (msg.type === 'actions') {
    const ok = msg.tick === 1 && Array.isArray(msg.entities) && msg.entities[0] && msg.entities[0].aware === true;
    process.exit(ok ? 0 : 2);
  }
});
send({ type: 'hello', capabilities: { protocolVersion: 'v1', game: 'stub', tickRateHz: 20, maxActionsPerTick: 64, features: [] } });
`;

test('stdio adapter: actions 帧带被处理帧的 tick 与 entities 回写', async () => {
  const adapter = createStdioAdapter([process.execPath, '-e', GAME_SCRIPT]);
  try {
    await adapter.ready();
    const s = await adapter.getState();
    assert.equal(s.tick, 1);
    await sleep(250); // 等 state(2) 到达：lastTick=2，但已交付被处理的仍是 tick 1
    adapter.execute([{ entityId: 'e1', type: 'hold' }], [{ id: 'e1', aware: true, morale: 0.5 }]);
    for (let i = 0; i < 40 && adapter.exitCode() === null; i++) await sleep(50);
    assert.equal(adapter.exitCode(), 0);
  } finally {
    adapter.dispose();
  }
});
