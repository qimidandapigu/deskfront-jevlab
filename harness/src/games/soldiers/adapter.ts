import type { Answer, Question } from '../../systemone/types.js';
import type { RealtimeGame } from '../../arena/plugin.js';
import { COMMANDS, SOLDIERS, isDirectCommand, newFirefight, soldierObservation, enemyObservation, stepFirefight, firingRoute, hasLos, controlledUnit, getOrder, setOrder, switchSoldier, tacticalAwareness, movementPreview } from './engine.js';
import type { Firefight, TacticalOrder, Unit } from './engine.js';
import type { DecisionHooks } from '../../arena/decision.js';
import { repeatedWithoutProgress } from '../../arena/decision.js';

export interface SoldiersState { receipts?: Partial<Record<'self' | 'rival', { accepted: number; retained: number; rejected: number }>>; game: Firefight; progress?: Record<string, { x: number; y: number; hp: number; ammo: number; stalled: number; target: string; ownHp: number; moved: number; damageTaken: number }>; }

const MOVEMENT = { hold: '停留原地', advance: '接近指定目标', retreat: '远离指定目标', left: '相对目标向左侧移躲枪，可同时射击', right: '相对目标向右侧移躲枪，可同时射击', reposition: '仅打不到敌人时绕障接近；已有射角时不移动，不是闪避动作' };
const WEAPON = { shoot: '向指定目标持续开火；只在射程和视线满足时执行，可与移动同时进行', cease: '停火，取消瞄准', reload: '换弹 1.2 秒，期间仍可移动但不能射击' };
const DURATIONS = { short: 200, normal: 500, long: 1000 };
function tacticalQuestions(prefix: string, label: string, targets: Record<string, string>, awareness: ReturnType<typeof tacticalAwareness>, feedback: unknown): Record<string, Question> {
  const context = `${label}：移动和武器独立选择，同时执行。沙袋挡路和子弹。双方均为100血、每枪10伤害、每秒10格、射程9格；双方开火均锁定位置0.5秒，射后冷却0.25秒，侧移可躲避。题目独立回答，不能假设其他题的答案。`;
  const attackable = awareness.targets.some(t => t.inRange && t.visible);
  const { reposition, ...combatMoves } = MOVEMENT;
  const movementChoices = { ...(attackable ? combatMoves : MOVEMENT) };
  // Body collision prevents overlap; model choices also avoid repeatedly pushing into an enemy.
  if (awareness.targets.some(t => t.tooClose)) delete (movementChoices as Partial<typeof MOVEMENT>).advance;
  return {
    [prefix + 'movement']: { type: 'choice', label: label + '移动', instructions: context + '选择移动意图。没有任何可射击敌人时，先 advance 接近最近敌人或 reposition 绕障；不要在射程外持续横移。方向相对指定目标；目标未选定时按最相关威胁判断。视线被沙袋阻挡时，停留加开火不会发射子弹；优先 reposition 绕障。已有射角时不要重复绕位。交火时优先选择可通行且仍能射击的左右侧移，避开锁定点；近敌时后退保持距离。换弹期间也可退向遮挡方向。hold 会暴露在定点射击下，仅在安全且有理由时使用。参考本单位态势：' + JSON.stringify(awareness) + '；上一段效果：' + JSON.stringify(feedback ?? null), criteria: movementChoices },
    [prefix + 'weapon']: { type: 'choice', label: label + '武器', instructions: context + '选择武器操作；子弹不足时优先换弹。', criteria: WEAPON },
    [prefix + 'target']: { type: 'choice', label: label + '目标', instructions: context + '选择仍存活的攻击和移动参照目标，优先可见且可击倒的敌人。', criteria: targets },
    [prefix + 'duration']: { type: 'choice', label: label + '时长', instructions: context + '选择本段移动执行时长；紧急闪避用短段；持续交火侧移用 normal，空旷接近可用 long。参考 timing.lastDecisionMs，避免动作远短于模型耗时而频繁停顿。到期释放移动和武器输入；正在换弹会自然完成，不自动继续射击。', criteria: { short: '0.2 秒：短促调整', normal: '0.5 秒：常规机动', long: '1 秒：长距离机动' } },
  };
}

