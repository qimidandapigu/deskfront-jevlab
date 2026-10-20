import { commentaryFocus, commentaryInstructions, TOY_DIRECTOR_PERSONA, TOY_DIRECTOR_SPEECH, MAX_DIRECTOR_TEXT_LENGTH, type PresentationRole } from './spectator-voice.js';
import { presenterStageContext, directorIntroductionGrounded } from './presenter-context.js';
import { nativeIntroduction, introSpeech, introductionSnapshot, introductionClaimsLiveState } from './presenter-intro.js';
import { presenterExperienceContext } from './presenter-experience.js';
import { directorNarrationGrounded, directorIntentGrounded } from './presenter-narration.js';
import { commentaryTooSimilar } from './commentary-style.js';
import { newPresentationFacts, samePresentationPlan } from './presenter-novelty.js';
import { introductionReasonFacts, introductionReasonIncluded, introductionForcesIncluded } from './presenter-introduction-reasons.js';
import { randomUUID } from 'node:crypto';
import type { RuntimeSnapshot } from '../arena/runtime.js';
import type { SystemOne } from '../systemone/types.js';
import { createRequestManager } from '../systemone/request.js';
import { SPECTATOR_STORY_INSTRUCTIONS, spectatorStoryReference, type SpectatorStoryReference } from './story-config.js';
import { publicBattleFrame, publicSpectatorText } from './spectator-observation.js';
import { spectatorEquipmentFacts, spectatorTextGrounded } from './spectator-story.js';
import { SpectatorHistory, type HistoricalFact } from './spectator-history.js';

type Row = Record<string, any>;
const row = (v: unknown): Row => v && typeof v === 'object' && !Array.isArray(v) ? v as Row : {};
const array = (v: unknown): Row[] => Array.isArray(v) ? v.map(row) : [];
type ExperienceContext = NonNullable<ReturnType<typeof presenterExperienceContext>>;
type ExperienceCue = NonNullable<ExperienceContext['plan']>;
/** An intro explains the adopted design. Analyst originals and later plans
 * remain available to reviews, but cannot become this operation's motive. */
const introductionCue = (cue?: ExperienceCue): ExperienceCue | undefined => cue ? { ...cue, facts: cue.facts.filter(f =>
  /^experience-current-(?:selected-intent|geometry|application|source|fixed-rules|authored-.+|delegated-fields)$/u.test(f.id)) } : undefined;
export interface BattleFrame { status: string; kind: string; world: Row; presenterStage?: ReturnType<typeof presenterStageContext>; presenterExperience?: ExperienceContext }
/** Read the native frame before the public evidence projection strips build state. */
export function constructionPresentationActive(frame: BattleFrame): boolean {
  const growth = row(frame.world.world_growth);
  return growth.phase === 'building' || row(growth.construction_preview).active === true;
}
export function battleFrame(snapshot: RuntimeSnapshot, kind: string): BattleFrame {
  const world = row(snapshot.observation);
  return { status: snapshot.status, kind, world, presenterStage: presenterStageContext(world),
    presenterExperience: kind === 'ai' ? presenterExperienceContext(world, row(row(snapshot.payload).game).worldDirector) : undefined };
}
export function battleKey(frame: BattleFrame): string {
  const w = frame.world;
  return JSON.stringify([w.run_id, w.world_growth?.revision, w.world_growth?.mission?.status, w.winner,
    w.world_growth?.mission?.operation_id,
    array(w.units).filter(u => u.hp > 0 && u.combat_ready !== false).map(u => u.id).sort()]);
}
/** A casualty updates the story; it does not automatically interrupt a spoken sentence. */
export function broadcastKey(frame: BattleFrame): string {
  const w = frame.world;
  return JSON.stringify([w.run_id, w.world_growth?.revision, w.world_growth?.mission?.status, w.winner, w.world_growth?.mission?.operation_id]);
}
/** A plan can finish across active/regrouping/completed within one encounter. */
export function narrationScopeKey(frame: BattleFrame): string {
  const w = frame.world;
  return JSON.stringify([w.run_id, w.world_growth?.revision, w.world_growth?.mission?.index, w.world_growth?.mission?.operation_id, w.winner]);
}
function usable(frame: BattleFrame | undefined): boolean {
  return !!frame && frame.kind === 'ai' && frame.status === 'running' && !frame.world.paused
    && !constructionPresentationActive(frame)
    && typeof frame.world.time === 'number' && array(frame.world.units).length > 0;
}
export interface Fact { id: string; text: string; evidence?: unknown; urgent?: boolean; routine?: boolean }
const factions: Record<string, string> = { green: '绿队', red: '红队', blue: '蓝队' };
const label = (u: Row) => `${factions[u.faction] ?? '队员'}${String(u.id).split('-').at(-1)}号`;
/** No disappearance=death inference; plans and accepted orders never become facts. */
export function battleFacts(current: BattleFrame, previous?: BattleFrame): Fact[] {
  const w = current.world, before = previous?.world;
  const units = array(w.units), old = new Map(array(before?.units).map(u => [u.id, u]));
  const fresh = !before || before.run_id !== w.run_id || before.world_growth?.revision !== w.world_growth?.revision;
  const facts: Fact[] = [];
  const add = (text: string, urgent = false) => facts.push({ id: `f${facts.length + 1}`, text, urgent });
  if (fresh) {
    for (const [team, name] of Object.entries(factions)) {
      const count = units.filter(u => u.faction === team && u.hp > 0 && u.combat_ready !== false).length;
      if (count) add(`当前${name}有${count}名已投入战斗的存活单位。`);
    }
    return facts;
  }
  for (const u of units) {
    const p = old.get(u.id);
    if (!p) continue;
    if (p.hp > 0 && u.hp <= 0) { add(`${label(u)}阵亡。`, true); continue; }
    if (!(u.hp > 0) || u.combat_ready === false) continue;
    if (u.in_cover === true && p.in_cover === false) add(`${label(u)}已经进入掩体。`);
    if (u.in_cover === false && p.in_cover === true) add(`${label(u)}已经离开掩体。`);
    if (u.ammo_infinite !== true && u.reload_remaining > 0 && !(p.reload_remaining > 0)) add(`${label(u)}开始换弹。`);
    if (u.ammo_infinite !== true && p.reload_remaining > 0 && u.reload_remaining === 0) add(`${label(u)}完成换弹。`);
    if (u.hp < p.hp) add(`${label(u)}受到伤害，目前仍存活。`);
    if (u.last_shot_at > p.last_shot_at && w.time - u.last_shot_at >= 0 && w.time - u.last_shot_at < 2) add(`${label(u)}刚刚实际开火；命中结果未知。`);
    if (u.posture === 'prone' && p.posture !== 'prone') add(`${label(u)}已经卧倒。`);
    if (Array.isArray(u.position) && Array.isArray(p.position)
      && Math.hypot(u.position[0] - p.position[0], u.position[1] - p.position[1]) > .12) add(`${label(u)}的位置发生明显移动；未据此确认到位、突破或包抄成功。`);
  }
  if (w.world_growth?.mission?.status === 'completed' && before?.world_growth?.mission?.status !== 'completed') add('引擎确认本段任务完成。', true);
  return facts.sort((a, b) => Number(!!b.urgent) - Number(!!a.urgent)).slice(0, 12);
}

