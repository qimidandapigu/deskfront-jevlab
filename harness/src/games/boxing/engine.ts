// Fixed-step authoritative fighting rules, ported from PetRival shared/boxing.mjs (rulesVersion 2).
export const BOXING = Object.freeze({ tickMs: 50, limitMs: 45000, width: 800, hp: 100, commandTicks: 10 });
export const ACTIONS: readonly string[] = Object.freeze(['idle', 'advance', 'retreat', 'jab', 'heavy', 'guard', 'throw', 'jump', 'dash', 'special']);

export interface AttackSpec { startup: number; active: number; recovery: number; range: number; damage: number }
export const ATTACKS: Readonly<Record<string, AttackSpec>> = Object.freeze({
  jab: { startup: 2, active: 1, recovery: 5, range: 114, damage: 3 },
  heavy: { startup: 7, active: 1, recovery: 14, range: 125, damage: 10 },
  special: { startup: 3, active: 2, recovery: 17, range: 175, damage: 18 },
  throw: { startup: 6, active: 1, recovery: 13, range: 102, damage: 8 },
});

export interface Fighter {
  x: number; hp: number; maxHp: number; power: number; action: string;
  attack: { kind: string; age: number; tried: boolean; connected?: boolean } | null;
  y: number; vy: number; meter: number; combo: number; dashCooldown: number; lastInput: string;
  stun: number; flash: number; facing: number;
}

export interface Bout {
  rulesVersion: 2; history: Array<Record<string, unknown>>; frame: number;
  status: 'running' | 'done'; winner: 0 | 1 | null; endMs: number | null;
  events: Array<Record<string, unknown>>; fighters: [Fighter, Fighter]; reason?: string;
}

const specs = (_bout: Bout): Readonly<Record<string, AttackSpec>> => ATTACKS;
const recovering = (f: Fighter, table: Readonly<Record<string, AttackSpec>>): boolean =>
  !!f.attack && f.attack.age >= table[f.attack.kind]!.startup + table[f.attack.kind]!.active;
function remember(bout: Bout, event: Record<string, unknown>) {
  bout.history.push({ frame: bout.frame, ...event });
  bout.history = bout.history.slice(-16);
}

export function newBout(multiplier = 1): Bout {
  const fighters = [1, multiplier].map((scale, i): Fighter => ({
    x: i ? 610 : 190, hp: BOXING.hp * scale, maxHp: BOXING.hp * scale, power: scale,
    y: 0, vy: 0, meter: 0, combo: 0, dashCooldown: 0, lastInput: 'idle',
    action: 'idle', attack: null, stun: 0, flash: 0, facing: i ? -1 : 1,
  }));
  return {
    rulesVersion: 2, history: [], frame: 0, status: 'running', winner: null,
    endMs: null, events: [], fighters: fighters as [Fighter, Fighter],
  };
}

export function finishBout(bout: Bout, winner: 0 | 1 | null, reason = 'ko'): void {
  if (bout.status !== 'running') return;
  bout.status = 'done'; bout.winner = winner; bout.reason = reason; bout.endMs = bout.frame * BOXING.tickMs;
}

interface Hit { from: number; damage: number; kind: string }

