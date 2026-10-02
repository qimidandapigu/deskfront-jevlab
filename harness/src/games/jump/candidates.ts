// Per-turn candidate action segments for the jump game: the A* route prefix as
// the main candidate plus deterministic perturbation variants (no RNG — offsets
// come from fixed tables). Pure function of (level, actor, progress); questions
// and act each recompute independently, nothing is cached in state.
import {
  Level, ActorState, Progress, Action,
  searchRoute, replayActions, validateActions,
} from './engine.js';

export interface Candidate {
  id: string;              // 'cand-0'（主候选）… 'cand-N'
  actions: Action[];       // 已 validateActions(·, 360) 校验，≤12 段 ≤360 帧
  summary: string;         // '右20帧→右跳30帧→右45帧'
  endX: number; endY: number; dead: boolean; won: boolean;
  gained: { coins: number; key: boolean; switchOn: boolean };
}

const MAX_SEGMENTS = 12;
const MAX_FRAMES = 360;
const SEGMENT_CAP = 90;

export function actionSummary(actions: Action[]): string {
  return actions
    .map(a => `${a.move < 0 ? '左' : a.move > 0 ? '右' : '停'}${a.jump ? '跳' : ''}${a.frames}帧`)
    .join('→');
}

// Split segments longer than the validateActions cap into ≤90-frame runs of the
// same input; physics-equivalent since a held input is applied per frame.
function splitLong(actions: Action[]): Action[] {
  const out: Action[] = [];
  for (const a of actions) {
    for (let left = a.frames; left > 0; left -= SEGMENT_CAP) {
      out.push({ move: a.move, jump: a.jump, frames: Math.min(left, SEGMENT_CAP) });
    }
  }
  return out;
}

function truncateTotal(actions: Action[]): Action[] {
  const out: Action[] = [];
  let total = 0;
  for (const a of actions) {
    if (out.length >= MAX_SEGMENTS || total >= MAX_FRAMES) break;
    const frames = Math.min(a.frames, MAX_FRAMES - total);
    if (frames < 1) break;
    out.push({ move: a.move, jump: a.jump, frames });
    total += frames;
  }
  return out;
}

function tryValid(actions: Action[]): Action[] | null {
  try {
    return validateActions(actions, MAX_FRAMES);
  } catch {
    return null;
  }
}

function cloneActions(actions: Action[]): Action[] {
  return actions.map(a => ({ ...a }));
}

export function generateCandidates(level: Level, a: ActorState, p: Progress): Candidate[] {
  // Fixed probe set: the whole list when no route is found, backfill when a
  // main candidate exists but variants are scarce. Either way the candidate
  // list is never empty and reaches five whenever physics allows.
  const probes: Action[][] = [
    [{ move: 1, jump: false, frames: 90 }],
    [{ move: 1, jump: true, frames: 20 }, { move: 1, jump: false, frames: 60 }],
    [{ move: 1, jump: true, frames: 40 }, { move: 1, jump: false, frames: 60 }],
    [{ move: -1, jump: false, frames: 90 }],
    [{ move: 0, jump: true, frames: 20 }],
  ];

  // Dedupe as we go: perturbations that clamp back to the main candidate's
  // exact values must not count toward the five-candidate floor.
  const seen = new Set<string>();
  const unique: Action[][] = [];
  const push = (actions: Action[] | null): void => {
    const valid = actions && tryValid(truncateTotal(actions));
    if (!valid || unique.length >= 10) return;
    const id = JSON.stringify(valid);
    if (seen.has(id)) return;
    seen.add(id);
    unique.push(valid);
  };

  const route = searchRoute(level, a, p);
  const main = route.verified && route.actions?.length
    ? tryValid(truncateTotal(splitLong(route.actions)))
    : null;

  if (main) {
    push(main);
    // Perturbation variants: for every jump-hold segment in the main candidate,
    // fixed ±5/±10 frame offsets, clamped to [1,90], total truncated to 360.
    for (let i = 0; i < main.length; i++) {
      if (!main[i]!.jump) continue;
      for (const delta of [5, -5, 10, -10]) {
        const variant = cloneActions(main);
        variant[i] = { ...variant[i]!, frames: Math.max(1, Math.min(SEGMENT_CAP, variant[i]!.frames + delta)) };
        push(variant);
      }
    }
    // Fillers when perturbations alone do not reach five unique candidates.
    const fillers: Array<() => Action[] | null> = [
      () => { // 末段截半
        const v = cloneActions(main), last = v[v.length - 1]!;
        const frames = Math.floor(last.frames / 2);
        if (frames < 1) return null;
        v[v.length - 1] = { ...last, frames };
        return v;
      },
      () => main.length > 1 ? cloneActions(main).slice(0, -1) : null, // 去掉末段
      () => { // 首段助跑 ×2
        const v = cloneActions(main);
        v[0] = { ...v[0]!, frames: Math.min(SEGMENT_CAP, v[0]!.frames * 2) };
        return v;
      },
      () => { // 首段助跑 ÷2
        const v = cloneActions(main);
        const frames = Math.floor(v[0]!.frames / 2);
        if (frames < 1) return null;
        v[0] = { ...v[0]!, frames };
        return v;
      },
    ];
    for (const fill of fillers) {
      if (unique.length >= 5) break;
      push(fill());
    }
    for (const probe of probes) {
      if (unique.length >= 5) break;
      push(probe);
    }
  } else {
    for (const probe of probes) push(probe);
  }

  return unique.map((actions, i): Candidate => {
    const { actor: end, progress: after } = replayActions(level, a, p, actions);
    return {
      id: `cand-${i}`,
      actions,
      summary: actionSummary(actions),
      endX: end.x, endY: end.y, dead: end.dead, won: after.won,
      gained: {
        coins: after.coins.filter(c => !p.coins.includes(c)).length,
        key: after.key && !p.key,
        switchOn: after.switchOn && !p.switchOn,
      },
    };
  });
}
