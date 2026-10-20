/** Game-specific facts, never pretend these are portable generic observations. */
import type { Context, ControlLease, Fields } from './contracts.js';
import { GameClient } from './client.js';
import { HttpTransport, type GameTransport } from './transport.js';

export type DeskfrontTeam = 'green' | 'red';
export const DESKFRONT_FORCES_EXTENSION = 'deskfront-forces/v1' as const;
export interface DeskfrontForceSlot {
  slot_id: string; kind: 'infantry' | 'tank'; weapon?: 'rifle' | 'smg' | 'rocket';
}
/** Exact slots, including crew. No engine-side hidden additions are authorized. */
export interface DeskfrontForceManifest {
  schema: typeof DESKFRONT_FORCES_EXTENSION;
  enemies: DeskfrontForceSlot[]; reinforcements: DeskfrontForceSlot[]; captives?: DeskfrontForceSlot[];
  /** Crews are explicit infantry slots: all enemies => red, all reinforcements => green.
   * A mixed-side crew is invalid. Equipment adds no implicit soldiers. */
  equipment: { slot_id: string; kind: 'mortar'; crew_slot_ids: string[] }[];
}
export interface DeskfrontSnapshot { context: Context; perspective: DeskfrontTeam | 'spectator'; state: Fields }
export interface DeskfrontCommand {
  id: string; context: Context; teamId: DeskfrontTeam; leaseId: string; controlEpoch: number;
  command: Fields & { action: 'squad_order' | 'soldier_order' | 'unit_emotion' | 'grow_world' | 'preview_world' | 'pause' | 'sidebar' };
}
export interface NativeAcknowledgement { id: string; accepted: boolean; message: string; tick: number }
export class DeskfrontClient {
  readonly game: GameClient;
  constructor(private readonly transport: GameTransport) { this.game = new GameClient(transport); }
  static http(url: string): DeskfrontClient { return new DeskfrontClient(new HttpTransport(url)); }
  observe(team: DeskfrontTeam = 'green', signal?: AbortSignal): Promise<DeskfrontSnapshot> {
    return this.transport.request('GET', `/v1/deskfront/state?team=${team}`, undefined, signal);
  }
  spectate(signal?: AbortSignal): Promise<DeskfrontSnapshot> {
    return this.transport.request('GET', '/v1/deskfront/spectator', undefined, signal);
  }
  acquire(context: Context, team: DeskfrontTeam, ownerId: string, worldControl = false): Promise<ControlLease> {
    return this.transport.request('POST', '/v1/control/acquire', { id: crypto.randomUUID(), context,
      teamId: team, ownerId, scope: { kind: 'team', id: team }, leaseSeconds: 30, worldControl });
  }
  renew(context: Context, team: DeskfrontTeam, lease: ControlLease): Promise<ControlLease> {
    return this.transport.request('POST', '/v1/control/renew', { context, teamId: team,
      leaseId: lease.leaseId, epoch: lease.epoch, leaseSeconds: 30 });
  }
  release(context: Context, team: DeskfrontTeam, lease: ControlLease): Promise<ControlLease> {
    return this.transport.request('POST', '/v1/control/release', { context, teamId: team,
      leaseId: lease.leaseId, epoch: lease.epoch });
  }
  async submit(command: DeskfrontCommand, signal?: AbortSignal): Promise<NativeAcknowledgement> {
    if (command.command.action === 'grow_world' && command.command.force_manifest !== undefined) {
      const info = await this.game.getInfo(signal);
      if (!info.extensions?.includes(DESKFRONT_FORCES_EXTENSION)) {
        const snapshot = await this.observe(command.teamId, signal);
        const state = snapshot.state as any, cap = state?.world_growth?.force_manifest_capability;
        if (snapshot.context?.instanceId !== command.context.instanceId
          || cap?.schema !== DESKFRONT_FORCES_EXTENSION || cap.deployment_receipt !== 'deskfront-force-receipt/v1'
          || !Number.isSafeInteger(cap.max_entities) || cap.max_entities < 1) throw new Error('force_manifest_upgrade_required');
      }
    }
    return this.transport.request('POST', '/v1/deskfront/commands', command, signal);
  }
  candidates(context: Context, team: DeskfrontTeam, actorId: string, proposals: Fields[], id = crypto.randomUUID()): Promise<Fields> {
    return this.transport.request('POST', '/v1/query', { id, context, teamId: team,
      kind: 'soldier_candidates', actorIds: [actorId], parameters: { proposals } });
  }
  getCandidates(id: string, team: DeskfrontTeam): Promise<Fields> {
    return this.transport.request('GET', `/v1/deskfront/queries/${encodeURIComponent(id)}?team=${team}`);
  }
  topology(context: Context, team: DeskfrontTeam, actorId: string): Promise<Fields> {
    return this.transport.request('POST', '/v1/query', { id: crypto.randomUUID(), context, teamId: team,
      kind: 'topology', actorIds: [actorId], parameters: {} });
  }
}
