import { GameClient } from '../dist/index.js';
import { startReferenceService } from './reference-service.mjs';

const reference = await startReferenceService();
const timer = setInterval(reference.step, 50);
try {
  const game = GameClient.http(reference.url);
  const info = await game.getInfo();
  const before = await game.observe();
  const lease = await game.acquireControl({ id: 'takeover-1', context: before.context, ownerId: 'example-harness', scope: { kind: 'team', id: 'green' }, leaseSeconds: 5 });
  const queued = await game.submitIntent({ id: 'move-1', context: before.context, leaseId: lease.leaseId, controlEpoch: lease.epoch, orderVersion: 1, actorIds: ['actor-1'], intent: { kind: 'move', parameters: { x: .5 } }, expiresAtGameTime: before.context.gameTime + 5 });
  const completed = await game.waitForReceipt(queued.id);
  const after = await game.observe();
  await game.releaseControl({ leaseId: lease.leaseId, context: after.context, epoch: lease.epoch });
  const released = await game.observe();
  console.log(JSON.stringify({ environment: 'protocol-reference-only', protocol: info.protocol, submitted: queued.status, actual: completed.status, position: after.actors[0].position, controllerAfterRelease: released.data.controller }, null, 2));
} finally { clearInterval(timer); await reference.close(); }
