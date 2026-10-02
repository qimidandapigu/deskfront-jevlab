import { move, DIRECTIONS } from './engine.js';
import type { SokobanState } from './engine.js';

export interface PushPoint { x: number; y: number; }

export interface PushOption {
  /** push-A-R 形式：箱子按位置排序标 A–D，便于 UI 展示 */
  id: string;
  box: PushPoint; boxTo: PushPoint; direction: string;
  wasOnGoal: boolean; onGoal: boolean;
  /** 走位步数与完整动作串（走位路径 + 推），供 act 执行 */
  walkSteps: number; actions: string;
  /** 推到非目标的墙角落 */
  corner: boolean;
  /** 推完后箱子无法分配到不同目标点（几何上不可能解，非绕远） */
  deadlock: boolean; warning?: string;
}

const point = (state: SokobanState, p: number): PushPoint => ({ x: p % state.width, y: Math.floor(p / state.width) });

/** 箱子固定、只走空地的 BFS，值是 UDLR 路径串。 */
export function walkingPaths(state: SokobanState): Map<number, string> {
  const w = state.width, size = w * state.height;
  const paths = new Map<number, string>([[state.player, '']]);
  const queue = [state.player];
  for (let index = 0; index < queue.length; index++) {
    const from = queue[index]!;
    for (const [action, [dx, dy]] of Object.entries(DIRECTIONS)) {
      const to = from + dx + dy * w;
      if (to < 0 || to >= size || Math.abs(to % w - from % w) > 1 ||
          state.walls.includes(to) || state.boxes.includes(to) || paths.has(to)) continue;
      paths.set(to, paths.get(from)! + action);
      queue.push(to);
    }
  }
  return paths;
}

/** 同一连通区域内的走位视为同一决策局面：排序后箱子位置 + 最小可达走格。 */
export function pushPositionKey(state: SokobanState): string {
  return `${[...state.boxes].sort((a, b) => a - b).join(',')}:${Math.min(...walkingPaths(state).keys())}`;
}

/** 每个目标点的反向拉箱可达集合（单箱几何，忽略其他箱子）。 */
export function goalReachability(state: SokobanState): Set<number>[] {
  const w = state.width, size = w * state.height;
  return state.goals.map(goal => {
    const seen = new Set([goal]);
    const queue = [goal];
    for (let n = 0; n < queue.length; n++) {
      for (const [dx, dy] of Object.values(DIRECTIONS)) {
        const previous = queue[n]! - dx - dy * w, standing = previous - dx - dy * w;
        if ([previous, standing].some(p => p < 0 || p >= size || state.walls.includes(p)) ||
            Math.abs(previous % w - queue[n]! % w) > 1 || Math.abs(standing % w - previous % w) > 1 ||
            seen.has(previous)) continue;
        seen.add(previous);
        queue.push(previous);
      }
    }
    return seen;
  });
}

/** 枚举所有可执行的单次推箱；只给事实，不替模型求解。 */
export function reachablePushes(state: SokobanState): PushOption[] {
  const w = state.width;
  const paths = walkingPaths(state), reachable = goalReachability(state);
  const sorted = [...state.boxes].sort((a, b) => a - b);
  return sorted.flatMap((box, boxIndex) => Object.entries(DIRECTIONS).flatMap(([direction, [dx, dy]]) => {
    const delta = dx + dy * w, behind = box - delta, to = box + delta;
    if (!paths.has(behind) || to < 0 || to >= w * state.height ||
        Math.abs(to % w - box % w) > 1 || state.walls.includes(to) || state.boxes.includes(to)) return [];
    const onGoal = state.goals.includes(to);
    // 箱-目标二分图匹配：推完后每个箱子（含 to）都要能占一个不同的目标点
    const others = state.boxes.filter(p => p !== box);
    const assign = (i: number, used: Set<number>): boolean =>
      i === others.length || reachable.some((set, goal) => !used.has(goal) && set.has(others[i]!) && assign(i + 1, new Set([...used, goal])));
    const compatible = reachable.some((set, goal) => set.has(to) && assign(0, new Set([goal])));
    const deadlock = !compatible;
    return [{
      id: `push-${'ABCD'[boxIndex]}-${direction}`,
      box: point(state, box), boxTo: point(state, to), direction,
      wasOnGoal: state.goals.includes(box), onGoal,
      walkSteps: paths.get(behind)!.length, actions: paths.get(behind)! + direction,
      corner: !onGoal && (state.walls.includes(to - 1) || state.walls.includes(to + 1)) &&
              (state.walls.includes(to - w) || state.walls.includes(to + w)),
      deadlock,
      ...(deadlock ? { warning: '这次推箱之后箱子无法分配到不同的目标点，几何上不可能通关。请撤销或选择其他推箱。' } : {}),
    }];
  }));
}

/** 按候选的 actions 逐字符调 move，走位由引擎自动完成。 */
export function applyPush(state: SokobanState, option: PushOption): SokobanState {
  let current = state;
  for (const action of option.actions) current = move(current, action).state;
  return current;
}
