// 玩具兵打枪：2v2 俯视战场。两支小队共用属性、移动与武器规则。
// 真人可切换绿方队员；其余单位由模型或内置 Bot 指挥。沙袋挡移动和视线。
// 弹道参数与命中公式与 JGP demo（src/jgp/sim.ts）共用。
import { segmentClear } from '../../jgp/sim.js';

const UNIT_STATS = Object.freeze({ hp: 100, speed: 0.5, damage: 10, cooldown: 5 });

export const SOLDIERS = Object.freeze({
  tickMs: 50,
  width: 40,
  height: 20,
  enemyCount: 2,
  playerHp: UNIT_STATS.hp,
  enemyHp: UNIT_STATS.hp,
  playerSpeed: UNIT_STATS.speed,
  enemySpeed: UNIT_STATS.speed,
  rifleRange: 9,
  unitSeparation: 1.2,
  /** 所有单位共享属性，不按阵营或控制者增强／削弱。 */
  playerDamage: UNIT_STATS.damage,
  enemyDamage: UNIT_STATS.damage,
  fireCooldownTicks: UNIT_STATS.cooldown,
  playerFireTicks: UNIT_STATS.cooldown,
  magazine: 6,
  reloadTicks: 24,
  aimTicks: 10,
  tracerTicks: 6,
  limitTicks: 3600,
});

export const COMMANDS: readonly string[] = Object.freeze([
  'shoot', 'advance', 'hold', 'peek', 'flank', 'retreat',
]);

export interface Unit {
  id: string;
  side: 'player' | 'enemy';
  x: number; y: number;
  hp: number; maxHp: number;
  /** 剩余射击冷却 tick 数。 */
  cool: number;
  /** 朝向（弧度），供渲染枪口方向。 */
  facing: number;
  /** 本 tick 是否移动过（命中率惩罚依据）。 */
  moved: boolean;
  ammo: number; reload: number; aim: number; aimX: number; aimY: number; aimTarget?: string;
}

export interface SoldierTracer {
  x1: number; y1: number; x2: number; y2: number;
  hit: boolean; ttl: number; id: string;
}

export interface TacticalOrder { movement: 'hold' | 'advance' | 'retreat' | 'left' | 'right' | 'reposition'; weapon: 'shoot' | 'cease' | 'reload'; target: string; expiresAt: number; durationMs: number; reason?: string; route?: Array<{ x: number; y: number }>; recovery?: string; }

/** Find a shortest walkable grid route to a firing position, not through cover. */
export function firingRoute(f: Firefight, u: Unit, target: Unit): Array<{ x: number; y: number }> | null {
  const cells = blockedCells(f);
  let start = { x: Math.round(u.x), y: Math.round(u.y) };
  // Rounded observations can sit exactly on a cover boundary. Start on the
  // nearest adjacent free cell, never ask the unit to walk into a sandbag center.
  if (cells.has(`${start.x},${start.y}`)) {
    const candidates = [[0, -1], [-1, 0], [1, 0], [0, 1]].map(([dx, dy]) => ({ x: start.x + dx!, y: start.y + dy! }))
      .filter(p => p.x >= 0 && p.y >= 0 && p.x < SOLDIERS.width && p.y < SOLDIERS.height && !cells.has(`${p.x},${p.y}`))
      .sort((a, b) => dist(u.x, u.y, a.x, a.y) - dist(u.x, u.y, b.x, b.y));
    if (!candidates[0]) return null;
    start = candidates[0];
  }
  const queue = [start], parents = new Map<string, string | null>();
  const key = (p: { x: number; y: number }) => `${p.x},${p.y}`;
  parents.set(key(start), null);
  for (let i = 0; i < queue.length; i++) {
    const p = queue[i]!;
    if (dist(p.x, p.y, target.x, target.y) <= SOLDIERS.rifleRange && segmentClear(p, target, cells)) {
      const route = [p];
      let prev = parents.get(key(p));
      while (prev) { const [x, y] = prev.split(',').map(Number); route.push({ x: x!, y: y! }); prev = parents.get(prev); }
      return route.reverse();
    }
    for (const [dx, dy] of [[0, -1], [-1, 0], [1, 0], [0, 1]]) {
      const next = { x: p.x + dx!, y: p.y + dy! }, id = key(next);
      if (next.x < 0 || next.y < 0 || next.x >= SOLDIERS.width || next.y >= SOLDIERS.height || cells.has(id) || parents.has(id)) continue;
      parents.set(id, key(p)); queue.push(next);
    }
  }
  return null;
}

