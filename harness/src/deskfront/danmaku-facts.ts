import type { BattleFrame, Fact } from './commentary.js';
import { publicMortars, publicSpectatorText } from './spectator-observation.js';

type Row = Record<string, any>;
export type DanmakuFaction = 'green' | 'red' | 'blue' | 'neutral';
export type DanmakuEntityKind = 'team' | 'infantry' | 'rifle' | 'smg' | 'rocket' | 'machinegun' | 'sniper' | 'pistol' | 'tank' | 'mortar' | 'gunner' | 'satchel';
export type DanmakuAction = 'present' | 'alive' | 'full_strength' | 'unharmed' | 'damaged' | 'loss' | 'all_eliminated' | 'last_survivor' | 'fired' | 'launched' | 'exploded' | 'captured' | 'unmanned' | 'advancing' | 'retreating' | 'moved' | 'stage_started' | 'mission_completed' | 'mission_failed';
export interface DanmakuSubject { kind: DanmakuEntityKind; faction?: DanmakuFaction; id?: string }
export interface DanmakuRelation {
  subjects: DanmakuSubject[]; action: DanmakuAction; count?: number;
  proof?: { type: 'public-snapshot'; entity_id: string; field: 'last_shot_at'; value: number };
}
export interface DanmakuFact {
  id: string; text: string; run_id: string; stage?: number; time: number;
  revision?: number; operation_id?: string;
  temporal: 'current' | 'event' | 'history'; relations: DanmakuRelation[];
}
export interface DanmakuEvidence {
  scope: { run_id: string; stage?: number; time: number; revision?: number; operation_id?: string; mission_status?: string };
  facts: DanmakuFact[];
  /** Public snapshot only, for negative presence statements and current-state revalidation. */
  entities: DanmakuSubject[];
}
export interface DanmakuValidation { accepted: boolean; reason: string; claims?: { action: string; subjects: DanmakuSubject[]; mode: string }[] }

const factions: Record<string, DanmakuFaction> = { 绿: 'green', 红: 'red', 蓝: 'blue', 中立: 'neutral' };
const teamOf = (text: string): DanmakuFaction | undefined => factions[/(绿|红|蓝|中立)(?:队|方|军)?/u.exec(text)?.[1] ?? '']
  ?? (/敌(?:人|军)|守军/u.test(text) ? 'red' : /友军|我方/u.test(text) ? 'green' : undefined);
const team = (faction?: DanmakuFaction): DanmakuSubject[] => faction ? [{ kind: 'team', faction }] : [];
const isTank = (unit: Row) => unit.kind === 'tank' || unit.tank === true;
const living = (unit: Row) => unit.hp > 0 && unit.combat_ready !== false;
const weapons: Record<string, DanmakuEntityKind> = { rifle: 'rifle', smg: 'smg', rocket: 'rocket', machinegun: 'machinegun', machine_gun: 'machinegun', sniper: 'sniper', pistol: 'pistol' };
const aliases: { kind: DanmakuEntityKind; expression: RegExp }[] = [
  { kind: 'gunner', expression: /炮手|炮兵|炮组/u },
  { kind: 'mortar', expression: /迫击炮|炮台|炮位|这门炮|那门炮|火炮/u },
  { kind: 'tank', expression: /坦克|装甲车|装甲/u },
  { kind: 'rocket', expression: /火箭(?:筒|兵)?/u },
  { kind: 'smg', expression: /冲锋枪(?:兵)?|冲锋兵/u },
  { kind: 'machinegun', expression: /机枪(?:兵|手)?/u },
  { kind: 'sniper', expression: /狙击(?:兵|手|枪)?/u },
  { kind: 'pistol', expression: /手枪(?:兵)?/u },
  { kind: 'rifle', expression: /步枪(?:兵|手)?/u },
  { kind: 'satchel', expression: /炸药包/u },
];
const matches = (wanted: DanmakuSubject, actual: DanmakuSubject) => (wanted.kind === actual.kind || wanted.kind === 'team' && !!wanted.faction && wanted.faction === actual.faction)
  && (!wanted.faction || wanted.faction === actual.faction) && (!wanted.id || wanted.id === actual.id);
