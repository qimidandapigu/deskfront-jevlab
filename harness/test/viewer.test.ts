import { after, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { startViewer } from '../src/viewer/server.js';
import { createDefaultRegistry } from '../src/games/index.js';
import { createMockSystemOne } from '../src/systemone/mock.js';

const tmpDirs: string[] = [];
function tmpLogDir(): string {
  const dir = mkdtempSync(join(tmpdir(), 'jev-view-'));
  tmpDirs.push(dir);
  return dir;
}
after(() => { for (const d of tmpDirs) rmSync(d, { recursive: true, force: true }); });

test('human versus model uses common cancellation; stopping never lets a late rival overwrite outcome', async () => {
  const dir = tmpLogDir();
  let complete: ((answers: Record<string, import('../src/systemone/types.js').Answer>) => void) | undefined;
  const server = await startViewer({ backend: createMockSystemOne(), backends: { names: ['slow'], defaultName: 'slow', create: () => ({ ask: () => new Promise(resolve => { complete = resolve; }) }) },
    registry: createDefaultRegistry(), port: 0, startDelayMs: 0, logDir: dir });
  const base = `http://127.0.0.1:${server.port}`;
  try {
    const started = await (await fetch(`${base}/api/match/boxing`, { method: 'POST', body: JSON.stringify({ mode: 'human', rival: 'slow' }) })).json() as { matchId: string };
    for (let i = 0; i < 40 && !complete; i++) await new Promise(r => setTimeout(r, 50));
    assert.ok(complete, 'rival request started');
    await fetch(`${base}/api/match/${started.matchId}/stop`, { method: 'POST' });
    const before = readFileSync(join(dir, `${started.matchId}.jsonl`), 'utf8');
    complete({ action: { type: 'choice', choice: 'heavy', confidence: 1, probabilities: { heavy: 1 } } });
    await new Promise(r => setTimeout(r, 30));
    assert.equal(readFileSync(join(dir, `${started.matchId}.jsonl`), 'utf8'), before);
    const records = before.trim().split('\n').map(line => JSON.parse(line));
    assert.ok(records.some(r => r.execution?.side === 'rival' && r.execution.status === 'discarded'));
    assert.equal(records.at(-1).outcome, 'aborted');
  } finally { await server.close(); }
});

test('viewer: 列表页、开局、轮询到终局、client.js 直出', async () => {
  const server = await startViewer({ backend: createMockSystemOne(), registry: createDefaultRegistry(), port: 0, startDelayMs: 0, turnDelayMs: 0, logDir: tmpLogDir() });
  const base = `http://127.0.0.1:${server.port}`;
  try {
    const home = await (await fetch(`${base}/`)).text();
    assert.ok(home.includes('推箱子') && home.includes('/game/sokoban'));

    const clientJs = await (await fetch(`${base}/client/sokoban.js`)).text();
    assert.ok(clientJs.includes('window.gameClient'));

    const started = await (await fetch(`${base}/api/match/sokoban`, { method: 'POST' })).json() as { matchId: string };
    assert.ok(started.matchId);

    type StateView = { status: string; outcome: string | null; stats: { steps: number }; latest: { observation: unknown; answers: Record<string, unknown> } | null };
    let final: StateView | null = null;
    for (let i = 0; i < 20; i++) {
      await new Promise(r => setTimeout(r, 50));
      final = await (await fetch(`${base}/api/match/${started.matchId}/state`)).json() as StateView;
      if (final && final.status === 'done') break;
    }
    assert.ok(final && final.status === 'done' && final.outcome !== null);
    assert.ok(final.latest && final.latest.observation && final.latest.answers['action']);
    assert.equal(final.stats.steps, 1, 'initial preview is not an executed action');
  } finally {
    await server.close();
  }
});

test('viewer: 游戏页标签由插件注入（question.label + optionLabels），无跨游戏硬编码表', async () => {
  const server = await startViewer({ backend: createMockSystemOne(), registry: createDefaultRegistry(), port: 0, startDelayMs: 0, turnDelayMs: 0, logDir: tmpLogDir() });
  const base = `http://127.0.0.1:${server.port}`;
  try {
    const sokoban = await (await fetch(`${base}/game/sokoban`)).text();
    assert.ok(sokoban.includes('"action":"动作"'), '题目标签来自 question.label');
    assert.ok(sokoban.includes('"deadlockRisk":"死锁风险"'));
    assert.ok(sokoban.includes('"U":"上"'), '选项标签来自 plugin.optionLabels');
    assert.ok(!sokoban.includes('被敌人瞄准'), '不应残留其他游戏的硬编码标签');

    const boxing = await (await fetch(`${base}/game/boxing`)).text();
    assert.ok(boxing.includes('"needGuard":"是否需要格挡"'));
    assert.ok(boxing.includes('"danger":"危险"'));
    assert.ok(boxing.includes('"jab":"刺拳"'));
    assert.ok(!boxing.includes('"U":"上"'), '不应残留其他游戏的硬编码选项标签');
  } finally {
    await server.close();
  }
});

test('viewer: 对局结束后 JSONL 末行是 outcome 结算记录', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'jev-view-'));
  try {
    const server = await startViewer({ backend: createMockSystemOne(), registry: createDefaultRegistry(), port: 0, startDelayMs: 0, turnDelayMs: 0, logDir: dir });
    const base = `http://127.0.0.1:${server.port}`;
    try {
      const started = await (await fetch(`${base}/api/match/sokoban`, { method: 'POST' })).json() as { matchId: string };
      let status = 'running';
      for (let i = 0; i < 40 && status !== 'done'; i++) {
        await new Promise(r => setTimeout(r, 50));
        status = ((await (await fetch(`${base}/api/match/${started.matchId}/state`)).json()) as { status: string }).status;
      }
      assert.equal(status, 'done');
      await new Promise(r => setTimeout(r, 50)); // outcome 记录在 runner resolve 的 then 里追加
      const lines = readFileSync(join(dir, `${started.matchId}.jsonl`), 'utf8').trim().split('\n').map(l => JSON.parse(l) as Record<string, unknown>);
      const last = lines[lines.length - 1]!;
      assert.equal(last['type'], 'outcome');
      assert.equal(last['game'], 'sokoban');
      assert.ok(typeof last['outcome'] === 'string');
      assert.ok(typeof last['turns'] === 'number');
      assert.equal(last['observation'], undefined, '结算记录不带观测');
    } finally {
      await server.close();
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('viewer: 未知游戏 404', async () => {
  const server = await startViewer({ backend: createMockSystemOne(), registry: createDefaultRegistry(), port: 0, startDelayMs: 0, turnDelayMs: 0, logDir: tmpLogDir() });
  try {
    const res = await fetch(`http://127.0.0.1:${server.port}/api/match/mahjong`, { method: 'POST' });
    assert.equal(res.status, 404);
  } finally {
    await server.close();
  }
});

test('viewer: 自己玩模式开局、出招、终局后拒绝行动', async () => {
  const server = await startViewer({ backend: createMockSystemOne(), registry: createDefaultRegistry(), port: 0, startDelayMs: 0, turnDelayMs: 0, logDir: tmpLogDir() });
  const base = `http://127.0.0.1:${server.port}`;
  try {
    const post = (path: string, body: unknown) => fetch(`${base}${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const started = await (await post('/api/match/sokoban', { variant: 'gravel', mode: 'human' })).json() as { matchId: string; kind: string };
    assert.equal(started.kind, 'human');

    type HumanView = { status: string; outcome: string | null; latest: { turn: number } | null; choices: { question: string; keys: string[] } | null };
    let view = await (await fetch(`${base}/api/match/${started.matchId}/state`)).json() as HumanView;
    assert.equal(view.status, 'running');
    assert.ok(view.choices && view.choices.keys.length > 0);

    const first = view.choices!;
    view = await (await post(`/api/match/${started.matchId}/action`, { question: first.question, choice: first.keys[0] })).json() as HumanView;
    assert.equal(view.status, 'running');
    assert.ok(view.latest && view.latest.turn === 2, '合法出招后进入第 2 回合');

    const bad = await post(`/api/match/${started.matchId}/action`, { question: first.question, choice: 'X' });
    assert.equal(bad.status, 400, '非法选择返回 400');
  } finally {
    await server.close();
  }
});

test('viewer: 实时游戏真人局可开（键盘输入模式），后端选择失败返回 400', async () => {
  const server = await startViewer({
    backend: createMockSystemOne(),
    backends: { names: ['mock', 'broken'], create: (name) => { if (name === 'broken') throw new Error('缺 API key'); return createMockSystemOne(); } },
    registry: createDefaultRegistry(),
    port: 0,
    logDir: tmpLogDir(),
  });
  const base = `http://127.0.0.1:${server.port}`;
  try {
    const post = (path: string, body: unknown) => fetch(`${base}${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const human = await post('/api/match/boxing', { mode: 'human' });
    assert.equal(human.status, 200);
    assert.equal(((await human.json()) as { kind: string }).kind, 'human');
    const badBackend = await post('/api/match/sokoban', { backend: 'broken' });
    assert.equal(badBackend.status, 400);
    assert.ok(((await badBackend.json()) as { error: string }).error.includes('缺 API key'));
  } finally {
    await server.close();
  }
});
