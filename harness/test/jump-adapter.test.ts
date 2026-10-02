import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createJumpGame, INPUTS, DURATION_LABELS, TIMED_INPUTS, previewMoves } from '../src/games/jump/adapter.js';
import type { JumpState } from '../src/games/jump/adapter.js';
import { createRealtimeMatch } from '../src/arena/realtime.js';
import { controlAnswer, createJumpBot, expandActions } from './jump-bot.js';
import { generateCandidates } from '../src/games/jump/candidates.js';
import { progress, step, validateLevel } from '../src/games/jump/engine.js';
import { createDeepSeekSystemOne } from '../src/systemone/deepseek.js';

function timedAnswer(control: string, frames: number) {
  return { ...controlAnswer(control), duration: controlAnswer(`frames_${frames}`)['control']! };
}

test('定时动作问题经过 DeepSeek logprobs 适配器，不超过20个候选', async () => {
  const game = createJumpGame();
  const state = game.initialState();
  let calls = 0;
  const backend = createDeepSeekSystemOne({ apiKey: 'test', fetchImpl: async () => {
    calls++;
    return new Response(JSON.stringify({ choices: [{ logprobs: { content: [{
      top_logprobs: [{ token: 'A', logprob: 0 }],
    }] } }] }), { status: 200 });
  } });
  const answers = await backend.ask(game.observe(state), game.questions(state));
  assert.equal(calls, 1);
  const control = answers['control'];
  assert.ok(control?.type === 'choice' && Object.hasOwn(TIMED_INPUTS, control.choice));
});

test('定时动作按准确帧数执行，到期松键；非法时长不执行', () => {
  const game = createJumpGame();
  let s = game.initialState();
  assert.throws(() => game.act(s, timedAnswer('right', 999)), /无效的持续时长/);
  s = game.act(s, timedAnswer('right', 36));
  for (let i = 0; i < 35; i++) s = game.step(s);
  assert.equal(game.decisionReady?.(s), false);
  s = game.step(s);
  assert.equal(game.decisionReady?.(s), true);
  assert.ok(Math.abs(s.actor.x - (64 + 36 * 3.2)) < 0.001);
  const x = s.actor.x;
  for (let i = 0; i < 10; i++) s = game.step(s);
  assert.equal(s.actor.x, x, '到期后不会因慢模型继续漂移');
});

test('定时动作中途落水立即取消，保留进度和实际死亡输入', () => {
  const game = createJumpGame();
  let s = game.act(game.initialState(), timedAnswer('right', 60));
  s.actor = { ...s.actor, x: 590, y: 469, vy: 5, grounded: false };
  s.progress.key = true;
  s = game.step(s);
  assert.equal(s.deaths, 1);
  assert.equal(s.remainingFrames, 0);
  assert.equal(s.deathLog[0]?.input, 'right');
  assert.equal(s.progress.key, true);
  assert.equal(s.actor.x, s.level.spawn.x);
});

test('动作段驱动调度：36帧动作中不重复问模型，1帧松键可立即接下一段', async () => {
  const frames: number[] = [];
  const game = createJumpGame();
  const match = createRealtimeMatch(game, { ask: async raw => {
    frames.push((raw as { frame: number }).frame);
    return controlAnswer(frames.length === 1 ? 'right_36' : 'idle_1');
  } }, { pauseWhileDeciding: true });
  for (let i = 0; i < 43; i++) await match.tick();
  assert.deepEqual(frames, [6, 42, 43]);
});

test('地面移动不会把远方最终落水误报为当前落点危险', () => {
  const game = createJumpGame();
  let s = game.act(game.initialState(), timedAnswer('right', 6));
  s = game.step(s);
  const obs = game.observe(s) as { facts: { landingSafe: boolean; landingX: number } };
  assert.equal(obs.facts.landingSafe, true);
  assert.equal(obs.facts.landingX, 67.2);
});

test('questions combine keys and duration in one bounded choice', () => {
 const game=createJumpGame(), qs=game.questions(game.initialState());
 assert.deepEqual(Object.keys(qs), ['control']);
 assert.ok(qs.control?.type === 'choice');
 assert.equal(Object.keys(qs.control.criteria).length,19);
});

test('observe：每次独立请求都携带地图，screen 默认不发', () => {
  const game = createJumpGame();
  const obs0 = game.observe(game.initialState()) as {
    realtime: boolean; frame: number; static?: { level: { width: number } }; level?: unknown;
    screen?: { rows: string[] }; actor: { x: number }; progress: { won: boolean }; deaths: number; physics?: unknown;
  };
  assert.equal(obs0.realtime, true);
  assert.equal(obs0.frame, 0);
  assert.ok(obs0.static && obs0.static.level.width >= 800, 'frame 0 观测带 static.level');
  assert.equal(obs0.level, undefined, 'level 不再随每次观测发送');
  assert.equal(obs0.screen, undefined, 'screen 默认不发');
  assert.equal(obs0.actor.x, 64);
  assert.equal(obs0.progress.won, false);
  assert.equal(obs0.deaths, 0);
  assert.equal(obs0.physics, undefined, '物理常量表不再随观测发送');
  // 首个决策帧（frame>0 的首次观测）需再带一次 static.level，之后不再发
  let s = game.initialState();
  s = game.step(s);
  assert.ok((game.observe(s) as { static?: unknown }).static, '模型首个决策帧仍需带 static.level');
  s = game.step(s);
  assert.ok((game.observe(s) as { static?: unknown }).static, '后续请求仍有完整地图');

  const qs = game.questions(game.initialState());
  const control = qs['control']!;
  assert.ok(control.type === 'choice' && control.instructions.includes('3.2'), 'instructions 携带物理参数');
  assert.equal(control.label, '动作与时长');

});

