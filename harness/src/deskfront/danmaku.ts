import { DANMAKU_VOICE } from './spectator-voice.js';
import { randomUUID } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync, renameSync } from 'node:fs';
import { resolve } from 'node:path';
import { createRequestManager } from '../systemone/request.js';
import { macroBattle, type BattleFrame, type CommentaryOptions, type Fact } from './commentary.js';
import { SPECTATOR_STORY_INSTRUCTIONS, spectatorStoryReference } from './story-config.js';
import { publicBattleFrame } from './spectator-observation.js';
import { spectatorEquipmentFacts, spectatorTextGrounded } from './spectator-story.js';
import { SpectatorHistory, type HistoricalFact } from './spectator-history.js';
import { buildDanmakuEvidence, validateDanmakuItem } from './danmaku-facts.js';

type Density = 'low' | 'normal';
interface State {
  enabled: boolean; density: Density; requests: number; lastAt: number; previous?: BattleFrame;
  controller?: AbortController; epoch: number; key?: string; recent: string[]; status: string;
  history: SpectatorHistory; pending: (HistoricalFact & { observation_window_start?: number })[];
  run?: string; observedTime?: number; observedStage?: string; terminalAttempt?: string;
  consumed: Set<string>;
}
interface Options extends Pick<CommentaryOptions, 'read' | 'backend' | 'record' | 'now' | 'story'> {
  directory(id: string): string; autoTick?: boolean; limit?: number;
  deliver?(id: string, value: Record<string, unknown>): boolean;
  playback?(id: string): { ready: boolean; session: string; run_id: string; updated_at: number } | undefined;
}
const stageIdentity = (f: BattleFrame) => JSON.stringify([f.world.run_id, f.world.world_growth?.revision,
  f.world.world_growth?.mission?.index, f.world.world_growth?.mission?.operation_id]);
const stageKey = (f: BattleFrame) => JSON.stringify([stageIdentity(f), f.world.world_growth?.mission?.status]);
const eventIdentity = (f: HistoricalFact) => JSON.stringify([f.id, f.stage, f.time, f.text]);
const recentEvent = (f: HistoricalFact & { observation_window_start?: number }, time: number, stage: unknown) => Number.isFinite(f.time)
  && f.time <= time && time - f.time <= 10 && (f.stage === undefined || f.stage === stage)
  && (f.observation_window_start === undefined || f.time - f.observation_window_start <= 10);
type ScopedFact = Fact & { time?: number; stage?: number; temporal?: 'current' | 'event' | 'history'; source_scope?: Record<string, unknown> };
const transient = (f: Fact) => f.id.startsWith('loss-') || f.id.startsWith('pressure-') || f.id === 'mission'
  || /^equipment-(?:tank-destroyed|satchel|mortar-(?:captured|shot|crew))-/.test(f.id);
