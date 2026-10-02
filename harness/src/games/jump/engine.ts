// Shared deterministic physics, ported from PetRival public/jump-world.mjs.
// Model controls the pet; search is generation QA only. Physics is fixed to the
// PHYSICS reference profile (PetRival kept it as a parameter to hide the numbers
// from the model; this harness has no such need). Co-op, interactables and
// near-miss attribution are intentionally not ported.
export const PHYSICS = Object.freeze({ speed: 3.2, gravity: 0.55, jump: -12.2, cut: -4, radius: 10, height: 24, fps: 60, graceFrames: 6 });

export interface Point { x: number; y: number }
export interface Platform { x: number; y: number; w: number }
export interface Level {
  version: 2; title: string; width: number;
  platforms: Platform[]; coins: Point[];
  spawn: Point; goal: Point; key: Point; switch: Point;
  door: { x: number; y: number; h: number };
}
export interface ActorState { x: number; y: number; vx: number; vy: number; grounded: boolean; held: boolean; dead: boolean; coyote?: number; jumpBuffer?: number }
export interface Progress { coins: number[]; key: boolean; switchOn: boolean; won: boolean }
export interface Action { move: -1 | 0 | 1; jump: boolean; frames: number }
export interface SearchResult { verified: boolean; visited: number; frames?: number; actions?: Action[]; reason?: string }

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null;
const n = (v: unknown, min: number, max: number): v is number =>
  typeof v === 'number' && Number.isFinite(v) && v >= min && v <= max;

export function validateLevel(raw: unknown): Level {
  const fail = (text: string): never => { throw new Error(`关卡格式：${text}`); };
  if (!isObj(raw) || raw['version'] !== 2 || !n(raw['width'], 800, 1600)) fail('version=2，宽度 800–1600');
  const r = raw as Record<string, unknown>;
  const width = r['width'] as number;
  const point = (p: unknown): p is Point => isObj(p) && n(p['x'], 16, width - 16) && n(p['y'], 80, 400);
  const platforms = r['platforms'];
  if (!Array.isArray(platforms) || platforms.length < 2 || platforms.length > 14 ||
    platforms.some(p => !isObj(p) || !n(p['x'], 0, width) || !n(p['y'], 128, 400) || !n(p['w'], 48, width) || p['x'] + p['w'] > width)) {
    fail('平台需要合法 x/y/w，最多 14 个');
  }
  if (!point(r['spawn']) || !point(r['goal']) || !point(r['key']) || !point(r['switch'])) fail('出生点、终点、钥匙和开关坐标无效');
  const coins = r['coins'];
  if (!Array.isArray(coins) || coins.length < 1 || coins.length > 5 || coins.some(p => !point(p))) fail('金币需要 1–5 个合法坐标');
  const door = r['door'];
  if (!isObj(door) || !point(door) || !n(door['h'], 48, 320) || door['y'] + door['h'] > 420) fail('门需要 x/y/h');
  const doorSpec = door as { x: number; y: number; h: number };
  const spawn = r['spawn'] as Point;
  const under = (platforms as Platform[]).find(p => Math.abs(p.y - spawn.y) < 0.1 && spawn.x >= p.x + 12 && spawn.x <= p.x + p.w - 12);
  if (!under) fail('出生点必须在安全平台上');
  const pick = (p: Point): Point => ({ x: p.x, y: p.y });
  return {
    version: 2, title: String(r['title'] || '小精灵的新冒险').slice(0, 40), width,
    platforms: (platforms as Platform[]).map(({ x, y, w }) => ({ x, y, w })),
    coins: (coins as Point[]).map(pick),
    spawn: pick(r['spawn'] as Point), goal: pick(r['goal'] as Point), key: pick(r['key'] as Point), switch: pick(r['switch'] as Point),
    door: { x: doorSpec.x, y: doorSpec.y, h: doorSpec.h },
  };
}

