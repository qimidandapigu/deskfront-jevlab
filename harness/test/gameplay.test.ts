import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { SOKOBAN_LEVELS } from '../src/games/sokoban/index.js';
import { parse, won } from '../src/games/sokoban/engine.js';
import { reachablePushes, applyPush, pushPositionKey } from '../src/games/sokoban/pushes.js';
import { startViewer } from '../src/viewer/server.js';
import { createDefaultRegistry } from '../src/games/index.js';

test('所有推箱子关卡存在可执行的通关路线', () => {
  for (const level of SOKOBAN_LEVELS) {
    const initial = parse(level.rows);
    const queue = [initial];
    const seen = new Set([pushPositionKey(initial)]);
    let solved = false;
    for (let i = 0; i < queue.length && i < 30_000; i++) {
      const state = queue[i]!;
      if (won(state)) { solved = true; break; }
      for (const push of reachablePushes(state)) {
        if (push.deadlock) continue;
        const next = applyPush(state, push);
        const key = pushPositionKey(next);
        if (!seen.has(key)) { seen.add(key); queue.push(next); }
      }
    }
    assert.equal(solved, true, `${level.id} 未找到解，不能交给玩家作为正式关卡`);
  }
});

test('预览所有游戏与真人通关无需模型，并准确统计操作次数', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'quickplay-ux-'));
  let calls = 0;
  const server = await startViewer({
    registry: createDefaultRegistry(), port: 0, startDelayMs: 0, logDir: dir,
    backend: { ask: async () => { calls++; throw new Error('真人模式不应请求模型'); } },
  });
  const base = `http://127.0.0.1:${server.port}`;
  const post = async (path: string, body: unknown) => fetch(base + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  try {
    for (const id of ['sokoban', 'boxing', 'jump', 'soldiers']) {
      const response = await fetch(`${base}/api/preview/${id}`);
      assert.equal(response.status, 200);
      assert.ok((await response.json() as { observation: unknown }).observation);
    }
    const start = await (await post('/api/match/sokoban', { mode: 'human', variant: 'first-push' })).json() as { matchId: string };
    const action = `/api/match/${start.matchId}/action`;
    const end = await (await post(action, { question: 'action', choice: 'U' })).json() as { status: string; outcome: string; stats: { steps: number } };
    assert.equal(end.status, 'done');
    assert.equal(end.outcome, 'won');
    assert.equal(end.stats.steps, 1);
    assert.equal((await post(action, { question: 'action', choice: 'U' })).status, 400);
    assert.equal(calls, 0);
  } finally {
    await server.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