test('observe: 死亡后下一次观测补发 screen 一次', () => {
  const game = createJumpGame();
  let s = game.initialState();
  game.observe(s); // 占位帧
  s = { ...s, actor: { x: s.level.spawn.x, y: 440, vx: 0, vy: 5, grounded: false, held: false, dead: false }, frames: 5 };
  let guard = 0;
  while (s.deaths === 0 && guard++ < 600) s = game.step(s);
  const obs = game.observe(s) as { screen?: { rows: string[] } };
  assert.ok(obs.screen && obs.screen.rows.length > 0, '死后首帧应带 screen');
  assert.equal((game.observe(s) as { screen?: unknown }).screen, undefined, '只补发一次');
});

test('lastControl 回喂：上一决策输入的持续帧数与进度/x 变化', () => {
  const game = createJumpGame();
  let s = game.initialState();
  assert.ok(!('lastControl' in (game.observe(s) as object)), '首个观测没有 lastControl');
  s = game.act(s, controlAnswer('right'));
  for (let i = 0; i < 12; i++) s = game.step(s);
  const obs = game.observe(s) as { lastControl: { input: string; frames: number; progressDelta: number; xDelta: number } };
  assert.equal(obs.lastControl.input, 'right');
  assert.equal(obs.lastControl.frames, 12);
  // 出生点右行 12 帧途经金币 (80,388)：progressDelta=1，x 推进约 38px
  assert.equal(obs.lastControl.progressDelta, 1);
  assert.ok(obs.lastControl.xDelta > 30, `xDelta=${obs.lastControl.xDelta}`);
});

test('act 非法 control：state 不变；合法 control：input 更新', () => {
  const game = createJumpGame();
  const s0 = game.initialState();
  assert.equal(game.act(s0, controlAnswer('fly')), s0);
  const s1 = game.act(s0, controlAnswer('jumpRight'));
  assert.notEqual(s1, s0);
  assert.deepEqual(s1.input, { move: 1, jump: true });
});

test('step 按住右：角色向右推进', () => {
  const game = createJumpGame();
  let s = game.initialState();
  s = game.act(s, controlAnswer('right'));
  const x0 = s.actor.x;
  for (let i = 0; i < 30; i++) s = game.step(s);
  assert.ok(s.actor.x > x0, `x ${x0} -> ${s.actor.x}`);
  assert.equal(s.frames, 30);
});

test('摔死：回出生点、progress 保留、deaths+1', () => {
  const game = createJumpGame();
  let s = game.initialState();
  // 悬空下落，越过 y=470 即死
  s = { ...s, actor: { x: s.level.spawn.x, y: 440, vx: 0, vy: 5, grounded: false, held: false, dead: false } };
  let guard = 0;
  while (s.deaths === 0 && guard++ < 600) s = game.step(s);
  assert.equal(s.deaths, 1, '应当摔死一次');
  assert.equal(s.actor.x, s.level.spawn.x, '复活回出生点');
  assert.equal(s.actor.dead, false);
  assert.equal(s.progress.won, false);
});

test('机器人后端全程通关 starterLevel（计划耗尽才重新规划）', async () => {
  const game = createJumpGame();
  const match = createRealtimeMatch(game, createJumpBot(6), { decisionMs: 100 });
  let guard = 0;
  while (match.summary.outcome === 'finished' && !game.isTerminal(match.state) && guard++ < 10000) {
    await match.tick();
  }
  assert.ok(game.isTerminal(match.state), `ticks=${match.summary.ticks} 未终局`);
  assert.equal((match.state as JumpState).progress.won, true,
    `frames=${(match.state as JumpState).frames} deaths=${(match.state as JumpState).deaths} 疑似撞帧数上限`);
  assert.ok(match.summary.decisions > 0);
});

test('直接驱动：按机器人策略逐帧推进可在帧数上限内通关', () => {
  const game = createJumpGame();
  let s: JumpState = game.initialState();
  let queue: string[] = [];
  let guard = 0;
  while (!game.isTerminal(s) && guard++ < 90 * 60) {
    if (queue.length === 0) {
      const c = generateCandidates(s.level, s.actor, s.progress).find(c => !c.dead);
      queue = c ? expandActions(c.actions) : ['idle'];
    }
    s = game.act(s, controlAnswer(queue.shift()!));
    s = game.step(s);
  }
  assert.equal(s.progress.won, true, `frames=${s.frames} deaths=${s.deaths} 未通关`);
  assert.ok(s.frames < 90 * 60);
});

