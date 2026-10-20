import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { completedForceDeployment, equipmentFaction, forceManifest } from '../src/deskfront/director-authorship.js';
import { presenterStageContext } from '../src/deskfront/presenter-context.js';
import { publicMortars } from '../src/deskfront/spectator-observation.js';
import { spectatorEquipmentFacts } from '../src/deskfront/spectator-story.js';

const path = process.env.SDK_NATIVE_EVIDENCE ?? new URL('../../../../../output/joint-force-20261018/native-candidate/result.json', import.meta.url);
const native = JSON.parse(readFileSync(path, 'utf8'));

for (const name of ['green1', 'green2', 'red1', 'red2']) {
  test(`actual native ${name} manifest, deployed crew and SDK stage facts agree`, () => {
    const observation = native.observations.find((r: any) => r.case === name);
    const { input_manifest: m, receipt: d } = observation;
    assert.ok(forceManifest(m));
    // The direct deployment fixture has a real force receipt, but no complete
    // world-build record. Wrap only identity/roster metadata needed by this
    // SDK contract; do not claim it is a full generated AI encounter.
    const receipt = { force_manifest: m, force_deployment: d, mission_kind: 'assault', index: 0,
      operation_id: 'joint-operation', spawned: d.units.filter((u: any) => u.faction === 'red').map((u: any) => u.entity_id),
      friendly_spawned: d.units.filter((u: any) => u.faction === 'green').map((u: any) => u.entity_id) };
    assert.ok(completedForceDeployment(receipt));
    const missingFaction = structuredClone(receipt);
    for (const gun of missingFaction.force_deployment.equipment) delete gun.faction;
    assert.equal(completedForceDeployment(missingFaction), name.startsWith('red'),
      'only historical red receipts may omit native equipment ownership');
    for (const gun of d.equipment) assert.equal(gun.faction, equipmentFaction(m, m.equipment.find((g: any) => g.slot_id === gun.slot_id)));
    const world = structuredClone(observation.state);
    world.world_growth.phase = 'encounter'; world.world_growth.revision = 1;
    world.world_growth.completed = [receipt];
    const context = presenterStageContext(world)!;
    assert.ok(context);
    const side = name.startsWith('green') ? '绿方' : '红方';
    assert.match(context.facts.find(f => f.id === 'director-deployed-support')!.text, new RegExp(side + '1门迫击炮'));
    const publicGuns = publicMortars(world.world_growth);
    assert.ok(publicGuns.some(gun => gun.faction === (name.startsWith('green') ? 'green' : 'red')));
  });
}

test('actual native completed fixed support is excluded; actual shots retain correct ownership', () => {
  const completed = native.observations.find((r: any) => r.case === 'post-completed-passive');
  assert.equal(completed.gun.support_completed, true);
  assert.deepEqual(publicMortars({ mortar_supports: [completed.gun] }), []);
  for (const side of ['green', 'red']) {
    const shot = native.observations.find((r: any) => r.case === side + '-shot-state');
    assert.ok(shot.gun.shots > 0);
    const world = { run_id: 'native-support-fixture', units: [shot.operator, shot.guard], world_growth: { revision: 1, mortar_supports: [shot.gun] } };
    const facts = spectatorEquipmentFacts({ kind: 'ai', status: 'running', world }).facts;
    assert.ok(facts.some(f => f.equipmentId === shot.gun.id && f.text.includes(side === 'green' ? '绿队控制' : '红队控制')));
  }
});
