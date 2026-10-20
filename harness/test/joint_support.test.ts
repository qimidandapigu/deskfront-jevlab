import assert from 'node:assert/strict';
import test from 'node:test';
import { completedForceDeployment, directorAuthorshipFacts, equipmentFaction, forceManifest, forceNumbersGrounded, manifestSummary } from '../src/deskfront/director-authorship.js';
import { recordedAssembly } from '../src/deskfront/director-replay.js';
import { presenterStageContext } from '../src/deskfront/presenter-context.js';
import { presenterArrangements } from '../src/deskfront/presenter-arrangements.js';
import { generationTags } from '../src/deskfront/generation-tags.js';
import { publicBattleFrame, publicMortars } from '../src/deskfront/spectator-observation.js';
import { spectatorEquipmentFacts } from '../src/deskfront/spectator-story.js';
import { introductionSnapshot } from '../src/deskfront/presenter-intro.js';
import { DeskfrontClient } from '../packages/game-sdk/src/deskfront.js';

function fixture() {
  const manifest = { schema: 'deskfront-forces/v1',
    enemies: [{ slot_id: 'enemy', kind: 'tank' }, { slot_id: 'ec1', kind: 'infantry', weapon: 'rifle' }],
    reinforcements: [{ slot_id: 'gc1', kind: 'infantry', weapon: 'rifle' }, { slot_id: 'gc2', kind: 'infantry', weapon: 'rifle' },
      { slot_id: 'rocket', kind: 'infantry', weapon: 'rocket' }, { slot_id: 'tank', kind: 'tank' }], captives: [],
    equipment: [{ slot_id: 'red-gun', kind: 'mortar', crew_slot_ids: ['ec1'] },
      { slot_id: 'green-gun', kind: 'mortar', crew_slot_ids: ['gc1', 'gc2'] }] };
  const units = ['enemies', 'reinforcements'].flatMap(group => manifest[group as 'enemies' | 'reinforcements'].map((u, i) =>
    ({ ...u, entity_id: `native-${u.slot_id}`, group, faction: group === 'enemies' ? 'red' : 'green', position: [i * .1, 0] })));
  const receipt = { index: 0, operation_id: 'build-a', run_id: 'run-a', mission_kind: 'assault', force_manifest: manifest,
    spawned: units.filter(u => u.faction === 'red').map(u => u.entity_id), friendly_spawned: units.filter(u => u.faction === 'green').map(u => u.entity_id),
    design: { covers: [], floors: [], assembly_kind: 'region_graph_v1' },
    force_deployment: { schema: 'deskfront-force-receipt/v1', status: 'completed',
      coordinate_frame: { kind: 'world_xz', stage_origin: [0, 0] }, units,
      equipment: manifest.equipment.map(gun => ({ ...gun, entity_id: `native-${gun.slot_id}`, kind: 'mortar', position: [.2, 0],
        faction: gun.slot_id === 'green-gun' ? 'green' : 'red', crew_entity_ids: gun.crew_slot_ids.map(id => `native-${id}`) })) } };
  const world = { run_id: 'run-a', time: 10, units: units.map(u => ({ ...u, id: u.entity_id, hp: 50, max_hp: 50 })),
    world_growth: { phase: 'encounter', revision: 1,
      mission: { index: 1, status: 'active', operation_id: 'build-a', mission_kind: 'assault', defenders: receipt.spawned, spec: receipt.design },
      completed: [receipt], mortar_supports: receipt.force_deployment.equipment.map(gun => ({ ...gun, id: gun.entity_id,
        hp: 100, crew_ids: gun.crew_entity_ids, crew_alive: gun.crew_entity_ids.length, available_current_encounter: true,
        next_encounter_available: false, available_for_next_encounter: false, capturable: false, shots: 0 })) } };
  return { manifest, receipt, world };
}

test('canonical manifest infers each mortar from its explicit same-side infantry crew', () => {
  const { manifest, receipt } = fixture(), m = forceManifest(manifest)!;
  assert.ok(m); assert.equal(equipmentFaction(m, m.equipment[0]!), 'red');
  assert.equal(equipmentFaction(m, m.equipment[1]!), 'green'); assert.ok(completedForceDeployment(receipt));
  assert.match(manifestSummary(m)!, /敌方1门迫击炮.*敌方人数.*友方1门迫击炮.*友军增援人数/);
});

