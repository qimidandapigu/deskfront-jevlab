import { completedForceDeployment, equipmentFaction, forceManifest } from './director-authorship.js';

type Row = Record<string, any>;
export interface ArrangementFact { id: string; text: string; evidence?: unknown }
export interface BuiltArrangement {
  runId: string; operationId: string; stage: number; coordinateFrame: 'stage_local_xz';
  forces?: Record<string, number>; routes?: { main: string[]; flank: string[]; fork: string };
  props?: Record<string, { count: number; positions: number[][] }>;
}
export interface ArrangementComparison {
  current: BuiltArrangement; previous?: BuiltArrangement;
  changes: ArrangementFact[]; facts: ArrangementFact[];
}
const row = (v: unknown): Row => v && typeof v === 'object' && !Array.isArray(v) ? v as Row : {};
const list = (v: unknown): Row[] => Array.isArray(v) && v.length <= 4096 ? v.map(row) : [];
const kinds: Record<string, string> = {
  book_atlas: '图册', bookstack: '书堆', concrete: '混凝土隔墙', desk_divider: '桌面隔断', drum: '圆桶',
  laptop: '笔记本电脑', mouse: '鼠标', phone: '手机', printer: '打印机', stapler: '订书机', tissues: '纸巾盒',
  warehouse: '纸盒', crate: '收纳盒', pipe: '管件', novel: '书本', ruler: '尺子', sandbag: '沙袋',
  file_rack: '文件架', tape: '胶带', calculator: '计算器',
};
const cells = (v: unknown): string[] | undefined => Array.isArray(v) && v.length >= 2 && v.length <= 9
  && v.every(x => typeof x === 'string' && /^c[0-2]r[0-2]$/u.test(x)) && new Set(v).size === v.length ? [...v] : undefined;
const location = (cell: string) => {
  const match = /^c([0-2])r([0-2])$/u.exec(cell);
  return match ? (cell === 'c1r1' ? '中央桌面' : `${['左侧', '中列', '右侧'][Number(match[1])]}${['上方', '中部', '下方'][Number(match[2])]}桌面`) : '';
};
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

function built(world: Row, receipt: Row, stage: number, spec: Row): BuiltArrangement {
  const result: BuiltArrangement = { runId: world.run_id, operationId: receipt.operation_id, stage, coordinateFrame: 'stage_local_xz' };
  if (completedForceDeployment(receipt)) {
    const manifest = forceManifest(receipt.force_manifest)!;
    const counts: Record<string, number> = {};
    const crewSlots = new Set(manifest.equipment.flatMap(gun => gun.crew_slot_ids));
    for (const group of ['enemies', 'reinforcements', 'captives'] as const) {
      for (const unit of manifest[group]) {
        const key = group + ':' + (unit.kind === 'tank' ? 'tank' : crewSlots.has(unit.slot_id) ? 'mortar_crew' : unit.weapon);
        counts[key] = (counts[key] ?? 0) + 1;
      }
    }
    for (const side of ['red', 'green'] as const) counts[`equipment_${side}:mortar`] = manifest.equipment.filter(gun => equipmentFaction(manifest, gun) === side).length;
    result.forces = counts;
  }
  // These coordinates come only from the native built region_graph spec, not
  // world-space actors, a planner draft or a new navigation query.
  if (spec.assembly_kind !== 'region_graph_v1') return result;
  const card = row(spec.design_card), main = cells(card.main_regions), flank = cells(card.flank_regions);
  if (card.alternate_route === true && main && flank && main[0] === flank[0] && main.at(-1) === flank.at(-1) && !same(main, flank)) {
    let shared = 0;
    while (shared < Math.min(main.length, flank.length) && main[shared] === flank[shared]) shared++;
    result.routes = { main, flank, fork: main[Math.max(0, shared - 1)]! };
  }
  if (Array.isArray(spec.covers) && spec.covers.length <= 128 && spec.covers.every((p: unknown) => Array.isArray(p)
    && p.length >= 5 && [p[0], p[1], p[2], p[3]].every(Number.isFinite) && p[2] > 0 && p[3] > 0 && typeof p[4] === 'string')) {
    result.props = {};
    for (const p of spec.covers) {
      if (!kinds[p[4]]) continue;
      const prop = result.props[p[4]] ??= { count: 0, positions: [] };
      prop.count++; prop.positions.push([p[0], p[1]]);
    }
    for (const prop of Object.values(result.props)) prop.positions.sort((a,b)=>a[0]!-b[0]! || a[1]!-b[1]!);
  }
  return result;
}

