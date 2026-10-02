import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';

test('cli: lists the shared catalog and plays a selected realtime game with limits', () => {
  const catalog = JSON.parse(execFileSync(process.execPath, ['--import', 'tsx', 'src/cli.ts', 'list'], { encoding: 'utf8' }));
  assert.ok(catalog.some((g: { id: string }) => g.id === 'soldiers-endless'));
  assert.ok(catalog.some((g: { id: string }) => g.id === 'jgp-demo'));
  const output = execFileSync(process.execPath, ['--import', 'tsx', 'src/cli.ts', 'play', 'boxing', '--backend', 'mock', '--max-ticks', '2'], { encoding: 'utf8', timeout: 10000 });
  const result = JSON.parse(output.slice(0, output.lastIndexOf('\n决策日志:')));
  assert.equal(result.gameId, 'boxing'); assert.equal(result.outcome, 'tick-limit');
  assert.equal(result.config.runtime.maxTicks, 2);
});

test('cli: inspect 打印 sokoban initialState 下的 observe + questions JSON', () => {
  const out = execFileSync(process.execPath, ['--import', 'tsx', 'src/cli.ts', 'inspect', 'sokoban'], { encoding: 'utf8', timeout: 60_000 });
  const parsed = JSON.parse(out) as {
    observe: { board: { rows: string[] } }; questions: Record<string, { type: string; label?: string }>;
  };
  assert.ok(parsed.observe.board.rows.length > 0);
  assert.equal(parsed.questions['action']?.type, 'choice');
  assert.equal(parsed.questions['action']?.label, '动作');
});

test('cli: inspect 实时游戏（jump 首帧观测带 static.level）与 sokoban variant', () => {
  const jump = JSON.parse(execFileSync(process.execPath, ['--import', 'tsx', 'src/cli.ts', 'inspect', 'jump'], { encoding: 'utf8', timeout: 60_000 })) as {
    observe: { static?: { level?: { width: number } } }; questions: Record<string, { type: string }>;
  };
  assert.ok(jump.observe.static?.level && jump.observe.static.level.width >= 800);
  assert.equal(jump.questions['control']?.type, 'choice');
  assert.equal(jump.questions['shouldJumpNow'], undefined);

  const twin = JSON.parse(execFileSync(process.execPath, ['--import', 'tsx', 'src/cli.ts', 'inspect', 'sokoban', 'twin-halls'], { encoding: 'utf8', timeout: 60_000 })) as {
    observe: { board: { rows: string[] } };
  };
  assert.ok(twin.observe.board.rows.some(r => r.includes('*')), 'twin-halls 关卡含已在目标上的箱子');
});