/** Guard execution, while retaining raw model answers in the match log. */
function prepareOrder(state: SoldiersState, u: Unit, order: TacticalOrder): TacticalOrder {
  const f = state.game, target = (u.side === 'player' ? f.enemies : f.allies).find(e => e.id === order.target);
  if (!target) return order;
  const progress = state.progress ??= {}, prev = progress[u.id];
  const blocked = !hasLos(f, u.x, u.y, target.x, target.y) || Math.hypot(u.x - target.x, u.y - target.y) > SOLDIERS.rifleRange;
  const unchanged = prev && prev.target === target.id && Math.hypot(u.x - prev.x, u.y - prev.y) < 0.2 && prev.hp === target.hp && prev.ammo === u.ammo;
  const stalled = repeatedWithoutProgress(prev?.stalled ?? 0, !!(blocked && unchanged && u.reload === 0));
  progress[u.id] = { x: u.x, y: u.y, hp: target.hp, ammo: u.ammo, target: target.id, stalled, ownHp: u.hp,
    moved: prev ? Math.hypot(u.x - prev.x, u.y - prev.y) : 0, damageTaken: prev ? Math.max(0, prev.ownHp - u.hp) : 0 };
  if (stalled >= 3 || order.movement === 'reposition') {
    const route = firingRoute(f, u, target);
    order.movement = 'reposition';
    order.route = route ?? [];
    if (stalled >= 3) order.recovery = '连续无效决策，系统绕障解卡';
    // A bounded route gets enough time to make progress; never extend it indefinitely.
    order.durationMs = Math.min(4000, Math.max(order.durationMs, (route?.length ?? 0) / (u.side === 'player' ? SOLDIERS.playerSpeed : SOLDIERS.enemySpeed) * SOLDIERS.tickMs + 100));
    order.expiresAt = f.tick + Math.ceil(order.durationMs / SOLDIERS.tickMs);
    if (!route) { order.reason = 'no-route'; order.recovery = '未找到可达射击点，请换目标'; }
  }
  return order;
}
function readOrder(answers: Record<string, Answer>, prefix: string, f: Firefight, targets: string[]): TacticalOrder | null {
  const pick = (key: string) => { const a = answers[prefix + key]; return a?.type === 'choice' ? a.choice : ''; };
  const movement = pick('movement'), weapon = pick('weapon'), target = pick('target'), duration = pick('duration');
  if (!Object.hasOwn(MOVEMENT, movement) || !Object.hasOwn(WEAPON, weapon) || !targets.includes(target) || !Object.hasOwn(DURATIONS, duration)) return null;
  const durationMs = DURATIONS[duration as keyof typeof DURATIONS];
  return { movement: movement as TacticalOrder['movement'], weapon: weapon as TacticalOrder['weapon'], target, durationMs, expiresAt: f.tick + durationMs / SOLDIERS.tickMs };
}

