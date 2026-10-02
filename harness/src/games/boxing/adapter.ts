import type { Answer, Question } from '../../systemone/types.js';
import type { RealtimeGame } from '../../arena/plugin.js';
import type { GroupedObservation } from '../../arena/observe.js';
import { dangerQuestion } from '../../arena/observe.js';
import { ATTACKS, BOXING, newBout, stepBout, fighterObservation, boxingBotAction } from './engine.js';
import type { Bout, FighterObservation } from './engine.js';
import type { DecisionHooks } from '../../arena/decision.js';

export interface BoxingState { bout: Bout; command: string; rivalCommand: string | null; commandUntil?: number; rivalUntil?: number; executionReason?: string; rivalExecutionReason?: string; }

const CRITERIA: Record<string, string> = {
  jump: '跳跃：躲过地面攻击与抱摔，空中可移动和出拳，但不能格挡',
  dash: '快速前冲65距离，冷却0.6秒，无无敌',
  special: '烈焰冲拳：消耗50气，射程175，伤害18；重拳命中后可以衔接',
  idle: '站立不动（不防御，挨打全吃）',
  advance: '前进逼近对手，直到下次决策',
  retreat: '后退拉开距离，直到下次决策，可诱使对手打空',
  jab: '刺拳：快（0.1s 起手），伤害 3，射程 114，可打断对手慢招',
  heavy: '重拳：慢（0.35s 起手），伤害 10，射程 125，收招硬直大',
  guard: '格挡：免疫打击伤害但吃硬直；被抱摔破防',
  throw: '抱摔：伤害 8，射程 102，无视格挡，怕刺拳打断',
};

/** 从某一侧视角构造分组观测（左右镜像：self/opponent 互换，招式计时同样取对应侧）。 */
function observeFighter(bout: Bout, side: 0 | 1): GroupedObservation {
  const obs = fighterObservation(bout, side) as FighterObservation;
  const attackMsLeft = (i: 0 | 1): number => {
    const attack = bout.fighters[i]!.attack;
    const spec = attack ? ATTACKS[attack.kind] : undefined;
    return spec && attack && attack.age < spec.startup ? (spec.startup - attack.age) * BOXING.tickMs : 0;
  };
  return {
    match: { secondsLeft: obs.secondsLeft, rulesVersion: obs.rulesVersion, frame: bout.frame, tickMs: BOXING.tickMs },
    fighters: { self: obs.self, opponent: obs.opponent },
    distance: obs.distance,
    recent: obs.recent,
    facts: {
      // 当前距离落入哪些招式的射程
      inRange: Object.entries(ATTACKS).filter(([kind, s]) => obs.distance <= s.range && Math.abs(obs.self.y - obs.opponent.y) < 65 && (kind !== 'special' || obs.self.meter >= 50) && (kind !== 'throw' || (obs.self.y === 0 && obs.opponent.y === 0))).map(([kind]) => kind),
      // 双方当前招式到命中还剩多少毫秒（未出招或已过命中窗口为 0）
      oppAttackMsLeft: attackMsLeft(side === 0 ? 1 : 0),
      selfAttackMsLeft: attackMsLeft(side),
      // 剩余时间比例：开局为 1，随时间逼近 0
      timePressure: +(obs.secondsLeft * 1000 / BOXING.limitMs).toFixed(3),
    },
  };
}

/** 从答案集中解析出指令（不按置信度过滤）；解析失败返回 null 表示保留上一指令。 */
function pickCommand(answers: Record<string, Answer>): string | null {
  // 观测站真人局：键位经 /input 直接映射为指令（control 不必出现在 questions 里）
  const control = answers['control'];
  if (control && control.type === 'choice' && (control.choice in CRITERIA || ['jumpForward', 'jumpBack'].includes(control.choice))) return control.choice;
  const action = answers['action'];
  if (action && action.type === 'choice' && action.choice in CRITERIA) {
    return action.choice;
  }
  return null;
}

/** Resource/physics constraints only; no probability threshold or confidence override. */
function executableCommand(state: BoxingState, side: 0 | 1, answers: Record<string, Answer>) {
  const selected = pickCommand(answers);
  if (!selected || answers.control) return { command: selected, reason: undefined };
  const f = state.bout.fighters[side], opponent = state.bout.fighters[side === 0 ? 1 : 0];
  const distance = Math.abs(f.x - opponent.x);
  const approach = distance > ATTACKS.jab!.range ? 'advance' : 'jab';
  const reason = selected === 'special' && f.meter < 50 ? '气不足50'
    : selected === 'dash' && (f.dashCooldown > 0 || f.y > 0 || distance <= 82) ? '冲刺冷却或无法位移'
    : selected === 'jump' && (f.y > 0 || f.lastInput === 'jump') ? '当前无法再次起跳'
    : selected === 'throw' && (f.y > 0 || opponent.y > 0) ? '空中无法抱摔'
    : selected === 'guard' && f.y > 0 ? '空中无法格挡' : undefined;
  return { command: reason ? approach : selected, reason: reason ? `${selected} → ${approach}：${reason}` : undefined };
}

