import { createJsonlLogger, type LogRecord, type OutcomeRecord } from './logger.js';
import { runTurnGame, type TurnRecord } from './runner.js';
import { createRealtimeMatch, runRealtimeGame, type RealtimeRecord } from './realtime.js';
import type { TurnBasedGame, RealtimeGame } from './plugin.js';
import type { GameRegistry } from './registry.js';
import type { SystemOne, Answer } from '../systemone/types.js';
import { normalizeSessionConfig, prepareGame, type SessionConfig } from './session-config.js';
import type { RuntimeRegistry, RuntimeSession } from './runtime.js';

const HUMAN_MAX_TURNS = 2000;
export class SessionError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
export interface SessionServiceOptions {
  backend: SystemOne; backends?: BackendSource; registry: GameRegistry;
  logDir?: string; startDelayMs?: number; turnDelayMs?: number; tickSleepMs?: number;
  humanIdleMs?: number;
  runtimes?: RuntimeRegistry;
}
interface HumanSession {
  game: TurnBasedGame<unknown>;
  state: unknown;
  turn: number;
  feedback: string | null;
  recent: string[];
  log: (record: LogRecord | OutcomeRecord) => void;
}

/** 实时游戏的真人会话：服务器按 tickMs 推进物理，玩家输入经 /input 写入。 */
interface HumanRtSession {
  event?(input: string): void;
  stop(): void;
  game: RealtimeGame<unknown>;
  state: unknown;
  frame: number;
  input: string;
  timer: NodeJS.Timeout;
  log: (record: LogRecord | OutcomeRecord) => void;
}

export interface MatchState {
  deadline?: NodeJS.Timeout;
  runtime?: RuntimeSession;
  config?: SessionConfig;
  completion?: Promise<void>;
  decisionStats?: { applied: number; requests: number; ms: number; tokens: number | null };
  gameId: string; status: 'running' | 'done'; outcome: string | null;
  kind: 'ai' | 'human';
  latest: TurnRecord | RealtimeRecord | null; recent: (TurnRecord | RealtimeRecord)[];
  /** 回放用完整记录流（实时局抽帧，上限 2000 条）。 */
  history: (TurnRecord | RealtimeRecord)[];
  startedAt: number;
  finishedAt?: number;
  backendName?: string;
  /** 模型对模型：右侧（RIVAL）模型名与其最近一次决策记录；缺省时右侧是内置 Bot。 */
  rivalBackendName?: string;
  latestRival?: RealtimeRecord | null;
  latestCompanion?: RealtimeRecord | null;
  finalObservation?: unknown;
  /** AI 实时局：每物理帧的最新观测（决策帧之外供观战端逐帧直播，避免"瞬移"）。 */
  liveObservation?: unknown;
  liveFrame?: number;
  error?: string;
  aborted?: boolean;
  /** 最近一次人类操作（/action、/input）的时间戳；闲置超时判中止用。 */
  lastActivityAt: number;
  human?: HumanSession;
  humanRt?: HumanRtSession;
}

const HISTORY_CAP = 2000;
function pushHistory(match: MatchState, record: TurnRecord | RealtimeRecord): void {
  match.history.push(record);
  if (match.history.length > HISTORY_CAP) match.history = match.history.slice(-HISTORY_CAP);
}

function newMatch(gameId: string, kind: 'ai' | 'human', backendName?: string): MatchState {
  return { gameId, status: 'running', outcome: null, kind, latest: null, recent: [], history: [], startedAt: Date.now(), lastActivityAt: Date.now(), ...(backendName ? { backendName } : {}) };
}

/** 汇总一局的关键数据，供结束页与对局列表展示。 */
export function matchStats(match: MatchState): { steps: number; avgMs: number | null; totalTokens: number | null } {
  if (match.decisionStats) {
    const stats = match.decisionStats;
    return { steps: match.human ? match.human.turn - 1 : stats.applied,
      avgMs: stats.requests ? Math.round(stats.ms / stats.requests) : null, totalTokens: stats.tokens };
  }
  const steps = match.human ? match.human.turn - 1 : match.history.filter(r => r.execution?.status === 'applied').length;
  const msValues = match.history.map(r => r.ms).filter(ms => ms > 0);
  const avgMs = msValues.length ? Math.round(msValues.reduce((a, b) => a + b, 0) / msValues.length) : null;
  let totalTokens: number | null = null;
  for (const r of match.history) {
    const usage = (r as TurnRecord).usage;
    const total = usage?.totalTokens ?? ((usage?.promptTokens ?? 0) + (usage?.completionTokens ?? 0));
    if (usage && total > 0) totalTokens = (totalTokens ?? 0) + total;
  }
  return { steps, avgMs, totalTokens };
}

