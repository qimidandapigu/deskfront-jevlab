import { createRequestManager } from '../../systemone/request.js';
import type { Answers, ExecutionRecord } from '../../arena/decision.js';
import { appendTerrain, trimTerrain, buildLevel, generateLevel, randomPlan, type Performance, type Plan } from './endless.js';
import { isDirectCommand, stepFirefight, type Firefight } from './engine.js';

import type { RuntimePlugin } from '../../arena/runtime.js';
import { createJsonlLogger } from '../../arena/logger.js';

export const endlessRuntime: RuntimePlugin = {
  maxSessions: 16,
  id: 'soldiers-endless', name: '玩具兵 · 无尽战场', description: '持续向前探索，沿途生成并拼接战场，也可选择随机对照。',
  page: '/game/soldiers-endless', variants: [{ id: 'model', name: '模型自适应生成' }, { id: 'random', name: '随机对照' }],
  capabilities: { human: true, ai: false, benchmark: false, seed: true },
  start(context, config) {
    for (const key of ['maxTurns', 'maxTicks', 'decisionMs'] as const) if (config.runtime?.[key] !== undefined) throw new Error(`Endless does not support ${key}`);
    const generation = config.variant === 'random' ? undefined : createRequestManager(context.createBackend(config.backend), {
      maxRequests: config.runtime?.maxRequests ?? 100, timeoutMs: config.runtime?.requestTimeoutMs ?? 8000,
    });
    const log = createJsonlLogger(`${context.logDir}/${context.id}.jsonl`);
    const seed = config.seed ?? 42;
    let active = true, outcome: string | null = null;
    let complete!: () => void;
    const completion = new Promise<void>(resolve => { complete = resolve; });
  type Session = { generation?: ReturnType<typeof createRequestManager>; id: string; mode: string; seed: number; stage: number; f: Firefight; hpStart: number; moved: number; touched: number; inputAt: number; history: unknown[]; recent: string[]; pending: boolean; next: null | { plan: Plan; map: Firefight; source: string; ms: number; input: Performance; answers?: unknown; error?: string; adjustment?: string; execution?: ExecutionRecord }; requests: number; paused: boolean };
  const publicState = (s: Session) => { const { generation, ...view } = s; return { ...view, history: s.history.slice(-10) }; };
  const prepare = async (s: Session) => {
    if (s.pending || s.next) return;
    s.pending = true;
    const input: Performance = { hp: s.f.player.hp, damage: Math.max(0, s.hpStart - s.f.player.hp), seconds: s.f.tick * .05, movingRatio: s.moved / Math.max(1, s.f.tick), stage: s.stage, recent: s.recent.slice(-3) };
    let plan = randomPlan(s.seed + s.stage * 997), source = '随机基线', ms = 0, answers: Answers | undefined, error: string | undefined;
    if (s.mode === 'jev') {
      const began = Date.now();
      try { const result = await generateLevel(s.generation!, input); Object.assign(input, result.input); plan = result.plan; ms = result.ms; answers = result.answers; source = config.backend ?? context.backendName ?? 'model'; }
      catch (e) { source = '规则回退'; ms = Date.now() - began; error = e instanceof Error ? e.message : '生成失败'; plan = { ...plan, pressure: 'recovery' }; }
      s.requests = s.generation?.count ?? s.requests;
    }
    let adjustment: string | undefined;
    if (input.hp <= 35 && plan.pressure !== 'recovery') { adjustment = '低血量保护：模型选择 ' + plan.pressure + '，执行 recovery'; plan = { ...plan, pressure: 'recovery' }; }
    const execution: ExecutionRecord = { schema: 'quickplay-execution-v1', id: `endless:${s.id}:${s.stage + 1}`, side: 'self', requestedAt: input.stage,
      resolvedAt: s.stage, status: 'pending', rawAnswers: answers ?? {}, executedAnswers: null, action: null,
      reason: error ?? adjustment ?? 'prepared-not-activated' };
    const next = { execution, adjustment, plan, map: buildLevel(plan, s.seed + s.stage, input.hp), source, ms, input, answers, error };
    if (!active) return;
    s.next = next; s.pending = false;
    s.history.push({ stage: s.stage + 1, ...next, map: undefined });
    log({ type: 'generation', game: 'soldiers-endless', outcome: 'pending', ...s.history.at(-1) as object });
    s.history = s.history.slice(-100);
  };

    const f = buildLevel({ ...randomPlan(seed), pressure: 'recovery' }, seed, 100);
    f.endless = { minY: 0, maxY: 19 };
    const s: Session = { generation, id: context.id, mode: config.variant === 'random' ? 'random' : 'jev', seed, stage: 1, f, hpStart: 100, moved: 0, touched: Date.now(), inputAt: Date.now(), history: [], recent: [], pending: false, next: null, requests: 0, paused: false };
    const finish = (reason: string) => {
      if (!active) return;
      active = false; outcome = reason; clearInterval(timer); if (duration) clearTimeout(duration);
      s.generation?.cancel('session-' + reason);
      log({ type: 'outcome', game: 'soldiers-endless', outcome: reason, stage: s.stage, config });
      complete();
    };
    const timer = setInterval(() => {
      if (!active || s.paused || Date.now() - s.touched > 1500) return;
      if (Date.now() - s.inputAt > 350) s.f.command = 'hold';
      try {
        if (s.f.status === 'running') {
          // A ready strip is joined ahead of the camera, never a level transition.
          if (s.f.player.y - s.f.endless!.minY < 35) {
            if (s.next) activate();
            else if (s.f.player.y - s.f.endless!.minY < 22) {
              const plan = { ...randomPlan(s.seed + s.stage * 997), pressure: 'recovery' };
              appendTerrain(s.f, plan, s.seed + s.stage, ++s.stage);
              const record = { stage: s.stage, plan, source: s.mode === 'random' ? '随机基线' : '规则回退：前方地形即时补齐', ms: 0 };
              s.history.push(record); s.history = s.history.slice(-100);
              log({ type: 'generation-activated', game: 'soldiers-endless', ...record });
            }
            void prepare(s).catch(() => finish('error'));
          }
          stepFirefight(s.f); if (s.f.player.moved) s.moved++;
          trimTerrain(s.f);
        }
        if (s.f.status === 'done') finish(s.f.winner === 'enemy' ? 'lost' : 'draw');
      } catch { finish('error'); }
    }, 50);
    timer.unref();
    const duration = config.runtime?.durationMs ? setTimeout(() => finish('time-limit'), config.runtime.durationMs) : undefined;
    const activate = () => {
          const n = s.next!;
          appendTerrain(s.f, n.plan, s.seed + s.stage, ++s.stage);
          if (n.execution) {
            n.execution.status = 'applied'; n.execution.resolvedAt = s.stage;
            n.execution.executedAnswers = n.error ? null : structuredClone(n.execution.rawAnswers);
            if (n.adjustment && n.execution.executedAnswers?.pressure?.type === 'choice') n.execution.executedAnswers.pressure.choice = 'recovery';
            n.execution.action = { command: n.plan, disposition: 'accepted' };
            n.execution.reason = n.error ?? n.adjustment ?? 'terrain-appended';
          }
          s.recent.push(JSON.stringify(n.plan)); s.recent = s.recent.slice(-3); s.next = null;

      log({ type: 'generation-activated', game: 'soldiers-endless', outcome: 'applied', execution: n.execution });
    };
    return {
      completion,
      snapshot() { return { status: active ? 'running' : 'done', outcome, observation: s.f, payload: publicState(s) }; },
      history: () => structuredClone(s.history),
      stop: () => finish('aborted'),
      input(body) {
        s.touched = s.inputAt = Date.now();
        const command = body.command ?? body.input;
        s.f.command = typeof command === 'string' && isDirectCommand(command) ? command : 'hold';
        if (typeof body.paused === 'boolean') s.paused = body.paused;
      },
      action() { throw new Error('连续战场自动延伸，无需切关'); },
    };
  },
};
