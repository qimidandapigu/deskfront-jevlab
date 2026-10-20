/** Small, read-only introduction to an encounter already built by the native game. */
import { directorIntentGrounded } from './presenter-experience.js';
import { completedForceDeployment, directorAuthorshipFacts, equipmentFaction, forceManifest, forceNumbersGrounded } from './director-authorship.js';
import { presenterArrangements, type ArrangementComparison } from './presenter-arrangements.js';
export interface PresenterStageContext {
  key: string;
  stage: number;
  facts: { id: string; text: string; evidence?: unknown }[];
  arrangements?: ArrangementComparison;
}

type Row = Record<string, any>;

/** Introductory design evidence must not masquerade as a combat result or order. */
export function directorIntroductionGrounded(text: string, evidence: { id: string; text: string }[]): boolean {
  if (!directorIntentGrounded(text, evidence)) return false;
  const design = evidence.filter(f => f.id.startsWith('director-'));
  if (!design.length) return false;
  const facts = design.map(f => f.text).join('\n');
  if (/我(?:们)?(?:来|刚刚?|已经|马上|亲自)?(?:让|叫|命令|指挥|控制).{0,12}(?:绿队|红队|小兵|士兵|开火|攻击|撤退)/u.test(text)) return false;
  if (/(?:救出来|救回来|救出|救回|打赢|拿下|通关|突破|消灭|全灭)(?:了|啦)|已经.{0,12}(?:救|消灭|打败|突破|完成)|成功.{0,8}(?:救|突破|消灭)|完成了.{0,6}(?:营救|救援)/u.test(text)) return false;
  if (/(?:主路|侧路|两路|岔路|两条路|绕)/u.test(text) && !design.some(f => /^director-(?:layout|layout-detail|change-route)/u.test(f.id))) return false;
  if (/(?:两|二|2)条侧路/u.test(text)) return false;
  if (!forceNumbersGrounded(text, evidence)) return false;
  for (const [mention, support] of [
    [/救|被困/u, /营救|被困|等待救援/u], [/火箭/u, /火箭筒/u], [/冲锋枪/u, /冲锋枪/u],
    [/步枪/u, /步枪/u], [/增援/u, /友军增援/u],
  ]) if (mention!.test(text) && !support!.test(facts)) return false;
  return true;
}
const object = (value: unknown): Row => value && typeof value === 'object' && !Array.isArray(value) ? value as Row : {};
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.slice(-4096).map(object) : [];
const identifier = (value: unknown): value is string => typeof value === 'string' && value.length > 0
  && value.length <= 160 && value.trim() === value && !/[\u0000-\u001f\u007f]/u.test(value);
const identifiers = (value: unknown): string[] => Array.isArray(value) && value.length <= 4096 && value.every(identifier)
  ? [...new Set(value)] : [];
const alive = (unit: Row) => typeof unit.hp === 'number' && Number.isFinite(unit.hp) && unit.hp > 0;
const weapons: Record<string, string> = { rifle: '步枪兵', smg: '冲锋枪兵', rocket: '火箭筒兵', pistol: '手枪兵' };
const cells = (value: unknown): string[] => Array.isArray(value) && value.length >= 2 && value.length <= 9
  && value.every(cell => typeof cell === 'string' && /^c[0-2]r[0-2]$/u.test(cell))
  && new Set(value).size === value.length ? value : [];

/**
 * No planner, preview or candidate slots enter this projection. The native
 * mission is created only after construction, and its operation identifies
 * which completed receipt and deployed actors belong to this encounter.
 */