/** Ground quiet passages in the current visible battle, not invented events. */
export function battleRoundup(current: BattleFrame): Fact[] {
  const units = array(current.world.units).filter(u => u.hp > 0 && u.combat_ready !== false);
  const facts: Fact[] = [];
  for (const [team, name] of Object.entries(factions)) {
    const members = units.filter(u => u.faction === team);
    if (!members.length) continue;
    const prone = members.filter(u => u.posture === 'prone').length;
    const wounded = members.filter(u => typeof u.max_hp === 'number' && u.hp < u.max_hp).length;
    
    const healthKnown = members.every(u => typeof u.max_hp === 'number');
    const cover = members.filter(u => u.in_cover === true).length;
    const finite = members.filter(u => u.ammo_infinite !== true);
    const reloading = finite.filter(u => u.reload_remaining > 0).length;
    const reloadFact = finite.length ? `、${reloading}人正在换弹` : '';
    facts.push({ id: `s${facts.length + 1}`, text: `${name}当前${members.length}人存活，${healthKnown ? `其中${wounded}人受伤` : '全队伤情统计未知'}、${prone}人卧姿，已确认${cover}人在掩体中${reloadFact}。掩体不保证安全；未确认任何战术成功。` });
  }
  if (current.world.world_growth?.mission?.status) facts.push({ id: 'mission', text: `当前遭遇状态：${current.world.world_growth.mission.status}；守军剩余${current.world.world_growth.mission.enemies_remaining ?? '未知'}。` });
  return facts;
}

/** Select match-level developments before asking a writer. Individual actions do not trigger narration. */
export function macroBattle(current: BattleFrame, previous?: BattleFrame): { facts: Fact[]; changed: boolean } {
  const w = current.world, before = previous?.world;
  const fresh = !before || before.run_id !== w.run_id || before.world_growth?.revision !== w.world_growth?.revision;
  const facts: Fact[] = []; let changed = fresh;
  for (const [team, name] of Object.entries(factions)) {
    const all = array(w.units).filter(u => u.faction === team && u.kind !== 'tank' && u.tank !== true);
    const alive = all.filter(u => u.hp > 0 && u.combat_ready !== false);
    const old = array(before?.units).filter(u => u.faction === team && u.kind !== 'tank' && u.tank !== true && u.hp > 0 && u.combat_ready !== false);
    if (!alive.length && !old.length) continue;
    const known = alive.length > 0 && alive.every(u => typeof u.max_hp === 'number' && u.max_hp > 0);
    const health = (rows: Row[]) => rows.length && rows.every(u => u.max_hp > 0)
      ? rows.reduce((sum, u) => sum + Math.max(0, Math.min(1, u.hp / u.max_hp)), 0) / rows.length : undefined;
    const hp = health(alive), oldHp = health(old);
    const heavy = known ? alive.filter(u => u.hp / u.max_hp < .5).length : 0;
    facts.push({ id: `s${facts.length + 1}`, text: `${name}当前${alive.length}人仍在战斗${known ? `，全队平均剩余血量约${Math.round(hp! * 100)}%，${heavy}人不足半血` : ''}。` });
    const losses = fresh ? 0 : old.filter(p => all.some(u => u.id === p.id && u.hp <= 0)).length;
    if (losses) {
      changed = true;
      facts.unshift({ id: `loss-${team}`, urgent: true, text: alive.length === 1
        ? `${name}阵亡${losses}人，只剩最后一人了！`
        : `${name}阵亡${losses}人，场上还剩${alive.length}人。` });
    }
    if (!fresh && hp !== undefined && oldHp !== undefined && oldHp - hp >= .25) {
      changed = true;
      facts.push({ id: `pressure-${team}`, text: `${name}这一阶段全队平均血量下降至少四分之一，整体消耗明显加重。` });
    }
  }
  if (w.world_growth?.mission?.status === 'completed' && before?.world_growth?.mission?.status !== 'completed') {
    changed = true; facts.unshift({ id: 'mission', urgent: true, text: '这一阶段拿下了！引擎确认本段任务完成。' });
  }
  return { facts, changed };
}