const movementOnly = (fact: { text: string }) => /名士兵实际转移了位置|换了位置/.test(fact.text);
export function repeatedAudienceReaction(text: string, previous: string[]): boolean {
  const normalized = (value: string) => value.replace(/这波|也|还|真|有点|就|啊|呀|呢|啦|哦/gu, '').replace(/[^\p{Letter}\p{Number}]/gu, '');
  const tokens = (value: string) => new Set(Array.from({ length: Math.max(0, value.length - 1) }, (_, i) => value.slice(i, i + 2)));
  const next = normalized(text), a = tokens(next);
  return previous.some(value => {
    const old = normalized(value), b = tokens(old);
    if (next === old) return true;
    const overlap = [...a].filter(token => b.has(token)).length;
    return a.size >= 3 && b.size >= 3 && 2 * overlap / (a.size + b.size) >= .72;
  });
}
export function createDanmaku(options: Options) {
  const states = new Map<string, State>(), now = options.now ?? Date.now, limit = options.limit ?? 30;
  let providerBusy = false; // At most one optional audience request across sessions.
  const get = (id: string) => {
    if (!states.has(id)) states.set(id, { enabled: false, density: 'low', requests: 0, lastAt: -Infinity, epoch: 0, recent: [], status: 'off', history: new SpectatorHistory(), pending: [], consumed: new Set() });
    return states.get(id)!;
  };
  function publish(id: string, value: Record<string, unknown>) {
    if (options.deliver?.(id, { session: id, ...value })) return;
    const folder = options.directory(id); mkdirSync(folder, { recursive: true });
    const file = resolve(folder, 'danmaku-command.json');
    writeFileSync(file + '.tmp', JSON.stringify({ session: id, ...value })); renameSync(file + '.tmp', file);
  }
  function clear(id: string, s: State) {
    s.epoch++; s.controller?.abort();
    publish(id, { enabled: false, items: [] });
  }
  function resetObservation(id: string, s: State) {
    clear(id, s); s.history = new SpectatorHistory(); s.pending = []; s.previous = undefined;
    s.consumed.clear(); s.recent = []; s.key = undefined; s.observedStage = undefined; s.terminalAttempt = undefined; s.observedTime = undefined;
  }
  function nativeReady(id: string, frame: BattleFrame) {
    try {
      const receipt = options.playback?.(id) ?? JSON.parse(readFileSync(resolve(options.directory(id), 'danmaku-status.json'), 'utf8'));
      return receipt.ready === true && receipt.session === id && receipt.run_id === frame.world.run_id
        && Number.isFinite(receipt.updated_at) && now() >= receipt.updated_at && now() - receipt.updated_at <= 3000;
    } catch { return false; }
  }
  function snapshot(id: string) { const s = get(id); return { enabled: s.enabled, density: s.density, requests: s.requests, limit, status: s.status, recent: s.recent }; }
  function configure(id: string, enabled: boolean, density: Density = get(id).density) {
    const s = get(id); clear(id, s); s.enabled = enabled; s.density = density;
    s.status = enabled ? 'watching' : 'off'; return snapshot(id);
  }
  async function step(id: string) {
    const s = get(id); if (!s.enabled) return;
    const observed = options.read(id);
    if (!observed || observed.kind !== 'ai' || observed.status !== 'running') { configure(id, false); return; }
    const frame = publicBattleFrame(observed);
    if (s.run !== undefined && (s.run !== frame.world.run_id || frame.world.time < (s.observedTime ?? -Infinity))) resetObservation(id, s);
    const priorObservedTime = s.observedTime;
    s.run = frame.world.run_id; s.observedTime = frame.world.time;
    const baseStage = stageIdentity(frame), currentStage = frame.world.world_growth?.mission?.index ?? frame.world.world_growth?.revision;
    if (s.observedStage !== undefined && s.observedStage !== baseStage) {
      clear(id, s); s.previous = undefined; s.pending = []; s.terminalAttempt = undefined;
    }
    s.observedStage = baseStage;
    const observedEvents = s.history.observe(frame).map(e => ({ ...e, observation_window_start: priorObservedTime ?? frame.world.time }));
    s.pending = [...s.pending, ...observedEvents].filter(e => recentEvent(e, frame.world.time, currentStage)
      && !s.consumed.has(eventIdentity(e))).slice(-32);
    if (frame.world.world_growth?.enabled && !frame.world.world_growth?.mission?.index) { s.status = 'watching'; return; }
    if (frame.world.paused) { if (s.status !== 'paused') clear(id, s); s.status = 'paused'; return; }
    const key = stageKey(frame);
    if (key !== s.key) { clear(id, s); s.key = key; }
    // Old engine copies have no overlay: do not spend requests invisibly.
    if (!nativeReady(id, frame)) { s.status = 'waiting-native'; return; }
    if (s.requests >= limit) { s.status = 'budget'; return; }
    if (s.controller || providerBusy || now() - s.lastAt < (s.density === 'low' ? 18000 : 12000)) return;
    const summary = macroBattle(frame, s.previous);
    const story = options.story?.(id) ? spectatorStoryReference({ storyMode: 'story' }) : undefined;
    {
      const equipment = spectatorEquipmentFacts(frame, s.previous);
      summary.facts.push(...equipment.facts); summary.changed ||= equipment.changed;
    }
    const currentEvents = s.pending.filter(e => !movementOnly(e) && recentEvent(e, frame.world.time, currentStage));
    const mission = frame.world.world_growth?.mission;
    const terminal = mission?.status === 'failed' || mission?.status === 'completed';
    const terminalEvent = currentEvents.some(e => mission.status === 'failed' ? /本段推进失败/.test(e.text) : /任务已经完成/.test(e.text));
    // Only an observed new terminal event gets one batch. A running transport does not
    // turn the same failed mission into a sequence of new audience reactions.
    if (terminal && (s.terminalAttempt === key || !terminalEvent)) { s.status = 'terminal-quiet'; return; }
    if (!summary.changed && !currentEvents.length) { s.status = 'watching'; return; }
    const navigationRevision = observed.world.navigation_revision;
    const sourceScope = { run_id: frame.world.run_id, revision: frame.world.world_growth?.revision, navigation_revision: navigationRevision,
      stage: currentStage, operation_id: mission?.operation_id, mission_status: mission?.status, observed_at: frame.world.time };
    const facts: ScopedFact[] = [...summary.facts.filter(f => !transient(f) || !s.previous || frame.world.time - s.previous.world.time <= 10).map(f => ({ ...f, time: frame.world.time, stage: currentStage,
      temporal: transient(f) ? 'event' as const : 'current' as const, source_scope: sourceScope })),
      ...currentEvents.map(e => ({ ...e, temporal: 'event' as const, source_scope: sourceScope }))];
    const recordedHistory = s.history.snapshot(frame.world.time);
    const history = { ...recordedHistory,
      timeline: recordedHistory.timeline.filter(e => !movementOnly(e)).map(e => ({ ...e, temporal: 'history' as const })),
      completed_stages: recordedHistory.completed_stages.map(e => ({ ...e, temporal: 'history' as const })),
      evidence_limits: recordedHistory.evidence_limits + '历史只供明确回顾，不是刚发生；priority仅含本关最近10游戏秒、尚未消费的新事件。' };
    if (mission?.status) facts.push({ id: 'stage', text: `当前第${mission.index ?? frame.world.world_growth?.revision ?? '未知'}关，阶段状态:${mission.status}。只有明确completed才代表本段完成。`,
      stage: currentStage, time: frame.world.time, temporal: 'current', source_scope: sourceScope });
    const evidence: ScopedFact[] = [...new Map([...facts, ...history.timeline, ...history.completed_stages].map(f => [f.id, f] as const)).values()];
    // Prefer the recent/current copy when the history contains the same event id.
    for (const fact of facts) { const index = evidence.findIndex(f => f.id === fact.id); if (index >= 0) evidence[index] = fact; }
    const evidenceContext = buildDanmakuEvidence(frame, evidence);
    const controller = new AbortController(), epoch = s.epoch, started = now();
    s.controller = controller; providerBusy = true; s.lastAt = started; s.requests++; s.status = 'generating';
    const observation = structuredClone(frame);
    const batchId = randomUUID();
    // Consume on dispatch, including empty/rejected/error responses. A provider failure
    // must not repeatedly promote an old urgent event into a fresh transition.
    s.previous = observation;
    for (const fact of currentEvents) s.consumed.add(eventIdentity(fact));
    s.consumed = new Set([...s.consumed].slice(-96));
    s.pending = s.pending.filter(e => e.time > observation.world.time);
    if (terminal) s.terminalAttempt = key;
    options.record?.(id, { type: 'danmaku-request', batch_id: batchId, source_scope: sourceScope, request: s.requests, observedAt: frame.world.time, facts, battle_history: history,
      factual_evidence: evidenceContext.facts,
      ...(story ? { narrative_reference: story } : {}) });
    try {
      const response = await createRequestManager(options.backend(), { timeoutMs: 3500 }).request(
        { current_stage: currentStage, source_scope: sourceScope, facts, factual_evidence: evidenceContext.facts, battle_history: history, priority: currentEvents.slice(-6), previous_comments: s.recent,
          audience: 'AI生成的观赛弹幕，不是真实用户；几位不同观众各说一句，不是解说员',
          reaction_lenses: ['支持绿队的观众', '替红队捏把汗的观众', '关注实际转折的观众', '轻松吐槽但不嘲讽伤亡的观众'],
          ...(story ? { narrative_reference: story } : {}) },
        { comments: { type: 'json', maxOutputTokens: 400,
          systemInstructions: '你写中文游戏直播的观众弹幕。几个人分别回应刚发生的比赛，各有立场和情绪，不能一齐复述同一个统计。只输出JSON，不指挥游戏，不编造战况。' + (story ? SPECTATOR_STORY_INSTRUCTIONS : ''), instructions:
          DANMAKU_VOICE } }, { signal: controller.signal });
      const answer = response.answers.comments;
      if (answer?.type !== 'json' || !Array.isArray(answer.value?.items)) {
        options.record?.(id, { type: 'danmaku-candidates', batch_id: batchId, source_scope: sourceScope, reason: 'invalid-batch', candidates: [] });
        throw Error('invalid-batch');
      }
      const candidates = answer.value.items.slice(0, 8).map((item: any, index: number) => ({ index,
        text: typeof item?.text === 'string' ? item.text.slice(0, 256) : undefined,
        evidence_ids: Array.isArray(item?.evidence_ids) ? item.evidence_ids.slice(0, 12).map((value: unknown) => typeof value === 'string' ? value.slice(0, 160) : '[invalid-id]') : [],
        truncated: typeof item?.text === 'string' && item.text.length > 256,
        evidence_ids_truncated: Array.isArray(item?.evidence_ids) && item.evidence_ids.length > 12,
      }));
      options.record?.(id, { type: 'danmaku-candidates', batch_id: batchId, source_scope: sourceScope, candidates,
        candidates_truncated: answer.value.items.length > 8 });
      const freshRaw = options.read(id), fresh = freshRaw ? publicBattleFrame(freshRaw) : undefined;
      const stale = epoch !== s.epoch ? 'cancelled-scope' : !s.enabled ? 'disabled' : !fresh || fresh.kind !== 'ai' || fresh.status !== 'running' ? 'not-running'
        : fresh.world.paused ? 'paused' : stageKey(fresh) !== key ? 'stage-changed'
          : freshRaw!.world.navigation_revision !== navigationRevision ? 'navigation-changed' : fresh.world.time < observation.world.time ? 'time-rewound'
          : now() - started > 6000 ? 'response-expired' : !nativeReady(id, fresh) ? 'native-not-ready' : undefined;
      if (stale || !fresh) {
        options.record?.(id, { type: 'danmaku-filter', batch_id: batchId, source_scope: sourceScope, rejected: candidates.map((item: any) => ({ index: item.index, reason: stale ?? 'no-frame' })), accepted: [] });
        return;
      }
      const freshContext = buildDanmakuEvidence(fresh, evidence);
      const texts: string[] = [], accepted: { index: number; text: string; evidence_ids: string[] }[] = [], rejected: { index: number; reason: string }[] = [];
      const reject = (index: number, reason: string) => { rejected.push({ index, reason }); };
      for (const [index, item] of answer.value.items.slice(0, 5).entries()) {
        if (!item || typeof item.text !== 'string' || !Array.isArray(item.evidence_ids) || !item.evidence_ids.length || item.evidence_ids.length > 12
          || !item.evidence_ids.every((factId: unknown) => typeof factId === 'string' && evidence.some(f => f.id === factId))) { reject(index, 'invalid-evidence'); continue; }
        const text = item.text.trim();
        if (Array.from(text).length < 1 || Array.from(text).length > 24 || /[<>\r\n]/u.test(text)) { reject(index, 'invalid-text'); continue; }
        const cited = evidence.filter(f => item.evidence_ids.includes(f.id));
        if (cited.some(f => f.temporal === 'event' && (typeof f.time !== 'number' || fresh.world.time - f.time > 10 || fresh.world.time < f.time))) { reject(index, 'event-expired'); continue; }
        const verdict = validateDanmakuItem(text, item.evidence_ids, evidenceContext);
        if (!verdict.accepted) { reject(index, verdict.reason); continue; }
        const freshVerdict = validateDanmakuItem(text, item.evidence_ids, freshContext);
        if (!freshVerdict.accepted) { reject(index, 'fresh-' + freshVerdict.reason); continue; }
        if (!spectatorTextGrounded(text, fresh, cited) || (/[一二三四五六七八九十]+人|HP/i.test(text) || (/\d/.test(text) && !/^6{2,6}[!！]*$/.test(text)))) { reject(index, 'public-text-guard'); continue; }
        if (/转移.*关键|关键.*转移|扔得.*[远准]|坦克.*又来|又.*坦克/.test(text)) { reject(index, 'unsupported-quality-claim'); continue; }
        const cheer = /^(?:6{2,6}|[啊哇哦噢]+[!！?？]*|[\p{Extended_Pictographic}\uFE0F\u200D]+)$/u.test(text);
        const highlight = currentEvents.some(f => f.urgent || (!f.routine && /击毁|血量.*零|接管|阵亡/.test(f.text)));
        if (repeatedAudienceReaction(text, [...s.recent, ...texts])
          && !(cheer && highlight && texts.filter(t => t === text).length < 2)) { reject(index, 'repeated-reaction'); continue; }
        texts.push(text); accepted.push({ index, text, evidence_ids: item.evidence_ids });
      }
      const selected = accepted.slice(0, s.density === 'low' ? 3 : 5), time = now();
      for (const candidate of candidates.slice(5)) reject(candidate.index, 'batch-limit');
      for (const item of accepted.slice(selected.length)) reject(item.index, 'density-limit');
      const items = selected.map((item, index) => { const itemId = randomUUID(); return { id: itemId, command_id: itemId, batch_id: batchId,
        text: item.text, evidence_ids: item.evidence_ids,
        at: time + index * (currentEvents.some(f => f.urgent) ? 800 : s.density === 'low' ? 2200 : 1200), expires: time + 20000 }; });
      options.record?.(id, { type: 'danmaku-filter', batch_id: batchId, source_scope: sourceScope, rejected,
        accepted: selected.map((item, index) => ({ index: item.index, item_id: items[index]!.id, evidence_ids: item.evidence_ids })) });
      publish(id, { enabled: true, batch_id: batchId, ...sourceScope, items });
      s.recent = [...s.recent, ...selected.map(item => item.text)].slice(-15); s.status = selected.length ? 'showing' : 'watching';
      options.record?.(id, { type: 'danmaku-batch', batch_id: batchId, source_scope: sourceScope, observedAt: frame.world.time, elapsedMs: now() - started, requests: s.requests, model: response.resolvedModel, usage: response.usage, items });
    } catch (error) {
      const wasCancelled = controller.signal.aborted;
      const httpStatus = error instanceof Error ? /HTTP (\d{3})/.exec(error.message)?.[1] : undefined;
      if (epoch === s.epoch) {
        if (httpStatus === '402' || httpStatus === '401' || httpStatus === '403') {
          configure(id, false); s.status = httpStatus === '402' ? 'payment-required' : 'auth-error';
        } else { s.status = 'retry-later'; if (httpStatus === '429') s.lastAt = now() + 45000; }
      }
      options.record?.(id, { type: 'danmaku-error', batch_id: batchId, source_scope: sourceScope, elapsedMs: now() - started, reason: wasCancelled ? 'cancelled' : error instanceof Error && error.message === 'request-timeout' ? 'timeout' : 'provider-or-format-error',
        errorType: error instanceof Error ? error.name : 'unknown',
        httpStatus,
        truncated: error instanceof Error && error.message.includes('截断') });
    }
    finally { s.controller = undefined; providerBusy = false; }
  }
  const tick = () => { for (const [id, s] of states) if (s.enabled) void step(id).catch(() => { s.status = 'error'; }); };
  const timer = options.autoTick === false ? undefined : setInterval(tick, 500); timer?.unref();
  return { configure, snapshot, step, close() { if (timer) clearInterval(timer); for (const [id, s] of states) clear(id, s); } };
}