function noteDecision(match: MatchState, record: RealtimeRecord | TurnRecord): void {
  if (!record.execution) return;
  const stats = match.decisionStats ??= { applied: 0, requests: 0, ms: 0, tokens: null };
  stats.requests++; stats.ms += record.ms;
  if (record.execution.status === 'applied') stats.applied++;
  if (record.usage) stats.tokens = (stats.tokens ?? 0) + (record.usage.totalTokens ?? (record.usage.promptTokens ?? 0) + (record.usage.completionTokens ?? 0));
}

function showFeedback(match: MatchState, feedback: import('../arena/decision.js').DecisionFeedback): void {
  const update = <T extends RealtimeRecord | TurnRecord | null>(r: T): T => r?.execution?.id === feedback.decisionId
    ? { ...r, execution: { ...r.execution, feedback } } as T : r;
  match.latest = update(match.latest);
  if (match.latestRival) match.latestRival = update(match.latestRival);
  match.history = match.history.map(update);
  match.recent = match.recent.map(update);
}

/** 对外的对局视图：只挑可序列化字段——human/humanRt 会话含游戏实例与定时器（循环引用），不能裸展开。 */
function matchView(match: MatchState, choices: unknown, compact = false) {
  return {
    config: match.config,
    ...(match.runtime ? { payload: match.runtime.snapshot().payload } : {}),
    gameId: match.gameId, status: match.status, outcome: match.outcome, kind: match.kind,
    latest: match.latest, recent: compact ? [] : match.recent,
    stats: matchStats(match),
    ...(match.backendName !== undefined ? { backendName: match.backendName } : {}),
    ...(match.rivalBackendName !== undefined ? { rivalBackendName: match.rivalBackendName } : {}),
    ...(match.latestCompanion ? { latestCompanion: match.latestCompanion } : {}),
    ...(match.latestRival ? { latestRival: match.latestRival } : {}),
    ...(match.finalObservation !== undefined ? { finalObservation: match.finalObservation } : {}),
    ...(match.liveObservation !== undefined && match.status === 'running'
      ? { liveObservation: match.liveObservation, liveFrame: match.liveFrame }
      : {}),
    ...(match.error !== undefined ? { error: match.error } : {}),
    choices,
  };
}

export interface BackendSource {
  names: string[];
  defaultName?: string;
  create(name: string): SystemOne;
}

/** 人类玩家的可选项：取第一个 choice 型问题，选项即 criteria。 */
function humanChoices(game: TurnBasedGame<unknown>, state: unknown) {
  const questions = game.humanQuestions?.(state) ?? game.questions(state);
  for (const [name, q] of Object.entries(questions)) {
    if (q.type !== 'choice') continue;
    return {
      question: name,
      keys: Object.keys(q.criteria),
      options: Object.entries(q.criteria).map(([id, label]) => ({ id, label })),
    };
  }
  return null;
}

function humanRecord(session: HumanSession, gameId: string): TurnRecord {
  return {
    game: gameId,
    turn: session.turn,
    observation: session.game.observe(session.state, {
      turn: session.turn, recent: session.recent.slice(-5), feedback: session.feedback,
    }),
    answers: {},
    feedback: session.feedback,
    ms: 0,
  };
}