export interface SpeechResult { audio: Buffer; firstAudioMs: number; totalMs: number }
export interface SpeechDelivery { emotion: string }
export async function synthesizeCommentary(text: string, env: NodeJS.ProcessEnv, signal: AbortSignal,
  fetchImpl: typeof fetch = fetch, delivery?: SpeechDelivery): Promise<SpeechResult> {
  if (!env.DOUBAO_TTS_API_KEY) throw new Error('speech-not-configured');
  const started = Date.now();
  const speaker = env.DOUBAO_TTS_SPEAKER ?? 'zh_male_jieshuoxiaoming_uranus_bigtts';
  const resource = env.DOUBAO_TTS_RESOURCE_ID ?? 'seed-tts-2.0';
  const tones: Record<string, string> = { neutral: '像在桌边把自己的小主意告诉朋友，认真投入，短句有自然停顿，避免播报新闻腔',
    tense: '带一点紧张感，短句紧凑，关键处稍作停顿，避免全句喊叫', surprised: '对刚发生的变化有惊讶感，随后恢复自然解说',
    happy: '兴奋而清晰，关键结果有感染力，避免持续喊叫', sad: '惋惜、低沉一点，尊重失利的一方',
    relieved: '松一口气，语气自然舒展', impressed: '带赞赏感，语气明快', confused: '带一点疑惑，语气自然', awkward: '带笑意地轻巧吐槽，短停顿后抛出反差' };
  const additions = delivery && speaker.endsWith('_uranus_bigtts') && resource.includes('2.0')
    ? { additions: JSON.stringify({ context_texts: [`${TOY_DIRECTOR_SPEECH}${tones[delivery.emotion] ?? tones.neutral}。`] }) } : {};
  const response = await fetchImpl('https://openspeech.bytedance.com/api/v3/tts/unidirectional', {
    method: 'POST', redirect: 'error', signal: AbortSignal.any([signal, AbortSignal.timeout(12000)]),
    headers: { 'Content-Type': 'application/json', 'X-Api-Key': env.DOUBAO_TTS_API_KEY,
      'X-Api-Resource-Id': resource, 'X-Api-Request-Id': randomUUID() },
    body: JSON.stringify({ user: { uid: 'quickplay-commentary' }, req_params: { text,
      speaker, ...additions, audio_params: { format: 'mp3', sample_rate: 24000, bit_rate: 64000, speech_rate: Math.max(-50, Math.min(100, Number(env.DOUBAO_TTS_SPEECH_RATE) || 0)) } } }),
  });
  if (!response.ok || !response.body) { await response.body?.cancel(); throw new Error(`speech-http-${response.status}`); }
  const reader = response.body.getReader(), decoder = new TextDecoder(), audio: Buffer[] = [];
  let pending = '', firstAudioMs = -1, complete = false, bytes = 0;
  const consume = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.code !== 0 && event.code !== 20000000) throw new Error('speech-provider-error');
    if (event.data) {
      if (firstAudioMs < 0) firstAudioMs = Date.now() - started;
      audio.push(Buffer.from(event.data, 'base64'));
    }
    if (event.code === 20000000) complete = true;
  };
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > 2_000_000) throw new Error('speech-response-too-large');
      pending += decoder.decode(value, { stream: true });
      let end: number;
      while ((end = pending.indexOf('\n')) >= 0) { consume(pending.slice(0, end)); pending = pending.slice(end + 1); }
    }
    consume(pending + decoder.decode());
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  if (!complete || !audio.length) throw new Error('speech-incomplete');
  return { audio: Buffer.concat(audio), firstAudioMs, totalMs: Date.now() - started };
}