test('cross-side crew, duplicate crew, captive/tank crew and false native ownership cannot authorize deployment', () => {
  for (const ids of [['ec1', 'gc1'], ['gc1', 'gc1'], ['tank'], ['missing']]) {
    const { manifest } = fixture(); manifest.equipment[1]!.crew_slot_ids = ids;
    assert.equal(forceManifest(manifest), undefined, JSON.stringify(ids));
  }
  const { receipt } = fixture(); receipt.force_deployment.equipment[1]!.faction = 'red';
  assert.equal(completedForceDeployment(receipt), false);
});

test('green receipt needs explicit native faction; only historical red-only omission is accepted', () => {
  const { receipt } = fixture();
  delete (receipt.force_deployment.equipment[0] as any).faction;
  assert.equal(completedForceDeployment(receipt), true, 'red omission keeps legacy compatibility');
  delete (receipt.force_deployment.equipment[1] as any).faction;
  assert.equal(completedForceDeployment(receipt), false, 'green omission cannot claim exact deployment');
});

test('map replay keeps the real green/red mortar side, without invented soldiers or changed positions', () => {
  const { receipt } = fixture(), before = structuredClone(receipt);
  const replay = recordedAssembly({ status: 'completed', construction: receipt }, [])!;
  assert.equal(replay.units.find(u => u.id === 'native-green-gun')!.faction, 'green');
  assert.equal(replay.units.find(u => u.id === 'native-red-gun')!.faction, 'red');
  assert.equal(replay.units.length, receipt.force_deployment.units.length + 2);
  assert.deepEqual(receipt, before);
});

test('arrangement facts count each crew as crew once and distinguish side-specific equipment', () => {
  const { receipt, world } = fixture();
  const arrangement = presenterArrangements(world, receipt, 1)!;
  assert.equal(arrangement.current.forces!['reinforcements:mortar_crew'], 2);
  assert.equal(arrangement.current.forces!['reinforcements:rifle'], undefined);
  assert.equal(arrangement.current.forces!['enemies:mortar_crew'], 1);
  assert.equal(arrangement.current.forces!['equipment_red:mortar'], 1);
  assert.equal(arrangement.current.forces!['equipment_green:mortar'], 1);
  assert.equal(arrangement.current.forces!['reinforcements:tank'], 1);
});

test('introduction facts distinguish friendly support from enemy crews and preserve the reinforcement total', () => {
  const { world } = fixture(), facts = presenterStageContext(world)!.facts;
  const text = facts.map(f => f.text).join('\n');
  assert.match(text, /加入了友军增援：3名步兵、1辆坦克/);
  assert.match(text, /红方1门迫击炮，1名迫击炮手.*守军/);
  assert.match(text, /绿方1门迫击炮，2名迫击炮手.*友军增援/);
  assert.match(text, /绿方炮组控制/);
  assert.match(introductionSnapshot(presenterStageContext(world)!).facts.find(f => f.id === 'director-friendly-support')!.text, /本关曾出现/);
  assert.equal(forceNumbersGrounded('绿方部署1门迫击炮。', facts), true);
  assert.equal(forceNumbersGrounded('红方部署2门迫击炮。', facts), false);
});

test('friendly-only gun cannot ground an enemy mortar count', () => {
  const facts = [{ id: 'director-deployed-support', text: '本关建成时实际部署：绿方1门迫击炮，2名迫击炮手已包含在友军增援人数中。' }];
  assert.equal(forceNumbersGrounded('绿方部署1门迫击炮。', facts), true);
  assert.equal(forceNumbersGrounded('红方部署1门迫击炮。', facts), false);
  assert.equal(forceNumbersGrounded('红方有1门迫击炮。', [{ id: 'director-support', text: '这关当前有红方炮组控制的迫击炮，共1门；炮手人数和炮门数分别统计。' }]), true);
});

test('card tags distinguish confirmed friendly tanks and both mortar sides', () => {
  const { receipt, manifest } = fixture();
  const tags = generationTags({ id: 'build-a' }, { operation_id: 'build-a', status: 'completed', construction: receipt, force_manifest: manifest }, null, null, null);
  for (const label of ['敌方1辆坦克＋1门迫击炮', '友方1辆坦克＋1门迫击炮']) assert.ok(tags.next.some(t => t.label === label && t.kind === 'confirmed'));
});