const entitySet = (frame: BattleFrame): DanmakuSubject[] => {
  const entities: DanmakuSubject[] = [];
  for (const unit of (frame.world.units ?? []) as Row[]) {
    if (!living(unit)) continue;
    const faction = unit.faction as DanmakuFaction;
    entities.push({ kind: isTank(unit) ? 'tank' : 'infantry', faction, id: unit.id });
    const weapon = !isTank(unit) && weapons[unit.weapon];
    if (weapon) entities.push({ kind: weapon, faction, id: unit.id });
  }
  for (const mortar of publicMortars(frame.world.world_growth)) {
    if (!(mortar.hp > 0)) continue;
    const faction = mortar.faction as DanmakuFaction;
    entities.push({ kind: 'mortar', faction, id: mortar.id });
    if (mortar.crew_alive > 0) entities.push({ kind: 'gunner', faction, id: mortar.id });
  }
  for (const faction of ['green', 'red', 'blue'] as DanmakuFaction[])
    if (entities.some(entity => entity.faction === faction)) entities.push({ kind: 'team', faction });
  return entities;
};
const numericStage = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : undefined;

/** Convert only the existing public fact factories' finite grammars. A valid id or an
 * equipment noun alone never promotes presence into an action or a battle result. */
export function buildDanmakuEvidence(frame: BattleFrame, source: Fact[]): DanmakuEvidence {
  const world = frame.world, mission = world.world_growth?.mission;
  const stage = numericStage(mission?.index ?? world.world_growth?.revision);
  const time = Number(world.time ?? 0), run_id = String(world.run_id ?? '');
  const entities = entitySet(frame);
  const facts: DanmakuFact[] = source.map(sourceFact => {
    const original = sourceFact as Fact & { time?: number; stage?: number; run_id?: string; temporal?: 'current' | 'event' | 'history'; source_scope?: { run_id?: string; stage?: number; revision?: number; operation_id?: string; observed_at?: number } };
    const text = sourceFact.text, faction = teamOf(text), subjects = team(faction);
    const explicitStage = numericStage(original.stage) ?? Number(/第(\d+)关/u.exec(text)?.[1] ?? NaN);
    const factStage = Number.isFinite(explicitStage) ? explicitStage : numericStage(original.source_scope?.stage) ?? stage;
    const factTime = typeof original.time === 'number' ? original.time : typeof original.source_scope?.observed_at === 'number' ? original.source_scope.observed_at : time;
    const temporal = original.temporal ?? (typeof original.time === 'number' || factStage !== stage || /^stage-\d+$/u.test(sourceFact.id) ? 'history' : 'current');
    const fact: DanmakuFact = { id: sourceFact.id, text, run_id: original.source_scope?.run_id ?? original.run_id ?? run_id, stage: factStage, time: factTime, temporal,
      ...(numericStage(original.source_scope?.revision) !== undefined ? { revision: original.source_scope!.revision } : {}),
      ...(typeof original.source_scope?.operation_id === 'string' ? { operation_id: original.source_scope.operation_id } : {}), relations: [] };
    const add = (action: DanmakuAction, targets = subjects, count?: number) => fact.relations.push({ action, subjects: targets, ...(count !== undefined ? { count } : {}) });
    const now = temporal === 'current' && factStage === stage;
    const currentMembers = entities.filter(entity => entity.faction === faction && entity.kind !== 'team');
    const equipmentId = (sourceFact as Fact & { equipmentId?: string }).equipmentId;
    const mortar = equipmentId ? publicMortars(world.world_growth).find(gun => gun.id === equipmentId) : undefined;
    const gunSubjects: DanmakuSubject[] = [{ kind: 'mortar', ...(mortar ? { id: mortar.id, faction: mortar.faction } : faction ? { faction } : {}) }];
    if (/^s\d+$/u.test(sourceFact.id) && /当前\d+人(?:仍在战斗|存活)/u.test(text) && faction && now) {
      const count = (world.units ?? []).filter((unit: Row) => unit.faction === faction && !isTank(unit) && living(unit)).length;
      if (count > 0) { add('alive', [...subjects, ...currentMembers], count); add('present', [...subjects, ...currentMembers]); }
      if (count === 1) add('last_survivor');
      const roster: Row[] = (world.units ?? []).filter((unit: Row) => unit.faction === faction);
      if (roster.length && roster.every(living)) {
        add('full_strength');
        if (roster.every(unit => typeof unit.max_hp === 'number' && unit.max_hp > 0 && unit.hp >= unit.max_hp)) add('unharmed');
      }
      for (const unit of (world.units ?? []) as Row[]) {
        if (unit.faction !== faction || isTank(unit) || !living(unit)) continue;
        const actor = entities.filter(entity => entity.id === unit.id);
        if (typeof unit.last_shot_at === 'number' && unit.last_shot_at >= 0 && time - unit.last_shot_at >= 0 && time - unit.last_shot_at <= 10)
          fact.relations.push({ action: 'fired', subjects: [...subjects, ...actor], proof: { type: 'public-snapshot', entity_id: unit.id, field: 'last_shot_at', value: unit.last_shot_at } });
      }
    }
    if (/^pressure-(?:green|red|blue)$/u.test(sourceFact.id) && /血量下降/u.test(text)) add('damaged');
    if (/^(?:loss-(?:green|red|blue)|h\d+)$/u.test(sourceFact.id) && /(?:新增\d+名士兵阵亡|阵亡\d+人)/u.test(text) && faction) {
      add('loss');
      if (/只剩最后一人|当前1名士兵仍在战斗|场上还剩1人/u.test(text)) add('last_survivor');
      if (/当前0名士兵仍在战斗|场上还剩0人/u.test(text)
        && factStage === stage && !entities.some(entity => entity.faction === faction)) add('all_eliminated');
    }
    if (/^equipment-tank-(?!destroyed-)/u.test(sourceFact.id) && /坦克实际在场/u.test(text)) {
      const id = sourceFact.id.slice('equipment-tank-'.length);
      if (entities.some(entity => entity.kind === 'tank' && entity.id === id && entity.faction === faction))
        add('present', [{ kind: 'tank', id, ...(faction ? { faction } : {}) }]);
      const unit = (world.units ?? []).find((unit: Row) => unit.id === id && isTank(unit) && living(unit));
      if (unit && typeof unit.last_shot_at === 'number' && unit.last_shot_at >= 0 && time - unit.last_shot_at >= 0 && time - unit.last_shot_at <= 10)
        fact.relations.push({ action: 'fired', subjects: [{ kind: 'tank', id, ...(faction ? { faction } : {}) }], proof: { type: 'public-snapshot', entity_id: id, field: 'last_shot_at', value: unit.last_shot_at } });
    }
    if (/^(?:equipment-tank-destroyed-|h\d+)/u.test(sourceFact.id) && /坦克血量实际降至零/u.test(text)) add('loss', [{ kind: 'tank', ...(faction ? { faction } : {}) }]);
    if (/^h\d+$/u.test(sourceFact.id) && /坦克开火。/u.test(text)) add('fired', [{ kind: 'tank', ...(faction ? { faction } : {}) }]);
    if (/^(?:equipment-mortar-|h\d+)/u.test(sourceFact.id)) {
      if (/迫击炮目前无人控制，可以接管/u.test(text) && (!now || mortar?.faction === 'neutral' && mortar.capturable === true)) { add('present', gunSubjects); add('unmanned', gunSubjects); }
      if (/迫击炮当前由(?:绿|红|蓝)队控制/u.test(text)) {
        if (now && (!mortar || mortar.faction !== faction || !(mortar.hp > 0))) return fact;
        add('present', gunSubjects);
        const count = now ? Number(mortar?.crew_alive) : Number(/存活炮组人数(\d+)/u.exec(text)?.[1] ?? NaN);
        if (count > 0) add('alive', [{ kind: 'gunner', ...(faction ? { faction } : {}) }], count);
      }
      if (/引擎确认(?:绿|红|蓝)队完成.*迫击炮接管/u.test(text)) add('captured', [...subjects, ...gunSubjects]);
      if (/迫击炮实际发射了\d+发炮弹/u.test(text)) add('fired', gunSubjects);
      if (/迫击炮存活炮组从\d+人变为\d+人/u.test(text)) {
        const counts = /从(\d+)人变为(\d+)人/u.exec(text)!;
        if (Number(counts[2]) < Number(counts[1])) add('loss', [{ kind: 'gunner', ...(faction ? { faction } : {}) }]);
        if (Number(counts[2]) > 0) add('alive', [{ kind: 'gunner', ...(faction ? { faction } : {}) }], Number(counts[2]));
      }
    }
    if (/^(?:equipment-satchel-|h\d+)/u.test(sourceFact.id) && /士兵的炸药包已实际(?:投出|爆炸)/u.test(text))
      add(/投出/u.test(text) ? 'launched' : 'exploded', [{ kind: 'satchel', ...(faction ? { faction } : {}) }]);
    if (/^h\d+$/u.test(sourceFact.id)) {
      if (/名士兵朝本关交战目标推进/u.test(text)) add('advancing');
      if (/名士兵从本关交战目标方向后撤/u.test(text)) add('retreating');
      if (/名士兵换了位置/u.test(text)) add('moved');
      if (/第\d+关已经开始/u.test(text)) add('stage_started');
      if (/任务已经完成/u.test(text)) add('mission_completed', team('green'));
      if (/绿队本段推进失败/u.test(text)) add('mission_failed', team('green'));
      // Initial equipment-history events are presence, never a fresh destruction/shot.
      if (/坦克实际在场/u.test(text)) add('present', [{ kind: 'tank', ...(faction ? { faction } : {}) }]);
    }
    if (sourceFact.id === 'mission' && /引擎确认本段任务完成/u.test(text)) add('mission_completed', team('green'));
    if (sourceFact.id === 'stage') {
      if (/阶段状态:completed/u.test(text) && mission?.status === 'completed') add('mission_completed', team('green'));
      if (/阶段状态:failed/u.test(text) && mission?.status === 'failed') add('mission_failed', team('green'));
    }
    if (/^stage-\d+$/u.test(sourceFact.id)) {
      if (/关结果：任务完成/u.test(text)) add('mission_completed', team('green'));
      if (/关结果：failed/u.test(text)) add('mission_failed', team('green'));
    }
    return fact;
  });
  return { scope: { run_id, stage, time, revision: numericStage(world.world_growth?.revision), ...(typeof mission?.operation_id === 'string' ? { operation_id: mission.operation_id } : {}), ...(typeof mission?.status === 'string' ? { mission_status: mission.status } : {}) }, facts, entities };
}