export interface Firefight {
  endless?: { minY: number; maxY: number };
  order: TacticalOrder | null;
  enemyOrders: (TacticalOrder | null)[];
  tick: number;
  status: 'running' | 'done';
  winner: 'player' | 'enemy' | null;
  command: string;
  /** 每个敌兵的姿态指令覆盖：null = 脚本 bot 驱动；模型对模型时由 rival.act 写入。 */
  enemyCommands: (string | null)[];
  player: Unit;
  allies: Unit[];
  allyOrders: Record<string, TacticalOrder | null>;
  human: boolean;
  companionBot: boolean;
  controlledId: string;
  controlEpoch: number;
  enemies: Unit[];
  /** 整数格沙袋。 */
  sandbags: Array<{ x: number; y: number }>;
  tracers: SoldierTracer[];
  /** 最近事件（人读），observe 透传给模型与面板。 */
  events: string[];
  rngState: number;
  pendingHits?: Array<{ target: Unit; damage: number }>;
}

function dist(ax: number, ay: number, bx: number, by: number): number {
  return Math.hypot(bx - ax, by - ay);
}

export function newFirefight(seed = 42): Firefight {
  const width = SOLDIERS.width, height = SOLDIERS.height;
  const seen = new Set<string>();
  const sandbags: Array<{ x: number; y: number }> = [];
  const add = (x: number, y: number): void => {
    const rx = Math.round(x), ry = Math.round(y);
    const key = `${rx},${ry}`;
    if (rx < 0 || ry < 0 || rx >= width || ry >= height || seen.has(key)) return;
    seen.add(key);
    sandbags.push({ x: rx, y: ry });
  };
  // Rotation-symmetric cover and spawns: neither team owns a better fortress.
  for (const [x, y] of [[9, 7], [10, 7], [11, 7], [17, 10], [18, 10]]) {
    add(x!, y!); add(width - 1 - x!, height - 1 - y!);
  }
  const mk = (id: string, side: Unit['side'], x: number, y: number, hp: number): Unit => ({
    id, side, x, y, hp, maxHp: hp, cool: 0, facing: side === 'player' ? -Math.PI / 2 : Math.PI / 2, moved: false, ammo: SOLDIERS.magazine, reload: 0, aim: 0, aimX: x, aimY: y,
  });
  const f: Firefight = {
    tick: 0, status: 'running', winner: null, command: 'hold', order: null, enemyOrders: [null, null],
    enemyCommands: Array.from({ length: SOLDIERS.enemyCount }, () => null),
    player: mk('player', 'player', 12, 16, SOLDIERS.playerHp),
    allies: [], allyOrders: {}, human: false, companionBot: false, controlledId: 'player', controlEpoch: 0,
    enemies: [], sandbags, tracers: [], events: [], rngState: seed >>> 0,
  };
  f.allies = [f.player, mk('ally-1', 'player', 27, 16, SOLDIERS.playerHp)];
  f.enemies = f.allies.map((u, i) => mk(`enemy-${i}`, 'enemy', width - 1 - u.x, height - 1 - u.y, SOLDIERS.enemyHp));
  return f;
}

function blockedCells(f: Firefight): Set<string> {
  return new Set(f.sandbags.map(s => `${s.x},${s.y}`));
}

export function hasLos(f: Firefight, ax: number, ay: number, bx: number, by: number): boolean {
  return segmentClear({ x: ax, y: ay }, { x: bx, y: by }, blockedCells(f));
}

