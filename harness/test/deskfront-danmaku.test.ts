import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createDanmaku } from '../src/deskfront/danmaku.js';
import type { BattleFrame } from '../src/deskfront/commentary.js';
import { commentaryScript } from '../src/deskfront/commentary-ui.js';

function fixture(limit = 30) {
  const directory = mkdtempSync(join(tmpdir(), 'danmaku-'));
  let now = 10000, calls = 0;
  let respond = async () => ({ comments: { type: 'json' as const, value: { items: [
    { text: '绿队这波稳住呀😰', evidence_ids: ['s1'] },
    { text: '红队也都还在场上', evidence_ids: ['s2'] },
    { text: '双方现在人数一样', evidence_ids: ['s1','s2'] },
    null, { text: '虚构的精彩绕后', evidence_ids: ['nonexistent'] },
  ] } } });
  const frame: BattleFrame = { kind: 'ai', status: 'running', world: { run_id: 'r', time: 1,
    world_growth: { revision: 1, mission: { status: 'active' } },
    units: [{ id: 'g', faction: 'green', hp: 50, max_hp: 50 }, { id: 'r', faction: 'red', hp: 50, max_hp: 50 }] } };
  const d = createDanmaku({ directory: () => directory, autoTick: false, limit, now: () => now,
    read: () => frame, backend: () => ({ async ask() { calls++; return respond(); } }) });
  const receipt = () => writeFileSync(join(directory, 'danmaku-status.json'), JSON.stringify({ ready: true, session: 'a', run_id: 'r', updated_at: now }));
  return { d, frame, directory, calls: () => calls, receipt, advance(ms = 15000) { now += ms; receipt(); },
    respond(fn: typeof respond) { respond = fn; }, command: () => JSON.parse(readFileSync(join(directory, 'danmaku-command.json'), 'utf8')),
    close() { d.close(); rmSync(directory, { recursive: true, force: true }); } };
}
test('audience requests require native readiness and changed facts; low density is spaced and evidence filtered', async () => {
  const f = fixture(); try {
    f.d.configure('a', true); await f.d.step('a'); assert.equal(f.calls(), 0);
    f.receipt(); await f.d.step('a');
    const batch = f.command(); assert.equal(batch.items.length, 3);
    assert.equal(batch.items[1].at - batch.items[0].at, 6000);
    assert.equal(batch.items[2].at - batch.items[1].at, 6000);
    await f.d.step('a'); assert.equal(f.calls(), 1);
    f.advance(); await f.d.step('a'); assert.equal(f.calls(), 1, 'quiet state incurs no calls');
    f.frame.world.units[0].hp = 20; await f.d.step('a'); assert.equal(f.calls(), 2);
    assert.equal(f.command().items.length, 0, 'recent exact repeats dropped');
  } finally { f.close(); }
});
test('budget persists across toggles; pause and stage replacement clear old comments', async () => {
  const f = fixture(1); try {
    f.receipt(); f.d.configure('a', true); await f.d.step('a');
    f.frame.world.paused = true; await f.d.step('a'); assert.equal(f.command().enabled, false);
    f.frame.world.paused = false; f.frame.world.world_growth.revision++;
    f.advance(); await f.d.step('a'); assert.equal(f.command().enabled, false);
    f.d.configure('a', false); f.d.configure('a', true); await f.d.step('a');
    assert.equal(f.calls(), 1); assert.equal(f.d.snapshot('a').status, 'budget');
  } finally { f.close(); }
});
test('stop aborts a pending request and ignores late answers', async () => {
  const f = fixture(); let release!: () => void;
  f.respond(() => new Promise(resolve => { release = () => resolve({ comments: { type: 'json', value: { items: [{text:'旧局不应该再出现', evidence_ids:['s1']}] } } }); }));
  try {
    f.receipt(); f.d.configure('a', true); const pending = f.d.step('a');
    await f.d.step('a'); assert.equal(f.calls(), 1, 'one in-flight request');
    f.d.configure('a', false); await pending; release();
    await Promise.resolve(); assert.equal(f.command().enabled, false); assert.equal(f.d.snapshot('a').status, 'off');
  } finally { f.close(); }
});
test('stage changes while model is working cannot publish stale facts', async () => {
  const f = fixture(); let release!: () => void;
  f.respond(() => new Promise(resolve => { release = () => resolve({ comments: { type: 'json', value: { items: [{text:'上一关的这条评论', evidence_ids:['s1']}] } } }); }));
  try {
    f.receipt(); f.d.configure('a', true); const pending = f.d.step('a');
    f.frame.world.world_growth.revision++; release(); await pending;
    assert.equal(f.command().enabled, false);
  } finally { f.close(); }
});
test('payment failure disables optional requests instead of endlessly retrying', async () => {
  const f = fixture(); f.respond(async () => { throw Error('模型服务暂时不可用（HTTP 402）'); });
  try {
    f.receipt(); f.d.configure('a', true); await f.d.step('a');
    assert.equal(f.d.snapshot('a').status, 'payment-required'); assert.equal(f.d.snapshot('a').enabled, false);
    f.advance(); await f.d.step('a'); assert.equal(f.calls(), 1); assert.equal(f.command().enabled, false);
  } finally { f.close(); }
});
test('embedded spectator UI remains valid JavaScript', () => { assert.doesNotThrow(() => new Function(commentaryScript)); });
