export const DIRECTIONS: Record<string, readonly [number, number]> = {
  U: [0, -1], D: [0, 1], L: [-1, 0], R: [1, 0],
};

export interface SokobanState {
  width: number; height: number;
  walls: number[]; goals: number[]; boxes: number[]; player: number;
}

export function parse(rows: string[]): SokobanState {
  if (!Array.isArray(rows) || ![8, 9, 10].includes(rows.length) ||
      rows.some(r => typeof r !== 'string' || r.length !== rows.length || /[^# .$@*+]/.test(r))) {
    throw new Error('地图必须是 8×8、9×9 或 10×10，只能包含 # 空格 . $ @ * +');
  }
  const width = rows.length, height = width;
  const walls: number[] = [], goals: number[] = [], boxes: number[] = [], players: number[] = [];
  rows.forEach((row, y) => [...row].forEach((c, x) => {
    const p = y * width + x;
    if ((x === 0 || y === 0 || x === width - 1 || y === height - 1) && c !== '#') throw new Error('地图边缘必须封闭');
    if (c === '#') walls.push(p);
    if ('.$*+'.includes(c) && c !== '$') goals.push(p);
    if ('$*'.includes(c)) boxes.push(p);
    if ('@+'.includes(c)) players.push(p);
  }));
  if (boxes.length < 1 || boxes.length > 4 || goals.length !== boxes.length || players.length !== 1) {
    throw new Error('需要 1–4 个箱子、相同数量的目标和一个玩家');
  }
  return { width, height, walls, goals, boxes: boxes.sort((a, b) => a - b), player: players[0]! };
}

export const won = (s: SokobanState): boolean => s.boxes.every(b => s.goals.includes(b));

export function move(state: SokobanState, action: string): { state: SokobanState; moved: boolean; pushed: boolean } {
  const width = state.width;
  const d = DIRECTIONS[action];
  if (!d) throw new Error('未知移动');
  const next = state.player + d[0] + d[1] * width;
  if (next < 0 || next >= width * state.height ||
      Math.abs(next % width - state.player % width) > 1 || state.walls.includes(next)) {
    return { state, moved: false, pushed: false };
  }
  const box = state.boxes.indexOf(next);
  const boxes = [...state.boxes];
  if (box >= 0) {
    const beyond = next + d[0] + d[1] * width;
    if (beyond < 0 || beyond >= width * state.height ||
        Math.abs(beyond % width - next % width) > 1 ||
        state.walls.includes(beyond) || boxes.includes(beyond)) {
      return { state, moved: false, pushed: false };
    }
    boxes[box] = beyond;
    boxes.sort((a, b) => a - b);
  }
  return { state: { ...state, player: next, boxes }, moved: true, pushed: box >= 0 };
}

export function renderRows(s: SokobanState): string[] {
  return Array.from({ length: s.height }, (_, y) =>
    Array.from({ length: s.width }, (_, x) => {
      const p = y * s.width + x;
      if (s.walls.includes(p)) return '#';
      if (p === s.player) return s.goals.includes(p) ? '+' : '@';
      if (s.boxes.includes(p)) return s.goals.includes(p) ? '*' : '$';
      return s.goals.includes(p) ? '.' : ' ';
    }).join(''));
}