export function starterLevel(): Level {
  return validateLevel({
    version: 2, title: '高台上的钥匙', width: 1152, spawn: { x: 64, y: 400 }, goal: { x: 1088, y: 400 },
    platforms: [{ x: 0, y: 400, w: 560 }, { x: 624, y: 400, w: 528 }, { x: 128, y: 336, w: 112 }, { x: 272, y: 272, w: 128 }, { x: 432, y: 336, w: 80 }, { x: 720, y: 336, w: 96 }],
    coins: [{ x: 80, y: 388 }, { x: 368, y: 260 }, { x: 816, y: 388 }], key: { x: 320, y: 260 }, switch: { x: 176, y: 388 }, door: { x: 928, y: 144, h: 256 },
  });
}

export function actor(spawn: Point): ActorState {
  return { x: spawn.x, y: spawn.y, vx: 0, vy: 0, grounded: true, held: false, dead: false };
}
export function progress(): Progress {
  return { coins: [], key: false, switchOn: false, won: false };
}
export function copyProgress(p: Progress): Progress {
  return { coins: [...p.coins], key: !!p.key, switchOn: !!p.switchOn, won: !!p.won };
}

export function step(a: ActorState, input: { move: number; jump: boolean }, level: Level, p: Progress): void {
  if (a.dead || p.won) return;
  const oldX = a.x, oldY = a.y;
  a.vx = [-1, 0, 1].includes(input.move) ? input.move * PHYSICS.speed : 0;
  a.coyote = a.grounded ? PHYSICS.graceFrames : Math.max(0, (a.coyote ?? 0) - 1);
  a.jumpBuffer = input.jump && !a.held ? PHYSICS.graceFrames : Math.max(0, (a.jumpBuffer ?? 0) - 1);
  const launch = () => {
    a.vy = input.jump ? PHYSICS.jump : PHYSICS.cut;
    a.grounded = false; a.coyote = 0; a.jumpBuffer = 0;
  };
  if (a.jumpBuffer > 0 && (a.grounded || a.coyote > 0)) launch();
  a.held = !!input.jump;
  if (!input.jump && a.vy < PHYSICS.cut) a.vy = PHYSICS.cut;
  a.x = Math.max(12, Math.min(level.width - 12, a.x + a.vx));
  const d = level.door;
  if (!p.switchOn && a.y > d.y && a.y - PHYSICS.height < d.y + d.h && Math.abs(a.x - d.x) < 14) a.x = oldX < d.x ? d.x - 14 : d.x + 14;
  if (a.grounded && !level.platforms.some(s => Math.abs(s.y - a.y) < 0.1 && a.x >= s.x && a.x <= s.x + s.w)) a.grounded = false;
  if (!a.grounded) { a.vy += PHYSICS.gravity; a.y += a.vy; }
  if (a.vy >= 0) {
    const surfaces = level.platforms.filter(s => a.x >= s.x && a.x <= s.x + s.w && oldY <= s.y + 0.01 && a.y >= s.y).sort((s1, s2) => s1.y - s2.y);
    const top = surfaces[0];
    if (top) { a.y = top.y; a.vy = 0; a.grounded = true; }
  }
  if (a.y > 470) a.dead = true;
  touch(a, level, p);
  if (a.grounded && (a.jumpBuffer ?? 0) > 0 && !p.won) launch();
}

export function touch(a: ActorState, level: Level, p: Progress): void {
  if (a.dead || p.won) return;
  const near = (o: Point) => Math.abs(a.x - o.x) < 22 && Math.abs(a.y - 12 - o.y) < 26;
  level.coins.forEach((o, i) => { if (!p.coins.includes(i) && near(o)) p.coins.push(i); });
  if (near(level.key)) p.key = true;
  if (p.key && near(level.switch) && a.grounded) p.switchOn = true;
  if (p.key && p.switchOn && p.coins.length === level.coins.length && Math.abs(a.x - level.goal.x) < 24 && Math.abs(a.y - level.goal.y) < 28) p.won = true;
}