export function createSessionService(options: SessionServiceOptions) {
  const { registry } = options;
  for (const runtime of options.runtimes?.list() ?? []) if (registry.list().some(p => p.id === runtime.id)) throw new Error(`Duplicate game id: ${runtime.id}`);
  const matches = new Map<string, MatchState>();
  let closed = false;
  const sync = (match: MatchState) => {
    if (!match.runtime) return;
    const view = match.runtime.snapshot();
    match.status = view.status; match.outcome = view.outcome; match.error = view.error;
    match.latest = { game: match.gameId, frame: 0, observation: view.observation, answers: {}, ms: 0 };
    if (view.status === 'done') { match.finishedAt ??= Date.now(); match.finalObservation = view.observation; }
  };
  const service = {
    catalog() {
      return [...registry.list().map(plugin => ({ id: plugin.id, name: plugin.name, description: plugin.description,
        page: `/game/${plugin.id}`, mode: plugin.mode, variants: plugin.variants ?? [], options: plugin.options ?? {},
        capabilities: { human: plugin.mode === 'turn' || !!plugin.humanControls, ai: true, benchmark: true, seed: !!plugin.capabilities?.seed } })),
        ...(options.runtimes?.list() ?? []).map(plugin => ({ id: plugin.id, name: plugin.name, description: plugin.description,
          page: plugin.page ?? `/runtime/${plugin.id}`, mode: 'external', variants: plugin.variants, options: plugin.options ?? {}, capabilities: plugin.capabilities }))];
    },
    /** Read-only map access for the existing lobby/replay presentation. */
    get matches(): ReadonlyMap<string, MatchState> { return matches; },
    start(gameId: string, body: SessionConfig = {}) {
      if (closed) throw new SessionError(409, 'Session service is closed');
      const runtime = options.runtimes?.get(gameId);
      if (runtime) {
        if (runtime.maxSessions && [...matches.values()].filter(m => m.gameId === gameId && m.status === 'running').length >= runtime.maxSessions) throw new SessionError(429, 'Too many active sessions');
        let config: SessionConfig;
        try {
          config = normalizeSessionConfig({ id: runtime.id, variants: runtime.variants, mode: 'turn', options: runtime.options }, body);
          config.backend ??= options.backends?.defaultName;
          if (config.rival) throw new Error('Rival model is not supported by this runtime');
          if (config.seed !== undefined && !runtime.capabilities.seed) throw new Error('This runtime does not support seed');
          if (config.mode === 'human' ? !runtime.capabilities.human : !runtime.capabilities.ai) throw new Error('Unsupported controller mode');
          for (const name of [config.backend]) if (name && !options.backends?.names.includes(name)) throw new Error(`Unknown backend: ${name}`);
        } catch (error) { throw new SessionError(400, error instanceof Error ? error.message : String(error)); }
        const matchId = `${gameId}-${crypto.randomUUID()}`;
        const match = newMatch(gameId, config.mode ?? 'ai', config.backend ?? options.backends?.defaultName);
        match.config = config;
        try {
          match.runtime = runtime.start({ id: matchId, logDir: options.logDir ?? 'logs', backendName: match.backendName,
            createBackend: name => {
              const selected = name ?? match.backendName;
              if (selected && options.backends) return options.backends.create(selected);
              return options.backend;
            } }, config);
        } catch (error) { throw new SessionError(400, error instanceof Error ? error.message : String(error)); }
        match.completion = match.runtime.completion.then(() => { sync(match); });
        matches.set(matchId, match); sync(match);
        return { matchId, kind: match.kind };
      }
        const plugin = registry.list().find(g => g.id === gameId);
        if (!plugin) throw new SessionError(404, 'unknown game');
        let prepared: ReturnType<typeof prepareGame>;
        try { prepared = prepareGame(plugin, body); }
        catch (error) { throw new SessionError(400, error instanceof Error ? error.message : String(error)); }
        const gameInstance = prepared.game;
        body = prepared.config;
        if (body.seed !== undefined && !plugin.capabilities?.seed) throw new SessionError(400, 'This game does not support seed');
        for (const name of [body.backend, body.rival]) {
          if (name && (!options.backends || !options.backends.names.includes(name))) throw new SessionError(400, `Unknown backend: ${name}`);
        }
        const matchId = `${plugin.id}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        const writeRecord = createJsonlLogger(`${options.logDir ?? 'logs'}/${matchId}.jsonl`);
        const log: typeof writeRecord = record => writeRecord('type' in record && record.type === 'outcome' ? { ...record, config: body } : record);
        if (body.mode === 'human') {
          if (plugin.mode !== 'turn') {
            if (!plugin.humanControls) {
              throw new SessionError(400, '该游戏暂不支持自己玩');
            }
            // 实时游戏真人局：服务器按 tickMs 推进，输入由 /input 端点写入；
            // 约定实时游戏的 act 识别名为 control 的 choice 答案（不必出现在 questions 里）。
            const game = gameInstance as RealtimeGame<unknown>;
            const match = newMatch(plugin.id, 'human');
            match.config = body;
            // 玩家 vs AI：右侧选了模型且游戏实现了 rival 钩子 → 创建对手位后端，
            // 物理不停表（玩家在实时操作），AI 按决策节奏异步出招，延迟表现为"反应慢"
            let rivalBackend: SystemOne | null = null;
            let companionBackend: SystemOne | null = null;
            if (body.rival && options.backends && game.rival) {
              try {
                rivalBackend = options.backends.create(body.rival);
                if (game.humanCompanion) companionBackend = options.backends.create(body.rival);
                match.rivalBackendName = body.rival;
              } catch (error) {
                throw new SessionError(400, `右侧模型不可用：${error instanceof Error ? error.message : String(error)}`);
              }
            }
            // 与 AI 局一致的 3-2-1 开局缓冲：倒计时期间服务器不推进物理
            const startDelay = options.startDelayMs ?? 3000;
            const startsAt = Date.now() + startDelay;
            const companion = !!game.humanCompanion && !!rivalBackend;
            const controller = createRealtimeMatch(game, companion ? companionBackend! : { ask: async () => { throw new Error('human side must never query a model'); } }, {
              ...prepared.runnerOptions,
              onUpdate: record => { noteDecision(match, record); match.latestCompanion = record; log(record); },
              ...(rivalBackend ? { rivalBackend } : {}),
              onRivalUpdate: record => { noteDecision(match, record); match.latestRival = record; log(record); },
              onFeedback: record => { log(record); showFeedback(match, record.feedback); }, onDiscard: record => { noteDecision(match, record); log(record); },
            });
            controller.startHumanCompanion(!!rivalBackend);
            controller.setControl('self', companion);
            const session: HumanRtSession = {
              game, get state() { return controller.state; }, get frame() { return controller.summary.ticks; }, input: 'idle', log,
              stop: () => controller.stop(),
              event: input => { session.input = 'idle'; controller.applyExternal({ control: { type: 'choice', choice: input, probabilities: { [input]: 1 }, confidence: 1 } }, 'self', companion); },
              timer: setInterval(() => {
                if (Date.now() < startsAt || match.status !== 'running') return;
                const failTick = (error: unknown) => {
                  if (match.status !== 'running') return;
                  clearInterval(session.timer); controller.stop(); match.status = 'done'; match.outcome = 'error';
                  if (match.deadline) clearTimeout(match.deadline);
                  match.finishedAt = Date.now();
                  match.error = error instanceof Error ? error.message : String(error);
                  log({ type: 'outcome', game: plugin.id, outcome: 'error', error: match.error });
                };
                try {
                  const input = session.input;
                  controller.applyExternal({ control: { type: 'choice', choice: input, probabilities: { [input]: 1 }, confidence: 1 } }, 'self', companion);
                  // Publish every physics tick even while companion and rival decisions are pending.
                  void controller.tick(false).then(() => {
                    if (match.status !== 'running') return;
                    const record: RealtimeRecord = { game: plugin.id, frame: session.frame, observation: game.observe(session.state, { live: true }), answers: {}, ms: 0 };
                    match.latest = record;
                    if (session.frame % 12 === 0) { log(record); match.recent.push(record); match.recent = match.recent.slice(-20); pushHistory(match, record); }
                    if (controller.done && match.status === 'running') {
                      clearInterval(session.timer); match.status = 'done'; match.outcome = controller.summary.outcome;
                      if (match.deadline) clearTimeout(match.deadline);
                      match.finishedAt = Date.now();
                      match.finalObservation = game.observe(session.state);
                      log({ type: 'outcome', game: plugin.id, outcome: match.outcome, frames: session.frame });
                    }
                  }).catch(failTick);
                } catch (error) { failTick(error); }
              }, game.tickMs),
            };
            session.timer.unref();
            match.humanRt = session;
            // 预览包含地图；每次独立模型请求也包含所需静态上下文。
            match.latest = { game: plugin.id, frame: 0, observation: game.observe(session.state), answers: {}, ms: 0 };
            pushHistory(match, match.latest);
            matches.set(matchId, match);
            if (body.runtime?.durationMs) match.deadline = setTimeout(() => service.stop(matchId), body.runtime.durationMs);
            return { matchId, kind: 'human', startsAt };
          }
          const game = gameInstance as TurnBasedGame<unknown>;
          const session: HumanSession = { game, state: game.initialState(), turn: 1, feedback: null, recent: [], log };
          const match = newMatch(plugin.id, 'human');
          match.config = body;
          match.human = session;
          match.latest = humanRecord(session, plugin.id);
          pushHistory(match, match.latest);
          matches.set(matchId, match);
          if (body.runtime?.durationMs) match.deadline = setTimeout(() => service.stop(matchId), body.runtime.durationMs);
          return { matchId, kind: 'human' };
        }
        let backend = options.backend;
        const requestedBackend = body.backend ?? options.backends?.defaultName;
        if (requestedBackend && options.backends) {
          try {
            backend = options.backends.create(requestedBackend);
          } catch (error) {
            throw new SessionError(400, error instanceof Error ? error.message : String(error));
          }
        }
        const match = newMatch(plugin.id, 'ai', body.backend ?? options.backends?.defaultName);
        match.config = body;
        // 模型对模型：右侧选了模型且该实时游戏实现了 rival 钩子时，创建第二后端
        let rivalBackend: SystemOne | null = null;
        if (plugin.mode !== 'turn' && body.rival && options.backends) {
          const probeGame = gameInstance as RealtimeGame<unknown>;
          if (probeGame.rival) {
            try {
              rivalBackend = options.backends.create(body.rival);
              match.rivalBackendName = body.rival;
            } catch (error) {
              throw new SessionError(400, `右侧模型不可用：${error instanceof Error ? error.message : String(error)}`);
            }
          }
        }
        matches.set(matchId, match);
        const durationTimer = body.runtime?.durationMs ? setTimeout(() => { match.aborted = true; }, body.runtime.durationMs) : undefined;
        const startDelay = options.startDelayMs ?? 3000;
        // Countdown does not issue unlogged paid warmup questions.
        const startsAt = Date.now() + startDelay;
        const wait = startDelay ? new Promise(r => setTimeout(r, startDelay)) : Promise.resolve();
        if (plugin.mode !== 'turn') {
          const game = gameInstance as RealtimeGame<unknown>;
          // 立即放一帧初始画面，开局延迟/首次决策期间棋盘不再空白
          match.latest = { game: plugin.id, frame: 0, observation: game.observe(game.initialState()), answers: {}, ms: 0 };
          pushHistory(match, match.latest);
          match.completion = wait.then(() => runRealtimeGame(game, backend, {
            onFeedback: record => { log(record); showFeedback(match, record.feedback); },
            onDiscard: record => { noteDecision(match, record); log(record); },
            shouldAbort: () => match.aborted === true,
            ...prepared.runnerOptions,
            // Physics continues while either model is pending; adapters expire their inputs.
            pauseWhileDeciding: false,
            ...(options.tickSleepMs != null ? { tickSleepMs: options.tickSleepMs } : {}),
            ...(rivalBackend ? {
              rivalBackend,
              onRivalUpdate: (record: RealtimeRecord) => { noteDecision(match, record); log(record); match.latestRival = record; },
            } : {}),
            // 每个物理帧更新直播观测：决策帧受模型延迟影响间隔数秒，只看决策帧小人会"瞬移"
            onTick: (state, frame) => {
              const observation = game.observe(state, { live: true });
              match.liveObservation = observation;
              match.liveFrame = frame;
              if (frame % 12 === 0) pushHistory(match, { game: plugin.id, frame, observation, answers: {}, ms: 0 });
            },
            onUpdate: (record, snapshot) => {
              noteDecision(match, record);
              log(record);
              match.latest = record;
              match.recent.push(record);
              match.recent = match.recent.slice(-20);
              pushHistory(match, record);
              if (snapshot.done) { match.status = 'done'; match.outcome = snapshot.outcome; }
            },
          })).then(summary => {
            match.status = 'done'; match.outcome = match.outcome ?? summary.outcome;
            if (summary.finalObservation !== undefined) match.finalObservation = summary.finalObservation;
            log({ type: 'outcome', game: plugin.id, outcome: match.outcome, ticks: summary.ticks, decisions: summary.decisions, skipped: summary.skipped, failures: summary.failures });
          })
            .catch((error: unknown) => { console.error('[match ' + matchId + ']', error); match.status = 'done'; match.outcome = match.outcome ?? 'error'; match.error = error instanceof Error ? error.message : String(error); log({ type: 'outcome', game: plugin.id, outcome: match.outcome, error: match.error }); });
          match.completion = match.completion.finally(() => { if (durationTimer) clearTimeout(durationTimer); match.finishedAt ??= Date.now(); });
          return { matchId, kind: 'ai', startsAt };
        }
        const game = gameInstance as TurnBasedGame<unknown>;
        const initial = game.initialState();
        // 立即放一帧初始画面，开局延迟/首次决策期间棋盘不再空白
        match.latest = { game: plugin.id, turn: 0, observation: game.observe(initial, { turn: 0, recent: [], feedback: null }), answers: {}, feedback: null, ms: 0 };
        pushHistory(match, match.latest);
        match.completion = wait.then(() => runTurnGame(game, backend, {
          maxTurns: 60,
          turnDelayMs: options.turnDelayMs ?? 800,
          // 走位动画节奏是观战特性：turnDelayMs 显式设 0（测试/快速跑局）时一并关闭
          playMsPacing: (options.turnDelayMs ?? 800) > 0,
          shouldAbort: () => match.aborted === true,
          ...prepared.runnerOptions,
          onUpdate: (record, snapshot) => {
            noteDecision(match, record);
            log(record);
            match.latest = record;
            match.recent.push(record);
            match.recent = match.recent.slice(-20);
            pushHistory(match, record);
            if (snapshot.done) {
              match.status = 'done'; match.outcome = snapshot.outcome;
              if (snapshot.finalObservation !== undefined) match.finalObservation = snapshot.finalObservation;
            }
          },
        })).then(summary => {
          match.status = 'done'; match.outcome = match.outcome ?? summary.outcome;
          log({ type: 'outcome', game: plugin.id, outcome: match.outcome, turns: summary.turns, invalidCount: summary.invalidCount });
        })
          .catch((error: unknown) => { console.error('[match ' + matchId + ']', error); match.status = 'done'; match.outcome = match.outcome ?? 'error'; match.error = error instanceof Error ? error.message : String(error); log({ type: 'outcome', game: plugin.id, outcome: match.outcome, error: match.error }); });
        match.completion = match.completion.finally(() => { if (durationTimer) clearTimeout(durationTimer); match.finishedAt ??= Date.now(); });
        return { matchId, kind: 'ai', startsAt };
    },
    input(id: string, body: Record<string, unknown> & { input?: string }) {
        const match = matches.get(id);
        if (match?.runtime) {
          sync(match);
          if (match.status !== 'running') throw new SessionError(409, 'Session has ended');
          if (!match.runtime.input) throw new SessionError(400, 'Input is not supported');
          try { match.runtime.input(body); } catch (error) { throw new SessionError(400, error instanceof Error ? error.message : String(error)); }
          match.lastActivityAt = Date.now(); return { ok: true };
        }
        if (!match || !match.humanRt) {
          throw new SessionError(404, 'unknown realtime human match');
        }
        if (match.status !== 'running') {
          throw new SessionError(400, '对局已结束');
        }
        if (typeof body.input !== 'string' || !/^[\w-]{1,32}$/.test(body.input)) {
          throw new SessionError(400, '非法输入');
        }
        const eventInputs = options.registry.get(match.gameId)?.humanControls?.events ?? [];
        if (eventInputs.includes(body.input)) match.humanRt.event?.(body.input);
        else match.humanRt.input = body.input;
        match.lastActivityAt = Date.now();
        return { ok: true };
    },
    action(id: string, body: Record<string, unknown> & { question?: string; choice?: string }) {
        const match = matches.get(id);
        if (match?.runtime) {
          sync(match);
          if (match.status !== 'running') throw new SessionError(409, 'Session has ended');
          if (!match.runtime.action) throw new SessionError(400, 'Action is not supported');
          try { match.runtime.action(body); } catch (error) { throw new SessionError(400, error instanceof Error ? error.message : String(error)); }
          match.lastActivityAt = Date.now(); return service.state(id);
        }
        if (!match || match.kind !== 'human' || !match.human) {
          throw new SessionError(404, 'unknown human match');
        }
        if (match.status !== 'running') {
          throw new SessionError(400, '对局已结束');
        }
        const session = match.human;
        const choices = humanChoices(session.game, session.state);
        if (!choices || body.question !== choices.question || !body.choice || !choices.keys.includes(body.choice)) {
          throw new SessionError(400, '非法选择');
        }
        match.lastActivityAt = Date.now();
        const answers: Record<string, Answer> = {
          [choices.question]: { type: 'choice', choice: body.choice, probabilities: { [body.choice]: 1 }, confidence: 1 },
        };
        const result = session.game.act(session.state, answers);
        session.feedback = result.feedback;
        if (result.feedback === null) {
          session.state = result.state;
          session.recent.push(`turn ${session.turn}: ok`);
          session.turn += 1;
        } else {
          session.recent.push(`turn ${session.turn}: ${result.feedback}`);
        }
        if (session.game.isTerminal(session.state)) {
          match.status = 'done';
          match.outcome = 'won';
        } else if (session.turn > (match.config?.runtime?.maxTurns ?? HUMAN_MAX_TURNS)) {
          match.status = 'done';
          match.outcome = 'turn-limit';
        }
        const record = humanRecord(session, match.gameId);
        session.log(record);
        if (match.status === 'done') {
          if (match.deadline) clearTimeout(match.deadline);
          match.finishedAt = Date.now();
          session.log({ type: 'outcome', game: match.gameId, outcome: match.outcome ?? 'won', turns: session.turn - 1 });
        }
        match.latest = record;
        match.recent.push(record);
        match.recent = match.recent.slice(-20);
        pushHistory(match, record);
        return matchView(match, match.status === 'running' ? humanChoices(session.game, session.state) : null);
    },
    stop(id: string) {
        const match = matches.get(id);
        if (!match) throw new SessionError(404, 'unknown match');
        if (match.deadline) clearTimeout(match.deadline);
        if (match.runtime) { match.runtime.stop(); sync(match); return { ok: true }; }
        if (match.status === 'running') {
          if (match.kind === 'ai') {
            match.aborted = true; // runner 下一回合检查 shouldAbort 后结束
          } else {
            if (match.humanRt) { clearInterval(match.humanRt.timer); match.humanRt.stop(); }
            match.status = 'done';
            match.outcome = 'aborted';
            match.finishedAt = Date.now();
            const humanLog = match.human?.log ?? match.humanRt?.log;
            humanLog?.({ type: 'outcome', game: match.gameId, outcome: 'aborted' });
          }
        }
        return { ok: true };
    },
    state(id: string, compact = false) {
        const match = matches.get(id);
        if (!match) throw new SessionError(404, 'unknown match');
        sync(match);
        if (match.status === 'done' && match.finishedAt === undefined) match.finishedAt = Date.now();
        const choices = match.kind === 'human' && match.human && match.status === 'running'
          ? humanChoices(match.human.game, match.human.state)
          : null;
        return matchView(match, choices, compact);
    },
    history(id: string) {
        const match = matches.get(id);
        if (!match) throw new SessionError(404, 'unknown match');
        sync(match);
        if (match.status === 'done' && match.finishedAt === undefined) match.finishedAt = Date.now();
        return {
          gameId: match.gameId, status: match.status, outcome: match.outcome, kind: match.kind,
          backendName: match.backendName ?? null, rivalBackendName: match.rivalBackendName ?? null,
          startedAt: match.startedAt, finishedAt: match.finishedAt ?? null,
          config: match.config, stats: matchStats(match), history: match.runtime?.history() ?? match.history,
          ...(match.finalObservation !== undefined ? { finalObservation: match.finalObservation } : {}),
        };
    },
    async wait(id: string) {
      const match = matches.get(id);
      if (!match) throw new SessionError(404, 'unknown match');
      if (match.completion) await match.completion;
      else while (match.status === 'running') await new Promise(resolve => setTimeout(resolve, 20));
      return service.state(id);
    },
    async close() {
      closed = true;
      clearInterval(sweeper);
      for (const id of matches.keys()) service.stop(id);
      await Promise.all([...matches.values()].map(m => m.completion));
    },
  };
  const sweeper = setInterval(() => {
    const now = Date.now();
    for (const [id, match] of matches) {
      if (match.status === 'done') {
        match.finishedAt ??= now;
        if (now - match.finishedAt > 30 * 60 * 1000) matches.delete(id);
      } else if (match.kind === 'human' && now - match.lastActivityAt > (options.humanIdleMs ?? 180000)) {
        service.stop(id); match.error = '闲置超时，自动结束';
      }
    }
  }, 30000);
  sweeper.unref();
  return service;
}
