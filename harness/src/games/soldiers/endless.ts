import { createRequestManager } from '../../systemone/request.js';
import { invalidAnswers } from '../../systemone/validation.js';
import type { Answer, Question, SystemOne } from '../../systemone/types.js';
import { newFirefight, SOLDIERS, type Firefight } from './engine.js';

export interface Performance { hp: number; damage: number; seconds: number; movingRatio: number; stage: number; recent: string[] }
export interface Plan { lane: number; density: string; formation: string; pressure: string; blocks: string[] }
const choice = (instructions: string, criteria: Record<string, string>): Question => ({ type: 'choice', instructions, criteria });
export const generationQuestions: Record<string, Question> = {
  lane: choice('Choose the main north-south passage column for the next battlefield. Vary from recent layouts. All questions independently use player performance.', { '10': 'Left passage', '20': 'Middle passage', '30': 'Right passage' }),
  density: choice('Choose cover density. A struggling player benefits from cover; avoid repetitive layouts.', { sparse: 'Few isolated covers', medium: 'Moderate cover', dense: 'More protected approaches' }),
  formation: choice('Choose enemy starting formation. Offer variety and readable approaches, never punish skill by always countering it.', { spread: 'Across the north edge', left: 'Northwest group', right: 'Northeast group' }),
  pressure: choice('Choose NEXT encounter intensity, not a label for how hard the CURRENT encounter was. Critical remaining health means choose recovery, never challenge. Healthy players who just had recovery can receive normal or challenge. Use healthCondition and recent history. Preserve pacing rather than monotonically increasing difficulty.', { recovery: 'A relief encounter for injured or overwhelmed players: two fragile enemies', normal: 'Balanced encounter for stable players: three regular enemies', challenge: 'Optional harder encounter for healthy, successful players after easy encounters: four enemies' }),
};
for (let i = 0; i < 6; i++) generationQuestions['block' + i] = choice(`Choose cover shape for sector ${i} of six (three columns, two rows). Respect performance and recent layouts. Code reserves a connected passage.`, { bar: 'Short horizontal wall', corner: 'L-shaped cover', pair: 'Two separate cover cells' });