export function validateActions(raw: unknown, maxFrames = 240): Action[] {
  if (!Array.isArray(raw) || !raw.length || raw.length > 12) throw new Error('动作应为 1–12 段');
  let total = 0;
  const actions = raw.map((a): Action => {
    if (!isObj(a) || ![-1, 0, 1].includes(a['move'] as number) || typeof a['jump'] !== 'boolean' ||
      !Number.isInteger(a['frames']) || (a['frames'] as number) < 1 || (a['frames'] as number) > 90) {
      throw new Error('动作需要 move=-1/0/1、jump=true/false、frames=1–90');
    }
    total += a['frames'] as number;
    return { move: a['move'] as -1 | 0 | 1, jump: a['jump'], frames: a['frames'] as number };
  });
  if (total > maxFrames) throw new Error(`动作总长度超过 ${maxFrames} 帧`);
  return actions;
}

export function replayActions(level: Level, start: ActorState, initial: Progress, actions: Action[]): { actor: ActorState; progress: Progress } {
  const a = { ...start }, p = copyProgress(initial);
  for (const action of actions) for (let i = 0; i < action.frames && !a.dead && !p.won; i++) step(a, action, level, p);
  return { actor: a, progress: p };
}

export function observation(level: Level, a: ActorState, p: Progress): unknown {
  return {
    level, actor: { x: +a.x.toFixed(1), y: +a.y.toFixed(1), vx: a.vx, vy: +a.vy.toFixed(2), grounded: a.grounded, held: a.held, coyote: a.coyote ?? 0, jumpBuffer: a.jumpBuffer ?? 0 },
    progress: copyProgress(p), physics: PHYSICS,
  };
}

// Bounded search over executed walking/jumping edges. A witness is always replayed
// by the same physics. Failure to find a witness means unverified, not impossible.
// searchRoute is the parameterized core (any mid-level actor/progress start);
// verifyLevel is the fresh-from-spawn wrapper used for generation QA.
interface SearchNode {
  a: ActorState; p: Progress; cost: number;
  parent: SearchNode | null; action: Action[] | null; priority: number;
}

export function searchRoute(level: Level, start: ActorState, initial: Progress, opts?: { maxNodes?: number }): SearchResult {
  const maxNodes = opts?.maxNodes ?? 9000;
  const root: SearchNode = { a: { ...start }, p: copyProgress(initial), cost: 0, parent: null, action: null, priority: 0 };
  const heap: SearchNode[] = [], seen = new Map<string, number>();
  let visited = 0;
  const score = (s: SearchNode): number => {
    const target: Point = !s.p.key ? level.key : !s.p.switchOn ? level.switch :
      level.coins.find((_, i) => !s.p.coins.includes(i)) ?? { x: level.goal.x, y: level.goal.y - 12 };
    return s.cost * 0.12 + Math.abs(s.a.x - target.x) / PHYSICS.speed + Math.abs(s.a.y - 12 - target.y) * 0.5;
  };
  const key = (s: SearchNode): string =>
    `${Math.round(s.a.x / 8)},${s.a.y},${s.p.key ? 1 : 0}${s.p.switchOn ? 1 : 0},${s.p.coins.reduce((v, i) => v | 1 << i, 0)}`;
  const push = (s: SearchNode): void => {
    const id = key(s);
    if ((seen.get(id) ?? Infinity) <= s.cost) return;
    seen.set(id, s.cost);
    s.priority = score(s);
    heap.push(s);
    let i = heap.length - 1;
    while (i > 0) {
      const j = (i - 1) >> 1, parent = heap[j]!;
      if (parent.priority <= s.priority) break;
      heap[i] = parent; i = j;
    }
    heap[i] = s;
  };
  const pop = (): SearchNode => {
    const s = heap[0]!, end = heap.pop()!;
    if (heap.length) {
      let i = 0;
      while (i * 2 + 1 < heap.length) {
        let j = i * 2 + 1;
        if (j + 1 < heap.length && heap[j + 1]!.priority < heap[j]!.priority) j++;
        if (end.priority <= heap[j]!.priority) break;
        heap[i] = heap[j]!; i = j;
      }
      heap[i] = end;
    }
    return s;
  };
  push(root);
  while (heap.length && visited++ < maxNodes) {
    const s = pop(), id = key(s);
    if (seen.get(id)! < s.cost) continue;
    if (s.p.won) {
      const actions: Action[] = [];
      for (let node: SearchNode | null = s; node && node.parent; node = node.parent) actions.push(...[...node.action!].reverse());
      actions.reverse();
      const check = replayActions(level, root.a, root.p, actions);
      return { verified: check.progress.won, visited, frames: s.cost, actions };
    }
    for (const move of [-1, 1] as const) for (const hold of [0, 8, 20, 48]) {
      const a = { ...s.a }, p = copyProgress(s.p), actions: Action[] = [];
      let frames = 0;
      if (hold && a.held) {
        const release: Action = { move: 0, jump: false, frames: 1 };
        step(a, release, level, p);
        actions.push(release);
        frames++;
      }
      for (let i = 0; i < (hold ? 95 : 5); i++) {
        const input = { move, jump: i < hold };
        step(a, input, level, p);
        frames++;
        const last = actions[actions.length - 1];
        if (last && last.jump === input.jump) last.frames++;
        else actions.push({ ...input, frames: 1 });
        if (a.dead || p.won || (hold && i > 0 && a.grounded)) break;
      }
      if (!a.dead && a.grounded) push({ a, p, cost: s.cost + frames, parent: s, action: actions, priority: 0 });
    }
  }
  return { verified: false, visited, reason: '有界物理搜索未找到完整通关路线，请缩短跳跃距离、降低平台或调整钥匙/开关/门的连接。' };
}