/** Shared body collision for humans, models and bots; overlapping spawns may separate. */
function moveUnit(f: Firefight, u: Unit, dx: number, dy: number): void {
  const cells = blockedCells(f);
  const isBlocked = (x: number, y: number): boolean => cells.has(`${Math.round(x)},${Math.round(y)}`)
    || [...f.allies, ...f.enemies].some(other => {
      if (other.id === u.id || other.hp <= 0) return false;
      const before = dist(u.x, u.y, other.x, other.y), after = dist(x, y, other.x, other.y);
      return after < SOLDIERS.unitSeparation - 1e-6 && after <= Math.min(before, SOLDIERS.unitSeparation) + 1e-6;
    });
  const nx = Math.min(Math.max(u.x + dx, 0), SOLDIERS.width - 1);
  const ny = Math.min(Math.max(u.y + dy, f.endless?.minY ?? 0), f.endless?.maxY ?? SOLDIERS.height - 1);
  if (!isBlocked(nx, ny)) { u.x = nx; u.y = ny; u.moved = true; return; }
  if (!isBlocked(nx, u.y)) { u.x = nx; u.moved = true; return; }
  if (!isBlocked(u.x, ny)) { u.y = ny; u.moved = true; }
}

/** Public geometry only: preview the same bounded movement used by physics. */
export function movementPreview(f: Firefight, u: Unit, target: Unit, movement: string, ticks = 4) {
  const probe = { ...u };
  for (let i = 0; i < ticks; i++) {
    const to = unitDirection(probe, target);
    const lateral = movement === 'left' || movement === 'right';
    const sign = movement === 'left' || movement === 'retreat' ? -1 : 1;
    moveUnit(f, probe, (lateral ? -to.y : to.x) * sign * UNIT_STATS.speed, (lateral ? to.x : to.y) * sign * UNIT_STATS.speed);
  }
  return { x: probe.x, y: probe.y, travel: dist(u.x, u.y, probe.x, probe.y),
    targetDistance: dist(probe.x, probe.y, target.x, target.y),
    visible: hasLos(f, probe.x, probe.y, target.x, target.y) };
}

export function tacticalAwareness(f: Firefight, u: Unit) {
  const enemies = (u.side === 'player' ? f.enemies : f.allies).filter(t => t.hp > 0);
  const threats = enemies.filter(t => t.aim > 0 && t.aimTarget === u.id).map(t => ({
    enemy: t.id, lockedPosition: { x: t.aimX, y: t.aimY }, firesInMs: t.aim * SOLDIERS.tickMs,
    stillOnLock: dist(u.x, u.y, t.aimX, t.aimY) <= 0.85,
    escapeDistance: Math.max(0, 0.86 - dist(u.x, u.y, t.aimX, t.aimY)),
  }));
  return { threats, targets: enemies.map(t => {
    const inRange = dist(u.x, u.y, t.x, t.y) <= SOLDIERS.rifleRange;
    const visible = hasLos(f, u.x, u.y, t.x, t.y);
    const directions = Object.fromEntries(['left', 'right', 'retreat', 'advance'].map(m => {
      const p = movementPreview(f, u, t, m);
      return [m, { travel: Math.round(p.travel * 10) / 10, blocked: p.travel < 0.2,
        distanceAfter: Math.round(p.targetDistance * 10) / 10, canShootAfter: p.visible && p.targetDistance <= SOLDIERS.rifleRange,
        breaksSight: !p.visible, escapesLocks: threats.every(lock => dist(p.x, p.y, lock.lockedPosition.x, lock.lockedPosition.y) > 0.85) }];
    }));
    return { id: t.id, distance: Math.round(dist(u.x, u.y, t.x, t.y) * 10) / 10, inRange, visible,
      tooClose: dist(u.x, u.y, t.x, t.y) < 3, preferredDistance: '4–7 格；小于 3 格优先后撤或侧移，禁止继续贴身推进',
      repositionNeeded: !inRange || !visible, directions };
  }), previewMs: 200 };
}