export function stepBout(bout: Bout, inputs: [string, string]): Bout {
  if (bout.status !== 'running') return bout;
  bout.frame++; bout.events = [];
  const hits: Hit[] = [], table = specs(bout), modern = bout.rulesVersion === 2;
  for (let i = 0; i < 2; i++) {
    const f = bout.fighters[i]!, opponent = bout.fighters[1 - i]!;
    f.facing = opponent.x >= f.x ? 1 : -1; f.flash = Math.max(0, f.flash - 1);
    f.dashCooldown = Math.max(0, f.dashCooldown - 1);
    if (f.y > 0 || f.vy > 0) { f.y = Math.max(0, f.y + f.vy); f.vy -= 5; if (f.y === 0) f.vy = 0; }
    if (opponent.stun === 0) f.combo = 0;
    if (f.stun > 0) { f.stun--; f.action = 'hurt'; continue; }
    const raw = inputs[i]!;
    let input = raw === 'jumpForward' || raw === 'jumpBack' ? 'jump' : ACTIONS.includes(raw) ? raw : 'idle';
    const fresh = input !== f.lastInput; f.lastInput = input;
    // Only confirmed hits can cancel recovery; whiffs and blocks stay punishable.
    if (f.attack?.connected && f.attack.age <= table[f.attack.kind]!.startup + 7 &&
        ((f.attack.kind === 'jab' && input === 'heavy') ||
         (f.attack.kind === 'heavy' && input === 'special' && f.meter >= 50))) f.attack = null;
    if (input === 'special' && f.meter < 50) input = 'idle';
    if (!f.attack && input === 'jump' && fresh && f.y === 0) { f.vy = 30; f.y = 1; }
    if (!f.attack && input === 'dash' && f.dashCooldown === 0 && f.y === 0) {
      f.x = Math.max(55, Math.min(745, f.x + f.facing * Math.min(65, Math.max(0, Math.abs(opponent.x-f.x)-82))));
      f.dashCooldown = 12;
    }
    if (!f.attack) {
      const spec = table[input];
      if (spec) {
        if (input === 'special') f.meter -= 50;
        f.attack = { kind: input, age: 0, tried: false };
        if (modern) remember(bout, { type: 'start', from: i, kind: input });
      } else {
        f.action = input;
        const direction = raw === 'jumpForward' ? f.facing : raw === 'jumpBack' ? -f.facing : input === 'advance' ? f.facing : input === 'retreat' ? -f.facing : 0;
        const next = Math.max(55, Math.min(745, f.x + direction * 11));
        f.x = i === 0 ? Math.min(next, opponent.x - 82) : Math.max(next, opponent.x + 82);
      }
    }
    if (f.attack) {
      const attack = f.attack, spec = table[attack.kind]!;
      f.action = attack.kind; attack.age++;

    }
  }
  // Sample hit ranges only after BOTH fighters have moved/advanced their pose.
  for (let i = 0; i < 2; i++) {
    const f = bout.fighters[i]!, opponent = bout.fighters[1 - i]!;
    const attack = f.attack;
    if (!attack || f.stun > 0) continue;
    const spec = table[attack.kind]!;
    if (!attack.tried && attack.age >= spec.startup && attack.age < spec.startup + spec.active) {
      attack.tried = true;
      if (Math.abs(opponent.x - f.x) <= spec.range && Math.abs(opponent.y - f.y) < 65 && (attack.kind !== 'throw' || (f.y === 0 && opponent.y === 0))) hits.push({ from: i, damage: spec.damage * f.power, kind: attack.kind });
      else bout.events.push({ type: 'miss', from: i, kind: attack.kind });
    }
  }
  // Resolve simultaneous hits from the same frame together; neither side gets iteration priority.
  const resolved = hits.map(hit => ({
    ...hit,
    counter: modern && recovering(bout.fighters[1 - hit.from]!, table),
    blocked: hit.kind !== 'throw' && bout.fighters[1 - hit.from]!.action === 'guard' &&
      bout.fighters[1 - hit.from]!.y === 0 && !bout.fighters[1 - hit.from]!.attack && !bout.fighters[1 - hit.from]!.stun,
  }));
  for (const hit of resolved) {
    const source = bout.fighters[hit.from]!, target = bout.fighters[1 - hit.from]!;
    source.meter = Math.min(100, source.meter + (hit.blocked ? 4 : 12));
    target.meter = Math.min(100, target.meter + (hit.blocked ? 3 : 6));
    if (!hit.blocked) { source.combo++; if(source.attack) source.attack.connected = true; }
    const damage = modern
      ? hit.blocked ? 0 : hit.damage + (hit.counter ? 2 * bout.fighters[hit.from]!.power : 0)
      : Math.ceil(hit.damage * (hit.blocked ? 0.2 : 1));
    target.hp = Math.max(0, target.hp - damage); target.flash = 4;
    target.x = Math.max(55, Math.min(745, target.x + (hit.from === 0 ? 1 : -1) * (hit.blocked ? modern ? 4 : 8 : hit.kind === 'jab' ? 4 : 20)));
    if (modern && hit.blocked) target.stun = hit.kind === 'heavy' ? 3 : 2;
    if (!hit.blocked) { target.stun = hit.kind === 'special' ? 12 : hit.kind === 'heavy' ? 9 : hit.kind === 'jab' ? 8 : 5; target.attack = null; target.action = 'hurt'; }
    const type = hit.blocked ? 'block' : hit.kind === 'throw' ? 'guardbreak' : hit.counter ? 'counter' : 'hit';
    bout.events.push({ type, from: hit.from, damage, kind: hit.kind, combo: source.combo });
  }
  for (const f of bout.fighters) {
    if (f.attack) {
      const spec = table[f.attack.kind]!;
      if (f.attack.age >= spec.startup + spec.active + spec.recovery) { f.attack = null; f.action = 'idle'; }
    }
  }
  if (modern) for (const event of bout.events) remember(bout, event);
  if (bout.fighters.some(f => f.hp === 0)) {
    finishBout(bout, bout.fighters[0].hp === bout.fighters[1].hp ? null : bout.fighters[0].hp > 0 ? 0 : 1);
  } else if (bout.frame * BOXING.tickMs >= BOXING.limitMs) {
    const difference = bout.fighters[0].hp / bout.fighters[0].maxHp - bout.fighters[1].hp / bout.fighters[1].maxHp;
    finishBout(bout, Math.abs(difference) < 1e-9 ? null : difference > 0 ? 0 : 1, 'time');
  }
  return bout;
}