export interface CommentaryEntry {
  id: string; text: string; subtitle?: string; facts: Fact[]; observedAt: number; observedWallTime: number; createdAt: number; expiresAt: number;
  key: string; urgent: boolean; source: 'model' | 'facts-fallback' | 'event'; audioReady: boolean;
  modelMs: number; speechMs?: number; firstAudioMs?: number; model?: string; warning?: string; emotion?: string;
  presentationRole?: PresentationRole; stageKey?: string;
  /** Versioned design evidence is distinct from observed combat facts. */
  narrationKey?: string; narrationCue?: ExperienceCue; narrationStage?: string;
  narratedObservationKey?: string;
  /** Native-completed encounter introduction: prepared early, played at this wall-clock time. */
  scheduledAt?: number;
}
export interface CommentaryResult { status: string; requests?: number; speechRequests?: number; limit?: number; entry?: CommentaryEntry }
interface Session {
  previous?: BattleFrame; lastAttempt: number; attempts: number; speechRequests: number;
  busy?: AbortController; entry?: CommentaryEntry; audio?: Buffer; lastTexts: string[]; recent: { time: number; text: string }[];
  history: SpectatorHistory; pending: HistoricalFact[];
  observedRun?: string; observedTime?: number;
  retryAt?: number;
  playbackEndedAt?: number;
  lastBattlePlayedAt?: number;
  battleStage?: string;
  battleStageCount?: number;
  introducedStages: Set<string>;
  handledNarration: Set<string>;
  lastHandledPlan?: string;
  lastHandledPlanCue?: ExperienceCue;
  handledStageFacts: Map<string, Fact[]>;
  lastPlan?: { stage: string; cue: ExperienceCue };
  stageIntroduction?: { key: string; dueAt: number; pausedAt?: number };
}
export interface CommentaryOptions {
  read(id: string): BattleFrame | undefined;
  story?(id: string): SpectatorStoryReference | undefined;
  backend(): SystemOne;
  speech(text: string, signal: AbortSignal, delivery?: SpeechDelivery): Promise<SpeechResult>;
  record?(id: string, event: unknown): void;
  now?: () => number;
  limit?: number;
  continuous?: boolean;
  /** The native director uses 10s; direct, on-demand commentary can omit scheduling. */
  introDelayMs?: number;
}
export function createCommentary(options: CommentaryOptions) {
  const states = new Map<string, Session>(), now = options.now ?? Date.now, limit = options.limit ?? 30;
  function state(id: string) {
    let s = states.get(id);
    if (!s) {
      // Only bounded active audio is retained. Request counts remain for the lifetime of the viewer.
      s = { lastAttempt: -Infinity, attempts: 0, speechRequests: 0, lastTexts: [], recent: [], history: new SpectatorHistory(), pending: [], introducedStages: new Set(), handledNarration: new Set(), handledStageFacts: new Map() }; states.set(id, s);
    }
    return s;
  }
  function stop(id: string) { const s = states.get(id); if (s) { s.busy?.abort(); s.entry = undefined; s.audio = undefined; s.previous = undefined; } }
  function result(s: Session, status: string, entry?: CommentaryEntry) {
    return { status, requests: s.attempts, speechRequests: s.speechRequests, limit, ...(entry ? { entry } : {}) };
  }
  function handleNarration(s: Session, key?: string, cue?: ExperienceCue) {
    if (!key) return;
    if (cue?.kind === 'plan') { s.lastHandledPlan = key; s.lastHandledPlanCue = cue; }
    s.handledNarration.add(key);
    if (s.handledNarration.size > 96) s.handledNarration.delete(s.handledNarration.values().next().value!);
  }
  function handleIntroduction(s: Session, stage?: NonNullable<BattleFrame['presenterStage']>, cue?: ExperienceCue) {
    if (!stage) return;
    // Handled includes deliberate silence. Played remains native-receipt-only.
    handleNarration(s, stage.key + ':intro');
    handleNarration(s, cue?.key, cue);
    s.handledStageFacts.set(stage.key, [...stage.facts, ...(cue?.facts ?? [])]);
    if (s.handledStageFacts.size > 32) s.handledStageFacts.delete(s.handledStageFacts.keys().next().value!);
  }
  function handleSupplement(s: Session, stage: BattleFrame['presenterStage'], cue?: ExperienceCue) {
    if (stage && cue?.kind === 'intro') s.handledStageFacts.set(stage.key, [...(s.handledStageFacts.get(stage.key) ?? []), ...cue.facts]);
  }
  function entryCurrent(id: string, entry: CommentaryEntry): boolean {
    const raw = options.read(id);
    const narrative = entry.presentationRole && entry.presentationRole !== 'battle_commentary';
    if (!raw || !usable(raw) || (narrative ? narrationScopeKey(raw) : options.continuous ? broadcastKey(raw) : battleKey(raw)) !== entry.key) return false;
    if (entry.scheduledAt !== undefined && raw.presenterStage?.key !== entry.stageKey) return false;
    if (!entry.narrationCue) return true;
    const context = publicBattleFrame(raw).presenterExperience;
    return [context?.currentDesign, context?.plan, context?.review, context?.observation].some(cue => cue?.key === entry.narrationCue?.key);
  }
  return {
    stop,
    isCurrent: entryCurrent,
    observe(id: string, frame: BattleFrame) {
      frame = publicBattleFrame(frame);
      const s = state(id);
      if (s.observedRun !== undefined && (s.observedRun !== frame.world.run_id || frame.world.time < (s.observedTime ?? 0))) {
        s.previous = undefined; s.pending = []; s.lastTexts = []; s.recent = []; s.lastAttempt = -Infinity;
        s.introducedStages.clear();
        s.handledNarration.clear(); s.handledStageFacts.clear(); s.lastPlan = undefined; s.lastHandledPlan = undefined; s.lastHandledPlanCue = undefined; s.playbackEndedAt = undefined; s.retryAt = undefined;
        s.stageIntroduction = undefined; s.lastBattlePlayedAt = undefined; s.battleStage = undefined; s.battleStageCount = 0;
      }
      s.observedRun = frame.world.run_id; s.observedTime = frame.world.time;
      if ((options.introDelayMs ?? 0) > 0 && frame.presenterStage && s.stageIntroduction?.key !== frame.presenterStage.key) {
        // presenterStage exists only for the native active/regrouping encounter,
        // never a planner proposal, preview, or an unfinished construction.
        s.stageIntroduction = { key: frame.presenterStage.key, dueAt: now() + options.introDelayMs! };
        options.record?.(id, { type: 'commentary-intro-scheduled', stage_key: frame.presenterStage.key,
          observedAt: frame.world.time, nativeObservedAt: now(), dueAt: s.stageIntroduction.dueAt });
      }
      if (s.stageIntroduction) {
        if (frame.world.paused && s.stageIntroduction.pausedAt === undefined) s.stageIntroduction.pausedAt = now();
        else if (!frame.world.paused && s.stageIntroduction.pausedAt !== undefined) {
          s.stageIntroduction.dueAt += Math.max(0, now() - s.stageIntroduction.pausedAt);
          s.stageIntroduction.pausedAt = undefined;
        }
      }
      s.pending = [...s.pending, ...s.history.observe(frame)].slice(-32);
    },
    markPlayed(id: string, entry: CommentaryEntry) {
      if (!publicSpectatorText(entry.text)) return;
      const s = state(id); s.history.markSpoken(entry.observedAt, entry.text);
      s.lastTexts = [...s.lastTexts, entry.text].slice(-8);
      if (entry.presentationRole === 'battle_commentary') {
        s.lastBattlePlayedAt = now();
        const scope = entry.stageKey ?? entry.key;
        if (s.battleStage !== scope) { s.battleStage = scope; s.battleStageCount = 0; }
        s.battleStageCount = (s.battleStageCount ?? 0) + 1;
      }
      if (entry.presentationRole === 'director_intro' && entry.stageKey) {
        s.introducedStages.add(entry.stageKey);
        handleIntroduction(s, { key: entry.stageKey, stage: entry.narrationCue?.stage ?? 0, facts: entry.facts }, entry.narrationCue);
        if (s.introducedStages.size > 32) s.introducedStages.delete(s.introducedStages.values().next().value!);
      }
      if (entry.presentationRole === 'director_review' && entry.narrationCue?.kind === 'intro' && entry.stageKey) {
        s.handledStageFacts.set(entry.stageKey, [...(s.handledStageFacts.get(entry.stageKey) ?? []), ...entry.narrationCue.facts]);
      }
      handleNarration(s, entry.narrationKey, entry.narrationCue);
      handleNarration(s, entry.narratedObservationKey);
      if (entry.narrationCue && entry.narrationStage && ['director_plan', 'director_revision'].includes(entry.presentationRole ?? '')) {
        s.lastPlan = { stage: entry.narrationStage, cue: entry.narrationCue };
      }
    },
    markPlaybackEnded(id: string) { state(id).playbackEndedAt = now(); },
    requeueIntroduction(id: string, entry: CommentaryEntry) {
      const s = state(id), frame = options.read(id);
      if (entry.scheduledAt === undefined || !entry.stageKey || frame?.presenterStage?.key !== entry.stageKey) return;
      s.introducedStages.delete(entry.stageKey); s.handledNarration.delete(entry.stageKey + ':intro'); s.handledStageFacts.delete(entry.stageKey);
      if (entry.narrationKey) s.handledNarration.delete(entry.narrationKey);
      // An interrupted sentence is not a completed explanation. Replay only
      // this same encounter after resume; a new stage gets a fresh reservation.
      s.stageIntroduction = { key: entry.stageKey, dueAt: now() + 1000, ...(frame.world.paused ? { pausedAt: now() } : {}) };
    },
    invalidate(id: string) { const s = states.get(id); if (s) { s.busy?.abort(); s.entry = undefined; s.audio = undefined; } },
    close() { for (const id of states.keys()) stop(id); states.clear(); },
    audio(id: string, entryId: string) {
      const s = states.get(id), current = options.read(id);
      return s?.entry?.id === entryId && current && now() < s.entry.expiresAt && entryCurrent(id, s.entry) ? s.audio : undefined;
    },
    async next(id: string): Promise<CommentaryResult> {
      const observed = options.read(id);
      if (observed && constructionPresentationActive(observed)) {
        this.invalidate(id);
        return result(state(id), 'quiet');
      }
      if (!observed || !usable(observed)) { stop(id); return { status: observed?.kind === 'human' ? 'spectator-only' : 'idle' }; }
      const current = publicBattleFrame(observed);
      const s = state(id);
      this.observe(id, current);
      if (current.world.world_growth?.enabled && !current.world.world_growth?.mission?.index) return result(s, 'quiet');
      if (s.busy) return result(s, 'busy');
      let stage = current.presenterStage;
      const scheduledIntro = stage && s.stageIntroduction?.key === stage.key
        && !s.introducedStages.has(stage.key) && !s.handledNarration.has(stage.key + ':intro') ? s.stageIntroduction : undefined;
      if (scheduledIntro && stage) stage = introductionSnapshot(stage);
      if (!scheduledIntro && now() < (s.retryAt ?? 0)) return result(s, 'model-unavailable');
      if (!scheduledIntro && (s.attempts >= limit || s.speechRequests >= limit)) return result(s, 'budget');
      const allChanges = battleFacts(current, s.previous);
      const macro = macroBattle(current, s.previous);
      const story = options.story?.(id) ? spectatorStoryReference({ storyMode: 'story' }) : undefined;
      {
        const equipment = spectatorEquipmentFacts(current, s.previous);
        macro.facts.push(...equipment.facts); macro.changed ||= equipment.notableChanged;
      }
      const heartbeat = options.continuous && now() - s.lastAttempt >= 30000;
      const notablePending = s.pending.some(f => !f.routine);
      const experience = current.presenterExperience;
      if (stage && experience?.introductionReasons?.length) stage = { ...stage,
        facts: [...stage.facts, ...experience.introductionReasons] };
      const introReasons = introductionReasonFacts(stage?.facts ?? []);
      const introBuiltIds = (stage?.facts ?? []).filter(f => /^director-(?:mission|deployment|composition|reinforcements|deployed-support|support|layout|layout-detail|prop-.+|change-.+)$/u.test(f.id)).map(f => f.id);
      const narrationStage = JSON.stringify([current.world.run_id, current.world.world_growth?.mission?.index, current.world.world_growth?.mission?.operation_id]);
      const reflectionKey = narrationStage + ':reflection';
      const completed = current.world.world_growth?.mission?.status === 'completed';
      const importantBattleChange = macro.facts.some(f => f.urgent || f.id.startsWith('pressure-')) || s.pending.some(f => f.urgent);
      // A selected future design still deserves its creator's explanation.
      // The construction phase itself remains silent and invalidates late audio.
      // A report refresh can change phrasing without changing an arrangement.
      // Compare only the immediately handled plan, so A -> B -> A stays valid.
      if (experience?.plan && samePresentationPlan(experience.plan, s.lastHandledPlanCue)) handleNarration(s, experience.plan.key, experience.plan);
      const lateDesign = experience?.currentDesign && stage && s.handledNarration.has(stage.key + ':intro')
        && !s.handledNarration.has(experience.currentDesign.key) ? experience.currentDesign : undefined;
      const lateFacts = lateDesign ? newPresentationFacts(lateDesign.facts, s.handledStageFacts.get(stage!.key) ?? []) : [];
      if (lateDesign && !lateFacts.length) handleNarration(s, lateDesign.key, lateDesign);
      const unseen = (cue?: ExperienceCue) => !!cue && (cue.kind === 'plan'
        ? cue.key !== s.lastHandledPlan && cue.key !== s.lastPlan?.cue.key
        : !s.handledNarration.has(cue.key));
      let narrationCue: ExperienceCue | undefined;
      let narrationKey: string | undefined;
      let presentationRole: PresentationRole = 'battle_commentary';
      const builderMode = current.world.world_growth?.enabled === true || !!experience;
      if (scheduledIntro) {
        // Reserve the opening explanation even when combat produces casualties.
        // A speech already playing is never interrupted by those battle changes.
        presentationRole = 'director_intro'; narrationCue = introductionCue(experience?.currentDesign);
        narrationKey = narrationCue?.key ?? stage!.key + ':intro';
      } else if (completed && unseen(experience?.plan)) {
        // A newly selected next encounter must not get stuck behind a failed
        // recap while construction is about to start.
        presentationRole = s.lastPlan?.stage === narrationStage ? 'director_revision' : 'director_plan';
        narrationCue = experience!.plan; narrationKey = narrationCue!.key;
      } else if (completed && !s.handledNarration.has(reflectionKey)) {
        presentationRole = 'director_reflection'; narrationKey = reflectionKey;
      } else if (builderMode || !importantBattleChange) {
        if (stage && !s.introducedStages.has(stage.key) && !s.handledNarration.has(stage.key + ':intro')) {
          presentationRole = 'director_intro'; narrationCue = introductionCue(experience?.currentDesign);
        } else if (!completed && lateDesign && lateFacts.length && unseen(lateDesign)) {
          // Late evidence supplements only the new detail; it cannot reopen the
          // same operation's complete introduction under another cue hash.
          presentationRole = 'director_review'; narrationCue = { ...lateDesign, facts: lateFacts };
        } else if (unseen(experience?.plan)) {
          presentationRole = s.lastPlan?.stage === narrationStage ? 'director_revision' : 'director_plan';
          narrationCue = experience!.plan;
        } else if (unseen(experience?.review)) {
          presentationRole = 'director_review'; narrationCue = experience!.review;
        } else if (unseen(experience?.observation)) {
          presentationRole = 'director_review'; narrationCue = experience!.observation;
        }
        narrationKey = narrationCue?.key ?? (presentationRole === 'director_intro' && stage ? stage.key + ':intro' : undefined);
      }
      const narrative = presentationRole !== 'battle_commentary';
      if (options.continuous && builderMode && !narrative) {
        // Leave ordinary movement, repeated shots and periodic roundups silent.
        // Only recent major outcomes can briefly interrupt the builder's story.
        const significant = [...macro.facts, ...s.pending.filter(f => current.world.time - f.time <= 10)]
          .some(f => f.urgent || /血量实际降至零|完成迫击炮接管|营救成功|完成营救|成功救出|推进失败|任务失败/u.test(f.text));
        const terminal = !!current.world.winner || ['completed', 'failed'].includes(current.world.world_growth?.mission?.status);
        const scope = stage?.key ?? broadcastKey(current);
        const battleQuotaUsed = s.battleStage === scope && (s.battleStageCount ?? 0) >= 2;
        if (!significant || (!terminal && (battleQuotaUsed || now() - (s.lastBattlePlayedAt ?? -Infinity) < 30000))) return result(s, 'quiet');
      }
      // Returning A -> B -> A is a real revision. Older wording for A can be
      // useful again; only the immediately preceding line is redundant here.
      const duplicateTexts = narrationCue?.kind === 'plan' ? s.lastTexts.slice(-1) : s.lastTexts;
      if (options.continuous && !macro.changed && !notablePending && !heartbeat && !narrative) return result(s, 'quiet');
      const changes = options.continuous ? [...macro.facts.filter(f => f.urgent || f.id.startsWith('pressure-')), ...s.pending.filter(f => !f.routine)] : allChanges;
      const recent = s.previous?.world.run_id === current.world.run_id && s.previous?.world.world_growth?.revision === current.world.world_growth?.revision ? s.recent : [];
      const recordedHistory = s.history.snapshot(current.world.time);
      const history = { ...recordedHistory, timeline: scheduledIntro ? [] : recordedHistory.timeline.filter(f => !f.routine || !/换了位置/.test(f.text)) };
      const facts = options.continuous ? [...macro.facts, ...s.pending.filter(f => !f.routine || !/换了位置/.test(f.text))] : [...changes, ...spectatorEquipmentFacts(current, s.previous).facts];
      // Design, planned experience and actual outcomes keep separate evidence IDs.
      // Current HP/count roundups are not an explanation of design intent.
      if (presentationRole === 'director_intro') facts.splice(0, facts.length, ...(stage?.facts ?? []));
      if (narrationCue) facts.push(...narrationCue.facts);
      const previousPlan = presentationRole === 'director_revision' ? s.lastPlan?.cue : undefined;
      if (previousPlan) facts.push(...previousPlan.facts.map(f => ({ ...f, id: 'previous-' + f.id })));
      if (presentationRole === 'director_reflection' || presentationRole === 'director_review') {
        if (narrationCue?.kind !== 'intro') facts.push(...(experience?.currentDesign?.facts ?? []));
        if (presentationRole === 'director_reflection') facts.push(...(experience?.review?.facts ?? []));
        if (narrationCue?.kind !== 'observation') facts.push(...(experience?.observation?.facts ?? []));
      }
      const evidence = [...facts, ...history.completed_stages, ...history.timeline];
      const urgent = facts.some(f => f.urgent), key = narrative ? narrationScopeKey(current) : options.continuous ? broadcastKey(current) : battleKey(current);
      // Silence is measured from confirmed native playback completion in real
      // time, not from request start or accelerated game time. Keep new facts
      // queued while the audience gets a pause.
      if (!scheduledIntro && options.continuous && s.playbackEndedAt !== undefined
        && now() - s.playbackEndedAt < (narrative ? 4000 : builderMode ? 12000 : urgent ? 5000 : 12000)) return result(s, 'quiet');
      if (!scheduledIntro && now() - s.lastAttempt < (options.continuous ? urgent ? 1000 : narrative ? 4000 : 8000 : urgent ? 4000 : 12000)) return result(s, 'quiet');
      s.recent = [...recent, ...changes.map(f => ({ time: current.world.time, text: f.text }))].filter(f => current.world.time - f.time <= 30).slice(-10);
      s.previous = structuredClone(current);
      if (!facts.length) return result(s, 'quiet');
      const controller = new AbortController(); s.busy = controller; s.lastAttempt = now();
      const fallbackOnly = !!scheduledIntro && (s.attempts >= limit || now() >= scheduledIntro.dueAt - 3000);
      if (!fallbackOnly) s.attempts++;
      options.record?.(id, { type: 'commentary-request', observedAt: current.world.time, facts, request: s.attempts,
        presentation_role: presentationRole, ...(stage ? { stage_key: stage.key } : {}),
        ...(narrationCue ? { narration_key: narrationKey, provenance: narrationCue.provenance } : {}),
        battle_history: history, trigger: narrative ? presentationRole : urgent ? 'important_event' : heartbeat ? 'continuity_review' : 'battle_change',
        ...(story ? { narrative_reference: story } : {}) });
      s.entry = undefined; s.audio = undefined;
      const started = now();
      // A stable plan is not eight-second battle news. Still bound preparation
      // time and cancel immediately when its semantic version is replaced.
      const lifetime = scheduledIntro ? Math.max(25000, scheduledIntro.dueAt - started + 25000) : narrative ? 25000 : options.continuous ? 8000 : 12000;
      const stale = () => {
        const fresh = options.read(id);
        return controller.signal.aborted || !fresh || !usable(fresh) || (narrative ? narrationScopeKey(fresh) : options.continuous ? broadcastKey(fresh) : battleKey(fresh)) !== key
          || fresh.world.time < current.world.time || (!narrative && fresh.world.time - current.world.time > (options.continuous ? 8 : 18)) || now() - started > lifetime
          || (!!scheduledIntro && fresh.presenterStage?.key !== stage!.key)
          || (!!narrationCue && ![fresh.presenterExperience?.currentDesign, fresh.presenterExperience?.plan, fresh.presenterExperience?.review, fresh.presenterExperience?.observation].some(cue => cue?.key === narrationCue!.key));
      };
      // Cancellation is also enforced while providers are in flight, independently of the browser.
      const watcher = setInterval(() => { if (stale()) controller.abort(); }, 200);
      try {
        let emotion = 'neutral', expression = ''; 
        let text = '', source: CommentaryEntry['source'] = 'model', model: string | undefined, warning: string | undefined;
        let narratedObservationKey: string | undefined;
        let validation = 'provider', proposal: Row | undefined;
        try {
          if (fallbackOnly) throw new Error('intro-preparation-deadline');
          const response = await createRequestManager(options.backend(), { timeoutMs: scheduledIntro
            ? Math.max(250, Math.min(4500, scheduledIntro.dueAt - now() - 4000)) : narrative ? 6500 : options.continuous ? 3000 : 6500 }).request(
            { facts, battle_history: history, changed: changes.length > 0, previous_commentary: s.lastTexts, recent_sequence: s.recent,
              presentation_role: presentationRole,
              ...(presentationRole === 'director_intro' ? { evidence_contract: {
                required_any: [...facts.filter(f => f.id.startsWith('director-')).map(f => f.id), ...(narrationCue?.facts.map(f => f.id) ?? [])],
                required_reason_any: introReasons.map(f => f.id),
                required_built_any: introBuiltIds,
                reason_status: introReasons.length ? 'bound_to_this_built_operation' : 'unavailable',
                note: '选一项实际建成的安排，再顺口带一句为什么这样安排：有required_reason_any时，必须引用其中一条并表达相应目的，用想让、试试或为了等自然说法，不必固定因为。提到步枪、冲锋枪、火箭、坦克、炮或增援时，必须同时引用director-composition、director-reinforcements或director-deployed-support等实际部署事实；原因里提过某兵种不证明它已经出现，也不要顺口说未部署的对比选项。原因仅限本关冻结采用的设计目的；不从人数猜他们太强了，不借历史h*、原想法或最新后续计划编造原因。没有原因记录就不补造，也不增加分析请求。部署人数不是现在存活人数。预约介绍约10秒后播出，不说准备时的实时动作或人质仍待救援。',
              } } : {}),
              ...(narrative ? { built_arrangements: stage?.arrangements ? { coordinate_frame: 'stage_local_xz',
                operation_id: stage.arrangements.current.operationId, previous_operation_id: stage.arrangements.previous?.operationId,
                changes: stage.arrangements.changes, visible_facts: stage.arrangements.facts } : undefined,
                director_context: { current_design: narrationCue?.kind === 'intro' && presentationRole === 'director_review' ? undefined
                  : presentationRole === 'director_intro' ? introductionCue(experience?.currentDesign) : experience?.currentDesign,
                selected: narrationCue, previous_plan: previousPlan ? { ...previousPlan, facts: previousPlan.facts.map(f => ({ ...f, id: 'previous-' + f.id })) } : undefined,
                review: presentationRole === 'director_reflection' ? experience?.review : undefined } } : {}),
              priority: scheduledIntro ? [] : changes,
              focus: commentaryFocus(presentationRole, narrationCue?.kind),
              viewpoint: '安妮是这张桌面世界的搭建者，每关都是她搭的。主要用第一人称讲真实的建造安排、后续打算和设计反馈，偶尔简短回应关键战况。已记录的生成意图以你的打算来表达，真实建成内容以你的布置来表达；士兵自主行动。', ...(story ? { narrative_reference: story } : {}) },
            { commentary: { type: 'json', maxOutputTokens: narrative ? 360 : 180, systemInstructions: TOY_DIRECTOR_PERSONA + '像在桌边玩玩具的小朋友，以第一人称指给朋友看自己真实搭好的东西，讲一件小主意；不朗读设计报告。本次只生成台词，不另发关卡或士兵命令。未建成的说准备，已建成的说我搭了，不编没有记录的因果或结果。仅返回JSON。' + (story ? SPECTATOR_STORY_INSTRUCTIONS : ''), instructions:
              commentaryInstructions(!!options.continuous, presentationRole) } },
            { signal: controller.signal });
          const answer = response.answers.commentary;
          if (answer?.type !== 'json') throw new Error('invalid-commentary');
          const value = answer.value;
          proposal = { text: typeof value.text === 'string' ? value.text.slice(0, 500) : undefined,
            evidence_ids: Array.isArray(value.evidence_ids) ? value.evidence_ids.filter(v => typeof v === 'string').slice(0, 24) : undefined };
          validation = 'format_and_evidence_ids';
          if (value.text === '' && Array.isArray(value.evidence_ids) && !value.evidence_ids.length) {
            // A reserved new-stage explanation cannot be consumed as a routine
            // silent review. Reuse the existing one-shot factual fallback.
            if (scheduledIntro && stage) throw new Error('invalid-commentary');
            if (stale()) return result(s, 'stale');
            handleNarration(s, narrationKey, narrationCue);
            if (narrationCue?.kind === 'plan' && experience?.observation) handleNarration(s, experience.observation.key);
            if (presentationRole === 'director_intro') handleIntroduction(s, stage, narrationCue);
            else handleSupplement(s, stage, narrationCue);
            s.pending = s.pending.filter(e => e.time > current.world.time);
            options.record?.(id, { type: 'commentary-model-silence', observedAt: current.world.time });
            return result(s, 'quiet');
          }
          if (typeof value.text !== 'string' || value.text.length < 4 || value.text.length > (narrative ? MAX_DIRECTOR_TEXT_LENGTH : 75)
            || /[<>\n]/.test(value.text) || !Array.isArray(value.evidence_ids) || !value.evidence_ids.length
            || value.evidence_ids.some(id => !evidence.some(f => f.id === id))) throw new Error('invalid-commentary');
          text = value.text.replace(/[\p{Extended_Pictographic}\uFE0F\u200D]/gu, '').trim();
          const evidenceIds = value.evidence_ids;
          const cited = evidence.filter(f => evidenceIds.includes(f.id));
          if (experience?.observation && cited.some(f => /^experience-(?:plan|observation)-(?:observation|judgment)$/u.test(f.id))) {
            narratedObservationKey = experience.observation.key;
          }
          validation = 'design_and_fact_grounding';
          if (presentationRole === 'director_intro' && !introductionReasonIncluded(text, cited, introReasons)) throw new Error('invalid-commentary');
          if (presentationRole === 'director_intro' && introReasons.length && !cited.some(f => introBuiltIds.includes(f.id))) throw new Error('invalid-commentary');
          if (presentationRole === 'director_intro' && introReasons.length && !introductionForcesIncluded(text, cited)) throw new Error('invalid-commentary');
          if (scheduledIntro && introductionClaimsLiveState(text)) throw new Error('invalid-commentary');
          if (!directorIntentGrounded(text, cited)) throw new Error('invalid-commentary');
          if (presentationRole === 'director_intro' && !narrationCue && !directorIntroductionGrounded(text, cited)) throw new Error('invalid-commentary');
          if (narrationCue ? !directorNarrationGrounded(text, narrationCue, cited) : !spectatorTextGrounded(text, current, cited)) throw new Error('invalid-commentary');
          if (typeof value.emotion === 'string') emotion = value.emotion;
          if (typeof value.expression === 'string') expression = value.expression;
          validation = 'repetition';
          if (options.continuous && ((!narrative && /不等于|不代表|未确认|未据此|挪步|挪动|位移|体量|动作量|节奏拉满|拉扯感|局面仍在持续|换弹|弹药|[一二三四五六七八九0-9]+号|谁先|值得关注|值得留意|接下来.*看看|最近.*没.*开火/.test(text)) || commentaryTooSimilar(text, duplicateTexts))) throw new Error('repetitive-commentary');
          model = response.resolvedModel ?? response.requestedModel;
          options.record?.(id, { type: 'commentary-model-response', observedAt: current.world.time, model, text, emotion, evidence_ids: value.evidence_ids });
        } catch (error) {
          if (stale()) return result(s, 'stale');
          const reason = error instanceof Error && ['invalid-commentary', 'repetitive-commentary', 'request-timeout', 'request-cancelled', 'request-aborted'].includes(error.message)
            ? error.message : error instanceof Error ? error.name : 'provider-error';
          options.record?.(id, { type: 'commentary-model-failed', observedAt: current.world.time, reason, validation,
            ...(proposal ? { proposal } : {}), elapsedMs: now() - started });
          if (!scheduledIntro || !stage) {
            s.retryAt = now() + 3000;
            return result(s, 'model-unavailable');
          }
          // One failed introduction must not become a minute of silent retries.
          // Reuse a short matching purpose only when its completed-operation
          // binding is present; a fallback cannot invent a missing motive.
          text = nativeIntroduction(stage, duplicateTexts); source = 'facts-fallback'; model = undefined;
          warning = '关卡介绍使用原生已确认事实'; emotion = 'neutral'; expression = '';
          // Retain the bound cue key: model and fallback consume one operation.
          narrationKey ??= stage.key + ':intro';
          facts.splice(0, facts.length, ...stage.facts);
          if (!text) {
            handleIntroduction(s, stage, narrationCue);
            options.record?.(id, { type: 'commentary-intro-silence', stage_key: stage.key, reason: 'no-new-built-facts' });
            return result(s, 'quiet');
          }
          if (!directorIntroductionGrounded(text, facts) || !spectatorTextGrounded(text, current, facts)
            || introReasons.length && !introductionForcesIncluded(text, facts)) return result(s, 'model-unavailable');
          options.record?.(id, { type: 'commentary-intro-fallback', stage_key: stage.key, reason, dueAt: scheduledIntro.dueAt });
        }
        if (stale()) return result(s, 'stale');
        if (commentaryTooSimilar(text, duplicateTexts)) {
          handleNarration(s, narrationKey, narrationCue);
          if (presentationRole === 'director_intro') handleIntroduction(s, stage, narrationCue);
          else handleSupplement(s, stage, narrationCue);
          return result(s, 'quiet');
        }
        const entry: CommentaryEntry = { id: randomUUID(), text, subtitle: commentarySubtitle(text, emotion, expression), facts, observedAt: current.world.time, observedWallTime: started,
          presentationRole, ...(stage ? { stageKey: stage.key } : {}),
          ...(narrationKey ? { narrationKey, narrationStage } : {}), ...(narrationCue ? { narrationCue } : {}),
          ...(narratedObservationKey ? { narratedObservationKey } : {}),
          ...(scheduledIntro ? { scheduledAt: scheduledIntro.dueAt } : {}),
          createdAt: now(), expiresAt: started + lifetime, key, urgent, source, model, warning, emotion,
          audioReady: false, modelMs: now() - started };
        const modelMs = entry.modelMs;
        try {
          if (s.speechRequests >= limit) throw new Error('speech-budget');
          s.speechRequests++;
          const speech = scheduledIntro
            ? await introSpeech(signal => options.speech(text, signal, { emotion }), controller.signal, Math.max(0, scheduledIntro.dueAt - now() - 1000))
            : await options.speech(text, controller.signal, { emotion });
          if (stale()) return result(s, 'stale');
          s.audio = speech.audio; entry.audioReady = true; entry.speechMs = speech.totalMs; entry.firstAudioMs = speech.firstAudioMs;
        } catch { entry.warning = [entry.warning, '语音暂不可用，本条仅显示字幕'].filter(Boolean).join('；'); }
        if (stale()) { s.audio = undefined; return result(s, 'stale'); }
        entry.createdAt = now(); s.entry = entry;
        s.retryAt = undefined;
        s.pending = s.pending.filter(e => e.time > current.world.time);
        if (!options.continuous) this.markPlayed(id, entry);
        options.record?.(id, { type: 'commentary', ...entry, modelMs, requests: s.attempts, speechRequests: s.speechRequests });
        return result(s, 'ready', entry);
      } finally { clearInterval(watcher); s.busy = undefined; }
    },
  };
}

/** Spectator expression only; speech always receives the plain text. */
const commentaryFaces = new Set(Array.from('😮😲😳🤯😰😨😬🫣🤩😆😃🥳😄😟😥😢😩🤔🧐😕😅😓🫠🙃😌🙂😎😏😁').concat('😮‍💨'));

export function commentarySubtitle(text: string, emotion: string, expression = ''): string {
  const selected = [...new Set(expression.trim().split(/\s+/u).filter(face => commentaryFaces.has(face)))].slice(0, 2);
  if (!selected.length) selected.push(({ confused: '🤔', awkward: '😅', impressed: '😎', surprised: '😮', tense: '😰', happy: '😄', sad: '😟', relieved: '😌' } as Record<string, string>)[emotion] ?? '🙂');
  let index = 0;
  const subtitle = text.replace(/[，。！？；]/gu, mark => index < selected.length ? ' ' + selected[index++] + mark : mark);
  return index < selected.length ? subtitle + ' ' + selected.slice(index).join(' ') : subtitle;
}
