// Jump 的 SystemOne 接入层（实时模式）：类马里奥玩法。物理 60fps 逐帧推进，
// AI 一次选择按键与持续帧数，到期再决策；真人仍按键持续控制。
// 左/右移动、跳、左跳、右跳或站立。摔死不判负：回出生点、progress 保留、
// deaths+1。终局：progress.won 或 frames 达到 maxFrames（实时线由 runner 的
// maxTicks 兜底）。观测站"自己玩"走 /api/match/:id/input，答案键约定为 control。
import type { RealtimeGame } from '../../arena/plugin.js';
import type { Question } from '../../systemone/types.js';
import type { GroupedObservation } from '../../arena/observe.js';

import { PHYSICS, actor, progress, copyProgress, observation, starterLevel, step, tileMap, replayActions } from './engine.js';
import type { ActorState, Level, Progress } from './engine.js';

export type { RealtimeGame } from '../../arena/plugin.js';

export interface JumpInput { move: -1 | 0 | 1; jump: boolean }

export interface DeathRecord {
  frame: number;
  /** 死亡时的坐标（像素），用于让模型记住"哪里会死" */
  x: number;
  y: number;
  /** 死亡瞬间正在执行的输入 */
  input: string;
}

export interface JumpState {
  level: Level;
  actor: ActorState;
  progress: Progress;
  input: JumpInput;
  recentResults?: Array<{ input: string; startX: number; endX: number; progressDelta: number }>;
  deaths: number;
  frames: number; // 已推进的物理帧数（60 帧 = 1 秒）
  /** 近期死亡记录（最新在后），作为跨决策的"记忆"随观测发给模型 */
  deathLog: DeathRecord[];
  /** 近期输入历史（最新在后），让模型看到自己刚才按了什么 */
  inputLog: string[];
  /** AI 动作剩余物理帧；真人/旧后端无此字段，保持原有按键语义。 */
  remainingFrames?: number;
  /** 上一次决策的快照（act 时记录），observe 据此产出 lastControl 成效回喂 */
  lastDecision?: { input: string; atFrame: number; progress: Progress; x: number };
}

export const INPUTS: Record<string, JumpInput> = {
  idle: { move: 0, jump: false },
  left: { move: -1, jump: false },
  right: { move: 1, jump: false },
  jump: { move: 0, jump: true },
  jumpLeft: { move: -1, jump: true },
  jumpRight: { move: 1, jump: true },
};

export const HOLD_FRAMES = [1, 6, 24, 36, 60] as const;
export const INPUT_LABELS: Record<string, string> = { idle: '松开所有键', left: '左移', right: '右移', jump: '原地跳', jumpLeft: '左跳', jumpRight: '右跳' };
export const DURATION_LABELS = Object.fromEntries(HOLD_FRAMES.map(frames =>
  [`frames_${frames}`, `${(frames / PHYSICS.fps).toFixed(2)}秒（${frames}帧）`],
));

const ENGLISH_INPUTS: Record<string, string> = { idle: 'Release all keys; stop horizontal movement and cut ascent', left: 'Move left; release jump', right: 'Move right; release jump', jump: 'Hold jump without horizontal movement', jumpLeft: 'Move left and hold jump', jumpRight: 'Move right and hold jump' };
export const TIMED_INPUTS: Record<string, {control: string; frames: number}> = Object.fromEntries(Object.keys(INPUTS).flatMap(control =>
  [6, 24, 36].map(frames => [`${control}_${frames}`, { control, frames }]),
).concat([['idle_1', { control: 'idle', frames: 1 }]]));
export const TIMED_LABELS = Object.fromEntries(Object.entries(TIMED_INPUTS).map(([id, a]) => [id, `${INPUT_LABELS[a.control]} ${(a.frames / 60).toFixed(2)}秒`]));

export function previewMoves(state: JumpState) {
  return Object.fromEntries(Object.entries(TIMED_INPUTS).map(([id, action]) => {
    const end = replayActions(state.level, state.actor, state.progress, [{ ...INPUTS[action.control]!, frames: action.frames }]);
    return [id, { x: +end.actor.x.toFixed(1), y: +end.actor.y.toFixed(1), grounded: end.actor.grounded,
      dead: end.actor.dead, won: end.progress.won, gainedKey: !state.progress.key && end.progress.key,
      activatedSwitch: !state.progress.switchOn && end.progress.switchOn,
      coinsGained: end.progress.coins.length - state.progress.coins.length }];
  }));
}

