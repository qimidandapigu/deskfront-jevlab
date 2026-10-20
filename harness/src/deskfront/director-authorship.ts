/** Read-only evidence for the director's exact authored order and its native receipt. */
type Row = Record<string, any>;
export type AuthorshipFact = { id: string; text: string; evidence?: unknown };
const row = (v: unknown): Row => v && typeof v === 'object' && !Array.isArray(v) ? v as Row : {};
const identifier = (v: unknown): v is string => typeof v === 'string' && /^[a-zA-Z0-9_.:-]{1,160}$/u.test(v);
const slotIdentifier = (v: unknown): v is string => typeof v === 'string' && /^[a-zA-Z0-9_-]{1,64}$/u.test(v);
const wholeText = (v: unknown): string => typeof v === 'string' && v.trim() && v.length <= 600
  && !/[\u0000-\u001f\u007f-\u009f]/u.test(v) ? v.trim() : '';
// Parsing resource bound, independent of the engine's configurable spawn budget.
const EVIDENCE_ROWS = 4096;
const array = (v: unknown): Row[] | undefined => Array.isArray(v) && v.length <= EVIDENCE_ROWS && v.every(x => x && typeof x === 'object' && !Array.isArray(x)) ? v : undefined;
const weapons = new Set(['rifle', 'smg', 'rocket']);
export interface ForceManifest { schema: 'deskfront-forces/v1'; enemies: Row[]; reinforcements: Row[]; captives: Row[]; equipment: Row[] }

/** Equipment ownership follows its real crew roster; a free-form owner cannot override it. */
export function equipmentFaction(manifest: ForceManifest, gun: Row): 'red' | 'green' | undefined {
  const ids = gun.crew_slot_ids;
  if (!Array.isArray(ids) || !ids.length) return undefined;
  if (ids.every(id => manifest.enemies.some(u => u.slot_id === id && u.kind === 'infantry'))) return 'red';
  if (ids.every(id => manifest.reinforcements.some(u => u.slot_id === id && u.kind === 'infantry'))) return 'green';
  return undefined;
}

export function forceManifest(value: unknown): ForceManifest | undefined {
  const m = row(value), enemies = array(m.enemies), reinforcements = array(m.reinforcements), captives = array(m.captives ?? []), equipment = array(m.equipment);
  if (m.schema !== 'deskfront-forces/v1' || !enemies || !reinforcements || !captives || !equipment) return undefined;
  const all = [...enemies, ...reinforcements, ...captives, ...equipment];
  if (!all.every(u => slotIdentifier(u.slot_id)) || new Set(all.map(u => u.slot_id)).size !== all.length) return undefined;
  if (![...enemies, ...reinforcements].every(u => u.kind === 'tank' && u.weapon == null || u.kind === 'infantry' && weapons.has(u.weapon))
    || !captives.every(u => u.kind === 'infantry' && u.weapon === 'rifle')) return undefined;
  const crews = new Set<string>();
  for (const gun of equipment) {
    if (gun.kind !== 'mortar' || !Array.isArray(gun.crew_slot_ids) || gun.crew_slot_ids.length < 1 || gun.crew_slot_ids.length > 2) return undefined;
    for (const id of gun.crew_slot_ids) {
      if (!slotIdentifier(id) || crews.has(id)) return undefined;
      crews.add(id);
    }
    if (!equipmentFaction({ schema: 'deskfront-forces/v1', enemies, reinforcements, captives, equipment }, gun)) return undefined;
  }
  return { schema: 'deskfront-forces/v1', enemies, reinforcements, captives, equipment };
}

