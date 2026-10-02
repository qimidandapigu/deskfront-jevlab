// 测试用的实时跳跃机器人：沿用旧回合制"恒选 cand-0（A* 解前缀）"的策略——
// 计划耗尽才重新规划，而不是每次决策都跑 A*。framesPerDecision 对应决策间隔
// 内的物理帧数（decisionMs / tickMs），决策间隔中其余帧沿用同一输入（等价真人按住键）。
import type { Answer, Question, SystemOne } from '../src/systemone/types.js';
import { generateCandidates } from '../src/games/jump/candidates.js';
import type { Action, ActorState, Level, Progress } from '../src/games/jump/engine.js';

export function controlName(move: number, jump: boolean): string {
  if (jump) return move < 0 ? 'jumpLeft' : move > 0 ? 'jumpRight' : 'jump';
  return move < 0 ? 'left' : move > 0 ? 'right' : 'idle';
}

export function expandActions(actions: Action[]): string[] {
  const out: string[] = [];
  for (const a of actions) for (let i = 0; i < a.frames; i++) out.push(controlName(a.move, a.jump));
  return out;
}function actorFrom(obs: { level: Level; actor: Partial<ActorState> }): ActorState {
  return {
    x: obs.actor.x ?? obs.level.spawn.x, y: obs.actor.y ?? obs.level.spawn.y,
    vx: obs.actor.vx ?? 0, vy: obs.actor.vy ?? 0,
    grounded: obs.actor.grounded ?? true, held: obs.actor.held ?? false, dead: false,
  };
}

export function controlAnswer(control: string): Record<string, Answer> {
  return { control: { type: 'choice', choice: control, probabilities: { [control]: 1 }, confidence: 1 } };
}

/** SystemOne 形态的跳跃机器人，可喂给 runRealtimeGame / viewer。 */
export function createJumpBot(framesPerDecision = 12): SystemOne {
  let queue: Action[] = [];
  let level: Level | null = null; // 瘦身观测只在首帧带 static.level，缓存复用
  return {
    async ask(state: unknown, _questions: Record<string, Question>) {
      const controlQuestion = _questions.control;
      if (controlQuestion?.type === 'choice' && Object.keys(controlQuestion.criteria).some(k => k.startsWith('landing-'))) {
        return controlAnswer(Object.keys(controlQuestion.criteria).filter(k => k.startsWith('landing-')).at(-1)!);
      }
      const obs = state as { static?: { level?: Level }; level?: Level; actor: Partial<ActorState>; progress: Progress };
      level = obs.static?.level ?? obs.level ?? level;
      if (!level) return controlAnswer('idle');
      if (queue.length < framesPerDecision) {
        const candidates = generateCandidates(level, actorFrom({ level, actor: obs.actor }), obs.progress);
        const c = candidates.find(c => !c.dead) ?? candidates[0];
        queue = c ? perFrame(c.actions) : [];
      }
      const chunk = queue.splice(0, framesPerDecision);
      if (chunk.length === 0) return controlAnswer('idle');
      // 决策间隔内输入持久：块内任意帧要跳就保持跳（跳跃高度取决于按住时长），方向取首个非零
      const jump = chunk.some(f => f.jump);
      const move = chunk.find(f => f.move !== 0)?.move ?? 0;
      const name = controlName(move, jump);
      const timed = `${name}_${framesPerDecision}`;
      return controlAnswer(controlQuestion?.type === 'choice' && timed in controlQuestion.criteria ? timed : name);
    },
  };
}

function perFrame(actions: Action[]): Action[] {
  const out: Action[] = [];
  for (const a of actions) for (let i = 0; i < a.frames; i++) out.push({ move: a.move, jump: a.jump, frames: 1 });
  return out;
}