/** Both sides lock a position before firing; either target can dodge. */
function fire(f: Firefight, shooter: Unit, target: Unit): boolean {
  if (shooter.aim > 0 && shooter.aimTarget) {
    const locked = [...f.allies, ...f.enemies].find(u => u.id === shooter.aimTarget && u.hp > 0);
    if (locked) target = locked; else { shooter.aim = 0; shooter.aimTarget = undefined; }
  }
  if (shooter.cool > 0 || shooter.reload > 0 || target.hp <= 0) return false;
  const d = dist(shooter.x, shooter.y, target.x, target.y);
  if (shooter.ammo === 0) { shooter.reload = SOLDIERS.reloadTicks; shooter.aim = 0; return false; }
  if (shooter.aim === 0) {
    if (d > SOLDIERS.rifleRange || !hasLos(f, shooter.x, shooter.y, target.x, target.y)) return false;
    shooter.aim = SOLDIERS.aimTicks; shooter.aimTarget = target.id;
    shooter.aimX = target.x; shooter.aimY = target.y;
    return false;
  }
  if (--shooter.aim > 0) return false;
  shooter.ammo--;
  const tx = shooter.aimX, ty = shooter.aimY;
  const hit = dist(tx, ty, target.x, target.y) <= 0.85 && hasLos(f, shooter.x, shooter.y, target.x, target.y);
  shooter.cool = UNIT_STATS.cooldown;
  f.tracers.push({ x1: shooter.x, y1: shooter.y, x2: tx, y2: ty, hit, ttl: SOLDIERS.tracerTicks, id: `${f.tick}:${shooter.id}` });
  if (f.tracers.length > 64) f.tracers = f.tracers.slice(-64);
  f.events.push(`${shooter.id} 开火：${hit ? '命中' : '躲开了'}`);
  if (hit) (f.pendingHits ??= []).push({ target, damage: UNIT_STATS.damage });
  return true;
}

const DIRECT = new Set(['north', 'south', 'west', 'east', 'shoot', 'reload']);
export function isDirectCommand(command: string): boolean {
  const parts = command.split('_');
  return parts.length <= 4 && parts.every(p => DIRECT.has(p));
}

function nearestEnemy(f: Firefight, u: Unit = f.player): Unit | null {
  let best: Unit | null = null, bd = Infinity;
  for (const e of u.side === 'player' ? f.enemies : f.allies) {
    if (e.hp <= 0) continue;
    const d = dist(u.x, u.y, e.x, e.y);
    const score = d + (d <= SOLDIERS.rifleRange && hasLos(f, u.x, u.y, e.x, e.y) ? 0 : 100);
    if (score < bd) { bd = score; best = e; }
  }
  return best;
}

function norm(dx: number, dy: number): { x: number; y: number } {
  const l = Math.hypot(dx, dy);
  return l > 1e-6 ? { x: dx / l, y: dy / l } : { x: 0, y: 0 };
}

/** Antisymmetric fallback also lets malformed/legacy overlapping states escape. */
function unitDirection(u: Unit, target: Unit): { x: number; y: number } {
  return dist(u.x, u.y, target.x, target.y) > 1e-6
    ? norm(target.x - u.x, target.y - u.y) : { x: u.id < target.id ? 1 : -1, y: 0 };
}

/** 姿态语义（敌我共用）：机动 + （shoot/peek 时）尝试开火。flank 换边依据 perSide 由调用方给。 */
function applyPosture(f: Firefight, u: Unit, target: Unit, command: string, speed: number, flankSide: number): void {
  const to = unitDirection(u, target);
  switch (command) {
    case 'advance':
      moveUnit(f, u, to.x * speed, to.y * speed);
      break;
    case 'retreat':
      moveUnit(f, u, -to.x * speed, -to.y * speed);
      break;
    case 'flank':
      moveUnit(f, u, -to.y * flankSide * speed, to.x * flankSide * speed);
      break;
    case 'peek':
      // 探头：缓慢向前摸出掩体并开火
      moveUnit(f, u, to.x * speed * 0.5, to.y * speed * 0.5);
      fire(f, u, target);
      break;
    case 'shoot':
      fire(f, u, target);
      break;
    case 'hold':
      break;
  }
}