test('帧数上限内化：frames 达上限未通关则终局且 won=false', () => {
  const game = createJumpGame(undefined, 100);
  const s0 = game.initialState();
  const stuck: JumpState = { ...s0, frames: 100 };
  assert.equal(game.isTerminal(stuck), true);
  assert.equal(stuck.progress.won, false);
});

test('facts: 站立时落点是脚下，gapAhead/gapTooWide 按朝向算出', () => {
  const game = createJumpGame();
  const obs = game.observe(game.initialState()) as {
    facts: {
      landingX: number; landingY: number; landingSafe: boolean;
      distToEdge: { left: number; right: number } | null; distToHazard: number | null;
      gapAhead: number | null; maxJumpPx: number; gapTooWide: boolean;
    };
  };
  const f = obs.facts;
  assert.equal(f.landingX, 64);   // 出生点站立不动
  assert.equal(f.landingY, 400);
  assert.equal(f.landingSafe, true);
  assert.deepEqual(f.distToEdge, { left: 64, right: 496 }); // 平台 {x:0,w:560}
  assert.ok(f.distToHazard !== null && f.distToHazard > 480 && f.distToHazard <= 500,
    `向右直走会在平台边缘（x=560）摔死，distToHazard=${f.distToHazard}`);
  assert.equal(f.gapAhead, 64);   // 朝向终点（右），下一块同高平台在 x=624
  assert.equal(f.gapTooWide, false, '64px 缺口在原地跳越能力内');
  assert.ok(f.maxJumpPx > 100 && f.maxJumpPx < 200, `maxJumpPx=${f.maxJumpPx}`);
});

test('facts: 空中外推落点与引擎逐步模拟一致', () => {
  const game = createJumpGame();
  const s0 = game.initialState();
  // 空中状态：地面上方向右跳起后的中间帧
  const airborne = { x: 300, y: 330, vx: 3.2, vy: -5, grounded: false, held: true, dead: false };
  const obs = game.observe({ ...s0, actor: airborne }) as {
    facts: { landingX: number; landingY: number; landingSafe: boolean };
  };
  // 用引擎按同一恒定输入（move=sign(vx), jump=held）独立模拟到落地/摔死
  const a = { ...airborne };
  const p = progress();
  for (let i = 0; i < 600 && !a.grounded && !a.dead; i++) step(a, { move: 1, jump: true }, s0.level, p);
  assert.equal(obs.facts.landingX, +a.x.toFixed(1));
  assert.equal(obs.facts.landingY, +a.y.toFixed(1));
  assert.equal(obs.facts.landingSafe, !a.dead && a.grounded);
  assert.equal(obs.facts.landingSafe, true, '该轨迹应落回地面平台');
});

test('facts: 水面正上方外推落点不安全；超宽缺口 gapTooWide=true', () => {
  const wide = validateLevel({
    version: 2, title: '天堑', width: 800, spawn: { x: 64, y: 400 }, goal: { x: 700, y: 400 },
    platforms: [{ x: 0, y: 400, w: 200 }, { x: 600, y: 400, w: 200 }],
    coins: [{ x: 100, y: 388 }], key: { x: 120, y: 388 }, switch: { x: 150, y: 388 },
    door: { x: 700, y: 300, h: 100 },
  });
  const game = createJumpGame(wide);
  const obs = game.observe(game.initialState()) as {
    facts: { gapAhead: number | null; gapTooWide: boolean; maxJumpPx: number };
  };
  assert.equal(obs.facts.gapAhead, 400);
  assert.equal(obs.facts.gapTooWide, true, '400px 缺口超过原地跳越能力');

  // 悬空在缺口正上方：落点在水里
  const falling = { x: 400, y: 300, vx: 0, vy: 2, grounded: false, held: false, dead: false };
  const obs2 = game.observe({ ...game.initialState(), actor: falling }) as {
    facts: { landingSafe: boolean; landingY: number };
  };
  assert.equal(obs2.facts.landingSafe, false);
  assert.ok(obs2.facts.landingY > 470, `落水点 y=${obs2.facts.landingY}`);
});


test('timed predictions reproduce execution and do not mutate state', () => {
 const game=createJumpGame(), s=game.initialState();
 s.actor={...s.actor,x:236.8,y:274.4,vx:3.2,vy:-8.9,grounded:false,held:true};
 const before=JSON.stringify(s), predictions=previewMoves(s);
 assert.equal(JSON.stringify(s),before);
 assert.equal(predictions.right_24!.gainedKey,true);
 assert.equal(predictions.idle_24!.gainedKey,false);
 for(const [id, action] of Object.entries(TIMED_INPUTS)) {
 let copy=game.act(structuredClone(s),controlAnswer(id));
 for(let i=0;i<action.frames;i++)copy=game.step(copy);
 assert.equal(+copy.actor.x.toFixed(1),predictions[id]!.x);
 assert.equal(+copy.actor.y.toFixed(1),predictions[id]!.y);
 }
});
