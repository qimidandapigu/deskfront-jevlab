import { GameClient } from './client.js';
import { HttpTransport } from './transport.js';
export const DESKFRONT_FORCES_EXTENSION = 'deskfront-forces/v1';
export class DeskfrontClient {
    transport;
    game;
    constructor(transport) {
        this.transport = transport;
        this.game = new GameClient(transport);
    }
    static http(url) { return new DeskfrontClient(new HttpTransport(url)); }
    observe(team = 'green', signal) {
        return this.transport.request('GET', `/v1/deskfront/state?team=${team}`, undefined, signal);
    }
    spectate(signal) {
        return this.transport.request('GET', '/v1/deskfront/spectator', undefined, signal);
    }
    acquire(context, team, ownerId, worldControl = false) {
        return this.transport.request('POST', '/v1/control/acquire', { id: crypto.randomUUID(), context,
            teamId: team, ownerId, scope: { kind: 'team', id: team }, leaseSeconds: 30, worldControl });
    }
    renew(context, team, lease) {
        return this.transport.request('POST', '/v1/control/renew', { context, teamId: team,
            leaseId: lease.leaseId, epoch: lease.epoch, leaseSeconds: 30 });
    }
    release(context, team, lease) {
        return this.transport.request('POST', '/v1/control/release', { context, teamId: team,
            leaseId: lease.leaseId, epoch: lease.epoch });
    }
    async submit(command, signal) {
        if (command.command.action === 'grow_world' && command.command.force_manifest !== undefined) {
            const info = await this.game.getInfo(signal);
            if (!info.extensions?.includes(DESKFRONT_FORCES_EXTENSION)) {
                const snapshot = await this.observe(command.teamId, signal);
                const state = snapshot.state, cap = state?.world_growth?.force_manifest_capability;
                if (snapshot.context?.instanceId !== command.context.instanceId
                    || cap?.schema !== DESKFRONT_FORCES_EXTENSION || cap.deployment_receipt !== 'deskfront-force-receipt/v1'
                    || !Number.isSafeInteger(cap.max_entities) || cap.max_entities < 1)
                    throw new Error('force_manifest_upgrade_required');
            }
        }
        return this.transport.request('POST', '/v1/deskfront/commands', command, signal);
    }
    candidates(context, team, actorId, proposals, id = crypto.randomUUID()) {
        return this.transport.request('POST', '/v1/query', { id, context, teamId: team,
            kind: 'soldier_candidates', actorIds: [actorId], parameters: { proposals } });
    }
    getCandidates(id, team) {
        return this.transport.request('GET', `/v1/deskfront/queries/${encodeURIComponent(id)}?team=${team}`);
    }
    topology(context, team, actorId) {
        return this.transport.request('POST', '/v1/query', { id: crypto.randomUUID(), context, teamId: team,
            kind: 'topology', actorIds: [actorId], parameters: {} });
    }
}
