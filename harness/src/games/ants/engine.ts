export type Vec = { x: number; y: number };
export type Rect = Vec & { w: number; h: number };
export type Pose = Vec & { angle: number };
export const WIDTH = 960, HEIGHT = 560;
export const DIRECTIONS: Record<string, Vec> = {
  stop: { x: 0, y: 0 }, east: { x: 1, y: 0 }, west: { x: -1, y: 0 },
  north: { x: 0, y: -1 }, south: { x: 0, y: 1 },
  ne: { x: Math.SQRT1_2, y: -Math.SQRT1_2 }, nw: { x: -Math.SQRT1_2, y: -Math.SQRT1_2 },
  se: { x: Math.SQRT1_2, y: Math.SQRT1_2 }, sw: { x: -Math.SQRT1_2, y: Math.SQRT1_2 },
};
export interface Level { id: number; name: string; hint: string; start: Pose; walls: Rect[]; shape: Rect[]; grips: Vec[]; goal: Rect }
const bar: Rect[] = [{ x: -76, y: -18, w: 152, h: 36 }];
const grips = [{ x: -65, y: -18 }, { x: 0, y: -18 }, { x: 65, y: -18 }, { x: 65, y: 18 }, { x: 0, y: 18 }, { x: -65, y: 18 }];
export const LEVELS: Level[] = [
  { id: 1, name: '转身过窄门', hint: '竖着会卡住。让两端向相反方向拉，把长条转到横向后穿门，送入终点。', start: { x: 200, y: 280, angle: Math.PI / 2 },
    walls: [{ x: 460, y: 0, w: 28, h: 224 }, { x: 460, y: 336, w: 28, h: 224 }], shape: bar, grips, goal: { x: 730, y: 120, w: 210, h: 320 } },
  { id: 2, name: '先退，才能进', hint: '前方小缝只有蚂蚁能过，整块食物过不去。先向左退出 U 形挡板，再从上方或下方绕行。', start: { x: 410, y: 280, angle: 0 },
    walls: [{ x: 290, y: 185, w: 280, h: 20 }, { x: 290, y: 355, w: 280, h: 20 }, { x: 550, y: 185, w: 20, h: 84 }, { x: 550, y: 291, w: 20, h: 84 }],
    shape: [{ x: -44, y: -44, w: 88, h: 88 }], grips: [{ x: -40, y: -40 }, { x: 0, y: -44 }, { x: 40, y: -40 }, { x: 40, y: 40 }, { x: 0, y: 44 }, { x: -40, y: 40 }], goal: { x: 750, y: 160, w: 190, h: 240 } },
  { id: 3, name: 'T 形大搬家', hint: '两道错位窄门。先转动 T 形物体过第一门，在中间房间调整拉力，再对准第二门。', start: { x: 155, y: 280, angle: Math.PI / 2 },
    walls: [{ x: 310, y: 0, w: 22, h: 166 }, { x: 310, y: 274, w: 22, h: 286 }, { x: 625, y: 0, w: 22, h: 286 }, { x: 625, y: 394, w: 22, h: 166 }],
    shape: [{ x: -65, y: -40, w: 130, h: 22 }, { x: -13, y: -18, w: 26, h: 58 }],
    grips: [{ x: -58, y: -40 }, { x: 0, y: -40 }, { x: 58, y: -40 }, { x: 13, y: 28 }, { x: 0, y: 40 }, { x: -13, y: 28 }], goal: { x: 760, y: 150, w: 180, h: 300 } },
];
export interface Ant { action: string; until: number; target?: Vec; force?: Vec }
export interface State { level: number; pose: Pose; ants: Ant[]; time: number; blocked: number; effort: number; distance: number; won: boolean; done: boolean }
export function createState(level = 1): State {
  const l = LEVELS[level - 1]; if (!l) throw new Error('Unknown level');
  return { level, pose: { ...l.start }, ants: Array.from({ length: 6 }, () => ({ action: 'stop', until: 0 })), time: 0, blocked: 0, effort: 0, distance: 0, won: false, done: false };
}
export function transform(p: Vec, pose: Pose): Vec { const c = Math.cos(pose.angle), s = Math.sin(pose.angle); return { x: pose.x + p.x * c - p.y * s, y: pose.y + p.x * s + p.y * c }; }
export function polygon(rect: Rect, pose: Pose): Vec[] { return [{ x: rect.x, y: rect.y }, { x: rect.x + rect.w, y: rect.y }, { x: rect.x + rect.w, y: rect.y + rect.h }, { x: rect.x, y: rect.y + rect.h }].map(p => transform(p, pose)); }
function intersects(a: Vec[], b: Vec[]): boolean {
  for (const poly of [a, b]) for (let i = 0; i < poly.length; i++) {
    const p = poly[i]!, q = poly[(i + 1) % poly.length]!, axis = { x: -(q.y - p.y), y: q.x - p.x };
    const pa = a.map(v => v.x * axis.x + v.y * axis.y), pb = b.map(v => v.x * axis.x + v.y * axis.y);
    if (Math.max(...pa) <= Math.min(...pb) || Math.max(...pb) <= Math.min(...pa)) return false;
  }
  return true;
}
export function validPose(level: Level, pose: Pose): boolean {
  return level.shape.every(r => { const poly = polygon(r, pose); return poly.every(p => p.x >= 8 && p.x <= WIDTH - 8 && p.y >= 8 && p.y <= HEIGHT - 8) && !level.walls.some(w => intersects(poly, polygon(w, { x: 0, y: 0, angle: 0 }))); });
}
export function atGoal(level: Level, pose: Pose): boolean { const g = level.goal; return level.shape.every(r => polygon(r, pose).every(p => p.x >= g.x && p.x <= g.x + g.w && p.y >= g.y && p.y <= g.y + g.h)); }
export function command(s: State, ant: number, action: string, duration = 4): void {
  if (!Number.isInteger(ant) || !s.ants[ant] || !Object.hasOwn(DIRECTIONS, action)) throw new Error('Invalid ant/action');
  s.ants[ant] = { action, until: s.time + Math.min(5, Math.max(0, duration)) };
}
export function moveTo(s: State, ant: number, target: Vec): void {
  if (!Number.isInteger(ant) || !s.ants[ant] || !Number.isFinite(target?.x) || !Number.isFinite(target?.y) || target.x < 8 || target.x > WIDTH - 8 || target.y < 8 || target.y > HEIGHT - 8) throw new Error('Invalid ant/target');
  s.ants[ant] = { action: 'stop', until: 0, target: { ...target } };
}
/** Overdamped rigid body: six world-space forces generate translation and torque. No auto-turn/path following. */
export function step(s: State, dt = 1 / 30): void {
  if (s.done) return;
  dt = Math.min(1 / 20, Math.max(0, dt)); s.time += dt;
  const l = LEVELS[s.level - 1]!; let fx = 0, fy = 0, torque = 0, active = 0;
  s.ants.forEach((a, i) => {
    const p = transform(l.grips[i]!, { x: 0, y: 0, angle: s.pose.angle });
    let f: Vec;
    if (a.target) {
      const x = a.target.x - s.pose.x - p.x, y = a.target.y - s.pose.y - p.y, distance = Math.hypot(x, y);
      if (distance <= 7) { delete a.target; a.action = 'stop'; f = DIRECTIONS.stop!; }
      else { f = { x: x / Math.max(20, distance), y: y / Math.max(20, distance) }; }
    } else { if (s.time > a.until) a.action = 'stop'; f = DIRECTIONS[a.action]!; }
    a.force = f; fx += f.x; fy += f.y; torque += p.x * f.y - p.y * f.x;
    if (Math.hypot(f.x, f.y) > 0) active++;
  });
  s.effort += active * dt;
  const dx = fx * 12 * dt, dy = fy * 12 * dt, da = torque * .0035 * dt;
  let blocked = false;
  // Separate small substeps allow sliding along walls without tunnelling.
  for (let j = 0; j < 3; j++) for (const part of [{ x: dx / 3, y: 0, angle: 0 }, { x: 0, y: dy / 3, angle: 0 }, { x: 0, y: 0, angle: da / 3 }]) {
    const next = { x: s.pose.x + part.x, y: s.pose.y + part.y, angle: s.pose.angle + part.angle };
    if (validPose(l, next)) { s.distance += Math.hypot(part.x, part.y); s.pose = next; } else blocked = true;
  }
  if (blocked && active) s.blocked += dt;
  s.won = atGoal(l, s.pose); s.done = s.won || s.time >= 180;
  if (s.done) s.ants.forEach(a => { a.action = 'stop'; delete a.target; a.force = { x: 0, y: 0 }; });
}
// Explicit fixed-route baseline for these three public teaching levels; not a learned model.
export const ROUTES: Pose[][] = [
  [{ x: 250, y: 280, angle: 0 }, { x: 600, y: 280, angle: 0 }, { x: 835, y: 280, angle: 0 }],
  [{ x: 220, y: 280, angle: 0 }, { x: 220, y: 110, angle: 0 }, { x: 670, y: 110, angle: 0 }, { x: 845, y: 280, angle: 0 }],
  [{ x: 185, y: 220, angle: 0 }, { x: 450, y: 220, angle: 0 }, { x: 460, y: 340, angle: 0 }, { x: 845, y: 340, angle: 0 }],
];
export function algorithmActions(s: State, target: Pose): string[] {
  const dx = target.x - s.pose.x, dy = target.y - s.pose.y;
  const angle = Math.atan2(Math.sin(target.angle - s.pose.angle), Math.cos(target.angle - s.pose.angle));
  const l = LEVELS[s.level - 1]!;
  return l.grips.map(grip => {
    const p = transform(grip, { x: 0, y: 0, angle: s.pose.angle });
    const x = (Math.abs(angle) > .15 ? 0 : dx * .018) - p.y * angle * .07;
    const y = (Math.abs(angle) > .15 ? 0 : dy * .018) + p.x * angle * .07;
    if (Math.hypot(x, y) < .04) return 'stop';
    return Object.keys(DIRECTIONS).filter(k => k !== 'stop').sort((a, b) => (DIRECTIONS[b]!.x * x + DIRECTIONS[b]!.y * y) - (DIRECTIONS[a]!.x * x + DIRECTIONS[a]!.y * y))[0]!;
  });
}
