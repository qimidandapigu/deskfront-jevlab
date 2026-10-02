import { responseBackend } from './request.js';
import type { Answer, Question, SystemOne } from './types.js';
import { confidenceFrom } from './types.js';

const SOKOBAN_DIRS = new Set(['U', 'D', 'L', 'R']);

interface Point { x: number; y: number; }
interface LegalMove { action: string; playerTo: Point; boxTo?: Point; boxOnGoal?: boolean; }
interface SokobanLikeState {
  board?: { rows?: unknown }; entities?: { goals?: unknown }; facts?: { corneredBoxes?: unknown };
  legalMoves?: unknown;
}

function asPointArray(v: unknown): Point[] {
  return Array.isArray(v)
    ? v.filter((p): p is Point => !!p && typeof p === 'object' &&
        Number.isFinite((p as Point).x) && Number.isFinite((p as Point).y))
    : [];
}

/** sokoban 观察态的宽松识别：有 legalMoves 且 action 全集 ⊆ UDLR。 */
function sokobanView(state: unknown): { rows: string[]; goals: Point[]; moves: LegalMove[]; cornered: Point[] } | null {
  if (!state || typeof state !== 'object') return null;
  const s = state as SokobanLikeState;
  if (!Array.isArray(s.legalMoves) || s.legalMoves.length === 0) return null;
  const moves = s.legalMoves.filter((m): m is LegalMove =>
    !!m && typeof m === 'object' && SOKOBAN_DIRS.has((m as LegalMove).action) &&
    !!(m as LegalMove).playerTo);
  if (moves.length !== s.legalMoves.length) return null;
  const rawRows = s.board?.rows;
  const rows = Array.isArray(rawRows) && rawRows.every(r => typeof r === 'string') ? rawRows as string[] : [];
  return { rows, goals: asPointArray(s.entities?.goals), moves, cornered: asPointArray(s.facts?.corneredBoxes) };
}

const isWallAt = (rows: string[], x: number, y: number): boolean =>
  y < 0 || y >= rows.length || x < 0 || x >= (rows[y]?.length ?? 0) || rows[y]![x] === '#';

/** 箱子推到非目标的墙角落（两侧垂直方向被墙挡住）即死锁。 */
function pushesIntoCorner(view: { rows: string[]; goals: Point[] }, boxTo: Point): boolean {
  if (view.goals.some(g => g.x === boxTo.x && g.y === boxTo.y)) return false;
  if (view.rows.length === 0) return false;
  const h = isWallAt(view.rows, boxTo.x - 1, boxTo.y) || isWallAt(view.rows, boxTo.x + 1, boxTo.y);
  const v = isWallAt(view.rows, boxTo.x, boxTo.y - 1) || isWallAt(view.rows, boxTo.x, boxTo.y + 1);
  return h && v;
}

interface PushCandidate { id: string; onGoal?: boolean; deadlock?: boolean; walkSteps?: number; }

/** 推箱级观测：availablePushes 里挑一个非死锁的推箱（优先推上目标点，其次走位最少）。 */
function sokobanPushPick(state: unknown, keys: string[]): string | null {
  if (!state || typeof state !== 'object') return null;
  const raw = (state as { availablePushes?: unknown }).availablePushes;
  if (!Array.isArray(raw)) return null;
  const pushes = raw.filter((p): p is PushCandidate => !!p && typeof p === 'object' && typeof (p as PushCandidate).id === 'string');
  const candidates = keys.filter(k => k !== 'undo').map(k => pushes.find(p => p.id === k)).filter((p): p is PushCandidate => !!p);
  if (candidates.length === 0) return null;
  const safe = candidates.filter(p => p.deadlock !== true);
  if (safe.length === 0) return candidates[0]!.id; // 全部死锁，按序取第一个
  const toGoal = safe.find(p => p.onGoal === true);
  if (toGoal) return toGoal.id;
  return safe.reduce((best, p) => (p.walkSteps ?? Infinity) < (best.walkSteps ?? Infinity) ? p : best).id;
}