/** Timed movement and independent weapon intent. Expiry never repeats movement. */
function applyOrder(f: Firefight, u: Unit, order: TacticalOrder, target: Unit | undefined): void {
  if (!target || target.hp <= 0 || u.hp <= 0) {
    order.expiresAt = Math.min(order.expiresAt, f.tick); order.reason = 'target-gone'; u.aim = 0; return;
  }
  if (f.tick > order.expiresAt || order.reason) {
    if (u.aim > 0) fire(f, u, target); // Finish a shot already committed; never start another.
    return;
  }
  const to = unitDirection(u, target);
  u.facing = Math.atan2(to.y, to.x);
  if (f.tick <= order.expiresAt && !order.reason && order.movement === 'reposition') {
    if (dist(u.x, u.y, target.x, target.y) <= SOLDIERS.rifleRange && hasLos(f, u.x, u.y, target.x, target.y)) {
      order.route = []; order.expiresAt = f.tick;
    } else {
      while (order.route?.length && dist(u.x, u.y, order.route[0]!.x, order.route[0]!.y) < 0.01) order.route.shift();
      const next = order.route?.[0];
      if (next) {
        const d = dist(u.x, u.y, next.x, next.y), speed = Math.min(d, u.side === 'player' ? SOLDIERS.playerSpeed : SOLDIERS.enemySpeed);
        const x = u.x, y = u.y;
        moveUnit(f, u, (next.x - x) / d * speed, (next.y - y) / d * speed);
        if (dist(x, y, u.x, u.y) < 0.01) { order.reason = 'blocked'; order.expiresAt = f.tick; }
      } else { order.reason = 'no-route'; order.expiresAt = f.tick; }
    }
  } else if (f.tick <= order.expiresAt && !order.reason && order.movement !== 'hold') {
    const speed = u.side === 'player' ? SOLDIERS.playerSpeed : SOLDIERS.enemySpeed;
    const sign = order.movement === 'retreat' || order.movement === 'left' ? -1 : 1;
    const lateral = order.movement === 'left' || order.movement === 'right';
    const dx = (lateral ? -to.y : to.x) * speed * sign;
    const dy = (lateral ? to.x : to.y) * speed * sign;
    const x = u.x, y = u.y;
    moveUnit(f, u, dx, dy);
    if (Math.hypot(u.x - x, u.y - y) < 0.01) { order.expiresAt = f.tick; order.reason = 'blocked'; }
  }
  if (order.weapon === 'reload') {
    // A reload order triggers once, not again after the magazine is consumed.
    if (u.reload === 0 && u.ammo < SOLDIERS.magazine) u.reload = SOLDIERS.reloadTicks;
  } else if (order.weapon === 'shoot') {
    // Continuing fire is bounded by the same live target, range and line of sight.
    if (dist(u.x, u.y, target.x, target.y) <= SOLDIERS.rifleRange && hasLos(f, u.x, u.y, target.x, target.y)) fire(f, u, target);
    else u.aim = 0;
  } else u.aim = 0;
}

/** 玩家执行当前指令：机动 + （shoot/peek 时）尝试开火。 */
function applyCommand(f: Firefight, p: Unit = f.player): void {
  if (p.hp <= 0) return;
  const target = nearestEnemy(f, p);
  if (!target && !isDirectCommand(f.command)) return;
  if (target) p.facing = Math.atan2(target.y - p.y, target.x - p.x);
  if (target && p.aim > 0 && !f.command.split('_').includes('shoot') && f.command !== 'peek') fire(f,p,target);
  if (isDirectCommand(f.command)) {
    const keys = f.command.split('_');
    const direction = norm(Number(keys.includes('east')) - Number(keys.includes('west')), Number(keys.includes('south')) - Number(keys.includes('north')));
    if (direction.x || direction.y) moveUnit(f, p, direction.x * SOLDIERS.playerSpeed, direction.y * SOLDIERS.playerSpeed);
    if (keys.includes('reload') && p.ammo < SOLDIERS.magazine && p.reload === 0) p.reload = SOLDIERS.reloadTicks;
    if (keys.includes('shoot') && target) fire(f, p, target);
    return;
  }
  if (!target) return;
  // 侧移，方向每 40 tick 确定性换边
  const flankSide = Math.floor(f.tick / 40) % 2 === 0 ? 1 : -1;
  if (f.command === 'flankLeft' || f.command === 'flankRight') {
    moveUnit(f, p, f.command === 'flankLeft' ? -SOLDIERS.playerSpeed : SOLDIERS.playerSpeed, 0);
  } else applyPosture(f, p, target, f.command, SOLDIERS.playerSpeed, flankSide);
}

/** 敌兵执行模型下发的姿态指令（目标恒为玩家）。 */
function applyEnemyCommand(f: Firefight, e: Unit, command: string): void {
  if (e.hp <= 0) return;
  const p = nearestEnemy(f, e);
  if (!p) return;
  if (e.aim > 0) { fire(f, e, p); return; }
  e.facing = Math.atan2(p.y - e.y, p.x - e.x);
  // 侧移方向按 id 确定（与脚本 bot 一致）
  const h = [...e.id].reduce((s, c) => s + c.charCodeAt(0), 0);
  applyPosture(f, e, p, command, SOLDIERS.enemySpeed, h % 2 === 0 ? 1 : -1);
}

