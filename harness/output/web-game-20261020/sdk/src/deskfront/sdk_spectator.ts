/** Existing commentary/danmaku scheduling, with HTTP delivery to released games. */
import type { RuntimeSnapshot } from '../arena/runtime.js';
import type { NativeStatus } from './commentary-director.js';
import { randomUUID } from 'node:crypto';

type Row = Record<string, any>;
interface Options { record?(id: string, event: Row): void }
let lastStreamStartedAt = 0;
export function createSdkSpectator(read: (id: string) => RuntimeSnapshot | undefined, options: Options = {}) {
  const cache = new Map<string, Row>(), busy = new Set<string>(), sessions = new Set<string>();
  const sequences = new Map<string, number>(), receiptCursors = new Map<string, { scope: string; sequence: number }>();
  const deliveryStream = randomUUID();
  const deliveryStreamStartedAt = lastStreamStartedAt = Math.max(Date.now(), lastStreamStartedAt + 1);
  let closed = false;
  function record(id: string, event: Row) { try { options.record?.(id, event); } catch { /* Observation never controls gameplay. */ } }
  function endpoint(id: string) {
    const snapshot = read(id), payload = snapshot?.payload as Row;
    const game = payload?.game ?? payload;
    if (!game?.attached || !game.sdkUrl) return undefined;
    const url = new URL(game.sdkUrl);
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1') return undefined;
    const w = snapshot?.observation as Row;
    if (!w?.run_id) return undefined;
    return { url: url.origin, context: { instanceId: game.engineInstance, runId: w.run_id,
      revision: w.navigation_revision, tick: w.tick, gameTime: w.time }, world: w };
  }
  function same(a: ReturnType<typeof endpoint>, b: ReturnType<typeof endpoint>) {
    return a && b && a.url === b.url && a.context.instanceId === b.context.instanceId && a.context.runId === b.context.runId;
  }
  function receipts(id: string, target: NonNullable<ReturnType<typeof endpoint>>, status: Row) {
    // The native overlay's receipt sequence survives F5; the engine instance does not.
    const scope = JSON.stringify([target.url, target.context.instanceId]);
    const old = receiptCursors.get(id), cursor = old?.scope === scope ? old.sequence : 0;
    const rows = Array.isArray(status.receipts) ? status.receipts.slice(-256) : [];
    const first = rows[0]?.sequence;
    if (cursor > 0 && Number.isSafeInteger(first) && first > cursor + 1)
      record(id, { type: 'danmaku-native-receipt-gap', after_sequence: cursor, first_available_sequence: first, scope: target.context });
    let next = cursor;
    for (const row of rows) {
      if (!Number.isSafeInteger(row?.sequence) || row.sequence <= cursor || !['accepted', 'displayed', 'dropped'].includes(row.status)) continue;
      record(id, { ...row, type: 'danmaku-native-item' }); next = Math.max(next, row.sequence);
    }
    receiptCursors.set(id, { scope, sequence: next });
  }
  async function poll(id: string) {
    const target = endpoint(id);
    if (!target || busy.has(id) || closed) return;
    busy.add(id);
    try {
      const response = await fetch(target.url + '/v1/presentation/status', { signal: AbortSignal.timeout(1500) });
      if (response.ok) {
        const status = await response.json() as Row, fresh = endpoint(id);
        // A GET begun before F5 or reconnect cannot repopulate a new session's cache.
        if (!closed && same(target, fresh) && status.context?.instanceId === target.context.instanceId && status.context?.runId === target.context.runId) {
          cache.set(id, status);
          if (status.danmaku?.session === id) receipts(id, target, status.danmaku);
        }
      } else cache.delete(id);
    } catch { cache.delete(id); } finally { busy.delete(id); }
  }
  function deliver(kind: 'commentary' | 'danmaku', id: string, value: Row, audio?: Buffer) {
    const target = endpoint(id);
    if (!target || closed) return false;
    sessions.add(id);
    const stopping = !value.enabled || value.action === 'stop';
    const sequence = (sequences.get(id) ?? 0) + 1; sequences.set(id, sequence);
    const command = value.id ?? value.command_id ?? value.batch_id ?? randomUUID();
    const wallRemaining = typeof value.expires_at === 'number' ? Math.max(0, (value.expires_at - Date.now()) / 1000) : 20;
    const body = { ...value, id: command, context: { ...target.context,
      ...(kind === 'danmaku' && value.navigation_revision !== undefined ? { revision: value.navigation_revision } : {}) },
      sessionId: id, deliveryStream, deliveryStreamStartedAt, deliverySequence: sequence, action: stopping ? 'stop' : value.action ?? 'play', text: value.text ?? '',
      items: value.items ?? [], expiresAtGameTime: target.context.gameTime + wallRemaining,
      ...(audio ? { audioBase64: audio.toString('base64') } : {}) };
    if (kind === 'danmaku') {
      // Keep the model batch's frozen scope. Never relabel old text as the new stage.
      const g = target.world.world_growth, stale = !stopping && (
        value.run_id !== target.context.runId || value.revision !== (g?.revision ?? 0) ||
        value.stage !== (g?.mission?.index ?? g?.revision ?? 0) ||
        (value.operation_id !== undefined && value.operation_id !== (g?.mission?.operation_id ?? '')) ||
        (value.mission_status !== undefined && value.mission_status !== (g?.mission?.status ?? '')) ||
        (value.navigation_revision !== undefined && value.navigation_revision !== target.context.revision));
      if (stale) {
        record(id, { type: 'danmaku-delivery-rejected', command_id: command, batch_id: value.batch_id ?? command,
          reason: 'sdk_stale_scope', item_ids: body.items.map((item: Row) => item.command_id ?? item.id) });
        return true; // Handled rejection: do not replay it through the legacy file transport.
      }
      record(id, { type: 'danmaku-delivery-submitted', command_id: command, batch_id: value.batch_id ?? command,
        delivery_stream: deliveryStream, delivery_stream_started_at: deliveryStreamStartedAt, delivery_sequence: sequence, scope: body.context, revision: value.revision, stage: value.stage,
        action: body.action, items: body.items });
    }
    // A successful enqueue is not a display receipt. No mutation is retried after timeout.
    void fetch(target.url + '/v1/presentation/' + kind, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body), signal: AbortSignal.timeout(5000) }).then(async response => {
      let reply: Row | undefined; try { reply = await response.json() as Row; } catch { /* Keep the transport outcome visible. */ }
      if (kind === 'danmaku') record(id, { type: 'danmaku-delivery-ack', command_id: command,
        batch_id: value.batch_id ?? command, http_status: response.status, accepted: response.ok,
        ...(reply ? { native: reply } : {}), outcome: response.status === 504 ? 'unconfirmed' : response.ok ? 'engine_acknowledged' : 'rejected' });
      if (!response.ok) cache.delete(id);
      if (!closed) void poll(id);
    }).catch(() => {
      cache.delete(id);
      if (kind === 'danmaku') record(id, { type: 'danmaku-delivery-unconfirmed', command_id: command,
        batch_id: value.batch_id ?? command, reason: 'transport_failure', item_ids: body.items.map((item: Row) => item.command_id ?? item.id) });
    });
    void poll(id);
    return true;
  }
  function playback(id: string, kind: 'commentary' | 'danmaku') {
    const entry = cache.get(id), target = endpoint(id), s = entry?.[kind];
    const currentScope = kind !== 'danmaku' || (s?.navigation_revision === undefined || s.navigation_revision === target?.context.revision) &&
      (s?.revision === undefined || s.revision === (target?.world.world_growth?.revision ?? 0));
    return target && currentScope && entry?.context?.instanceId === target.context.instanceId && entry?.context?.runId === target.context.runId &&
      s?.session === id && s?.run_id === target.context.runId && Number.isFinite(s.updated_at) && Date.now() - s.updated_at >= -3000 && Date.now() - s.updated_at < 3000 ? s : undefined;
  }
  const timer = setInterval(() => { for (const id of sessions) void poll(id); }, 500);
  timer.unref();
  return {
    deliver,
    commentary(id: string): NativeStatus | undefined { return playback(id, 'commentary'); },
    danmaku(id: string) { return playback(id, 'danmaku'); },
    close() { closed = true; clearInterval(timer); sessions.clear(); cache.clear(); sequences.clear(); receiptCursors.clear(); },
  };
}