const forceLabel = (key: string) => {
  const [group, kind] = key.split(':');
  const name = ({ rifle: '步枪兵', smg: '冲锋枪兵', rocket: '火箭筒兵', tank: '坦克', mortar: '迫击炮', mortar_crew: '迫击炮手' } as Record<string,string>)[kind!];
  return name ? (group === 'enemies' ? '守军中的' : group === 'reinforcements' ? '友军增援中的' : group === 'captives' ? '待救援的'
    : group === 'equipment_green' ? '友方' : group === 'equipment_red' ? '敌方' : '') + name : undefined;
};
const unit = (key: string) => key.endsWith(':tank') ? '辆' : key.startsWith('equipment') ? '门' : '名';

/** Small, identity-bound before/after evidence. Unavailable old data stays unknown. */
export function presenterArrangements(world: Row, receipt: Row | undefined, stage: number): ArrangementComparison | undefined {
  if (!receipt || typeof receipt.operation_id !== 'string') return undefined;
  const growth = row(world.world_growth), mission = row(growth.mission);
  const current = built(world, receipt, stage, row(mission.spec));
  const previousRows = list(growth.completed).filter(r => r.index === stage - 2 && r.operation_id !== receipt.operation_id
    && typeof r.operation_id === 'string' && (r.run_id === undefined || r.run_id === world.run_id));
  // Conflicting history cannot authorize a comparison.
  const previousReceipt = previousRows.length === 1 ? previousRows[0] : undefined;
  const previous = previousReceipt ? built(world, previousReceipt, stage - 1, row(previousReceipt.design ?? previousReceipt.spec)) : undefined;
  const facts: ArrangementFact[] = [], changes: ArrangementFact[] = [];
  if (current.routes) {
    const fork = current.routes.fork === current.routes.main[0] ? '入口这张桌面' : location(current.routes.fork);
    facts.push({ id: 'director-layout-detail', text: `这关两条通路在${fork}分开，再在${location(current.routes.main.at(-1)!)}汇合。`,
      evidence: { source: 'native_mission.spec.design_card', coordinateFrame: current.coordinateFrame, ...current.routes } });
  }
  if (current.props) {
    for (const [kind, value] of Object.entries(current.props)) facts.push({ id: 'director-prop-' + kind,
      text: `这关建成的桌面摆了${value.count}件${kinds[kind]}。`,
      evidence: { source: 'native_mission.spec.covers', coordinateFrame: current.coordinateFrame, kind, ...value } });
  }
  const add = (id: string, text: string, before: unknown, after: unknown) => changes.push({ id: 'director-change-' + id, text,
    evidence: { kind: id, beforeOperation: previous?.operationId, afterOperation: current.operationId, before, after, coordinateFrame: current.coordinateFrame } });
  if (previous?.forces && current.forces) {
    for (const key of [...new Set([...Object.keys(previous.forces), ...Object.keys(current.forces)])].sort()) {
      const before = previous.forces[key] ?? 0, after = current.forces[key] ?? 0, label = forceLabel(key);
      if (label && before !== after) add('force-' + key.replace(':','-'), `和上一关建成时相比，${label}从${before}${unit(key)}变成${after}${unit(key)}。`, before, after);
    }
  }
  if (previous?.routes && current.routes && previous.routes.fork !== current.routes.fork) {
    add('route-fork', `上一关的通路在${location(previous.routes.fork)}分开，这关改在${current.routes.fork === current.routes.main[0] ? '入口这张桌面' : location(current.routes.fork)}分开。`, previous.routes, current.routes);
  }
  if (previous?.props && current.props) {
    for (const kind of [...new Set([...Object.keys(previous.props), ...Object.keys(current.props)])].sort()) {
      const before = previous.props[kind]?.count ?? 0, after = current.props[kind]?.count ?? 0;
      if (before !== after) add('prop-' + kind, `和上一关相比，${kinds[kind]}从${before}件变成${after}件。`, before, after);
      // Positions stay attached to current native evidence. Without native
      // prop identity / table bounds, coordinate jitter cannot authorize a
      // claim that a particular object moved to a different table.
    }
  }
  if (!current.forces && !facts.length) return undefined;
  return { current, ...(previous ? { previous } : {}), changes: changes.slice(0, 8), facts: facts.slice(0, 8) };
}
