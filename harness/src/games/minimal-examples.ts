/** Thin bindings to two existing engines; no pathfinding or combat strategy here. */
import { createMinimalRealtimeGame, createMinimalTurnGame } from '../arena/minimal.js';
import { createStallRecoveryAssist } from '../arena/assistance.js';
import { parse, move, won, renderRows, DIRECTIONS } from './sokoban/engine.js';
import { ACTIONS, BOXING, newBout, stepBout, fighterObservation, boxingBotAction } from './boxing/engine.js';
import type { Bout } from './boxing/engine.js';

export function createMinimalSokoban(rows: string[], recovery = false) {
  return createMinimalTurnGame({
    id: 'sokoban-minimal', instructions: '把箱子推到目标。每次选择一个方向，执行一格移动；只能推不能拉。',
    initial: () => parse(rows),
    inspect: state => ({ observation: { rows: renderRows(state) },
      actions: { U: '上', D: '下', L: '左', R: '右' }, outcome: won(state) ? 'won' : null,
      effect: { progress: state.boxes.filter(box => state.goals.includes(box)).length,
        position: `${state.player}/${state.boxes.join(',')}` } }),
    execute: (state, action) => {
      const result = move(state, action);
      return { state: result.state, accepted: result.moved, ...(!result.moved ? { reason: 'blocked' } : {}) };
    },
    ...(recovery ? { assistance: { tools: [createStallRecoveryAssist(2)],
      ports: (state: ReturnType<typeof parse>) => ({ alternatives: { question: 'action',
        choices: Object.keys(DIRECTIONS).filter(action => move(state, action).moved) } }) } } : {}),
  });
}

interface MinimalBoxing { bout: Bout; input: string; }
export function createMinimalBoxing(recovery = false) {
  return createMinimalRealtimeGame<MinimalBoxing>({
    id: 'boxing-minimal', instructions: '击败对手。选择一个按键，保持十帧。伤害、距离和收招由游戏规则决定。',
    tickMs: BOXING.tickMs, actionTicks: BOXING.commandTicks,
    initial: () => ({ bout: newBout(), input: 'idle' }),
    inspect: ({ bout }) => ({ observation: fighterObservation(bout, 0),
      actions: Object.fromEntries(ACTIONS.map(action => [action, action])),
      outcome: bout.status === 'running' ? null : bout.winner === null ? 'draw' : bout.winner === 0 ? 'won' : 'lost',
      effect: { progress: bout.fighters[0].hp - bout.fighters[1].hp, position: String(bout.fighters[0].x) } }),
    execute: (state, input) => ({ state: { ...state, input }, accepted: true }),
    step: state => ({ ...state, bout: stepBout(structuredClone(state.bout), [state.input, boxingBotAction(state.bout, 1)]) }),
    release: state => ({ ...state, input: 'idle' }),
    ...(recovery ? { assistance: { tools: [createStallRecoveryAssist(2)],
      ports: () => ({ alternatives: { question: 'action', choices: ['advance', 'retreat'] } }) } } : {}),
  });
}