export function decodePlan(answers: Record<string, Answer>): Plan {
  const pick = (key: string) => {
    const a = answers[key], q = generationQuestions[key];
    if (!a || a.type !== 'choice' || !q || q.type !== 'choice' || !Object.hasOwn(q.criteria, a.choice)) throw new Error('模型返回无效选项: ' + key);
    return a.choice;
  };
  return { lane: Number(pick('lane')), density: pick('density'), formation: pick('formation'), pressure: pick('pressure'), blocks: Array.from({ length: 6 }, (_, i) => pick('block' + i)) };
}
export function randomPlan(seed: number): Plan {
  let n = seed >>> 0;
  const random = (size: number) => { n = (Math.imul(n, 1664525) + 1013904223) >>> 0; return n % size; };
  return { lane: [10, 20, 30][random(3)]!, density: ['sparse', 'medium', 'dense'][random(3)]!, formation: ['spread', 'left', 'right'][random(3)]!, pressure: ['recovery', 'normal', 'challenge'][random(3)]!, blocks: Array.from({ length: 6 }, () => ['bar', 'corner', 'pair', 'empty'][random(4)]!) };
}
export function buildLevel(plan: Plan, seed: number, hp: number): Firefight {
  const f = newFirefight(seed);
  f.allies = [f.player];
  f.player.x = plan.lane; f.player.y = 17;
  f.player.hp = Math.min(100, hp + ({ recovery: 25, normal: 10, challenge: 5 }[plan.pressure] ?? 0));
  const count = plan.pressure === 'recovery' ? 2 : plan.pressure === 'challenge' ? 4 : 3;
  f.enemies = Array.from({ length: count }, (_, i) => {
    const x = plan.formation === 'left' ? 3 + i * 3 : plan.formation === 'right' ? 28 + i * 3 : 4 + i * 30 / Math.max(1, count - 1);
    const maxHp = plan.pressure === 'recovery' ? 20 : 40;
    return { ...f.enemies[0]!, id: 'enemy-' + i, x, y: 2, hp: maxHp, maxHp, aimX: x, aimY: 2 };
  });
  f.enemyOrders = f.enemies.map(() => null); f.enemyCommands = f.enemies.map(() => null);
  const cells = new Map<string, { x: number; y: number }>();
  plan.blocks.forEach((shape, i) => {
    const x = 6 + (i % 3) * 12, y = 6 + Math.floor(i / 3) * 6;
    const length = plan.density === 'dense' ? 6 : plan.density === 'sparse' ? 2 : 4;
    const add = (a: number, b: number) => {
      // Protected continuous passage + full-width spawn/exit bands.
      if (Math.abs(a - plan.lane) <= 2 || b <= 3 || b >= 15 || a < 1 || a > 38) return;
      cells.set(`${a},${b}`, { x: a, y: b });
    };
    if (shape === 'bar' || shape === 'corner') for (let j = 0; j < length; j++) add(x + j, y);
    if (shape === 'corner') for (let j = 1; j < 3; j++) add(x, y + j);
    if (shape === 'pair') { add(x, y); add(x + 3, y + 1); }
  });
  f.sandbags = [...cells.values()];
  if (!validateLevel(f)) throw new Error('关卡连通性校验失败');
  return f;
}
export function validateLevel(f: Firefight): boolean {
  const blocked = new Set(f.sandbags.map(p => `${p.x},${p.y}`));
  const queue = [{ x: Math.round(f.player.x), y: Math.round(f.player.y) }];
  const seen = new Set<string>();
  for (let i = 0; i < queue.length; i++) {
    const p = queue[i]!, key = `${p.x},${p.y}`;
    if (seen.has(key) || blocked.has(key) || p.x < 0 || p.x >= SOLDIERS.width || p.y < 0 || p.y >= SOLDIERS.height) continue;
    seen.add(key);
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) queue.push({ x: p.x + dx!, y: p.y + dy! });
  }
  return f.enemies.every(e => seen.has(`${Math.round(e.x)},${Math.round(e.y)}`) && Math.hypot(e.x - f.player.x, e.y - f.player.y) > SOLDIERS.rifleRange) && [...seen].some(k => k.endsWith(',0'));
}
export async function generateLevel(backend: SystemOne | ReturnType<typeof createRequestManager>, state: Performance) {
  const input = { ...state, healthCondition: state.hp <= 35 ? 'critical: player may die soon, needs relief next' : state.hp >= 80 ? 'healthy: can handle a varied encounter' : 'wounded: use moderate pressure' };
  const start = Date.now();
  const requests = 'ask' in backend ? createRequestManager(backend, { timeoutMs: 8000 }) : backend;
  const response = await requests.request(input, generationQuestions);
  const invalid = invalidAnswers(generationQuestions, response.answers);
  if (invalid) throw new Error(invalid);
  return { input, plan: decodePlan(response.answers), answers: response.answers, ms: Date.now() - start, request: response };
}

/** Append a connected strip in world coordinates without resetting combat state. */
export function appendTerrain(f: Firefight, plan: Plan, seed: number, index: number): void {
  const map = buildLevel(plan, seed, f.player.hp);
  const top = (f.endless?.minY ?? 0) - SOLDIERS.height;
  f.endless = { minY: top, maxY: f.endless?.maxY ?? 19 };
  f.sandbags.push(...map.sandbags.map(p => ({ x: p.x, y: p.y + top })));
  f.enemies.push(...map.enemies.map(e => ({ ...e, id: `strip-${index}-${e.id}`, y: e.y + top, aimY: e.aimY + top })));
  f.enemyOrders = f.enemies.map(() => null);
  f.enemyCommands = f.enemies.map(() => null);
}

/** Keep a bounded trailing window; the camera and player remain in world coordinates. */
export function trimTerrain(f: Firefight): void {
  if (!f.endless) return;
  f.endless.maxY = Math.min(f.endless.maxY, Math.ceil(f.player.y + 30));
  f.sandbags = f.sandbags.filter(p => p.y <= f.endless!.maxY);
  f.enemies = f.enemies.filter(e => e.y <= f.endless!.maxY && e.hp > 0).slice(-32);
  f.enemyOrders = f.enemies.map(() => null);
  f.enemyCommands = f.enemies.map(() => null);
}
