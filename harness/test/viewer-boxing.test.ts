import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { startViewer } from '../src/viewer/server.js';
import { createMockSystemOne } from '../src/systemone/mock.js';
import { createDefaultRegistry } from '../src/games/index.js';

test('viewer: 打拳开局并跑到终局', { timeout: 60_000 }, async () => {
  const dir = mkdtempSync(join(tmpdir(), 'jev-view-'));
  try {
    const server = await startViewer({ backend: createMockSystemOne(), registry: createDefaultRegistry(), port: 0, startDelayMs: 0, turnDelayMs: 0, tickSleepMs: 0, logDir: dir });
    const base = `http://127.0.0.1:${server.port}`;
    interface MatchView { status: string; outcome: string | null; latest: { observation: unknown } | null }
    try {
      const started = await (await fetch(`${base}/api/match/boxing`, { method: 'POST' })).json() as { matchId: string };
      assert.ok(started.matchId);
      let final: MatchView | null = null;
      for (let i = 0; i < 600; i++) {   // 打拳 45 秒局 + 决策时间，给足轮询预算
        await new Promise(r => setTimeout(r, 200));
        final = await (await fetch(`${base}/api/match/${started.matchId}/state`)).json() as MatchView;
        if (final.status === 'done') break;
      }
      assert.ok(final && final.status === 'done', `status=${final && final.status}`);
      assert.ok(final.outcome !== null && ['won', 'lost', 'draw', 'finished', 'void', 'tick-limit'].includes(final.outcome), `outcome=${final.outcome}`);
    } finally {
      await server.close();
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