const DEFAULT_MAX_FRAMES = 90 * PHYSICS.fps; // 90 秒
const MAX_LOG = 8;

function inputName(input: JumpInput): string {
  return Object.keys(INPUTS).find(k => INPUTS[k] === input) ?? 'idle';
}

/** 按当前 vx/vy 与重力外推落点：以恒定输入（保持当前方向与按住状态）逐步模拟到落地或摔死。 */
function extrapolateLanding(level: Level, a0: ActorState): { x: number; y: number; safe: boolean } {
  if (a0.grounded) return { x: +a0.x.toFixed(1), y: +a0.y.toFixed(1), safe: true };
  const input = { move: Math.sign(a0.vx) as -1 | 0 | 1, jump: a0.held };
  const a = { ...a0 };
  const p = progress();
  let airborne = !a.grounded;
  for (let i = 0; i < 600; i++) {
    if (!airborne && a.grounded && input.move === 0) break; // 站定不动：落点就是脚下
    step(a, input, level, p);
    if (!a.grounded) airborne = true;
    if (a.dead || (airborne && a.grounded)) break;
  }
  return { x: +a.x.toFixed(1), y: +a.y.toFixed(1), safe: !a.dead && a.grounded };
}

/** 脚下平台的边缘距离（像素，分左右）；悬空或脚下无平台时为 null。 */
function distToEdge(level: Level, a: ActorState): { left: number; right: number } | null {
  if (!a.grounded) return null;
  const p = level.platforms.find(s => Math.abs(s.y - a.y) < 0.1 && a.x >= s.x && a.x <= s.x + s.w);
  if (!p) return null;
  return { left: +(a.x - p.x).toFixed(1), right: +(p.x + p.w - a.x).toFixed(1) };
}

/** 向左/右直走并自然下落，摔死则记一次危险；返回最近危险距离（无危险为 null）。 */
function distToHazard(level: Level, a0: ActorState): number | null {
  if (!a0.grounded) return null;
  let best: number | null = null;
  for (const move of [-1, 1] as const) {
    const a = { ...a0 };
    const p = progress();
    let lastGroundedX = a.x;
    for (let i = 0; i < 600; i++) {
      step(a, { move, jump: false }, level, p);
      if (a.dead) {
        const d = Math.abs(lastGroundedX - a0.x);
        if (best === null || d < best) best = d;
        break;
      }
      if (a.grounded) {
        lastGroundedX = a.x;
        if (a.x <= 13 || a.x >= level.width - 13) break; // 走到场地边界仍安全
      }
    }
  }
  return best !== null ? +best.toFixed(1) : null;
}

/** 前方同高度平台间的缺口宽度（无缺口为 null）；dir 取当前移动方向，站立时朝向终点。 */
function gapAhead(level: Level, a: ActorState, dir: -1 | 1): number | null {
  if (!a.grounded) return null;
  const p = level.platforms.find(s => Math.abs(s.y - a.y) < 0.1 && a.x >= s.x && a.x <= s.x + s.w);
  if (!p) return null;
  const edge = dir > 0 ? p.x + p.w : p.x;
  let best: number | null = null;
  for (const q of level.platforms) {
    if (q === p || Math.abs(q.y - p.y) >= 0.1) continue;
    const gap = dir > 0 ? (q.x > edge ? q.x - edge : null) : (q.x + q.w < edge ? edge - (q.x + q.w) : null);
    if (gap !== null && (best === null || gap < best)) best = gap;
  }
  return best;
}