/** 敌方脚本 bot：接近 → 有视线且在射程内 → 开火；被挡住就横移找射角；残血后撤。 */
function botAct(f: Firefight, e: Unit): void {
  if (e.hp <= 0) return;
  const p = nearestEnemy(f, e);
  if (!p) return;
  if (e.aim > 0) { fire(f, e, p); return; }
  e.facing = Math.atan2(p.y - e.y, p.x - e.x);
  const d = dist(e.x, e.y, p.x, p.y);
  const to = unitDirection(e, p);
  const speed = SOLDIERS.enemySpeed;
  if (e.hp / e.maxHp <= 0.3 && d < 5) {
    moveUnit(f, e, -to.x * speed, -to.y * speed);
    return;
  }
  if (d > SOLDIERS.rifleRange * 0.85) {
    moveUnit(f, e, to.x * speed, to.y * speed);
    return;
  }
  if (hasLos(f, e.x, e.y, p.x, p.y)) {
    fire(f, e, p);
    return;
  }
  // 被沙袋挡住：沿垂直方向横移找射角，方向按 id 确定
  const h = [...e.id].reduce((s, c) => s + c.charCodeAt(0), 0);
  const side = h % 2 === 0 ? 1 : -1;
  moveUnit(f, e, -to.y * side * speed, to.x * side * speed);
}

export function stepFirefight(f: Firefight): Firefight {
  if (f.status !== 'running') return f;
  f.tick++;
  f.events = [];
  f.pendingHits = [];
  for (const u of [...f.allies, ...f.enemies]) {
    u.moved = false;
    u.cool = Math.max(0, u.cool - 1);
    if (u.reload > 0 && --u.reload === 0) u.ammo = SOLDIERS.magazine;
  }
  f.tracers = f.tracers.filter(t => --t.ttl > 0);

  for (const u of f.allies) {
    if (u.hp <= 0) continue;
    const order = getOrder(f, u);
    if (f.human && u.id === f.controlledId) applyCommand(f, u);
    else if (order) applyOrder(f, u, order, f.enemies.find(e => e.id === order.target));
    else if (f.human && f.companionBot) botAct(f, u);
    else if (!f.human && u === f.player) applyCommand(f, u);
  }
  f.enemies.forEach((e, i) => {
    if (e.hp <= 0) return;
    const cmd = f.enemyCommands[i], order = f.enemyOrders[i];
    if (order) applyOrder(f, e, order, f.allies.find(u => u.id === order.target));
    else if (cmd && COMMANDS.includes(cmd)) applyEnemyCommand(f, e, cmd);
    else botAct(f, e);
  });

  // Resolve damage together so iteration order cannot cancel the other team's lethal shot.
  for (const {target, damage} of f.pendingHits) target.hp = Math.max(0,target.hp-damage);
  f.pendingHits = [];
  for (const u of [...f.allies,...f.enemies]) if (u.hp <= 0) u.aim = 0;
  const greenAlive = f.allies.some(u => u.hp > 0), redAlive = f.enemies.some(u => u.hp > 0);
  if (!greenAlive || (!redAlive && !f.endless)) {
    f.status = 'done'; f.winner = greenAlive ? 'player' : redAlive ? 'enemy' : null;
    f.events.push('一方全员被击倒');
  } else if (f.human && controlledUnit(f).hp <= 0) {
    switchSoldier(f);
  } else if (!f.endless && f.tick >= SOLDIERS.limitTicks) {
    f.status = 'done'; f.winner = null;
    f.events.push('时间到，未能清除全部敌兵');
  }
  return f;
}

