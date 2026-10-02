import { after, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { startViewer } from '../src/viewer/server.js';
import { createDefaultRegistry } from '../src/games/index.js';
import { createJumpBot } from './jump-bot.js';

const tmpDirs: string[] = [];
function tmpLogDir(): string {
  const dir = mkdtempSync(join(tmpdir(), 'jev-view-'));
  tmpDirs.push(dir);
  return dir;
}
after(() => { for (const d of tmpDirs) rmSync(d, { recursive: true, force: true }); });

test('viewer: 闯关实时模式注册、AI 对局跑通、client.js 与 kaplay 直出', async () => {
  const registry = createDefaultRegistry();
  const plugin = registry.get('jump');
  assert.equal(plugin.name, '萤光小径');
  assert.equal(plugin.mode, 'realtime');

  const server = await startViewer({ backend: createJumpBot(6), registry, port: 0, startDelayMs: 0, tickSleepMs: 0, logDir: tmpLogDir() });
  const base = `http://127.0.0.1:${server.port}`;
  try {
    const home = await (await fetch(`${base}/`)).text();
    assert.ok(home.includes(plugin.name) && home.includes('/game/jump'));

    const clientJs = await (await fetch(`${base}/client/jump.js`)).text();
    assert.ok(clientJs.includes('window.gameClient'));

    const kaplay = await fetch(`${base}/vendor/kaplay.js`);
    assert.equal(kaplay.status, 200);
    assert.ok((await kaplay.text()).includes('kaplay'));

    const started = await (await fetch(`${base}/api/match/jump`, { method: 'POST' })).json() as { matchId: string };
    interface MatchStateView { status: string; outcome: string | null; latest: { frame: number; observation: { progress: { won: boolean } } } | null }
    let final: MatchStateView | null = null;
    for (let i = 0; i < 600; i++) {
      await new Promise(r => setTimeout(r, 50));
      final = await (await fetch(`${base}/api/match/${started.matchId}/state`)).json() as MatchStateView;
      if (final.status === 'done') break;
    }
    assert.ok(final && final.status === 'done', `status=${final && final.status}`);
    assert.equal(final.outcome, 'won');
    assert.ok(final.latest && typeof final.latest.observation.progress.won === 'boolean');
  } finally {
    await server.close();
  }
});

test('viewer: 闯关真人实时局——/input 驱动角色移动', async () => {
  const registry = createDefaultRegistry();
  const server = await startViewer({ backend: createJumpBot(), registry, port: 0, startDelayMs: 0, tickSleepMs: 0, logDir: tmpLogDir() });
  const base = `http://127.0.0.1:${server.port}`;
  try {
    const started = await (await fetch(`${base}/api/match/jump`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: 'human' }),
    })).json() as { matchId: string; kind: string };
    assert.equal(started.kind, 'human');

    const stateOf = async () => (await (await fetch(`${base}/api/match/${started.matchId}/state`)).json()) as {
      status: string; latest: { frame: number; observation: { actor: { x: number } } } | null;
    };
    const x0 = (await stateOf()).latest?.observation.actor.x ?? 0;

    // 按住右 1 秒
    const inp = await fetch(`${base}/api/match/${started.matchId}/input`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ input: 'right' }),
    });
    assert.equal(inp.status, 200);
    await new Promise(r => setTimeout(r, 1000));
    const s1 = await stateOf();
    assert.ok(s1.latest && s1.latest.observation.actor.x > x0, `x ${x0} -> ${s1.latest?.observation.actor.x}`);
    assert.ok(s1.latest.frame > 30, `frame=${s1.latest?.frame}，服务器应按 60fps 推进`);
    const compact = await (await fetch(`${base}/api/match/${started.matchId}/state?compact=1`)).json() as {
      recent: unknown[]; latest: { observation: Record<string, unknown> };
    };
    assert.deepEqual(compact.recent, []);
    assert.ok(compact.latest.observation.actor);
    assert.equal(compact.latest.observation.movePreviews, undefined, '真人帧不生成模型动作预测');
    const full = await (await fetch(`${base}/api/match/${started.matchId}/state`)).json() as { recent: unknown[] };
    assert.ok(full.recent.length > 0, '完整接口仍保留最近记录');
    assert.ok(JSON.stringify(compact).length < JSON.stringify(full).length / 2, '精简轮询显著减少传输量');

    // 非法 input 被拒
    const bad = await fetch(`${base}/api/match/${started.matchId}/input`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ input: '";DROP' }),
    });
    assert.equal(bad.status, 400);
  } finally {
    await server.close();
  }
});
