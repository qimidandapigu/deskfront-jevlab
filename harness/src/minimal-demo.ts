/** Offline executable example: npx tsx src/minimal-demo.ts [--recovery] */
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createMinimalBoxing, createMinimalSokoban } from './games/minimal-examples.js';
import { SOKOBAN_LEVELS } from './games/sokoban/index.js';
import { runTurnGame } from './arena/runner.js';
import { runRealtimeGame } from './arena/realtime.js';
import { createMockSystemOne } from './systemone/mock.js';

const args = process.argv.slice(2);
if (args.some(arg => arg !== '--recovery')) throw new Error('Usage: npx tsx src/minimal-demo.ts [--recovery]');
const recovery = args.includes('--recovery');
const records: unknown[] = [];
const backend = createMockSystemOne();
const sokoban = await runTurnGame(createMinimalSokoban(SOKOBAN_LEVELS[0]!.rows, recovery), backend,
  { maxTurns: 30, onUpdate: record => records.push(record) });
const boxing = await runRealtimeGame(createMinimalBoxing(recovery), backend,
  { maxTicks: 120, tickSleepMs: 0, onUpdate: record => records.push(record), onFeedback: record => records.push(record) });
const dir = resolve('logs', `minimal-${recovery ? 'recovery' : 'off'}-${Date.now()}`);
mkdirSync(dir, { recursive: true });
writeFileSync(resolve(dir, 'decisions.jsonl'), records.map(r => JSON.stringify(r)).join('\n') + '\n');
writeFileSync(resolve(dir, 'summary.json'), JSON.stringify({ backend: 'mock', recovery, sokoban, boxing }, null, 2) + '\n');
console.log(JSON.stringify({ backend: 'mock', recovery, sokoban: sokoban.outcome, boxing: boxing.outcome, logs: dir }, null, 2));