export function createBoxingGame(training?: string): RealtimeGame<BoxingState> {
  const decision = (side: 0 | 1): DecisionHooks<BoxingState> => ({
    maxAgeMs: 500,
    schedule: { canInterrupt: s => !s.bout.fighters[side].attack && s.bout.fighters[side].stun === 0, eventKey: s => s.bout.fighters[side === 0 ? 1 : 0].attack?.kind ?? 'none' },
    capture: s => ({ progress: s.bout.fighters[side]!.hp - s.bout.fighters[side === 0 ? 1 : 0]!.hp,
      position: String(s.bout.fighters[side]!.x) }),
    describe: (s, answers) => {
      const command = side === 0 ? s.command : s.rivalCommand;
      return { disposition: pickCommand(answers) === null ? 'retained' : 'accepted', command, expiresAt: side === 0 ? s.commandUntil : s.rivalUntil,
        ...((side === 0 ? s.executionReason : s.rivalExecutionReason) ? { reason: side === 0 ? s.executionReason : s.rivalExecutionReason } : {}) };
    },
    recover: (state, answers) => {
      const resolved = executableCommand(state, side, answers);
      return resolved.reason && answers.action?.type === 'choice' && resolved.command
        ? { answers: { ...answers, action: { ...answers.action, choice: resolved.command } }, reason: resolved.reason } : null;
    },
    release: s => side === 0 ? { ...s, command: 'idle', commandUntil: undefined } : { ...s, rivalCommand: 'idle', rivalUntil: undefined },
  });
  return {
    id: 'boxing',
    decision: decision(0),
    tickMs: BOXING.tickMs,
    initialState: () => { const bout = newBout(1); if (training) bout.fighters[0].meter = 100; return { bout, command: 'idle', rivalCommand: null }; },
    observe: state => observeFighter(state.bout, 0),
    questions: (): Record<string, Question> => ({
      action: {
        type: 'choice',
        label: '动作',
        instructions: '选择下一个拳击指令（持续约 0.5 秒或直到下次决策）。目标：击倒对手或在时间到时血量百分比领先。打收招中的对手 +2 反击伤害；别在远处空挥。facts.inRange 列出当前距离可命中的招式，facts.oppAttackMsLeft / facts.selfAttackMsLeft 是双方招式到命中的毫秒数。',
        criteria: CRITERIA,
      },
      needGuard: { type: 'noul', purpose: 'display', label: '是否需要格挡', instructions: '对手当前正在出招且我在其射程内，我应立即格挡吗' },
      danger: dangerQuestion('当前面临的即时危险程度（对手招式即将命中且我在射程内=危急）', { 0: '安全', 1: '受压', 2: '危急' }),
    }),
    act: (state, answers) => {
      const { command, reason } = executableCommand(state, 0, answers);
      return command !== null ? { ...state, command, executionReason: reason, commandUntil: answers['control'] ? undefined : state.bout.frame + BOXING.commandTicks } : state;
    },
    ...(training ? {} : { rival: {
      decision: decision(1),
      observe: state => observeFighter(state.bout, 1),
      act: (state, answers) => {
        const { command, reason } = executableCommand(state, 1, answers);
        return command !== null ? { ...state, rivalCommand: command, rivalExecutionReason: reason, rivalUntil: state.bout.frame + BOXING.commandTicks } : { ...state, rivalCommand: state.rivalCommand ?? 'idle' };
      },
    } }),
    step: state => {
      if (state.commandUntil !== undefined && state.bout.frame >= state.commandUntil) state.command = 'idle';
      if (state.rivalUntil !== undefined && state.bout.frame >= state.rivalUntil) state.rivalCommand = 'idle';
      const practice = training === 'practice-guard' ? 'guard' : training === 'practice-heavy' ? 'heavy' : 'idle';
      stepBout(state.bout, [state.command, training ? practice : state.rivalCommand ?? boxingBotAction(state.bout, 1)]);
      return state;
    },
    isTerminal: state => state.bout.status !== 'running',
    outcome: state => state.bout.winner === 0 ? 'won' : state.bout.winner === 1 ? 'lost' : 'draw',
  };
}
