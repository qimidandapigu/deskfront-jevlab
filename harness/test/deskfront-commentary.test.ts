import test from 'node:test';
import assert from 'node:assert/strict';
import { commentarySubtitle, battleFacts, macroBattle, createCommentary, synthesizeCommentary, type BattleFrame } from '../src/deskfront/commentary.js';
import type { SystemOne } from '../src/systemone/types.js';
import { envForModel } from '../src/config.js';

test('commentary has separate non-thinking configuration; combat model settings are unchanged', () => {
  const config = { defaultModel: 'deepseek' as const, jev: { provider: 'typesafe' as const, apiKey: 'test' },
    deepseek: { provider: 'openrouter' as const, apiKey: 'test', model: 'test-model' } };
  assert.equal(JSON.parse(envForModel(config, 'commentary', {}).MODEL_EXTRA_BODY!).reasoning.effort, 'none');
  assert.equal(JSON.parse(envForModel(config, 'deepseek', {}).MODEL_EXTRA_BODY!).reasoning, undefined);
});

function frame(): BattleFrame {
  return { kind: 'ai', status: 'running', world: { run_id: 'r1', time: 10, units: [
    { id: 'green-1', faction: 'green', hp: 100, position: [0, 0], last_shot_at: -1 },
    { id: 'red-1', faction: 'red', hp: 100, position: [1, 0], last_shot_at: -1 },
  ] } };
}
const model: SystemOne = { async ask() { return { commentary: { type: 'json', value: {
  text: '双方各有一名队员在场，看看接下来会有什么变化。', evidence_ids: ['f1', 'f2'],
} } }; } };
const speech = async () => ({ audio: Buffer.from('audio'), firstAudioMs: 10, totalMs: 20 });

test('macro selection ignores reload and minor hits, reacts to aggregate attrition and confirmed losses', () => {
  const before = frame(); before.world.units.forEach((u: any) => { u.max_hp = 100; });
  const current = structuredClone(before);
  Object.assign(current.world.units[0], { hp: 95, reload_remaining: 2, last_shot_at: 10, in_cover: true });
  assert.equal(macroBattle(current, before).changed, false);
  current.world.units[0].hp = 60;
  const pressure = macroBattle(current, before);
  assert.equal(pressure.changed, true);
  assert.match(pressure.facts.map(f => f.text).join(' '), /整体消耗/);
  assert.doesNotMatch(pressure.facts.map(f => f.text).join(' '), /换弹|1号|开火/);
  current.world.units[0].hp = 0;
  assert.equal(macroBattle(current, before).facts.some(f => f.urgent), true);
  current.world.units.shift();
  assert.equal(macroBattle(current, before).facts.some(f => f.urgent), false, 'unload is not a casualty');
});