test('completed fixed support disappears from current public/narration facts, ordinary neutral capture stays', () => {
  const { world } = fixture();
  const oldGun: any = { ...world.world_growth.mortar_supports[1], id: 'old-green', support_completed: true,
    phase: 'completed_support', faction: 'neutral', capturable: false, available_current_encounter: false };
  const neutral: any = { ...world.world_growth.mortar_supports[0], id: 'capture-gun', faction: 'neutral', capturable: true,
    crew_alive: 0, crew_ids: [], available_current_encounter: false };
  world.world_growth.mortar_supports.push(oldGun, neutral);
  assert.equal(publicMortars(world.world_growth).some(gun => gun.id === 'old-green'), false);
  assert.ok(publicMortars(world.world_growth).some(gun => gun.id === 'capture-gun'));
  const frame: any = publicBattleFrame({ kind: 'ai', status: 'running', world });
  assert.equal(spectatorEquipmentFacts(frame).facts.some(f => f.equipmentId === 'old-green'), false);
  assert.ok(spectatorEquipmentFacts(frame).facts.some(f => f.equipmentId === 'capture-gun' && /可以接管/.test(f.text)));
});

test('SDK exact transport preserves mixed enemy/support plan and adds no crew', async () => {
  const { manifest } = fixture(), sent: any[] = [];
  const transport: any = { request: async (method: string, path: string, body: any) => {
    if (path === '/v1/info') return { protocol: 'quickplay-bridge/v1', extensions: ['deskfront-forces/v1'] };
    sent.push(body); return { accepted: true };
  } };
  const command: any = { id: 'command-a', context: {}, teamId: 'green', command: { action: 'grow_world', force_manifest: manifest } };
  const before = structuredClone(command);
  await new DeskfrontClient(transport).submit(command);
  assert.deepEqual(sent[0], before); assert.deepEqual(command, before);
});

test('legacy authored equipment group references resolve in their actual enemy or reinforcement roster', () => {
  const { receipt } = fixture();
  const names: Record<string,string> = { enemy: 'e-tank-1', ec1: 'e-crew-1', gc1: 'r-crew-1', gc2: 'r-crew-2', rocket: 'r-rocket-1', tank: 'r-tank-1' };
  for (const group of ['enemies', 'reinforcements'] as const) for (const unit of receipt.force_manifest[group]) unit.slot_id = names[unit.slot_id]!;
  for (const unit of receipt.force_deployment.units) unit.slot_id = names[unit.slot_id]!;
  for (const gun of [...receipt.force_manifest.equipment, ...receipt.force_deployment.equipment]) gun.crew_slot_ids = gun.crew_slot_ids.map(id => names[id]!);
  const order = { schema: 'director-content/v1', order_id: 'order-a', source_report_id: 'report-a', origin: 'director',
    mission_kind: { mode: 'fixed', value: 'assault' },
    enemies: { mode: 'fixed', groups: [{ group_id: 'tank', kind: 'tank', count: 1 }, { group_id: 'crew', kind: 'infantry', weapon: 'rifle', count: 1 }] },
    reinforcements: { mode: 'fixed', groups: [{ group_id: 'crew', kind: 'infantry', weapon: 'rifle', count: 2 },
      { group_id: 'rocket', kind: 'infantry', weapon: 'rocket', count: 1 }, { group_id: 'tank', kind: 'tank', count: 1 }] },
    equipment: { mode: 'fixed', items: receipt.force_manifest.equipment.map(gun => ({ slot_id: gun.slot_id, kind: 'mortar', crew_group_ids: ['crew'] })) } };
  const record = { ...receipt, director_order: order, director_order_id: order.order_id,
    generation_authority: { order_id: order.order_id, source_report_id: order.source_report_id,
      explicit_fields: ['mission_kind', 'enemies', 'reinforcements', 'equipment'], delegated_fields: [], source_scope: { run_id: 'run-a' } } };
  const facts = directorAuthorshipFacts(record, 'director', true, { runId: 'run-a', operationId: 'build-a' });
  assert.match(facts.find(f => f.id === 'director-authored-equipment')!.text, /敌方1门迫击炮.*友方1门迫击炮/);
});
