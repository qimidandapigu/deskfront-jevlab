import type { BattleFrame, Fact } from './commentary.js';
import { publicMortars, publicSpectatorText } from './spectator-observation.js';

type Row = Record<string, any>;
const teamName = (team: string) => ({ green: '绿队', red: '红队', blue: '蓝队' })[team] ?? '未知阵营';
export interface EquipmentFact extends Fact { equipmentId?: string }

/** Fail closed for obvious spoilers even when a model cites an unrelated valid id. */
export function spectatorTextGrounded(text: string, current: BattleFrame, evidence: Fact[]): boolean {
  if (!publicSpectatorText(text)) return false;
  const facts = evidence.map(f => f.text).join('\n');
  if (/下一关|下关/.test(text)) return false;
  if (/坦克|装甲/.test(text) && !/坦克|装甲/.test(facts)) return false;
  if (/迫击炮|炮台|炮位|炮组/.test(text) && !/迫击炮|炮台|炮位|炮组/.test(facts)) return false;
  const stage = Number(current.world.world_growth?.mission?.index ?? current.world.world_growth?.revision ?? 0);
  const chinese: Record<string, number> = { 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10 };
  for (const match of text.matchAll(/第([一二三四五六七八九十]|\d+)关/gu)) {
    const number = match[1]!;
    if ((chinese[number] ?? Number(number)) > stage) return false;
  }
  return true;
}

/** Story-relevant evidence from engine snapshots, never inferred from the script. */
export function spectatorEquipmentFacts(current: BattleFrame, previous?: BattleFrame): { facts: EquipmentFact[]; changed: boolean; notableChanged: boolean } {
  const w = current.world, old = previous?.world;
  const sameStage = !!old && old.run_id === w.run_id && old.world_growth?.revision === w.world_growth?.revision;
  const units: Row[] = Array.isArray(w.units) ? w.units : [];
  const before = new Map<string, Row>((sameStage && Array.isArray(old.units) ? old.units : []).map((u: Row) => [u.id, u]));
  const facts: EquipmentFact[] = []; let changed = false, notableChanged = false;
  for (const u of units) {
    const p = before.get(u.id);
    if ((u.kind === 'tank' || u.tank === true) && typeof u.hp === 'number') {
      if (u.hp > 0) {
        facts.push({ id: 'equipment-tank-' + u.id, text: `${teamName(u.faction)}坦克实际在场，当前剩余血量${u.hp}。` });
        if (sameStage && !p) changed = notableChanged = true;
      } else if (p?.hp > 0) {
        facts.push({ id: 'equipment-tank-destroyed-' + u.id, text: `${teamName(u.faction)}坦克血量实际降至零。` }); changed = notableChanged = true;
      }
    }
    const satchel = u.combat?.satchel, prior = p?.combat?.satchel;
    if (p && satchel && (satchel.time !== prior?.time || satchel.status !== prior?.status)) {
      if (satchel.status === 'launched' || satchel.status === 'detonated') {
        facts.push({ id: 'equipment-satchel-' + u.id, text: `${teamName(u.faction)}士兵的炸药包已${satchel.status === 'launched' ? '实际投出' : '实际爆炸'}。` }); changed = notableChanged = true;
      }
    }
  }
  const mortars = publicMortars(w.world_growth);
  const priorMortars = new Map(publicMortars(sameStage ? old.world_growth : undefined).map(gun => [gun.id, gun]));
  for (const mortar of mortars) {
    if (typeof mortar.hp !== 'number' || mortar.hp <= 0) continue;
    const prior = priorMortars.get(mortar.id), label = mortars.length > 1 ? '其中一门迫击炮' : '迫击炮';
    const fact = (kind: string, text: string, routine = false) => facts.push({
      id: `equipment-mortar-${kind}-${mortar.id}`, equipmentId: mortar.id, text, routine,
    });
    if (mortar.faction === 'neutral' && mortar.capturable === true) {
      fact('unmanned', `${label}目前无人控制，可以接管。`);
    } else if (['green', 'red', 'blue'].includes(mortar.faction)) {
      fact('owner', `${label}当前由${teamName(mortar.faction)}控制，存活炮组人数${mortar.crew_alive ?? '未知'}。`);
    }
    if (prior && prior.faction !== mortar.faction) {
      changed = notableChanged = true;
      if (Number(mortar.capture_count) > Number(prior.capture_count) && ['green', 'red', 'blue'].includes(mortar.faction)) {
        fact('captured', `引擎确认${teamName(mortar.faction)}完成${label}接管。`);
      }
    }
    if (prior && typeof mortar.shots === 'number' && typeof prior.shots === 'number' && mortar.shots > prior.shots) {
      const routine = prior.shots > 0;
      fact('shot', `${label}实际发射了${mortar.shots - prior.shots}发炮弹。`, routine); changed = true;
      notableChanged ||= !routine;
    }
    if (prior && typeof mortar.crew_alive === 'number' && typeof prior.crew_alive === 'number' && mortar.crew_alive !== prior.crew_alive) {
      fact('crew', `${label}存活炮组从${prior.crew_alive}人变为${mortar.crew_alive}人，当前控制方为${mortar.faction === 'neutral' ? '中立' : teamName(mortar.faction)}。`);
    }
  }
  return { facts, changed, notableChanged };
}