function forceSummary(units: Row[]): string {
  const tanks = units.filter(u => u.kind === 'tank').length, infantry = units.length - tanks;
  return [infantry ? `${infantry}名步兵` : '', tanks ? `${tanks}辆坦克` : ''].filter(Boolean).join('、') || '0个单位';
}
export function manifestSummary(value: unknown): string | undefined {
  const m = forceManifest(value);
  return m ? `敌方共${m.enemies.length}个单位（${forceSummary(m.enemies)}）；友军增援${m.reinforcements.length}个单位（${forceSummary(m.reinforcements)}）`
    + (m.captives.length ? `；${m.captives.length}名待救援队员（不计入入场增援）` : '')
    + (m.equipment.length ? '；' + ['red', 'green'].flatMap(side => {
      const count = m.equipment.filter(gun => equipmentFaction(m, gun) === side).length;
      return count ? [`${side === 'red' ? '敌方' : '友方'}${count}门迫击炮，炮手已包含在${side === 'red' ? '敌方' : '友军增援'}人数中`] : [];
    }).join('；') : '') : undefined;
}

function spokenNumber(value: string): number {
  if (/^\d+$/u.test(value)) return Number(value);
  const digits: Record<string, number> = { 零: 0, 〇: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
  if (value === '十') return 10;
  if (value.includes('十')) { const [tens, ones] = value.split('十'); return (tens ? digits[tens]! : 1) * 10 + (ones ? digits[ones]! : 0); }
  return digits[value] ?? NaN;
}

/** Narrow count/ownership guard. Writer evidence checks still own arbitrary prose. */
export function forceNumbersGrounded(text: string, facts: AuthorshipFact[]): boolean {
  const evidence = facts.filter(f => /(?:^director-(?:deployment|composition|reinforcements|deployed-support|support|friendly-support)$|(?:^director|experience-(?:current|plan))-authored-(?:enemies|reinforcements|equipment)$)/u.test(f.id));
  const changeEvidence = facts.filter(f => f.id.startsWith('director-change-force-')).flatMap(f => {
    const e = row(f.evidence);
    const label = typeof e.kind === 'string' && e.kind.endsWith('-tank') ? '辆坦克'
      : /^force-equipment(?:_red|_green)?-mortar$/u.test(e.kind) ? '门迫击炮' : typeof e.kind === 'string' && e.kind.endsWith('-mortar_crew') ? '名迫击炮手' : '';
    return label && Number.isSafeInteger(e.before) && Number.isSafeInteger(e.after) ? [{ id: f.id, text: `${e.before}${label}、${e.after}${label}` }] : [];
  });
  evidence.push(...changeEvidence);
  const number = '([0-9零〇一二两三四五六七八九十]+)';
  // A friendly mortar is not evidence for an enemy mortar (or vice versa).
  // Only explicit side/count claims are checked here; free prose remains the
  // writer's evidence responsibility.
  const sideOf = (part: string): 'red' | 'green' | undefined => {
    const names = [...part.matchAll(/红(?:方|队|军)|敌(?:方|军)|守军|绿(?:方|队|军)|友(?:方|军)|我方/gu)];
    const name = names.at(-1)?.[0];
    return name ? /^(?:红|敌|守)/u.test(name) ? 'red' : 'green' : undefined;
  };
  for (const clause of text.split(/[。；;！？]/u)) {
    for (const match of clause.matchAll(new RegExp(number + '(?:辆|台|门)(坦克|迫击炮)', 'gu'))) {
      const side = sideOf(clause.slice(0, match.index)), wanted = spokenNumber(match[1]!);
      if (!side) continue;
      const available = evidence.flatMap(f => f.text.split(/[。；;]/u).flatMap(part => {
        const implicit = /reinforcements|friendly-support/u.test(f.id) ? 'green'
          : /(?:composition|deployment|support|authored-enemies)$/u.test(f.id) ? 'red' : undefined;
        const values = [...part.matchAll(new RegExp(number + '(?:辆|台|门)' + match[2], 'gu'))]
          .filter(m => (sideOf(part.slice(0, m.index)) ?? implicit) === side).map(m => spokenNumber(m[1]!));
        if (match[2] === '迫击炮' && /迫击炮/u.test(part) && (sideOf(part) ?? implicit) === side)
          values.push(...[...part.matchAll(new RegExp('共' + number + '门', 'gu'))].map(m => spokenNumber(m[1]!)));
        return values;
      }));
      if (!available.includes(wanted)) return false;
    }
  }
  for (const suffix of ['(?:辆|台)坦克', '门迫击炮', '(?:名|个)迫击炮手']) {
    const mentions = [...text.matchAll(new RegExp(number + suffix, 'gu'))].map(m => spokenNumber(m[1]!));
    if (!mentions.length) continue;
    const available = evidence.flatMap(f => [...f.text.matchAll(new RegExp(number + suffix, 'gu'))].map(m => spokenNumber(m[1]!)));
    // Native current support historically uses "共N门" after the noun.
    if (suffix === '门迫击炮') for (const f of evidence.filter(f => /迫击炮/u.test(f.text))) {
      available.push(...[...f.text.matchAll(new RegExp('共' + number + '门', 'gu'))].map(m => spokenNumber(m[1]!)));
    }
    if (mentions.some(n => !Number.isFinite(n) || !available.includes(n))) return false;
  }
  // Names and vehicles cannot be swapped or added twice. Enemy/allied counts
  // are checked against their own evidence even when both sides have infantry.
  for (const [suffix, applicable, factSuffix] of [
    ['(?:名|个)(?:(?:敌方|敌军|敌)(?:步兵|守军|敌兵)|守军|敌兵)', evidence.filter(f => !/reinforcements/u.test(f.id)), '(?:名|个)(?:步兵|守军|敌兵)'],
    ['(?:名|个)(?:友军|绿色|绿方)?(?:补员|补兵|援军)', evidence.filter(f => /reinforcements/u.test(f.id)), '(?:名|个)(?:步兵|友军增援)'],
  ] as const) {
    const mentions = [...text.matchAll(new RegExp(number + suffix, 'gu'))].map(m => spokenNumber(m[1]!));
    if (!mentions.length) continue;
    const available = applicable.flatMap(f => [...f.text.matchAll(new RegExp(number + factSuffix, 'gu'))].map(m => spokenNumber(m[1]!)));
    if (mentions.some(n => !Number.isFinite(n) || !available.includes(n))) return false;
  }
  if (/我(?:这次|这回|已经|亲自)?(?:决定|选定|选择|指定|要求)/u.test(text)) {
    if (!facts.some(f => /-authored-(?:order|enemies|reinforcements|equipment|goal|layout)$/u.test(f.id))) return false;
    if (/敌兵|守军|敌方/u.test(text) && !facts.some(f => /-authored-enemies$/u.test(f.id))) return false;
    if (/坦克/u.test(text) && !facts.some(f => /-authored-(?:enemies|reinforcements)$/u.test(f.id))) return false;
    if (/增援|援军|补员/u.test(text) && !facts.some(f => /-authored-reinforcements$/u.test(f.id))) return false;
    if (/迫击炮/u.test(text) && !facts.some(f => /-authored-equipment$/u.test(f.id))) return false;
  }
  return true;
}

function signature(units: Row[]): string {
  return units.map(u => `${u.slot_id}:${u.kind}:${u.kind === 'infantry' ? u.weapon : ''}`).sort().join('|');
}
function fixedUnits(value: unknown, prefix: string): Row[] | undefined {
  const field = row(value), groups = array(field.groups);
  if (field.mode !== 'fixed' || !groups || new Set(groups.map(g => g.group_id)).size !== groups.length) return undefined;
  if (!groups.every(g => slotIdentifier(g.group_id) && g.group_id.length <= 48 && Number.isSafeInteger(g.count) && g.count >= 0 && g.count <= EVIDENCE_ROWS
    && (g.kind === 'tank' && g.weapon == null || g.kind === 'infantry' && weapons.has(g.weapon)))) return undefined;
  if (groups.reduce((n, g) => n + g.count, 0) > EVIDENCE_ROWS) return undefined;
  return groups.flatMap(g => Array.from({ length: g.count }, (_, i) => ({ ...g, slot_id: `${prefix}-${g.group_id}-${i + 1}` })));
}

/** Native success is exact, not a promise inferred from the requested count. */
export function completedForceDeployment(value: unknown): boolean {
  const receipt = row(value), m = forceManifest(receipt.force_manifest), d = row(receipt.force_deployment);
  const units = array(d.units), equipment = array(d.equipment);
  if (!m || d.schema !== 'deskfront-force-receipt/v1' || d.status !== 'completed' || !units || !equipment
    || units.length !== m.enemies.length + m.reinforcements.length + m.captives.length || equipment.length !== m.equipment.length) return false;
  if (!['assault', 'rescue'].includes(receipt.mission_kind) || m.captives.length !== (receipt.mission_kind === 'rescue' ? 1 : 0)) return false;
  const all = [...units, ...equipment];
  if (!all.every(u => identifier(u.entity_id) && slotIdentifier(u.slot_id))
    || new Set(all.map(u => u.entity_id)).size !== all.length || new Set(all.map(u => u.slot_id)).size !== all.length) return false;
  if (!units.every(u => Array.isArray(u.position) && u.position.length === 2 && u.position.every((n: unknown) => typeof n === 'number' && Number.isFinite(n)))) return false;
  for (const [list, faction, roster] of [[m.enemies, 'red', receipt.spawned], [m.reinforcements, 'green', receipt.friendly_spawned],
    [m.captives, 'green', receipt.captive_id ? [receipt.captive_id] : []]] as const) {
    if (!Array.isArray(roster) || roster.length !== list.length || new Set(roster).size !== roster.length) return false;
    for (const slot of list) {
      const u = units.find(u => u.slot_id === slot.slot_id);
      if (!u || u.faction !== faction || u.kind !== slot.kind || slot.kind === 'infantry' && u.weapon !== slot.weapon || !roster.includes(u.entity_id)) return false;
      if (u.group !== (list === m.enemies ? 'enemies' : list === m.reinforcements ? 'reinforcements' : 'captives')) return false;
      if (list === m.captives && u.role !== 'captive' || list !== m.captives && u.role === 'captive') return false;
    }
  }
  for (const slot of m.equipment) {
    const gun = equipment.find(g => g.slot_id === slot.slot_id);
    if (!gun || gun.kind !== 'mortar' || !Array.isArray(gun.crew_slot_ids) || !Array.isArray(gun.crew_entity_ids)
      || [...gun.crew_slot_ids].sort().join('|') !== [...slot.crew_slot_ids].sort().join('|')) return false;
    const faction = equipmentFaction(m, slot);
    // Historical red-only receipts omitted faction. A new friendly deployment
    // needs explicit green acknowledgement; crew intent alone is not a receipt.
    if (!faction || faction === 'green' && gun.faction !== 'green'
      || gun.faction !== undefined && gun.faction !== faction) return false;
    const ids = slot.crew_slot_ids.map((id: string) => units.find(u => u.slot_id === id)?.entity_id).sort();
    if ([...gun.crew_entity_ids].sort().join('|') !== ids.join('|')) return false;
  }
  return true;
}

/** Only fixed fields belong to the director; delegated choices retain their owner. */
export function directorAuthorshipFacts(value: unknown, prefix: string, built: boolean,
  scope: { runId: string; operationId?: string; instanceId?: string }): AuthorshipFact[] {
  const record = row(value), order = row(record.director_order), authority = row(record.generation_authority), source = row(authority.source_scope);
  const m = forceManifest(record.force_manifest);
  if (order.schema !== 'director-content/v1' || order.origin !== 'director' || !identifier(order.order_id)
    || !identifier(order.source_report_id) || record.director_order_id !== order.order_id || authority.order_id !== order.order_id
    || authority.source_report_id !== order.source_report_id || source.run_id !== scope.runId
    || scope.instanceId && source.instance_id !== scope.instanceId
    || scope.operationId && record.operation_id !== scope.operationId || !m) return [];
  const fixed = ['mission_kind', 'enemies', 'reinforcements', 'equipment'].filter(k => row(order[k]).mode === 'fixed');
  const delegated = ['mission_kind', 'enemies', 'reinforcements', 'equipment'].filter(k => row(order[k]).mode === 'delegate');
  if (fixed.length + delegated.length !== 4 || !Array.isArray(authority.explicit_fields) || !Array.isArray(authority.delegated_fields)
    || [...authority.explicit_fields].sort().join('|') !== [...fixed].sort().join('|')
    || [...authority.delegated_fields].sort().join('|') !== [...delegated].sort().join('|')) return [];
  for (const key of ['enemies', 'reinforcements'] as const) {
    if (row(order[key]).mode === 'fixed') {
      const requested = fixedUnits(order[key], key === 'enemies' ? 'e' : 'r');
      if (!requested || signature(requested) !== signature(m[key])) return [];
    }
  }
  if (row(order.equipment).mode === 'fixed') {
    const items = array(order.equipment.items);
    if (!items || items.length !== m.equipment.length) return [];
    const seen = new Set<string>();
    for (const item of items) {
      if (!slotIdentifier(item.slot_id) || seen.has(item.slot_id) || item.kind !== 'mortar') return [];
      seen.add(item.slot_id);
      const actual = m.equipment.find(u => u.slot_id === item.slot_id);
      let crew = item.crew_slot_ids;
      if (crew === undefined && Array.isArray(item.crew_group_ids)) {
        const pool = equipmentFaction(m, actual ?? {}) === 'green' ? m.reinforcements : m.enemies;
        const prefix = pool === m.reinforcements ? 'r' : 'e';
        if (!item.crew_group_ids.every((group: unknown) => slotIdentifier(group) && group.length <= 48
          && pool.some(u => u.slot_id.startsWith(`${prefix}-${group}-`) && /^\d+$/u.test(u.slot_id.slice(`${prefix}-${group}-`.length))))) return [];
        crew = item.crew_group_ids.flatMap((group: unknown) => typeof group === 'string'
          ? pool.filter(u => u.slot_id.startsWith(`${prefix}-${group}-`) && /^\d+$/u.test(u.slot_id.slice(`${prefix}-${group}-`.length))).map(u => u.slot_id) : []);
      }
      if (!actual || !Array.isArray(crew) || crew.length !== actual.crew_slot_ids.length
        || [...crew].sort().join('|') !== [...actual.crew_slot_ids].sort().join('|')) return [];
    }
  }
  if (row(order.mission_kind).mode === 'fixed' && (!['assault', 'rescue'].includes(order.mission_kind.value)
    || record.mission_kind !== order.mission_kind.value)) return [];
  if (built && !completedForceDeployment(record)) return [];
  const facts: AuthorshipFact[] = [];
  const status = built ? '同一指令已获本关原生逐项部署回执确认' : '这是导演已明确下达的原始安排，尚未建成';
  facts.push({ id: `${prefix}-authored-order`, text: `${status}；指令编号${order.order_id}。` });
  if (fixed.includes('enemies')) facts.push({ id: `${prefix}-authored-enemies`, text: `导演原始指令明确指定敌方共${m.enemies.length}个单位：${forceSummary(m.enemies)}。` });
  if (fixed.includes('reinforcements')) facts.push({ id: `${prefix}-authored-reinforcements`, text: `导演原始指令明确指定友军增援${m.reinforcements.length}个单位：${forceSummary(m.reinforcements)}。` });
  if (fixed.includes('equipment')) facts.push({ id: `${prefix}-authored-equipment`, text: m.equipment.length
    ? '导演原始指令明确指定' + ['red', 'green'].flatMap(side => {
      const count = m.equipment.filter(gun => equipmentFaction(m, gun) === side).length;
      return count ? [`${side === 'red' ? '敌方' : '友方'}${count}门迫击炮；炮手计入${side === 'red' ? '敌方' : '友军增援'}人数，不额外生成`] : [];
    }).join('；') + '。' : '导演原始指令明确指定0门迫击炮。' });
  if (delegated.length) facts.push({ id: `${prefix}-delegated-fields`, text: `导演交给生成器补全的项目：${delegated.join('、')}。这些结果不能说成导演事先指定的数量或配置。` });
  const goal = wholeText(order.experience_goal), layout = wholeText(order.layout_intent);
  if (goal) facts.push({ id: `${prefix}-authored-goal`, text: '该原始指令希望带来的体验（期望，不是已达成结果）：' + goal });
  if (layout) facts.push({ id: `${prefix}-authored-layout`, text: '该原始指令给搭建器的空间意图（意图不等于几何验证）：' + layout });
  return facts;
}
