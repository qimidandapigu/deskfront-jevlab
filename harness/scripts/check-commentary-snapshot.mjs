// One billed model + speech attempt on a recorded engine snapshot, NOT a live match.
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { loadEnvironment, createConfiguredBackend } from '../src/config.ts';
import { createCommentary, synthesizeCommentary } from '../src/deskfront/commentary.ts';
loadEnvironment();
const file = process.argv[2];
if (!file) throw Error('Provide a saved /state JSON path. This probe makes one billed model and speech attempt.');
const saved = JSON.parse(readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
const observation = saved.latest?.observation;
if (!observation?.units?.length || observation.paused) throw Error('Snapshot must contain unpaused engine units');
const folder = resolve('logs/commentary/recorded-probe'); mkdirSync(folder, { recursive: true });
let audio;
const service = createCommentary({
  read: () => ({ kind: 'ai', status: 'running', world: observation }),
  backend: () => createConfiguredBackend('commentary'),
  speech: async (text, signal) => { const result = await synthesizeCommentary(text, process.env, signal); audio = result.audio; return result; },
});
try {
  const result = await service.next('recorded-snapshot');
  const report = { scope: 'Recorded real engine snapshot; real model and speech; not live playback timing', file, ...result };
  writeFileSync(resolve(folder, 'report.json'), JSON.stringify(report, null, 2));
  if (result.entry?.audioReady && audio) writeFileSync(resolve(folder, 'sample.mp3'), audio);
  console.log(JSON.stringify(report));
  if (result.entry?.source !== 'model' || !result.entry?.audioReady) process.exitCode = 1;
} finally { service.close(); }
