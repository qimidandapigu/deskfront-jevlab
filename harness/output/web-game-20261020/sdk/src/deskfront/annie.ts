/** Open Annie is a spectator. It cannot issue combat commands or invent speech. */
import { readFileSync } from 'node:fs';
import { createRequestManager } from '../systemone/request.js';
import type { SystemOne, Question } from '../systemone/types.js';
import type { CommentaryEntry } from './commentary.js';
import type { NativeStatus } from './commentary-director.js';
import { TOY_DIRECTOR_PERSONA } from './spectator-voice.js';

const catalog = JSON.parse(readFileSync(new URL('./annie-assets/catalog.json', import.meta.url), 'utf8')) as {
  faces: Record<string, string>; clips: Record<string, string>;
};
export interface AnnieBroadcast {
  enabled: boolean; status: string; entry?: CommentaryEntry; playback?: NativeStatus;
}
export interface AnnieDecision { entryId: string; face: string; clip: string; accent: string; energy: string; source: 'jev'; latencyMs: number }
interface HostState {
  enabled: boolean; seen: number; serial: number; requests: number; entryId?: string;
  decision?: AnnieDecision; status: string; busy?: AbortController;
  lingerUntil?: number; lastEntry?: CommentaryEntry; lastPlayback?: NativeStatus; runId?: string; recentClips?: string[];
}
function hasPlacement(status?: NativeStatus): status is NativeStatus {
  const rect = status?.subtitle_rect, viewport = status?.viewport_size;
  return !!(status?.ready && Array.isArray(rect) && rect.length === 4 && Array.isArray(viewport) && viewport.length === 2
    && [...rect, ...viewport].every(Number.isFinite)
    && viewport[0] > 0 && viewport[1] > 0 && rect[2] > 0 && rect[3] > 0
    && rect[0] >= 0 && rect[1] >= 0 && rect[0] < viewport[0] && rect[1] < viewport[1]);
}
export function annieQuestions(): Record<string, Question> {
  return {
    face: { type: 'choice', criteria: { ...catalog.faces,
      neutral: '安静认真地看自己的玩具', curious: '注意到新东西，想看看会怎样', thinking: '正在想一个小主意，不是讲解专业原理',
      proud: '自己的真实安排有了进展，忍不住小得意', happy: '朴素的开心，愿意和朋友分享', playful: '玩玩具时的小淘气，不逗伤亡或嘲讽小兵',
      surprised: '突然注意到真实新变化，眼睛一亮', concerned: '担心小兵，认真看，不始终愁眉苦脸', sad: '真实损失或期待落空后的失落', relieved: '实际危险过去，松了一口气',
    }, instructions: TOY_DIRECTOR_PERSONA + '表情跟随spoken_text里这一个念头和真实结果。好奇不等于总托腮，小得意不等于成人自信营业；没有开心的内容不强选笑脸。' },
    clip: { type: 'choice', criteria: { ...catalog.clips,
      none: '普通说一句小想法或关心小兵；小幅自然手势就够了，不额外演一个动作',
      point_self: '台词确实在认领我摆的东西时，短短指自己；不是每个我字都需要',
      think: '真的在犹豫或琢磨一个新主意时短暂托腮，不用于专业讲解',
      shrug: '确实没想明白时小小摊手，不是例行无奈吐槽',
      laugh: '玩具故事里有真实好笑的事才笑，不笑伤亡',
      clap: '真的成功了，轻轻拍手，不给自己的普通介绍鼓掌',
      excited_bounce: '确实特别开心的成功才蹦一下，不持续跳、不因战况激烈就兴奋',
      sad_slump: '重大损失或明确落空才短暂失落，普通担心不用垮下去',
      surprised_recoil: '突然发生意外才轻轻一惊', wave: '真正打招呼或告别才挥手', bow: '确实道谢或道歉才短暂鞠躬',
    }, instructions: '按这句小朋友的心思选一个开口动作。普通表达可选none，由小幅说话动作承接。结合recent_clips避免连续托腮、耸肩或拍手；不要为了可爱强加动作。只用已安装动作，不控制小兵。' },
    accent: { type: 'choice', criteria: { none: '这句只有一个念头，或很短；不加第二个动作', shrug: '后半句真的转为没想明白', laugh: '后半句有真实好笑的转折', clap: '后半句才得知真实成功', surprised_recoil: '后半句突然意外', excited_bounce: '后半句才出现特别开心的真实成功' }, instructions: '只有台词后半有不同的情绪转折才选第二个动作；通常选none。不能重复开头动作，也不靠多动表现小朋友。' },
    energy: { type: 'choice', criteria: { gentle: '安静观察、担心小兵或失落，轻轻说', moderate: '平常玩玩具，认真、好奇、轻快', high: '短暂的真惊讶或确认成功后的高兴，不全程亢奋' }, instructions: '按这句话的情绪选动作活力，不按战斗压力数值选。小朋友也有安静的时候，不用成人主播式连续大手势。' },
  };
}
export function parseAnnieDecision(answers: Record<string, any>, entryId: string, latencyMs: number): AnnieDecision {
  const face = answers.face?.choice, clip = answers.clip?.choice, energy = answers.energy?.choice;
  const accent = answers.accent?.choice ?? 'none';
  if (!(face in catalog.faces) || !(clip === 'none' || clip in catalog.clips) || !['gentle', 'moderate', 'high'].includes(energy)) throw Error('invalid-presenter-choice');
  // Parameters are checked against installed assets; probability never suppresses a valid selection.
  if (!['none','shrug','laugh','clap','surprised_recoil','excited_bounce'].includes(accent)) throw Error('invalid-presenter-accent');
  return { entryId, face, clip, accent, energy, source: 'jev', latencyMs };
}
export function createAnnieHost(options: {
  read(id: string): AnnieBroadcast; backend(): SystemOne; now?: () => number;
  record?(id: string, event: unknown): void; limit?: number; autoTick?: boolean;
  presentation?(id: string, enabled: boolean): void;
}) {
  const states = new Map<string, HostState>(), now = options.now ?? Date.now, limit = options.limit ?? 40;
  function get(id: string) {
    let s = states.get(id);
    if (!s) { s = { enabled: false, seen: now(), serial: 0, requests: 0, status: 'off' }; states.set(id, s); }
    return s;
  }
  function setEnabled(id: string, enabled: boolean) {
    const s = get(id); s.seen = now();
    if (s.enabled !== enabled) { s.serial++; s.busy?.abort(); s.busy = undefined; s.decision = undefined; s.entryId = undefined; }
    s.enabled = enabled; s.status = enabled ? 'watching' : 'off';options.presentation?.(id,enabled);
    if (!enabled) { s.lingerUntil = 0; s.lastEntry = undefined; s.lastPlayback = undefined; s.runId = undefined; }
    return snapshot(id);
  }
  function snapshot(id: string) {
    const s = get(id); s.seen = now(); const broadcast = options.read(id);
    const allowed = broadcast.enabled && !['off','ended','paused','service-error','native-delivery-failed','waiting-native'].includes(broadcast.status);
    const runId = broadcast.playback?.run_id;
    if (!s.enabled || !allowed || (runId !== undefined && s.runId !== undefined && runId !== s.runId)) {
      s.lingerUntil = 0; s.lastEntry = undefined; s.lastPlayback = undefined;
    }
    if (runId !== undefined) s.runId = runId;
    const live = allowed && broadcast.playback?.phase === 'playing' && broadcast.entry?.id === broadcast.playback.id;
    const cue = allowed && ['cueing','starting'].includes(broadcast.status) && !!broadcast.entry;
    const active = !!(live && broadcast.playback?.subtitle_visible);
    // Native idle receipts already contain the caption anchor. Use that before
    // speech starts, instead of showing at a fallback then jumping on playback.
    const placement = s.enabled && allowed && hasPlacement(broadcast.playback) ? broadcast.playback : undefined;
    if (s.enabled && (active || cue)) {
      s.lingerUntil = now() + 2000; s.lastEntry = broadcast.entry;
      s.lastPlayback = placement ? { ...placement, subtitle_rect: [...placement.subtitle_rect!], viewport_size: [...placement.viewport_size!] } : undefined;
    }
    const outro = s.enabled && allowed && !cue && !active && now() < (s.lingerUntil ?? 0);
    if (!cue && !active && !outro) { s.lastEntry = undefined; s.lastPlayback = undefined; }
    const entry = live || cue ? broadcast.entry : outro ? s.lastEntry : undefined;
    return { enabled: s.enabled, status: s.status, requests: s.requests, limit,
      visible: !!(s.enabled && (active || cue || outro)), phase: cue ? 'intro' : active ? 'speaking' : outro ? 'outro' : 'hidden',
      speaking: !!(s.enabled && live && broadcast.playback?.audio_playing),
      entry: s.enabled && entry ? { id: entry.id, text: entry.text, observedAt: entry.observedAt } : undefined,
      playback: s.enabled && live ? broadcast.playback : undefined,
      // Only the brief outro may retain a same-run receipt. Never carry an old
      // sentence's geometry into a new cue or across a pause/disable/run change.
      placement: placement ?? (outro && s.lastPlayback?.run_id === s.runId ? s.lastPlayback : undefined),
      decision: s.enabled && entry?.id === s.decision?.entryId ? s.decision : undefined };
  }
  async function step(id: string) {
    const s = get(id), broadcast = options.read(id);
    if (!s.enabled || now() - s.seen > 8000) { s.busy?.abort();options.presentation?.(id,false); return; }
    options.presentation?.(id,true);
    const entry = broadcast.entry;
    if (!broadcast.enabled || !entry || !['cueing','starting', 'playing'].includes(broadcast.status)) { s.busy?.abort(); return; }
    if (entry.id === s.entryId) return;
    s.busy?.abort(); s.busy = undefined;
    if(s.decision) s.recentClips = [...(s.recentClips ?? []),s.decision.clip].slice(-3);
    s.entryId = entry.id; s.decision = undefined;
    const serial = ++s.serial;
    if (s.requests >= limit) { s.status = 'budget'; return; }
    const controller = new AbortController(); s.busy = controller; s.status = 'deciding'; s.requests++;
    const started = now();
    const state = { role: 'toy-table-child-director-commentator', presentation_role: entry.presentationRole ?? 'battle_commentary', spoken_text: entry.text, speech_emotion: entry.emotion,
      facts: entry.facts.slice(0, 6).map(f => f.text), observed_game_time: entry.observedAt, recent_clips: s.recentClips ?? [],
      instructions: '只选择安妮这个桌边小朋友的表情和动作；这些事实不授权控制士兵。不要另写解说。' };
    options.record?.(id, { type: 'annie-request', entryId: entry.id, state, request: s.requests });
    try {
      const manager = createRequestManager(options.backend(), { timeoutMs: 1800 });
      const result = await manager.request(state, annieQuestions(), { signal: controller.signal });
      if (!s.enabled || serial !== s.serial || now() - s.seen > 8000 || options.read(id).entry?.id !== entry.id) return;
      s.decision = parseAnnieDecision(result.answers, entry.id, now() - started); s.status = 'ready';
      options.record?.(id, { type: 'annie-decision', ...s.decision, usage: result.usage, requestedModel: result.requestedModel, resolvedModel: result.resolvedModel });
    } catch {
      if (serial === s.serial && s.enabled) { s.status = 'model-unavailable'; options.record?.(id, { type: 'annie-unavailable', entryId: entry.id }); }
      // Retain procedural idle/talk motion. Do not fabricate a JEV expression or retry every frame.
    } finally { if (serial === s.serial) s.busy = undefined; }
  }
  const timer = options.autoTick === false ? undefined : setInterval(() => { for (const id of states.keys()) void step(id); }, 250);
  timer?.unref();
  return { snapshot, setEnabled, step, close() { if (timer) clearInterval(timer); for (const s of states.values()) s.busy?.abort(); states.clear(); } };
}