const subjectFor = (text: string): DanmakuSubject[] => {
  const faction = teamOf(text), found = aliases.filter(alias => alias.expression.test(text)).map(alias => ({ kind: alias.kind, ...(faction ? { faction } : {}) } as DanmakuSubject));
  if (/小兵|士兵|步兵/u.test(text) && !found.some(subject => ['rifle', 'smg', 'rocket', 'machinegun', 'sniper', 'pistol', 'gunner'].includes(subject.kind))) found.push({ kind: 'infantry', ...(faction ? { faction } : {}) });
  if (!found.length && faction) found.push({ kind: 'team', faction });
  return found;
};
const historical = (text: string) => /上一关|上关|前一关|之前那关|回看|回顾|先前|前面那关|那一关|上次/u.test(text);
const stageNumber = (text: string): number => {
  if (/^\d+$/u.test(text)) return Number(text);
  const digits: Record<string, number> = { 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
  if (text === '十') return 10;
  if (text.includes('十')) { const [tens, ones] = text.split('十'); return (tens ? digits[tens] ?? NaN : 1) * 10 + (ones ? digits[ones] ?? NaN : 0); }
  return digits[text] ?? NaN;
};
const uncertainty = (text: string) => /(?:吗|么|是否|会不会|能不能|有没有|打没打中|不知|看不清|还不确定|说不准)/u.test(text)
  && !/终于|又.{0,5}(?:了|倒|灭)|已经|果然/u.test(text);
const requestOrWish = (text: string) => /加油|顶住|稳住|别急|小心|冲呀|冲啊|撑住|希望|但愿|可别|别再|别倒|别死|别炸|别送|要赢|争口气|守住|快点/u.test(text);
const actionPatterns: { action: DanmakuAction | 'hit' | 'causal_kill' | 'tactical_success' | 'stalled'; expression: RegExp }[] = [
  { action: 'causal_kill', expression: /(?:打死|杀了|击杀|收掉|干掉).{0,6}(?:红|绿|蓝|坦克|兵)|(?:坦克|炮|兵).{0,5}(?:打死了|击杀了|收掉了|干掉了)|(?:一炮|炮弹|子弹|火箭弹|火箭兵|炮手).{0,10}(?:送走|带走|击毁|炸毁|打死|打爆|打炸|收掉|干掉)|(?:绿|红|蓝)(?:队|方|军).{0,6}(?:击毁|打爆|炸毁|击杀|干掉)/u },
  { action: 'all_eliminated', expression: /全灭|死光|团灭|全倒|都倒了|全没了|一个不剩|没(?:有)?人了|没人(?:活着|剩下)/u },
  { action: 'full_strength', expression: /全员(?:健在|活着|都在|没事)|一个(?:都)?没(?:少|死)/u },
  { action: 'unharmed', expression: /毫发无伤/u },
  { action: 'alive', expression: /还在|还活|仍在|活着|健在|没死|没倒/u },
  { action: 'loss', expression: /阵亡|减员|少了人|少个人|倒(?:一|个)|(?:倒|死|没撑过去|没了|炸|爆|击毁|打掉|报废)(?:下|了|掉|啦|喽|咯|！|!|。|$)|被(?:炸|打)毁|损失/u },
  { action: 'hit', expression: /命中|打中|炸中|轰中|打准了|打得准|中弹/u },
  { action: 'captured', expression: /(?:抢|夺|拿|接管|占)(?:到|下|好|完|住|了)|到手|拿到了|抢回来了/u },
  { action: 'fired', expression: /开(?:火|炮|枪)|炮响|枪响|响了|发射|射出了/u },
  { action: 'launched', expression: /投出|扔出|丢出/u },
  { action: 'exploded', expression: /炸药包.{0,5}(?:爆|炸)/u },
  { action: 'mission_completed', expression: /(?:这关|本关|这段|任务|这一关|这一段).{0,6}(?:拿下|过了|完成|赢了|通了|结束)|(?:拿下|过关|通关|赢了|胜利)(?:了|啦|！|!|$)/u },
  { action: 'mission_failed', expression: /失败|输(?:了|啦|掉)|没撑过去/u },
  { action: 'stage_started', expression: /刚开场|刚开局|才开场|才开局|这关开始|第[一二三四五六七八九十\d]+关开了/u },
  { action: 'advancing', expression: /推进了|压上来了|向前推进|往前走了|往.{0,6}目标.{0,3}推进|还在推进|正在推进|继续推进/u },
  { action: 'retreating', expression: /退回来了|后撤了|撤回来了|退下来了/u },
  { action: 'tactical_success', expression: /绕后成功|突破成功|压制住了|包抄成功|封死了/u },
  // Position samples and a failed mission do not by themselves establish that
  // execution is stalled or blocked, much less explain the mechanical cause.
  { action: 'stalled', expression: /推进.{0,4}(?:卡|受阻|停滞|停住)|(?:走|动|推)不动|一直不动|卡住了|停滞了|受阻了|动弹不得/u },
];

/** This is a finite guard for supported public entities/actions/results, not a
 * claim to prove arbitrary Chinese semantics. Unclassified ordinary reactions
 * remain natural; recognized factual claims must cite a matching typed relation. */
export function validateDanmakuItem(text: string, evidenceIds: string[], context: DanmakuEvidence): DanmakuValidation {
  const deny = (reason: string): DanmakuValidation => ({ accepted: false, reason });
  if (!publicSpectatorText(text) || /下一关|下关/u.test(text)) return deny('private-or-future-claim');
  if (!evidenceIds.length || evidenceIds.some(id => !context.facts.some(fact => fact.id === id))) return deny('unknown-evidence');
  const cited = context.facts.filter(fact => evidenceIds.includes(fact.id));
  if (cited.some(fact => fact.run_id !== context.scope.run_id)) return deny('wrong-run-evidence');
  const mentionedStages = [...text.matchAll(/第([一二三四五六七八九十\d]+)关/gu)].map(match => stageNumber(match[1]!));
  if (mentionedStages.some(stage => !Number.isFinite(stage) || stage > (context.scope.stage ?? 0) || !cited.some(fact => fact.stage === stage))) return deny('stage-mismatch');
  const lookBack = historical(text) || mentionedStages.some(stage => stage < (context.scope.stage ?? 0));
  if (!lookBack && cited.some(fact => fact.revision !== undefined && fact.revision !== context.scope.revision
    || fact.operation_id !== undefined && fact.operation_id !== context.scope.operation_id)) return deny('wrong-operation-evidence');
  const eligible = cited.filter(fact => lookBack || fact.stage === context.scope.stage
    && (fact.temporal === 'current' || fact.temporal === 'event' && context.scope.time - fact.time <= 10 && fact.time <= context.scope.time));
  const relations = eligible.flatMap(fact => fact.relations);
  const allSubjects = relations.flatMap(relation => relation.subjects);
  const claims: NonNullable<DanmakuValidation['claims']> = [];
  for (const clause of text.split(/[，,；;。！!]/u).filter(Boolean)) {
    const subjects = subjectFor(clause), wishes = requestOrWish(clause), unsure = uncertainty(clause);
    for (const subject of subjects) {
      const explicitlyAbsent = new RegExp(`(?:没有|没带|没配|不见)(?:.{0,2})${aliases.find(alias => alias.kind === subject.kind)?.expression.source ?? '(?!)'}`, 'u').test(clause);
      if (explicitlyAbsent && !unsure) {
        if (lookBack || context.entities.some(entity => matches(subject, entity))) return deny('unsupported-absence');
        continue;
      }
      if (!allSubjects.some(actual => matches(subject, actual)) && !(wishes && !lookBack && context.entities.some(actual => matches(subject, actual)))) return deny('unsupported-subject');
    }
    for (const pattern of actionPatterns) {
      if (!pattern.expression.test(clause)) continue;
      // “还在往目标推进” asserts continuing movement, rather than a second
      // independent survival event. The actor must remain visible alive now.
      if (pattern.action === 'alive' && /还在|仍在/u.test(clause) && actionPatterns.some(other => ['advancing', 'retreating', 'fired'].includes(other.action) && other.expression.test(clause))) {
        if (!lookBack && subjects.length && !subjects.every(subject => context.entities.some(actual => matches(subject, actual)))) return deny('stale-continuing-action');
        continue;
      }
      if (pattern.action === 'loss' && subjects.some(subject => subject.kind === 'satchel')) continue;
      if (pattern.action === 'captured' && /这关|本关|任务|这一关|这段|这一段|拿下(?:了|啦|！|!|$)/u.test(clause)
        && !subjects.some(subject => subject.kind === 'mortar' || subject.kind === 'gunner')) continue;
      // Wishes and real uncertainty do not claim that the outcome happened;
      // mentioning an actor still requires that actor to exist in cited evidence.
      const negated = pattern.action !== 'alive' && /(?:还|并|根本|压根|也)?(?:没|未|不是|不算).{0,5}(?:打中|命中|炸|死|倒|灭|击毁|接管|抢到|拿下|完成|赢|失败)/u.test(clause);
      if (wishes || unsure || negated) {
        claims.push({ action: pattern.action, subjects, mode: wishes ? 'wish' : unsure ? 'question' : 'negated' });
        // A positive live tank is enough for “还没炸”, never for an explicit miss.
        if (!wishes && !unsure && /没(?:打中|命中)/u.test(clause)) return deny('unobserved-miss');
        if (!wishes && !unsure && negated) {
          if (['loss', 'all_eliminated'].includes(pattern.action) && subjects.length && !subjects.every(subject => context.entities.some(entity => matches(subject, entity)))) return deny('contradicted-negative-state');
          if (pattern.action === 'mission_completed' && context.scope.mission_status === 'completed'
            || pattern.action === 'mission_failed' && context.scope.mission_status === 'failed') return deny('contradicted-negative-result');
        }
        continue;
      }
      claims.push({ action: pattern.action, subjects, mode: lookBack ? 'retrospective' : 'assertion' });
      if (['hit', 'causal_kill', 'tactical_success', 'stalled'].includes(pattern.action)) return deny('unsupported-result');
      const supported = eligible.some(fact => fact.relations.some(relation => (relation.action === pattern.action || pattern.action === 'alive' && relation.action === 'present' && fact.temporal === 'current')
        && (subjects.length ? subjects.every(subject => relation.subjects.some(actual => matches(subject, actual))) : true)));
      if (!supported) return deny(lookBack ? 'unsupported-historical-action' : 'unsupported-action');
    }
  }
  return { accepted: true, reason: claims.length ? 'typed-claims-supported' : 'reaction-or-presence', claims };
}