export function createSoldiersGame(seed = 42): RealtimeGame<SoldiersState> {
  const units = (s: SoldiersState, rival: boolean) => (rival ? s.game.enemies : s.game.allies)
    .filter(u => u.hp > 0 && (rival || !s.game.human || u.id !== s.game.controlledId));
  const prefix = (u: Unit) => u.id === 'player' ? '' : u.id + '_';
  const questions = (s: SoldiersState, rival: boolean) => {
    const targets = Object.fromEntries((rival ? s.game.allies : s.game.enemies).filter(u => u.hp > 0)
      .map(u => [u.id, `${u.id}：生命 ${u.hp}，位置 ${u.x.toFixed(1)},${u.y.toFixed(1)}`]));
    return Object.assign({}, ...units(s, rival).map(u => tacticalQuestions(prefix(u), `${u.id} `, targets, tacticalAwareness(s.game, u), s.progress?.[u.id] ? { moved: Math.hypot(u.x - s.progress[u.id]!.x, u.y - s.progress[u.id]!.y), damageTaken: Math.max(0, s.progress[u.id]!.ownHp - u.hp), previousMovement: getOrder(s.game,u)?.movement, previousReason: getOrder(s.game,u)?.reason } : null)));
  };
  const actTeam = (s: SoldiersState, answers: Record<string, Answer>, rival: boolean) => {
    const f = s.game;
    const receipt = { accepted: 0, retained: 0, rejected: 0 };
    (s.receipts ??= {})[rival ? 'rival' : 'self'] = receipt;
    for (const u of units(s, rival)) {
      if (rival) f.enemyCommands[f.enemies.indexOf(u)] ??= 'hold';
      const order = readOrder(answers, prefix(u), f, (rival ? f.allies : f.enemies).filter(t => t.hp > 0).map(t => t.id));
      const existing = getOrder(f, u);
      if (!order) receipt.rejected++;
      else if (existing?.movement === 'reposition' && (order.movement === 'reposition' || !!existing.recovery && order.movement === 'hold') && existing.target === order.target && !existing.reason && existing.expiresAt > f.tick) receipt.retained++;
      else { setOrder(f, u, prepareOrder(s, u, order)); receipt.accepted++; }
      const legacy = answers[`enemy${f.enemies.indexOf(u)}`];
      if (rival && legacy?.type === 'choice' && COMMANDS.includes(legacy.choice)) f.enemyCommands[f.enemies.indexOf(u)] = legacy.choice;
    }
    return s;
  };
  const decision = (rival: boolean): DecisionHooks<SoldiersState> => ({
    maxAgeMs: 5000,
    validateResponse: (s, answers, ageMs) => {
      if (ageMs > 5000) return 'observation-expired';
      for (const u of units(s, rival)) {
        const order = readOrder(answers, prefix(u), s.game, (rival ? s.game.allies : s.game.enemies).filter(t => t.hp > 0).map(t => t.id));
        if (!order) return 'target-or-action-changed';
        const target = (rival ? s.game.allies : s.game.enemies).find(t => t.id === order.target)!;
        if (order.movement === 'left' || order.movement === 'right' || order.movement === 'retreat') {
          if (ageMs > 1500 && order.durationMs === DURATIONS.short) return 'evasion-expired';
          const preview = movementPreview(s.game, u, target, order.movement);
          if (preview.travel < 0.2) return 'movement-now-blocked';
          // A normal/long maneuver is relative to the LIVE target, not a stale locked point.
          // Revalidate its first segment against every currently visible aiming threat.
          if (ageMs > 1500 && tacticalAwareness(s.game,u).threats.some(t => t.stillOnLock &&
            Math.hypot(preview.x - t.lockedPosition.x, preview.y - t.lockedPosition.y) <= 0.85)) return 'live-threat-conflict';
        }
        // Approaches are replanned by prepareOrder at execution, never follow stale routes.
        if (order.movement === 'reposition' && !firingRoute(s.game, u, target)) return 'no-live-route';
      }
      return null;
    },
    schedule: { prefetch: (s, latencyMs) => units(s,rival).some(u => { const o = getOrder(s.game,u); return o && !o.reason && o.expiresAt > s.game.tick && (o.expiresAt - s.game.tick) * SOLDIERS.tickMs <= Math.min(1200, Math.max(200, latencyMs + 100)); }), ready: s => units(s,rival).some(u => !getOrder(s.game,u) || s.game.tick >= getOrder(s.game,u)!.expiresAt), eventKey: s => [...s.game.allies,...s.game.enemies].filter(u=>u.hp>0).map(u=>u.id).join(','), canInterrupt: () => true, maxWaitMs: 4000 },
    contextKey: s => `${rival ? '' : s.game.controlEpoch}:${[...s.game.allies, ...s.game.enemies].filter(e => e.hp > 0).map(e => e.id).join(',')}`,
    capture: s => ({ progress: (rival ? -1 : 1) * (s.game.allies.reduce((n,u)=>n+u.hp,0) - s.game.enemies.reduce((n,u)=>n+u.hp,0)),
      position: units(s, rival).map(u => `${u.x.toFixed(1)},${u.y.toFixed(1)}`).join(';') }),
    describe: s => {
      const orders = units(s, rival).map(u => getOrder(s.game, u)).filter((o): o is TacticalOrder => !!o);
      const receipt = s.receipts?.[rival ? 'rival' : 'self'];
      return { disposition: receipt?.accepted ? 'accepted' : receipt?.retained ? 'retained' : 'rejected', command: { orders, receipt }, expiresAt: orders.length ? Math.max(...orders.map(o => o.expiresAt)) : s.game.tick,
        ...(orders.some(o => o.recovery) ? { reason: orders.map(o => o.recovery).filter(Boolean).join(';') } : {}) };
    },
    release: s => {
      for (const u of units(s, rival)) { const o = getOrder(s.game,u); if (o) o.expiresAt = Math.min(o.expiresAt,s.game.tick); }
      return s;
    },
  });
  return {
    id: 'soldiers', decision: decision(false), tickMs: 50,
    initialState: () => ({ game: newFirefight(seed) }),
    humanCompanion: {
      start: (s, model) => { s.game.human = true; s.game.companionBot = !model; return s; },
    },
    observe: state => { const obs = soldierObservation(state.game) as Record<string,unknown>; return { ...obs, team: 'green', squad: obs.allies, opponents: obs.enemies, aiUnitIds: units(state,false).map(u=>u.id), tactics: units(state,false).map(u => ({ id: u.id, ...tacticalAwareness(state.game,u) })) }; },
    decisionReady: s => units(s,false).some(u => !getOrder(s.game,u) || s.game.tick >= getOrder(s.game,u)!.expiresAt),
    questions: s => questions(s,false),
    act: (state, answers) => {
      const f = state.game, control = answers.control;
      if (control?.type === 'choice') {
        if (control.choice === 'switch') { switchSoldier(f); return state; }
        setOrder(f, controlledUnit(f), null);
        if (control.choice === 'idle') f.command = 'hold';
        else if (COMMANDS.includes(control.choice) || isDirectCommand(control.choice) || ['flankLeft','flankRight'].includes(control.choice)) f.command = control.choice;
        return state;
      }
      const action = answers.action;
      if (action?.type === 'choice' && COMMANDS.includes(action.choice)) { f.order = null; f.command = action.choice; return state; }
      return actTeam(state,answers,false);
    },
    rival: { decision: decision(true), observe: s => ({ ...(enemyObservation(s.game) as Record<string,unknown>), tactics: units(s,true).map(u => ({ id: u.id, ...tacticalAwareness(s.game,u) })) }), questions: s => questions(s,true), act: (s,a) => actTeam(s,a,true) },
    step: s => { stepFirefight(s.game); return s; },
    isTerminal: s => s.game.status !== 'running',
    outcome: s => s.game.status !== 'done' ? null : s.game.winner === 'player' ? 'won' : s.game.winner === 'enemy' ? 'lost' : 'draw',
  };
}