// 原地满按跳的水平位移（本物理无水平加速度，助跑不改变跳跃能力）；模块加载时用引擎模拟一次
const JUMP_RANGE = (() => {
  const flat: Level = { version: 2, title: 'range', width: 800, platforms: [{ x: 0, y: 400, w: 800 }], coins: [], spawn: { x: 400, y: 400 }, goal: { x: 700, y: 400 }, key: { x: 700, y: 400 }, switch: { x: 100, y: 400 }, door: { x: 780, y: 320, h: 80 } };
  const a = actor(flat.spawn);
  const input = { move: 1 as const, jump: true };
  step(a, input, flat, progress());
  for (let i = 0; i < 300 && !a.grounded && !a.dead; i++) step(a, input, flat, progress());
  return Math.abs(a.x - flat.spawn.x);
})();

/** 通关里程碑进度分：金币数 + 钥匙 + 开关 + 通关。 */
function progressScore(p: Progress): number {
  return p.coins.length + (p.key ? 1 : 0) + (p.switchOn ? 1 : 0) + (p.won ? 1 : 0);
}

export function createJumpGame(level: Level = starterLevel(), maxFrames = DEFAULT_MAX_FRAMES): RealtimeGame<JumpState> {
  // 每个独立请求携带地图；死亡后补发一次字符画帮助理解死因。
  let screenSentForDeaths = 0;
  return {
    id: 'jump',
    decision: {
      capture: s => ({ progress: progressScore(s.progress) - s.deaths, position: `${s.actor.x.toFixed(1)},${s.actor.y.toFixed(1)}` }),
      contextKey: s => `${s.deaths}:${JSON.stringify(s.progress)}`,
      maxAgeMs: 1500,
      describe: s => ({ disposition: 'accepted', command: { ...s.input }, ...(s.remainingFrames !== undefined ? { expiresAt: s.frames + s.remainingFrames } : {}) }),
      release: s => ({ ...s, input: INPUTS.idle!, remainingFrames: 0 }),
    },
    tickMs: 1000 / PHYSICS.fps,
    decisionMs: 100, // 跳跃高度取决于按住时长，200ms 粒度过粗会跳不上高台
    decisionReady: state => state.remainingFrames === undefined ? undefined : state.remainingFrames <= 0,
    initialState: () => ({
      level, actor: actor(level.spawn), progress: progress(),
      input: INPUTS['idle']!, deaths: 0, frames: 0, deathLog: [], inputLog: [],
    }),
    observe(state, opts): GroupedObservation {
      const obs = observation(state.level, state.actor, state.progress) as { actor: unknown };
      const dir: -1 | 1 = state.input.move !== 0 ? state.input.move : (state.level.goal.x >= state.actor.x ? 1 : -1);
      const landing = extrapolateLanding(state.level, state.actor);
      const gap = gapAhead(state.level, state.actor, dir);
      const last = state.lastDecision;
      const grouped: GroupedObservation = {
        realtime: true,
        frame: state.frames,
        time: +(state.frames / PHYSICS.fps).toFixed(1),
        actor: obs.actor,
        progress: state.progress,
        deaths: state.deaths,
        input: inputName(state.input),
        execution: { remainingFrames: state.remainingFrames ?? null, remainingSeconds: state.remainingFrames === undefined ? null : state.remainingFrames / PHYSICS.fps },
        deathLog: state.deathLog,
        inputLog: state.inputLog,
        recentResults: state.recentResults ?? [],
        // 成效回喂：上一决策输入持续的帧数与期间的进度/x 变化
        ...(last ? {
          lastControl: {
            input: last.input,
            frames: state.frames - last.atFrame,
            progressDelta: progressScore(state.progress) - progressScore(last.progress),
            xDelta: +(state.actor.x - last.x).toFixed(1),
          },
        } : {}),
        // 代码预计算的推导量，模型不做算术（物理常量见 instructions，不随观测重复发送）
        facts: {
          landingX: landing.x,
          landingY: landing.y,
          landingSafe: landing.safe,
          distToEdge: distToEdge(state.level, state.actor),
          distToHazard: distToHazard(state.level, state.actor),
          gapAhead: gap,
          maxJumpPx: +JUMP_RANGE.toFixed(1),
          gapTooWide: gap !== null && gap > JUMP_RANGE,
        },
      };
      // systemOne 每次请求独立，不能依赖模型记住首帧地图。
      grouped['objective'] = !state.progress.key ? { kind: 'key', ...state.level.key } : !state.progress.switchOn ? { kind: 'switch', ...state.level.switch } : { kind: 'remainingCoinsThenGoal', coins: state.level.coins.filter((_, i) => !state.progress.coins.includes(i)), goal: state.level.goal };
      if (!opts?.live) grouped['movePreviews'] = previewMoves(state);
      grouped['static'] = { level: state.level };
      if (!opts?.live && state.deaths > screenSentForDeaths) {
        screenSentForDeaths = state.deaths;
        grouped['screen'] = tileMap(state.level, state.actor, state.progress);
      }
      return grouped;
    },
    questions: (): Record<string, Question> => ({
      control: {
        type: 'choice', label: '动作与时长',
        instructions: 'Select one complete timed action to make progress toward objective. Compare movePreviews: exact short-horizon physics outcomes for each choice, NOT a guaranteed eventual landing. Prefer collecting the key, activating the switch, collecting remaining coins, then reaching the goal. Avoid death and repeated actions with no progress. Use platforms to climb; nearest horizontal distance alone is insufficient. Coordinates are feet; y increases downward. Horizontal speed is 3.2 px/frame. Releasing jump cuts ascent but moving right/left still moves horizontally; idle stops horizontal movement. Jump requires a fresh press; holding after landing does not jump again. Airborne jump does not double-jump. To rearm jump release for 1 frame. A preview that is still airborne may require another action to land. facts.landingX is only a projection of PREVIOUS motion, not the selected action. Prefer useful longer actions over repeated tiny adjustments when safe. Each option includes its duration; do not infer another duration.',
        criteria: Object.fromEntries(Object.entries(TIMED_INPUTS).map(([id, a]) => [id, `${ENGLISH_INPUTS[a.control]} for ${a.frames} frames (${a.frames / 60} seconds). See movePreviews.${id}.`])),
      },
    }),
    act(state, answers) {
      let control = answers['control'];
      const timed = control?.type === 'choice' ? TIMED_INPUTS[control.choice] : undefined;
      if (timed && control?.type === 'choice') control = { ...control, choice: timed.control };
      const duration = answers['duration'];
      if (duration && (duration.type !== 'choice' || !Object.hasOwn(DURATION_LABELS, duration.choice))) throw new Error('无效的持续时长答案');
      if (control && control.type === 'choice' && Object.hasOwn(INPUTS, control.choice)) {
        const input = INPUTS[control.choice]!;
        const frames = timed ? timed.frames : duration?.type === 'choice' ? Number(duration.choice.slice('frames_'.length)) : undefined;
        const inputLog = [...state.inputLog, control.choice].slice(-MAX_LOG);
        // 快照上一决策的起点，下次 observe 时 diff 出 lastControl
        const lastDecision = { input: control.choice, atFrame: state.frames, progress: copyProgress(state.progress), x: state.actor.x };
        const previous = state.lastDecision;
        const recentResults = previous ? [...(state.recentResults ?? []), { input: previous.input, startX: previous.x, endX: state.actor.x, progressDelta: progressScore(state.progress) - progressScore(previous.progress) }].slice(-8) : [];
        return { ...state, input, inputLog, lastDecision, recentResults, remainingFrames: frames };
      }
      return state;
    },
    step(state) {
      const executedInput = inputName(state.input);
      step(state.actor, state.input, state.level, state.progress);
      state.frames += 1;
      if (state.remainingFrames !== undefined) {
        state.remainingFrames = Math.max(0, state.remainingFrames - 1);
        if (state.remainingFrames === 0) state.input = INPUTS['idle']!;
      }
      if (state.actor.dead) {
        state.deathLog = [
          ...state.deathLog,
          { frame: state.frames, x: Math.round(state.actor.x), y: Math.round(state.actor.y), input: executedInput },
        ].slice(-MAX_LOG);
        state.actor = actor(state.level.spawn);
        state.deaths += 1;
        state.input = INPUTS['idle']!;
        if (state.remainingFrames !== undefined) state.remainingFrames = 0;
      }
      return state;
    },
    isTerminal: state => state.progress.won || state.frames >= maxFrames,
    outcome: state => state.progress.won ? 'won' : 'lost',
  };
}