export function verifyLevel(level: Level, opts?: { maxNodes?: number }): SearchResult {
  return searchRoute(level, actor(level.spawn), progress(), opts);
}

// A screen, not a blueprint: the level as a character grid the model can read line
// by line, the way a player sees it. One cell is TILE pixels, row 0 is the top.
export const TILE = 16;
export const TILE_LEGEND = '# 地面或平台 · 空格=空气 · ~ 水（掉下去会死） · c 金币 · k 钥匙 · s 机关 · D 关着的门 · d 开着的门 · G 终点 · @ 你自己';

export function tileMap(
  level: Level, a: ActorState | null,
  p: Partial<Progress> = {},
  opts?: { water?: number; rows?: number },
): { legend: string; tile: number; rows: string[] } {
  const water = opts?.water ?? 430, rows = opts?.rows ?? 30;
  const cols = Math.ceil(level.width / TILE);
  const grid = Array.from({ length: rows }, () => Array<string>(cols).fill(' '));
  const put = (x: number, y: number, ch: string): void => {
    const col = Math.floor(x / TILE), row = Math.floor(y / TILE);
    if (row >= 0 && row < rows && col >= 0 && col < cols) grid[row]![col] = ch;
  };
  const fill = (x: number, y: number, w: number, h: number, ch: string): void => {
    for (let yy = y; yy < y + h; yy += TILE) for (let xx = x; xx < x + w; xx += TILE) put(xx + 1, yy + 1, ch);
  };
  // Ground runs to the bottom of the screen; higher ledges are thin, the way they look.
  for (const plat of level.platforms) fill(plat.x, plat.y, plat.w, plat.y >= 400 ? rows * TILE - plat.y : 24, '#');
  for (let row = Math.floor(water / TILE); row < rows; row++)
    for (let col = 0; col < cols; col++) if (grid[row]![col] === ' ') grid[row]![col] = '~';
  level.coins.forEach((coin, i) => { if (!(p.coins ?? []).includes(i)) put(coin.x, coin.y, 'c'); });
  if (!p.key) put(level.key.x, level.key.y, 'k');
  put(level.switch.x, level.switch.y, 's');
  fill(level.door.x, level.door.y, 16, level.door.h, p.switchOn ? 'd' : 'D');
  put(level.goal.x, level.goal.y - TILE, 'G');
  if (a && !a.dead) put(a.x, a.y - TILE, '@');
  return { legend: TILE_LEGEND, tile: TILE, rows: grid.map(row => row.join('').replace(/\s+$/, '')) };
}