/** 观察态：喂给模型，也直接驱动 client.js 渲染。 */
export function soldierObservation(f: Firefight): unknown {
  const p = controlledUnit(f), order = getOrder(f, p);
  const target = order ? f.enemies.find(e => e.id === order.target && e.hp > 0) : nearestEnemy(f, p);
  const unit = (u: Unit) => ({
    id: u.id, x: Math.round(u.x * 10) / 10, y: Math.round(u.y * 10) / 10,
    hp: u.hp, maxHp: u.maxHp, alive: u.hp > 0,
    ammo: u.ammo, reloadTicks: u.reload, aimTicks: u.aim, aimX: u.aimX, aimY: u.aimY,
    cooldownTicks: u.cool, facing: Math.round(u.facing * 100) / 100,
    targets: (u.side === 'player' ? f.enemies : f.allies).filter(t=>t.hp>0).map(t=>({
      id:t.id, distance:Math.round(dist(u.x,u.y,t.x,t.y)*10)/10,
      inRange:dist(u.x,u.y,t.x,t.y)<=SOLDIERS.rifleRange,
      visible:hasLos(f,u.x,u.y,t.x,t.y),
    })),
  });
  const enemies = f.enemies.map(e => {
    const d = dist(e.x, e.y, p.x, p.y);
    return {
      ...unit(e), tacticalOrder: getOrder(f,e),
      distToPlayer: Math.round(d * 10) / 10,
      inRange: d <= SOLDIERS.rifleRange,
      canSeePlayer: e.hp > 0 && p.hp > 0 && hasLos(f, e.x, e.y, p.x, p.y),
      playerSees: e.hp > 0 && p.hp > 0 && hasLos(f, p.x, p.y, e.x, e.y),
    };
  });
  return {
    tick: f.tick,
    status: f.status,
    winner: f.winner,
    command: f.command,
    order: order ? { ...order, remainingMs: Math.max(0, order.expiresAt - f.tick) * SOLDIERS.tickMs } : null,
    width: SOLDIERS.width,
    height: SOLDIERS.height,
    rifleRange: SOLDIERS.rifleRange,
    magazine: SOLDIERS.magazine, reloadDuration: SOLDIERS.reloadTicks, aimDuration: SOLDIERS.aimTicks,
    targetId: target?.id ?? null,
    fireStatus: p.hp <= 0 ? 'defeated' : !target ? 'clear' : p.reload > 0 ? 'reloading' : p.ammo <= 0 ? 'empty' : p.cool > 0 ? 'cooldown' : dist(p.x, p.y, target!.x, target!.y) > SOLDIERS.rifleRange ? 'range' : !hasLos(f, p.x, p.y, target!.x, target!.y) ? 'blocked' : 'ready',
    player: unit(p),
    allies: f.allies.map(u => ({ ...unit(u), tacticalOrder: getOrder(f, u), controlled: f.human && u.id === f.controlledId })),
    alliesAlive: f.allies.filter(u => u.hp > 0).length,
    controlledId: f.controlledId, human: f.human, controlEpoch: f.controlEpoch,
    enemies,
    enemiesAlive: enemies.filter(e => e.alive).length,
    exposed: enemies.some(e => e.canSeePlayer && e.inRange),
    sandbags: f.sandbags,
    tracers: f.tracers.map(t => ({ ...t })),
    events: f.events.slice(-6),
  };
}

/** Both models receive the same battlefield detail from their own team view. */
export function enemyObservation(f: Firefight): unknown {
  const obs = soldierObservation(f) as Record<string, unknown>;
  return { ...obs, team: 'red', aiUnitIds: f.enemies.filter(u=>u.hp>0).map(u=>u.id), squad: obs.enemies, opponents: obs.allies, squadAlive: f.enemies.filter(u => u.hp > 0).length };
}

export function controlledUnit(f: Firefight): Unit { return f.allies.find(u => u.id === f.controlledId) ?? f.player; }
export function getOrder(f: Firefight, u: Unit): TacticalOrder | null {
  return u.side === 'enemy' ? f.enemyOrders[f.enemies.indexOf(u)] ?? null : u === f.player ? f.order : f.allyOrders[u.id] ?? null;
}
export function setOrder(f: Firefight, u: Unit, order: TacticalOrder | null): void {
  if (u.side === 'enemy') f.enemyOrders[f.enemies.indexOf(u)] = order;
  else if (u === f.player) f.order = order;
  else f.allyOrders[u.id] = order;
}
export function switchSoldier(f: Firefight): void {
  const alive = f.allies.filter(u => u.hp > 0);
  const next = alive[(alive.findIndex(u => u.id === f.controlledId) + 1) % alive.length];
  if (!next || next.id === f.controlledId) return;
  setOrder(f, controlledUnit(f), null); setOrder(f, next, null);
  f.controlledId = next.id; f.controlEpoch++; f.command = 'hold';
}
