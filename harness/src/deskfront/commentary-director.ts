import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import { constructionPresentationActive, narrationScopeKey, createCommentary, type CommentaryEntry, type CommentaryOptions } from './commentary.js';

export interface NativeStatus {
  ready: boolean; session: string; run_id: string; phase: string; id: string; text: string;
  updated_at: number; remaining_ms: number; subtitle_visible: boolean; audio_playing: boolean;
  subtitle_rect?: [number, number, number, number]; viewport_size?: [number, number];
}
interface Prepared { entry: CommentaryEntry; audio?: Buffer; readyAt?: number }
interface Broadcast {
  enabled: boolean; volume: number; status: string; generation: number; busy: boolean;
  key?: string; active?: Prepared & { sentAt: number; acknowledged?: boolean }; pending?: Prepared;
  history: CommentaryEntry[]; requests: number; speechRequests: number; limit: number; playback?: NativeStatus;
  presenter?: boolean;
}
export interface DirectorOptions extends CommentaryOptions {
  directory(id: string): string; autoTick?: boolean;
  deliver?(id: string, value: Record<string, unknown>, audio?: Buffer): boolean;
  playback?(id: string): NativeStatus | undefined;
}

/** Playback-clocked scheduling with quiet passages. Browser visibility is not the broadcast clock. */
export function createCommentaryDirector(options: DirectorOptions) {
  const now = options.now ?? Date.now;
  const core = createCommentary({ ...options, introDelayMs: options.introDelayMs ?? 10000, continuous: true, limit: options.limit ?? 600 });
  const broadcasts = new Map<string, Broadcast>();
  function get(id: string) {
    let s = broadcasts.get(id);
    if (!s) { s = { enabled: false, volume: 1, status: 'off', generation: 0, busy: false,
      history: [], requests: 0, speechRequests: 0, limit: options.limit ?? 600 }; broadcasts.set(id, s); }
    return s;
  }
  function command(id: string, value: Record<string, unknown>, audio?: Buffer) {
    if (options.deliver?.(id, { session: id, command_id: randomUUID(), volume: get(id).volume, ...value }, audio)) return;
    const folder = options.directory(id); mkdirSync(folder, { recursive: true });
    if (audio) {
      writeFileSync(resolve(folder, 'commentary.mp3.tmp'), audio);
      renameSync(resolve(folder, 'commentary.mp3.tmp'), resolve(folder, 'commentary.mp3'));
    }
    const file = resolve(folder, 'commentary-command.json');
    writeFileSync(file + '.tmp', JSON.stringify({ session: id, command_id: randomUUID(), volume: get(id).volume, ...value }));
    renameSync(file + '.tmp', file);
  }
  function clear(id: string, s: Broadcast, enabled: boolean) {
    if (s.active?.acknowledged) core.requeueIntroduction(id, s.active.entry);
    if (s.active?.acknowledged) core.markPlaybackEnded(id);
    s.generation++; core.invalidate(id); s.pending = undefined; s.active = undefined;
    command(id, { enabled, action: 'stop' });
  }
  function nativeStatus(id: string): NativeStatus | undefined {
    if (options.playback) {
      const remote = options.playback(id);
      if (remote) return remote;
    }
    try {
      const status = JSON.parse(readFileSync(resolve(options.directory(id), 'commentary-status.json'), 'utf8')) as NativeStatus;
      if (status.ready && status.session === id && now() - status.updated_at < 3000) return status;
    } catch { /* A new/old engine or a concurrent atomic replacement has no receipt yet. */ }
    return undefined;
  }
  function snapshot(id: string) {
    const s = get(id);
    return { enabled: s.enabled, volume: s.volume, status: s.status, requests: s.requests, speechRequests: s.speechRequests,
      limit: s.limit, entry: s.active?.entry ?? (s.status === 'cueing' ? s.pending?.entry : undefined), history: s.history, playback: s.playback };
  }
  function setEnabled(id: string, enabled: boolean, volume = get(id).volume) {
    const s = get(id); s.volume = Math.max(0, Math.min(1, volume));
    if (enabled === s.enabled) return snapshot(id);
    s.enabled = enabled; clear(id, s, enabled); s.status = enabled ? 'waiting-native' : 'off';
    if (!enabled) core.stop(id);
    return snapshot(id);
  }
  function volume(id: string, value: number) {
    const s = get(id); s.volume = Math.max(0, Math.min(1, value));
    let current: Record<string, unknown> = { enabled: s.enabled, action: 'volume' };
    try { current = JSON.parse(readFileSync(resolve(options.directory(id), 'commentary-command.json'), 'utf8')); } catch {}
    command(id, { ...current, volume: s.volume });
    return snapshot(id);
  }
  async function tickOne(id: string, s: Broadcast) {
    const frame = options.read(id);
    if (frame?.status === 'running' && frame.kind === 'ai') core.observe(id, frame);
    if (!s.enabled) return;
    const receipt = nativeStatus(id); s.playback = receipt;
    if (!frame || frame.status !== 'running' || frame.kind !== 'ai') {
      setEnabled(id, false); s.status = frame?.kind === 'human' ? 'spectator-only' : 'ended'; return;
    }
    if (frame.world.paused) {
      if (s.status !== 'paused') clear(id, s, true);
      s.status = 'paused'; return;
    }
    // Give the construction animation the audience's attention, including
    // previews that arrive while the native phase is still ready.
    if (constructionPresentationActive(frame)) {
      if (s.status !== 'building') clear(id, s, true);
      s.status = 'building'; return;
    }
    if (!receipt || receipt.run_id !== frame.world.run_id) { s.status = 'waiting-native'; return; }
    const key = narrationScopeKey(frame);
    if (s.key && s.key !== key) clear(id, s, true);
    else if (s.active?.entry.presentationRole === 'battle_commentary' && !core.isCurrent(id, s.active.entry)) clear(id, s, true);
    s.key = key;
    if (s.active) {
      if (receipt.id === s.active.entry.id) {
        if (receipt.phase === 'playing') {
          if (!s.active.acknowledged) {
            s.active.acknowledged = true;
            core.markPlayed(id, s.active.entry);
            s.history = [...s.history, s.active.entry].slice(-8);
            options.record?.(id, { type: 'commentary-native-started', id: receipt.id, text: s.active.entry.text,
              at: now(), snapshotToPlaybackMs: now() - s.active.entry.observedWallTime, readyToPlaybackMs: now() - s.active.entry.createdAt,
              presentationRole: s.active.entry.presentationRole, stageKey: s.active.entry.stageKey,
              ...(s.active.entry.scheduledAt !== undefined ? { scheduledAt: s.active.entry.scheduledAt, deadlineOffsetMs: now() - s.active.entry.scheduledAt } : {}),
              subtitleVisible: receipt.subtitle_visible, audioPlaying: receipt.audio_playing,
              playbackMode: receipt.audio_playing ? 'audio-and-subtitle' : 'subtitle-only' });
          }
          s.status = 'playing';
        } else {
          options.record?.(id, { type: 'commentary-native-ended', id: receipt.id, at: now() });
          core.markPlaybackEnded(id);
          s.active = undefined;
        }
      } else if (now() - s.active.sentAt > 4000) {
        setEnabled(id, false); s.status = 'native-delivery-failed'; return;
      }
    }
    // The native overlay polls independently. Do not hand off a nearly
    // expired line and then disable commentary because it never started.
    if (s.pending && (!core.isCurrent(id, s.pending.entry) || now() + 1000 >= s.pending.entry.expiresAt)) {
      options.record?.(id, { type: 'commentary-delivery-skipped', id: s.pending.entry.id, reason: 'stale_or_insufficient_delivery_window' });
      s.pending = undefined; s.status = 'watching';
    }
    if (!s.active && s.pending) {
      if (s.pending.entry.scheduledAt !== undefined && now() < s.pending.entry.scheduledAt) {
        s.status = 'cueing'; return;
      }
      if (s.presenter && now() < (s.pending.readyAt ?? now()) + 900) { s.status = 'cueing'; return; }
      const ready = s.pending; s.pending = undefined;
      command(id, { enabled: true, action: 'play', id: ready.entry.id, text: ready.entry.subtitle ?? ready.entry.text,
        run_id: frame.world.run_id, expires_at: ready.entry.expiresAt, audio: !!ready.audio }, ready.audio);
      s.active = { ...ready, sentAt: now() }; s.status = 'starting';
      options.record?.(id, { type: 'commentary-native-submitted', id: ready.entry.id, at: now() });
    }
    // Gather events during speech, then select the latest unspoken design or
    // battle change. Never overlap audio or queue superseded plan versions.
    if (s.busy || s.pending || s.active) return;
    const generation = s.generation; s.busy = true;
    if (!s.active) s.status = 'preparing';
    try {
      const result = await core.next(id);
      s.requests = result.requests ?? s.requests; s.speechRequests = result.speechRequests ?? s.speechRequests;
      if (!s.enabled || generation !== s.generation) return;
      if (result.status === 'quiet' && !s.active) s.status = 'watching';
      if (result.status === 'model-unavailable') { s.status = 'model-unavailable'; return; }
      if (result.status === 'budget') { s.status = 'budget'; return; }
      if (result.entry) {
        if (!core.isCurrent(id, result.entry)) { s.status = 'watching'; return; }
        if (s.presenter && now() + 1900 >= result.entry.expiresAt) {
          options.record?.(id, { type: 'commentary-delivery-skipped', id: result.entry.id, reason: 'insufficient_presenter_cue_window' });
          s.status = 'watching'; return;
        }
        s.pending = { entry: result.entry, audio: core.audio(id, result.entry.id), readyAt: now() };
        if (s.presenter) s.status = 'cueing';
      }
    } finally { s.busy = false; }
  }
  function tick() {
    for (const [id, s] of broadcasts) void tickOne(id, s).catch(() => {
      s.status = 'service-error'; s.enabled = false; core.stop(id);
      try { command(id, { enabled: false, action: 'stop' }); } catch { /* Surface error without touching gameplay. */ }
    });
  }
  const timer = options.autoTick === false ? undefined : setInterval(tick, 200);
  timer?.unref();
  return { snapshot, setEnabled, volume, tick,
    setPresenter(id: string, enabled: boolean) { get(id).presenter = enabled; },
    audio(id: string, entryId: string) {
      const s = broadcasts.get(id);
      const frame = options.read(id);
      if (frame && constructionPresentationActive(frame)) return undefined;
      return s?.enabled ? s.active?.entry.id === entryId ? s.active.audio : s.status === 'cueing' && s.pending?.entry.id === entryId ? s.pending.audio : undefined : undefined;
    },
    async step(id: string) { await tickOne(id, get(id)); },
    close() { if (timer) clearInterval(timer); for (const [id, s] of broadcasts) { if (s.enabled) setEnabled(id, false); } core.close(); },
  };
}
