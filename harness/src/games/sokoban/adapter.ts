import { createDecisionHistory } from '../../arena/decision.js';
import type { TurnBasedGame } from '../../arena/plugin.js';
import type { GroupedObservation } from '../../arena/observe.js';
import { move, parse, renderRows, won, DIRECTIONS } from './engine.js';
import type { SokobanState } from './engine.js';
import { reachablePushes, pushPositionKey, applyPush } from './pushes.js';
import type { PushOption } from './pushes.js';

export type { TurnBasedGame, TurnResult } from '../../arena/plugin.js';

interface Point { x: number; y: number; }

interface DecisionRecord {
  choice: string;
  beforeBoxes: Point[]; afterBoxes: Point[];
  goalsBefore: number; goalsAfter: number;
  revisitedPosition: boolean;
}

const DIR_LABEL: Record<string, string> = { U: '上', D: '下', L: '左', R: '右' };

export function createSokobanGame(rows: string[]): TurnBasedGame<SokobanState> {
  const initial = parse(rows);
  const point = (state: SokobanState, p: number): Point => ({ x: p % state.width, y: Math.floor(p / state.width) });

  // 决策记忆挂在 game 实例上；observe/questions 保持纯函数，只在 act 成功后更新
  const pushVisits = createDecisionHistory(512); pushVisits.visit(pushPositionKey(initial));
  const tried = createDecisionHistory(512);
  const decisions: DecisionRecord[] = [];
  const undoStack: SokobanState[] = [];
  // 上一次 act 的走位路径（玩家逐格坐标），observe 透出供前端逐步播放，避免宏动作"瞬移"
  let lastPath: Point[] | null = null;
  let revision = 0;

  const legalMoves = (state: SokobanState) =>
    Object.keys(DIRECTIONS).flatMap(action => {
      const result = move(state, action);
      if (!result.moved) return [];
      const pushedTo = result.pushed ? result.state.boxes.find(p => !state.boxes.includes(p)) : undefined;
      return [{
        action,
        playerTo: point(result.state, result.state.player),
        ...(pushedTo !== undefined
          ? { boxTo: point(result.state, pushedTo), boxOnGoal: state.goals.includes(pushedTo) }
          : {}),
      }];
    });

  const goalsFilled = (state: SokobanState) => state.boxes.filter(p => state.goals.includes(p)).length;

  // 观测用的候选视图：预演一步查访问记忆，不暴露 actions（执行细节由 act 处理）
  const observedPushes = (state: SokobanState, position: string) =>
    reachablePushes(state).map(option => {
      const { actions, ...rest } = option;
      return {
        ...rest,
        triedFromThisPosition: tried.count(`${position}/${option.id}`) ?? 0,
        returnsToVisitedPosition: pushVisits.count(pushPositionKey(applyPush(state, option))) ?? 0,
      };
    });

  return {
    id: 'sokoban',
    decision: {
      recover(state, answers) {
        const answer = answers.action;
        if (answer?.type !== 'choice') return null;
        const choices = reachablePushes(state), selected = choices.find(p => p.id === answer.choice);
        if (!selected || pushVisits.count(pushPositionKey(applyPush(state, selected))) < 3) return null;
        const alternative = choices.find(p => pushVisits.count(pushPositionKey(applyPush(state, p))) === 0);
        if (!alternative) return null;
        return { answers: { ...answers, action: { ...answer, choice: alternative.id } }, reason: 'unvisited-push-recovery' };
      },
      capture: state => ({ progress: goalsFilled(state), position: pushPositionKey(state) }),
      describe: (_state, answers) => ({ disposition: 'accepted', command: { action: answers.action?.type === 'choice' ? answers.action.choice : null, path: lastPath } }),
    },
    initialState: () => initial,
    observe(state, ctx): GroupedObservation {
      const position = pushPositionKey(state);
      return {
        turn: ctx.turn,
        revision,
        board: {
          rows: renderRows(state),
          coordinates: 'x increases right, y increases down; top-left is (0,0)',
        },
        entities: {
          player: point(state, state.player),
          boxes: state.boxes.map(p => ({ ...point(state, p), onGoal: state.goals.includes(p) })),
          goals: state.goals.map(p => point(state, p)),
        },
        facts: {
          corneredBoxes: state.boxes.filter(p => {
            if (state.goals.includes(p)) return false;
            const w = state.width;
            const hBlocked = state.walls.includes(p - 1) || state.walls.includes(p + 1);
            const vBlocked = state.walls.includes(p - w) || state.walls.includes(p + w);
            return hBlocked && vBlocked;
          }).map(p => point(state, p)),
        },
        legalMoves: legalMoves(state),
        availablePushes: observedPushes(state, position),
        visitsToThisPushPosition: pushVisits.count(position) ?? 1,
        recentDecisions: decisions.slice(-8),
        remainingGoals: state.goals.filter(p => !state.boxes.includes(p)).map(p => point(state, p)),
        assignmentGuidance: '每个箱子必须占一个不同的目标点。deadlock=true 表示这次推箱之后几何上不可能通关（死锁，不是绕远），绝不要选。用 recentDecisions 和 returnsToVisitedPosition 识别循环；陷入循环时可用 undo 撤销上一次推箱决策（含走位）回溯。',
        recent: ctx.recent,
        feedback: ctx.feedback,
        ...(lastPath && lastPath.length > 0 ? { lastPath } : {}),
      };
    },
    questions(state) {
      const position = pushPositionKey(state);
      const criteria: Record<string, string> = {};
      for (const option of observedPushes(state, position)) {
        const letter = option.id.split('-')[1]!;
        let label = `把 ${letter} 箱向${DIR_LABEL[option.direction]}推到 (${option.boxTo.x},${option.boxTo.y})（走 ${option.walkSteps} 步）`;
        if (option.onGoal) label += '，到达目标点';
        if (option.deadlock) label += ' ⚠将死锁';
        else if (option.corner) label += ' ⚠死角';
        if (option.returnsToVisitedPosition > 0) label += ' ⚠回到旧局面';
        criteria[option.id] = label;
      }
      // 中间目标有时必须腾开才能通关；循环由 runner 判定，不删掉合法回溯动作。
      if (undoStack.length > 0) criteria['undo'] = '撤销上一次推箱决策（含走位）';
      return {
        action: { type: 'choice', label: '动作', instructions: '每回合选择一次推箱（走位由引擎自动完成）。目标：把所有箱子推到目标点，每个箱子占一个不同的目标点。绝不选 deadlock=true 的推箱；避免把箱子推到无目标的死角。', criteria },
        deadlockRisk: {
          purpose: 'display',
          type: 'score', label: '死锁风险', instructions: '当前局面的死锁风险（箱子推到无法到达目标的角落）。observe 中 facts.corneredBoxes 列出了已卡死的箱子',
          levels: { '0': '局面健康，没有风险', '1': '有轻微风险但可挽回', '2': '高风险，接近死局', '3': '已有箱子卡死' },
        },
      };
    },
    /** 人类玩家：经典逐格走位（UDLR），推箱在走入箱子时自然发生；undo 撤销上一步。 */
    humanQuestions(state) {
      const criteria: Record<string, string> = { U: '向上走', D: '向下走', L: '向左走', R: '向右走' };
      if (undoStack.length > 0) criteria['undo'] = '撤销上一步';
      return {
        action: { type: 'choice', label: '移动', instructions: '方向键或点按钮逐格移动，走进箱子即可推动它。把所有箱子推到金色标记处。', criteria },
      };
    },
    act(state, answers) {
      const action = answers['action'];
      if (!action || action.type !== 'choice') return { state, feedback: '模型未返回有效的 action 选择' };
      const position = pushPositionKey(state);
      if (action.choice === 'undo') {
        const previous = undoStack.pop();
        if (!previous) return { state, feedback: '没有可撤销的推箱决策' };
        revision++;
        lastPath = null;
        const after = pushPositionKey(previous);
        pushVisits.visit(after);
        decisions.push({
          choice: 'undo',
          beforeBoxes: state.boxes.map(p => point(state, p)),
          afterBoxes: previous.boxes.map(p => point(previous, p)),
          goalsBefore: goalsFilled(state), goalsAfter: goalsFilled(previous),
          revisitedPosition: pushVisits.count(after)! > 1,
        });
        return { state: previous, feedback: null };
      }
      const option = reachablePushes(state).find((o: PushOption) => o.id === action.choice);
      if (!option) {
        // 人类走位：UDLR 单步移动（走入箱子即推），不进入 AI 的候选动作空间
        if (action.choice in DIRECTIONS) {
          const result = move(state, action.choice);
          if (!result.moved) return { state, feedback: '这个方向走不了（撞墙或箱子推不动）' };
          undoStack.push(state);
          revision++;
          lastPath = [point(result.state, result.state.player)];
          const next = result.state;
          const after = pushPositionKey(next);
          pushVisits.visit(after);
          decisions.push({
            choice: action.choice,
            beforeBoxes: state.boxes.map(p => point(state, p)),
            afterBoxes: next.boxes.map(p => point(next, p)),
            goalsBefore: goalsFilled(state), goalsAfter: goalsFilled(next),
            revisitedPosition: pushVisits.count(after)! > 1,
          });
          return { state: next, feedback: null };
        }
        return { state, feedback: `非法动作 "${action.choice}"，请从 availablePushes 的 id 中选择${undoStack.length > 0 ? '，或用 undo 撤销上一次推箱决策' : ''}` };
      }
      tried.visit(`${position}/${option.id}`);
      revision++;
      undoStack.push(state);
      // 逐格重放 actions 记录走位路径（含最后一步推箱后的站位）
      const path: Point[] = [];
      {
        let current = state;
        for (const step of option.actions) {
          current = move(current, step).state;
          path.push(point(current, current.player));
        }
      }
      lastPath = path;
      const next = applyPush(state, option);
      const after = pushPositionKey(next);
      pushVisits.visit(after);
      decisions.push({
        choice: option.id,
        beforeBoxes: state.boxes.map(p => point(state, p)),
        afterBoxes: next.boxes.map(p => point(next, p)),
        goalsBefore: goalsFilled(state), goalsAfter: goalsFilled(next),
        revisitedPosition: pushVisits.count(after)! > 1,
      });
      // 走位逐步播放耗时（与 client.js 的 stepDur 对齐），观战端等动画播完再要下一步
      return { state: next, feedback: null, playMs: path.length * 110 + 400 };
    },
    isTerminal: won,
    renderText: state => renderRows(state).join('\n'),
  };
}