/** 贪婪基线：推箱上目标 > 安全推箱 > 向最近未就位箱子靠近。 */
function sokobanPick(state: unknown, keys: string[]): string | null {
  if (!keys.every(k => SOKOBAN_DIRS.has(k))) return null;
  const view = sokobanView(state);
  if (!view) return null;
  const legal = view.moves.filter(m => keys.includes(m.action));
  if (legal.length === 0) return null;
  const toGoal = legal.find(m => m.boxOnGoal);
  if (toGoal) return toGoal.action;
  const safePush = legal.find(m => m.boxTo && !pushesIntoCorner(view, m.boxTo));
  if (safePush) return safePush.action;
  const walks = legal.filter(m => !m.boxTo);
  if (walks.length === 0) return legal[0]!.action; // 只剩危险推箱，按序取第一个
  const goals = new Set(view.goals.map(g => `${g.x},${g.y}`));
  const boxes = view.moves
    .filter(m => m.boxTo)
    .map(m => ({ x: m.playerTo.x, y: m.playerTo.y })) // 推箱前箱子在被推方向的反侧
    .filter(b => !goals.has(`${b.x},${b.y}`));
  if (boxes.length === 0) return walks[0]!.action;
  let best = walks[0]!;
  let bestDist = Infinity;
  for (const w of walks) {
    const d = Math.min(...boxes.map(b => Math.abs(b.x - w.playerTo.x) + Math.abs(b.y - w.playerTo.y)));
    if (d < bestDist) { bestDist = d; best = w; }
  }
  return best.action;
}

function pickFor(state: unknown, question: Question): string | null {
  if (question.type !== 'choice') return null;
  const keys = Object.keys(question.criteria);
  return sokobanPushPick(state, keys) ?? sokobanPick(state, keys);
}

function answerFor(state: unknown, question: Question): Answer {
  if (question.type === 'json') throw new Error('mock 不生成作战计划');
  if (question.type === 'choice') {
    const keys = Object.keys(question.criteria);
    if (keys.length === 0) throw new Error('choice 问题至少需要一个选项');
    const winner = pickFor(state, question) ?? keys[0]!;
    const rest = keys.length > 1 ? 0.2 / (keys.length - 1) : 0;
    const probabilities: Record<string, number> = {};
    keys.forEach(k => { probabilities[k] = keys.length === 1 ? 1 : k === winner ? 0.8 : rest; });
    return { type: 'choice', choice: winner, probabilities, confidence: confidenceFrom(probabilities) };
  }
  if (question.type === 'score') {
    const levels = Object.keys(question.levels);
    if (levels.length < 2) throw new Error('score 问题至少需要两级');
    if (!levels.every(l => Number.isFinite(Number(l)))) throw new Error('score 等级 key 必须是数字');
    // sokoban 观察态下按 corneredBoxes 给出风险分，其余均匀取中值
    const view = sokobanView(state);
    if (view) {
      const score = view.cornered.length > 0 ? Number(levels[levels.length - 1]) : Number(levels[0]);
      const probabilities: Record<string, number> = {};
      levels.forEach(l => { probabilities[l] = Number(l) === score ? 0.8 : 0.2 / (levels.length - 1); });
      return { type: 'score', score, probabilities, confidence: confidenceFrom(probabilities) };
    }
    const probabilities: Record<string, number> = {};
    levels.forEach(l => { probabilities[l] = 1 / levels.length; });
    const mid = (Number(levels[0]) + Number(levels[levels.length - 1])) / 2;
    return { type: 'score', score: mid, probabilities, confidence: confidenceFrom(probabilities) };
  }
  return { type: 'noul', noul: 0.5, confidence: 0 }; // 完全不确定：confidence 0
}

export function createMockSystemOne(): SystemOne {
  return responseBackend(async (state, questions) => {
      const answers: Record<string, Answer> = {};
      for (const [key, question] of Object.entries(questions)) answers[key] = answerFor(state, question);
      return { answers, requestedModel: 'local-heuristic', resolvedModel: 'local-heuristic-v1', usage: { promptTokens: 0, completionTokens: 0, totalTokens: 0 }, usageComplete: true };
  });
}