export interface VisibleFighter {
  y: number; meter: number; combo: number;
  x: number; phase: string; attackKind: string | null; startup: number; active: number; recovery: number;
  hp: number; maxHp: number; power: number; action: string;
  attackAge: number | null; stunned: boolean; recovering: boolean; recoveryMs: number;
}

export interface FighterObservation {
  rulesVersion: number;
  recent: Array<Record<string, unknown>>;
  secondsLeft: number;
  distance: number;
  self: VisibleFighter;
  opponent: VisibleFighter;
}

export function fighterObservation(bout: Bout, fighter: 0 | 1): unknown {
  const self = bout.fighters[fighter], rival = bout.fighters[fighter === 0 ? 1 : 0];
  const visible = (f: Fighter): VisibleFighter => {
    const table = specs(bout);
    const rec = recovering(f, table);
    const spec = f.attack ? table[f.attack.kind]! : null;
    return {
      y: f.y, meter: f.meter, combo: f.combo,
      x: f.x, attackKind: f.attack?.kind ?? null,
      phase: f.stun > 0 ? 'stun' : !f.attack ? f.action : rec ? 'recovery' : f.attack.age < spec!.startup ? 'startup' : 'active',
      startup: spec?.startup ?? 0, active: spec?.active ?? 0, recovery: spec?.recovery ?? 0,
      hp: f.hp, maxHp: f.maxHp, power: f.power, action: f.action,
      attackAge: f.attack?.age ?? null, stunned: f.stun > 0, recovering: rec,
      recoveryMs: rec && spec && f.attack ? (spec.startup + spec.active + spec.recovery - f.attack.age) * BOXING.tickMs : 0,
    };
  };
  return {
    rulesVersion: bout.rulesVersion || 1,
    recent: (bout.history || []).slice(-10).map(e => ({ ...e, from: e['from'] === fighter ? 'self' : 'opponent' })),
    secondsLeft: Math.max(0, (BOXING.limitMs - bout.frame * BOXING.tickMs) / 1000),
    distance: Math.round(Math.abs(self.x - rival.x)),
    self: visible(self), opponent: visible(rival),
  };
}

export function boxingBotAction(bout: Bout, fighter: 0 | 1): string {
  const o = fighterObservation(bout, fighter) as FighterObservation;
  const opp = o.opponent;
  if (o.rulesVersion !== 2) {
    const phase = Math.floor(bout.frame / 12) % 6;
    return o.distance > 110 ? 'advance' : phase === 0 ? 'guard' : phase === 1 ? 'retreat' : phase === 4 ? 'heavy' : 'jab';
  }
  if (o.self.meter >= 50 && o.distance < 170 && opp.recovering) return 'special';
  if (o.distance > 230) return 'dash';
  if (opp.action === 'throw' && o.self.y === 0) return 'jump';
  if (opp.recovering) return o.distance > 112 ? 'advance' : opp.recoveryMs > 600 ? 'heavy' : 'jab';
  if (opp.action === 'throw' && !opp.stunned) return o.distance <= 114 ? 'jab' : 'retreat';
  if (opp.action === 'heavy' && !opp.stunned && o.distance <= 125) return 'guard';
  if (o.distance > 110) return 'advance';
  if (opp.action === 'guard') return o.distance > 100 ? 'advance' : 'throw';
  const phase = (Math.floor(bout.frame / 16) + fighter) % 4;
  return phase === 0 ? 'guard' : phase === 1 ? 'retreat' : phase === 2 ? 'jab' : 'heavy';
}