test('only explicit death is a casualty; unload/disappearance and new region are not kills', () => {
  const before = frame(), after = frame(); after.world.units.pop();
  assert.equal(battleFacts(after, before).length, 0);
  after.world.units[0].hp = 0;
  assert.match(battleFacts(after, before)[0]!.text, /阵亡/);
  after.world.world_growth = { revision: 2 };
  assert.equal(battleFacts(after, before).some(f => f.urgent), false);
});
test('actual shots do not imply hits and movement does not imply arrival', () => {
  const before = frame(), after = frame(); after.world.units[0].last_shot_at = 10;
  after.world.units[0].position = [.3, 0];
  const facts = battleFacts(after, before);
  assert.match(facts.map(f => f.text).join(' '), /命中结果未知/);
  assert.match(facts.map(f => f.text).join(' '), /未据此确认到位/);
});
test('commentary follows cover, blocked route and reload transitions without inventing arrival', () => {
  const before = frame(), after = frame();
  Object.assign(before.world.units[0], { in_cover: false, reload_remaining: 0, path_failure: '' });
  Object.assign(after.world.units[0], { in_cover: true, reload_remaining: 2, path_failure: 'blocked' });
  const first = battleFacts(after, before).map(f => f.text).join(' ');
  assert.match(first, /进入掩体/); assert.match(first, /行进受阻/); assert.match(first, /开始换弹/);
  const recovered = structuredClone(after);
  Object.assign(recovered.world.units[0], { path_failure: '', reload_remaining: 0 });
  const next = battleFacts(recovered, after).map(f => f.text).join(' ');
  assert.match(next, /阻塞状态已解除；不代表已经到达/); assert.match(next, /完成换弹/);
});
test('continuous speech expires after eight seconds of preparation and never publishes late audio', async () => {
  let now = 1000;
  const service = createCommentary({ read: frame, backend: () => model, continuous: true, now: () => now,
    speech: async () => { now += 8100; return speech(); } });
  assert.equal((await service.next('late')).status, 'stale');
  service.close();
});
test('verified casualty bypasses text model and goes directly to speech', async () => {
  let now = 1000, calls = 0;
  const current = frame();
  const service = createCommentary({ read: () => current, continuous: true, now: () => now,
    backend: () => { calls++; return model; }, speech });
  await service.next('a'); now += 2000; current.world.units[0].hp = 0;
  const result = await service.next('a');
  assert.equal(calls, 1); assert.equal(result.entry?.source, 'event');
  assert.match(result.entry!.text, /阵亡/); assert.equal(result.requests, 1);
  assert.equal(result.speechRequests, 2); service.close();
});
test('human sessions and paused matches never call either provider', async () => {
  const current = frame(); let calls = 0;
  const service = createCommentary({ read: () => current, backend: () => { calls++; return model; }, speech });
  current.kind = 'human'; assert.equal((await service.next('a')).status, 'spectator-only');
  current.kind = 'ai'; current.world.paused = true; assert.equal((await service.next('a')).status, 'idle');
  assert.equal(calls, 0); service.close();
});
test('one in-flight request; stop rejects late response and cannot reset budget', async () => {
  let finish!: () => void;
  const delayed: SystemOne = { async ask(...args) { await new Promise<void>(r => { finish = r; }); return model.ask(...args); } };
  const current = frame();
  const service = createCommentary({ read: () => current, backend: () => delayed, speech, limit: 1 });
  const pending = service.next('a');
  assert.equal((await service.next('a')).status, 'busy');
  service.stop('a'); finish();
  assert.equal((await pending).status, 'stale');
  assert.equal((await service.next('a')).status, 'budget');
  service.close();
});
test('world change while speech is pending discards text and audio', async () => {
  const current = frame();
  const service = createCommentary({ read: () => current, backend: () => model,
    speech: async () => { current.world.units[0].hp = 0; return speech(); } });
  assert.equal((await service.next('a')).status, 'stale'); service.close();
});
test('voice errors preserve caption; model errors are explicitly labeled fallback', async () => {
  const service = createCommentary({ read: frame, backend: () => ({ async ask() { throw Error('secret must not escape'); } }),
    speech: async () => { throw Error('private upstream message'); } });
  const result = await service.next('a');
  assert.equal(result.entry?.source, 'facts-fallback'); assert.equal(result.entry?.audioReady, false);
  assert.ok(result.entry?.text); assert.doesNotMatch(JSON.stringify(result), /secret|private/); service.close();
});
test('unchanged world stays quiet and cached audio expires', async () => {
  let time = 1000; const current = frame();
  const service = createCommentary({ read: () => current, backend: () => model, speech, now: () => time });
  const result = await service.next('a');
  assert.ok(result.entry); assert.ok(service.audio('a', result.entry!.id));
  assert.equal((await service.next('a')).status, 'quiet');
  time += 13000;
  assert.equal(service.audio('a', result.entry!.id), undefined);
  assert.equal((await service.next('a')).status, 'quiet'); service.close();
});
test('invalid evidence is rejected and replaced by observed fact', async () => {
  const service = createCommentary({ read: frame, backend: () => ({ async ask() { return { commentary: {
    type: 'json', value: { text: '绿队已经取得胜利！', evidence_ids: ['invented'] },
  } }; } }), speech });
  const result = await service.next('a'); assert.equal(result.entry?.source, 'facts-fallback');
  assert.doesNotMatch(result.entry!.text, /胜利/); service.close();
});
test('speech accepts split NDJSON frames and requires provider completion', async () => {
  const stream = (complete: boolean) => new Response(new ReadableStream({ start(controller) {
    for (const part of ['{"code":0,"da', 'ta":"YWJj"}\n', ...(complete ? ['{"code":20000000}'] : [])]) controller.enqueue(new TextEncoder().encode(part));
    controller.close();
  } }));
  let request: RequestInit | undefined;
  const result = await synthesizeCommentary('测试', { DOUBAO_TTS_API_KEY: 'secret' }, new AbortController().signal,
    (async (_url, init) => { request = init; return stream(true); }) as typeof fetch);
  assert.equal(result.audio.toString(), 'abc');
  assert.equal((request?.headers as Record<string, string>)['X-Api-Key'], 'secret');
  await assert.rejects(synthesizeCommentary('测试', { DOUBAO_TTS_API_KEY: 'secret' }, new AbortController().signal,
    (async () => stream(false)) as typeof fetch), /incomplete/);
});

test('subtitle expressions are frequent, bounded and placed at pauses', () => {
  assert.equal(commentarySubtitle('双方还在观察。', 'neutral'), '双方还在观察 🙂。');
  assert.equal(commentarySubtitle('真紧张，终于结束了！', 'tense', '😰 😌 🤯'), '真紧张 😰，终于结束了 😌！');
  assert.equal(commentarySubtitle('局势变化。', 'neutral', '⚔️ invalid'), '局势变化 🙂。');
  assert.equal(commentarySubtitle('松口气。', 'relieved', '😮‍💨'), '松口气 😮‍💨。');
});