export function presenterStageContext(world: Row): PresenterStageContext | undefined {
  const growth = object(world.world_growth), mission = object(growth.mission);
  const stage = growth.revision;
  if (!identifier(world.run_id) || !Number.isSafeInteger(stage) || stage < 1 || stage > 1_000_000
    || mission.index !== stage || !identifier(mission.operation_id)
    || growth.phase !== 'encounter' || !['active', 'regrouping'].includes(mission.status)
    || (mission.run_id !== undefined && mission.run_id !== world.run_id)) return undefined;

  const facts: PresenterStageContext['facts'] = [];
  const add = (id: string, text: string) => facts.push({ id: 'director-' + id, text });
  add('stage', `第${stage}关已经搭好，${mission.status === 'regrouping' ? '当前正在重整' : '当前正在进行'}。`);
  if (mission.mission_kind === 'rescue') add('mission', '本关任务是清除包围守军，营救被困队友。');
  else if (mission.mission_kind === 'assault') add('mission', '本关任务是清除这一段的全部守军。');

  // Native completed[].spawned contains actual IDs, including deployed tank
  // and mortar crew. spec.defender_slots and requested enemy_count do not.
  // The native builder records completed[].index before incrementing revision;
  // mission.index then uses the new revision. A reconstructed native_mission
  // receipt already uses mission.index and must be identified explicitly.
  const receipt = rows(growth.completed).find(row => (row.index === stage - 1
    || (row.index === stage && row.evidence === 'native_mission')) && row.operation_id === mission.operation_id
    && (row.run_id === undefined || row.run_id === world.run_id));
  const deployed = identifiers(receipt?.spawned);
  if (deployed.length) add('deployment', `本关建成时实际部署了${deployed.length}个敌方单位。`);
  // Resolve the completed spawn roster, including casualties. A later living
  // headcount must not silently replace the force that was actually deployed.
  // Only describe a complete, known roster; tanks are vehicles, not people.
  const exactDeployment = !!receipt && completedForceDeployment(receipt);
  const deployedUnits = deployed.map(id => exactDeployment
    ? rows(receipt.force_deployment.units).find(unit => unit.entity_id === id && unit.faction === 'red')
    : rows(world.units).find(unit => unit.id === id && unit.faction === 'red'));
  const mortars = Array.isArray(growth.mortar_supports) ? rows(growth.mortar_supports) : [object(growth.mortar_support)];
  const deployedCrew = new Set(exactDeployment ? rows(receipt.force_deployment.equipment).flatMap(gun => identifiers(gun.crew_entity_ids))
    : mortars.filter(gun => gun.kind === 'mortar' && gun.faction === 'red').flatMap(gun => identifiers(gun.crew_ids)));
  const deployedKinds = deployedUnits.map(unit => unit && (unit.kind === 'tank' || unit.tank === true
    ? '坦克' : deployedCrew.has(unit.entity_id ?? unit.id) ? '迫击炮手' : weapons[unit.weapon]));
  if (deployed.length && deployedKinds.every((kind): kind is string => !!kind)) {
    const counts = new Map<string, number>();
    for (const kind of deployedKinds) counts.set(kind, (counts.get(kind) ?? 0) + 1);
    const tanks = counts.get('坦克') ?? 0, infantry = deployed.length - tanks;
    const total = [infantry ? `${infantry}名守军` : '', tanks ? `${tanks}辆坦克` : ''].filter(Boolean).join('和');
    add('composition', `这回部署的是${total}。` + (infantry ? '步兵配备：' + [...counts]
      .filter(([kind]) => kind !== '坦克').map(([kind, count]) => `${count}名${kind}`).join('、') + '。' : ''));
  }
  const added = identifiers(receipt?.friendly_spawned);
  if (added.length) {
    const tanks = exactDeployment ? rows(receipt.force_deployment.units).filter(u => u.group === 'reinforcements' && u.kind === 'tank').length : 0;
    const people = added.length - tanks;
    add('reinforcements', !exactDeployment ? `本关建成时加入了${added.length}名友军增援。`
      : `本关建成时加入了友军增援：${[people ? `${people}名步兵` : '', tanks ? `${tanks}辆坦克` : ''].filter(Boolean).join('、')}。`);
  }
  if (exactDeployment) {
    const manifest = forceManifest(receipt.force_manifest)!;
    const support = ['red', 'green'].flatMap(side => {
      const guns = manifest.equipment.filter(gun => equipmentFaction(manifest, gun) === side);
      const crew = guns.reduce((n, gun) => n + gun.crew_slot_ids.length, 0);
      return guns.length ? [`${side === 'red' ? '红方' : '绿方'}${guns.length}门迫击炮，${crew}名迫击炮手已包含在${side === 'red' ? '守军' : '友军增援'}人数中`] : [];
    });
    if (support.length) add('deployed-support', '本关建成时实际部署：' + support.join('；') + '。');
    facts.push(...directorAuthorshipFacts(receipt, 'director', true,
      { runId: world.run_id, operationId: mission.operation_id, instanceId: world.instance_id }));
  }

  const defenderIds = new Set(identifiers(mission.defenders));
  const seen = new Set<string>();
  const defenders = rows(world.units).filter(unit => {
    if (!identifier(unit.id) || seen.has(unit.id) || !defenderIds.has(unit.id)
      || unit.faction !== 'red' || !alive(unit) || unit.combat_ready === false) return false;
    seen.add(unit.id); return true;
  });
  // Mortars can remain after an old encounter. Require a living crew member
  // in this mission before announcing the current enemy emplacement.
  const currentMortars = mortars.filter(mortar => mortar.kind === 'mortar' && mortar.faction === 'red' && alive(mortar)
    && defenders.some(unit => identifiers(mortar.crew_ids).includes(unit.id)));
  const crewIds = new Set(currentMortars.flatMap(mortar => identifiers(mortar.crew_ids)));
  const counts = new Map<string, number>();
  for (const unit of defenders) {
    const kind = unit.kind === 'tank' || unit.tank === true ? '坦克'
      : crewIds.has(unit.id) ? '迫击炮手' : weapons[unit.weapon];
    if (kind) counts.set(kind, (counts.get(kind) ?? 0) + 1);
  }
  if (counts.size) add('defenders', '这关当前在场的红方包括' + [...counts].map(([kind, count]) =>
    `${count}${kind === '坦克' ? '辆' : '名'}${kind}`).join('、') + '。');
  if (currentMortars.length) add('support', `这关当前有红方炮组控制的迫击炮，共${currentMortars.length}门；炮手人数和炮门数分别统计。`);
  const ownUnits = rows(world.units).filter(unit => unit.faction === 'green' && alive(unit) && unit.combat_ready !== false);
  const friendlyMortars = mortars.filter(mortar => mortar.kind === 'mortar' && mortar.faction === 'green' && alive(mortar)
    && mortar.retired !== true && mortar.support_completed !== true && !['retired', 'completed_support'].includes(mortar.phase)
    && mortar.available_current_encounter !== false
    && ownUnits.some(unit => identifiers(mortar.crew_ids).includes(unit.id)));
  if (friendlyMortars.length) add('friendly-support', `这关当前有绿方炮组控制的迫击炮，共${friendlyMortars.length}门；炮手属于绿方，不额外计作新加入的步枪兵。`);

  const captive = identifier(mission.captive_id) && mission.rescue_status === 'trapped'
    && rows(world.units).some(unit => unit.id === mission.captive_id && unit.faction === 'green'
      && alive(unit) && unit.combat_ready === false);
  if (captive) add('captive', '这关有一名绿方队友正在等待救援，还没有加入战斗。');

  const spec = object(mission.spec), card = object(spec.design_card);
  const main = cells(card.main_regions), flank = cells(card.flank_regions);
  if (spec.assembly_kind === 'region_graph_v1' && card.alternate_route === true && main.length && flank.length
    && main[0] === flank[0] && main.at(-1) === flank.at(-1) && JSON.stringify(main) !== JSON.stringify(flank)) {
    add('layout', '这关已建成的布局记录包含主路和一条不同的侧路。');
  }
  const arrangements = presenterArrangements(world, receipt, stage);
  if (arrangements) facts.push(...arrangements.changes, ...arrangements.facts);
  return { key: JSON.stringify([world.run_id, stage, mission.operation_id]), stage, facts, ...(arrangements ? { arrangements } : {}) };
}
