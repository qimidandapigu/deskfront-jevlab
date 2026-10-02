import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createCommentaryDirector } from '../src/deskfront/commentary-director.js';
import type { BattleFrame } from '../src/deskfront/commentary.js';

test('native playback clock waits for macro changes, keeps volume command, cancels on pause', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'commentary-'));
  let now = 10000, calls = 0;
  const frame: BattleFrame = { kind: 'ai', status: 'running', world: { run_id: 'r', time: 1,
    units: [{ id: 'g', faction: 'green', hp: 100, max_hp: 100 }, { id: 'r', faction: 'red', hp: 100, max_hp: 100 }] } };
  const director = createCommentaryDirector({ directory: () => directory, autoTick: false, now: () => now,
    read: () => frame, backend: () => ({ async ask() { calls++; return { commentary: { type: 'json', value: {
      text: calls === 1 ? '双方队员仍在场上，兵力暂时相当。' : '目前双方均没有队员卧倒。', evidence_ids: ['s1'] } } }; } }),
    speech: async () => ({ audio: Buffer.from('test audio'), totalMs: 1, firstAudioMs: 1 }) });
  const receipt = (id = '', phase = 'idle', remaining_ms = 0) => writeFileSync(join(directory, 'commentary-status.json'), JSON.stringify({
    ready: true, session: 'a', run_id: 'r', updated_at: now, id, phase, remaining_ms,
    subtitle_visible: phase === 'playing', audio_playing: phase === 'playing' }));
  const command = () => JSON.parse(readFileSync(join(directory, 'commentary-command.json'), 'utf8'));
  try {
    director.setEnabled('a', true);
    await director.step('a'); assert.equal(calls, 0, 'old engines must not incur provider costs');
    receipt(); await director.step('a'); await director.step('a');
    const first = command(); assert.equal(first.action, 'play'); assert.equal(calls, 1);
    director.volume('a', .3); assert.equal(command().command_id, first.command_id); assert.equal(command().action, 'play');
    now += 2000; receipt(first.id, 'playing', 15000); await director.step('a'); assert.equal(calls, 1);
    receipt(first.id, 'playing', 2500); await director.step('a'); assert.equal(calls, 1, 'unchanged world stays quiet');
    now += 10000; frame.world.units[0].hp = 60; receipt(first.id, 'playing', 2500); await director.step('a'); assert.equal(calls, 2);
    await director.step('a'); assert.equal(calls, 2, 'only one next sentence buffered');
    now += 2000; receipt(first.id); await director.step('a'); assert.notEqual(command().id, first.id);
    frame.world.paused = true; await director.step('a'); assert.equal(command().action, 'stop');
    assert.equal(director.snapshot('a').status, 'paused'); assert.equal(calls, 2);
    receipt(first.id); await director.step('a');
    assert.equal(director.snapshot('a').playback?.audio_playing, false, 'paused API must refresh native stop receipt');
    director.setEnabled('a', false); assert.equal(command().enabled, false);
  } finally { director.close(); rmSync(directory, { recursive: true, force: true }); }
});
