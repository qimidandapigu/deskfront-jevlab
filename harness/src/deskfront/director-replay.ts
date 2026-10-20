/** Read-only replay of recorded decisions. No generator, model or navigation calls. */
import { completedForceDeployment, equipmentFaction, forceManifest } from './director-authorship.js';
export type ReplayCell = { id: string; template: string; rotation: number | null };
export type ReplayFrame = {
  id: string; title: string; text: string; phase: number; source: string; kind: string;
  covers: (string | number)[][]; routes: { main: number[][]; flank: number[][] };
  cells: ReplayCell[]; connections: string[]; entry: string; exit: string;
  batchId?: string; focusCells?: string[]; focusConnections?: string[];
};
const txt = (v: unknown, limit = 2400) => typeof v === 'string' ? v.slice(0, limit) : '';
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const cellId = (v: unknown): v is string => typeof v === 'string' && /^c[0-2]r[0-2]$/.test(v);
const edgeId = (v: unknown): v is string => typeof v === 'string' && /^c[0-2]r[0-2]__c[0-2]r[0-2]$/.test(v);
const list = (v: any): any[] => Array.isArray(v) ? v : [];
const cells = (v: any): ReplayCell[] => list(v).filter(c => cellId(c?.id)).slice(0, 9).map(c => ({ id: c.id, template: txt(c.template, 120), rotation: finite(c.rotation) ? c.rotation : null }));
const edges = (v: any): string[] => [...new Set(list(v).filter(edgeId))].slice(0, 36);
const cellLabel = (id: string) => `桌面 ${Number(id[3]) * 3 + Number(id[1]) + 1}`;
const sameCell = (a: ReplayCell | undefined, b: ReplayCell) => a?.template === b.template && a?.rotation === b.rotation;
const batchSource = '真实批次操作 · 同批动作分步展示，非引擎施工顺序';

const token = (v: unknown) => typeof v === 'string' && /^[a-zA-Z0-9_:-]{1,160}$/.test(v) ? v : '';
const point = (v: any): number[] | null => Array.isArray(v) && v.length === 2 && v.every(n => finite(n) && Math.abs(n) <= 1000) ? [...v] : null;
/** Reject an entire malformed path: removing a waypoint would invent a segment. */
const route = (v: any, limit = 1024): number[][] => {
  if (!Array.isArray(v) || v.length > limit || v.some(p => !point(p))) return [];
  return v.map(p => [...p]);
};
const coverRows = (v: any): (string | number)[][] | null => {
  if (!Array.isArray(v) || v.length > 200 || v.some(p => !Array.isArray(p) || p.length !== 6
    || !token(p[4]) || p[4].length > 64 || ![p[0],p[1],p[2],p[3],p[5]].every(n => finite(n) && Math.abs(n) <= 1000)
    || p[2] <= 0 || p[3] <= 0 || p[5] <= 0)) return null;
  return v.map(p => [...p]);
};
const floorRows = (v: any): number[][] => Array.isArray(v) && v.length <= 64 && v.every(p => Array.isArray(p)
  && p.length === 4 && p.every(n => finite(n) && Math.abs(n) <= 1000) && p[2] > p[0] && p[3] > p[1]) ? v.map(p => [...p]) : [];
function displayRoutes(main: any, flank: any, source: string) {
  const a = route(main), b = route(flank), shared = !!a.length && !!b.length && JSON.stringify(a) === JSON.stringify(b);
  return { main: a, flank: shared ? [] : b, shared, source, start: 21, duration: 3.5, meaning: '规划通路，不是小兵实战行走轨迹' };
}
const unitSources = new Set(['completed_deployment', 'completed_captive_deployment', 'early_engine_observation', 'recorded_engine_deployment']);
function displayUnits(value: any) {
  return list(value).slice(0, 128).flatMap((u, i) => {
    const position = point(u?.position), id = token(u?.id);
    if (!id || !position || position[0]! < 0 || position[0]! > 1.8 || Math.abs(position[1]!) > 1.05
      || !['green','red'].includes(u.faction) || !['infantry','tank','mortar'].includes(u.kind) || !unitSources.has(u.source)) return [];
    return [{ id, faction: u.faction, kind: u.kind, weapon: token(u.weapon), position,
      posture: ['stand','crouch','prone'].includes(u.posture) ? u.posture : '', source: u.source,
      observedAt: finite(u.observedAt) ? u.observedAt : null, weaponKnown: u.weaponKnown !== false && !!token(u.weapon),
      role: txt(u.role,80), start: 24.5 + Math.min(i * .26, 3.5) }];
  });
}
/** Geometry is already compiled/recorded. This function never compiles or queries navigation. */
export function assemblyGeometry(g: any, source: string, engineConfirmed = false, batchId = '') {
  // Legacy 2D projections may omit bad rows. Such a partial projection must not
  // silently become a complete layout in the native assembly presentation.
  if (g?.assembly_usable === false) return null;
  const covers = coverRows(g?.covers);
  if (covers === null) return null;
  const candidates = list(g?.defender_slots).slice(0,16).flatMap(r => Array.isArray(r) && r.length === 4 && point(r.slice(0,2)) && token(r[2])
    ? [{ position: r.slice(0,2), weapon: token(r[2]), role: txt(r[3],80) }] : []);
  return { covers, floors: floorRows(g.floors), source, engineConfirmed, batchId: token(batchId),
    routes: displayRoutes(g.main_route, g.flank, engineConfirmed ? 'completed_design_geometry' : 'recorded_builder_geometry'),
    entry: point(g.entry), exit: point(g.exit), units: [] as ReturnType<typeof displayUnits>,
    candidateSlots: { defenders: candidates, friendly: route(g.friendly_slots,16), meaning: '候选站位，不是已经部署的小兵' },
    visualPattern: token(g.visual_pattern || g.design_card?.visual_pattern),
    mainRegions: list(g.main_regions || g.design_card?.main_regions).filter(cellId).slice(0,9) };
}

/** Preserve the legacy display whitelist while recording whether it is complete. */
function recordedGeometry(g: any) {
  if (g?.source !== 'builder_compiled_spec') return null;
  // Older records can carry private trailing columns; only the six public
  // geometry columns belong to either display. Never copy those extra fields.
  const rawCovers = list(g.covers).map(p => Array.isArray(p) ? p.slice(0,6) : p);
  const completeCovers = Array.isArray(g.covers) ? coverRows(rawCovers) : null;
  const covers = rawCovers.slice(0,200).flatMap(p => coverRows([p]) || []);
  const floors = list(g.floors).slice(0,64).flatMap(p => floorRows([p]));
  const completeFloors = g.floors === undefined || (Array.isArray(g.floors)
    && g.floors.length <= 64 && floors.length === g.floors.length);
  return {
    version:g.version === 2 ? 2 : 1, source:'builder_compiled_spec', display_only:true, engine_confirmed:false,
    assembly_usable:completeCovers !== null && completeFloors,
    covers, floors, visual_pattern:txt(g.visual_pattern,64), main_regions:list(g.main_regions).filter(cellId).slice(0,9),
    main_route:route(g.main_route), flank:route(g.flank), entry:point(g.entry), exit:point(g.exit),
    defender_slots:list(g.defender_slots).slice(0,16).filter(p=>Array.isArray(p)&&p.length===4&&point(p.slice(0,2))&&token(p[2])).map(p=>[p[0],p[1],token(p[2]),txt(p[3],80)]),
    friendly_slots:route(g.friendly_slots,16), deployment_basis:'candidate_slots_not_spawned_units',
  };
}

/** One read-only 3D assembly record. Missing drafts never borrow final geometry. */
export function recordedAssembly(r: any, buildSteps: any[], cached: any = null) {
  const steps = list(buildSteps).slice(0,16);
  const batch = (b: any) => {
    if (!b) return null;
    if (b.geometry?.source === 'builder_compiled_spec') return assemblyGeometry(b.geometry, 'builder_compiled_spec', false, b.id);
    const saved = cached?.batches?.find((row: any) => row.id === b.id);
    return saved ? assemblyGeometry({ covers: saved.covers }, 'offline_reconstruction_cache', false, b.id) : null;
  };
  const draft = batch(steps.find(b => b.stage === 'layout_draft'));
  const revision = batch([...steps].reverse().find(b => b.stage === 'batch_revision'));
  const completed = r.status === 'completed' && r.construction;
  const final = completed ? assemblyGeometry(r.construction.design, 'completed_engine_receipt', true) : null;
  // The 30-second presentation contains a confirmed-layout chapter. Until an
  // actual final receipt exists, keep the ordinary progress replay instead.
  if (!final) return null;
  const c = completed || {}, spec = c.design || {}, ids = list(c.spawned).filter(token).slice(0,128);
  const nativeUnits: any[] = [];
  const exact = completedForceDeployment(c), frame = c.force_deployment?.coordinate_frame;
  const nativeOrigin = exact && frame?.kind === 'world_xz' ? point(frame.stage_origin) : null;
  if (nativeOrigin) {
    const local = (p: number[]) => [p[0]! - nativeOrigin[0]!, p[1]! - nativeOrigin[1]!];
    for (const u of c.force_deployment.units) nativeUnits.push({ id:u.entity_id,faction:u.faction,kind:u.kind,
      weapon:u.weapon,position:local(u.position),role:u.role,source:u.role === 'captive' ? 'completed_captive_deployment' : 'completed_deployment' });
    const manifest = forceManifest(c.force_manifest)!;
    for (const u of c.force_deployment.equipment) if (point(u.position)) nativeUnits.push({ id:u.entity_id,
      faction:equipmentFaction(manifest, manifest.equipment.find(gun => gun.slot_id === u.slot_id)!),kind:'mortar',
      weapon:'mortar',position:local(u.position),source:'completed_deployment' });
  }
  // The saved native naming contract provides the exact defender-to-slot link;
  // require that ID in the authoritative spawned receipt, never use spare slots.
  if (!exact && final && Number.isInteger(c.index) && c.index >= 0) list(spec.defenders).slice(0,16).forEach((row, i) => {
    const id = `red-${100 + c.index * 10 + i}`;
    if (Array.isArray(row) && ids.includes(id)) nativeUnits.push({ id, faction:'red',kind:'infantry',weapon:row[2],position:row.slice(0,2),role:row[3],source:'completed_deployment' });
  });
  if (!exact && final) list(spec.friendlies).slice(0,16).forEach((position, i) => {
    const id = list(c.friendly_spawned)[i];
    if (token(id)) nativeUnits.push({ id,faction:'green',kind:'infantry',weapon:'',weaponKnown:false,position,source:'completed_deployment' });
  });
  if (!exact && final && token(c.captive_id) && point(spec.rescue?.captive)) nativeUnits.push({ id:c.captive_id,faction:'green',kind:'infantry',weapon:'',weaponKnown:false,position:spec.rescue.captive,role:'待救援',source:'completed_captive_deployment' });
  const units = final ? displayUnits(cached?.deployment?.units || nativeUnits) : [];
  if (final) final.units = units.map(u => ({ ...u, position:[...u.position] }));
  const omitted = list(cached?.deployment?.omitted).slice(0,32).flatMap(u => token(u?.id) && ['green','red'].includes(u.faction) && point(u.position)
    ? [{ id:token(u.id),faction:u.faction,position:point(u.position),reason:token(u.reason) }] : []);
  const origin = nativeOrigin ?? point(cached?.deployment?.coordinateFrame?.worldOrigin);
  return { version:1, operationId:token(r.operation_id), status:txt(r.status,80), source:'recorded_assembly_facts',
    coordinateFrame:{ kind:'stage_local_xz', ...(origin ? { worldOrigin:origin } : {}) },
    draft, revision, final, routes:final?.routes || displayRoutes([],[],'unavailable'), units, duration:30,
    deployment:{ source:cached?.deployment ? 'completed_deployment_and_first_saved_observation' : 'completed_deployment',
      observation:finite(cached?.deployment?.observation) ? cached.deployment.observation : null,
      note:cached?.deployment ? '支援采用建成后的首份已保存观测；小兵原地落位，不是实战走位。' : '仅显示有完成回执位置的单位；候选站位不代表已部署。',
      omitted, missingSpawned:ids.filter(id => !units.some(u => u.id === id)) },
    summary:final ? '按保存记录拼装桌面、物件、规划通路与已知部署。' : '生成方案预览；等待引擎完成回执。',
    notes:{draft:draft ? (draft.source === 'offline_reconstruction_cache' ? '初稿按旧操作离线复原，不是历史精确几何快照。' : '已保存的初稿几何；候选站位尚未部署。') : '未记录初稿几何，留空等待已保存阶段。',
      revision:revision ? (revision.source === 'offline_reconstruction_cache' ? '修改稿按旧操作离线复原，不是历史精确几何快照。' : '已保存的修改稿几何。') : '未记录修改稿几何，不由最终布局倒推。',
      final:final ? '引擎已确认建成的最终布局。' : '尚无引擎完成回执。',
      routes:final?.routes.shared ? '本关主侧路重合，只画一条规划通路；不是实战轨迹。' : '主侧路线来自已保存的设计，不代表小兵实际走过。',
      units:cached?.deployment ? '小兵原地落位；支援位置来自建成后的首份已保存观测。' : '仅展示完成回执中有位置的部署；没有记录的单位不补造。'},
    note:cached?.batches?.length ? '中间布局含旧操作离线复原，不是历史精确快照；动画时间仅用于展示。' : '按已保存布局与完成回执展示；动画时间不是原始施工时刻。' };
}

/** Whitelist only display facts from an existing world-builder record. */
export function recordedBuilderStep(r: any) {
  const ops = list(r.operations), receipt = r.tool_receipt || r.technical_preview || {};
  const ports = ops.find(x => x?.op === 'set_ports') || {};
  return {
    id: txt(r.requestId, 160), stage: txt(r.stage, 80), elapsedMs: finite(r.elapsed_ms) ? r.elapsed_ms : null,
    cells: cells(ops.filter(x => x?.op === 'place_region').map(x => ({ id: x.cell, template: x.module, rotation: x.rotation }))),
    connections: edges(ops.filter(x => x?.op === 'connect_regions').map(x => x.edge)),
    deployment: txt(ops.find(x => x?.op === 'deploy')?.module, 80),
    entry: cellId(ports.entry) ? ports.entry : '', exit: cellId(ports.exit) ? ports.exit : '',
    ok: receipt.ok === true,
    geometry: recordedGeometry(r.geometry),
    check: { ok: typeof receipt.ok === 'boolean' ? receipt.ok : null, reason: txt(receipt.reason),
      mainRegions: list(receipt.graph?.main_regions).filter(cellId).slice(0, 9),
      flankRegions: list(receipt.graph?.flank_regions).filter(cellId).slice(0, 9) },
    edits: ops.filter(x => x && cellId(x.cell) && (x.op === 'place_prop' || x.op === 'edit_component')).slice(0, 32).map(x => ({
      op: x.op, cell: x.cell, action: txt(x.action, 40), asset: txt(x.asset, 120),
      index: finite(x.index) ? x.index : null, x: finite(x.x) ? x.x : null,
      z: finite(x.z) ? x.z : null, rotation: finite(x.rotation) ? x.rotation : null,
    })),
  };
}

/** Frames are deterministic snapshots. Their duration is controlled locally by the UI. */
export function generationReplay(s: any): { version: 1; note: string; frames: ReplayFrame[] } {
  const frames: ReplayFrame[] = [];
  let layout: ReplayCell[] = [], links: string[] = [], entry = '', exit = '', deployment = '';
  const add = (key: string, title: string, text: string, phase: number, source: string, extra: Partial<ReplayFrame> = {}) => {
    frames.push({ id: `${txt(s.id, 160)}:${key}`, title, text: txt(text, 4000), phase, source, kind: key,
      covers: [], routes: { main: [], flank: [] }, cells: layout.map(c => ({ ...c })), connections: [...links], entry, exit, ...extra });
  };
  const o = s.observation, a = s.analysis, goal = a?.goal || {};
  const stats: string[] = [];
  if (finite(o?.time)) stats.push(`游戏 ${o.time.toFixed(1)} 秒的战况样本`);
  if (finite(o?.greenAlive)) stats.push(`绿队存活 ${o.greenAlive} 人`);
  if (finite(o?.enemies)) stats.push(`本关剩余守军 ${o.enemies} 人`);
  add('observation', '观察战况', stats.join('；') || '这次生成没有关联战况快照；不补造战场表现。', 0,
    o ? `真实观察 · 绑定报告 ${txt(s.reportId, 160)}` : '记录缺失');
  if (a?.text) add('analysis', '导演的战况判断', a.text, 0, `已记录报告原文 · ${txt(s.reportId, 160)}`);
  const goals = [goal.experience && `下一关体验：${goal.experience}`, goal.tactical_problem && `战术问题：${goal.tactical_problem}`, goal.layout_change && `布局要求：${goal.layout_change}`].filter(Boolean);
  add('goal', '确定下一关目标', goals.join('\n') || '未记录与本关关联的体验目标。', 1, goals.length ? '绑定体验报告 · 目标原文' : '记录缺失');
  const intent = txt(s.planning?.intent || s.intent || s.reason);
  if (intent) add('plan', '规划关卡与部署', intent, 1, s.planning?.intent ? `真实规划结果 · ${txt(s.plannerId, 160)}` : '本关已保存的布局说明');

  const steps = list(s.buildSteps).slice(0, 16);
  if (!steps.length) add('missing-layout', '布局过程未记录', '没有找到本关的布局批次；只在收到最终回执后展示已保存的结果，不从最终布局反推初稿。', 2, '记录缺失');
  for (const [batchIndex, b] of steps.entries()) {
    const phase = b.stage === 'layout_draft' ? 2 : 3;
    const label = phase === 2 ? '布局初稿' : b.stage === 'prop_edit_details' ? '物件修改参数' : '批量修改';
    const batchId = txt(b.id, 160) || `batch-${batchIndex}`;
    const key = (part: string) => `${batchId}:${part}`;
    const extra = { batchId, kind: 'batch' };
    if (b.stage === 'prop_edit_details' && !list(b.cells).length) {
      add(key('details'), label, '记录了物件参数请求，但没有独立可复原布局；具体修改在随后完整批次中展示。', phase, batchSource, extra);
      continue;
    }
    const targetCells = cells(b.cells), targetLinks = edges(b.connections);
    let changes = 0;
    if ((cellId(b.entry) && entry !== b.entry) || (cellId(b.exit) && exit !== b.exit)) {
      entry = cellId(b.entry) ? b.entry : entry; exit = cellId(b.exit) ? b.exit : exit;
      add(key('ports'), `${label} · 确定入口与出口`, `入口：${entry ? cellLabel(entry) : '未记录'}；出口：${exit ? cellLabel(exit) : '未记录'}。`, phase, batchSource, extra); changes++;
    }
    for (const c of targetCells) {
      const old = layout.find(x => x.id === c.id);
      if (sameCell(old, c)) continue;
      layout = layout.filter(x => x.id !== c.id); layout.push(c);
      const action = c.template === 'empty' ? '留空' : old ? old.template === c.template ? '调整方向' : '更换布局' : '选择布局';
      add(key(`cell-${c.id}`), `${label} · ${cellLabel(c.id)}${action}`, `已记录选择：${c.template || '未记录模板'}${c.rotation === null ? '' : `，方向 ${c.rotation}°`}。${old ? `此前：${old.template}。` : ''}\n此处逐桌展开同一批选择，不表示模型按这个顺序思考。`, phase, batchSource,
        { ...extra, focusCells: [c.id] }); changes++;
    }
    const removed = links.filter(edge => !targetLinks.includes(edge));
    const added = targetLinks.filter(edge => !links.includes(edge));
    // Small groups keep the topology legible without inventing per-edge timestamps.
    for (const [action, group] of [['remove', removed], ['add', added]] as const) {
      for (let i = 0; i < group.length; i += 3) {
        const part = group.slice(i, i + 3);
        links = action === 'add' ? [...links, ...part] : links.filter(x => !part.includes(x));
        add(key(`edges-${action}-${i / 3}`), `${label} · ${action === 'add' ? '连接桌面' : '关闭连接'}`,
          part.map(edge => edge.split('__').map(cellLabel).join(' ↔ ')).join('\n') + '\n这里只显示生成方案中的连接；不等于士兵已有可执行路径或射界。', phase, batchSource,
          { ...extra, focusConnections: part }); changes++;
      }
    }
    for (const [i, edit] of list(b.edits).slice(0, 32).entries()) {
      if (!cellId(edit?.cell)) continue;
      const action = edit.op === 'place_prop' ? '添加物件' : ({ remove: '移除物件', move: '移动物件', replace: '替换物件' } as Record<string, string>)[edit.action] || '修改物件';
      add(key(`edit-${i}`), `${label} · ${cellLabel(edit.cell)}${action}`, [edit.asset && `素材：${txt(edit.asset, 120)}`, finite(edit.index) && `原物件编号：${edit.index}`, finite(edit.x) && finite(edit.z) && `位置：(${edit.x}, ${edit.z})`, '已保存修改参数，未记录本步独立几何；地图仍为桌面拓扑。'].filter(Boolean).join('\n'), phase, batchSource, { ...extra, focusCells: [edit.cell] }); changes++;
    }
    if (b.deployment && deployment !== b.deployment) {
      deployment = txt(b.deployment, 80);
      const name = ({ rear: '后场驻守', distributed: '分区部署', forward: '前沿驻守', layered: '前哨与后卫分层' } as Record<string, string>)[deployment] || deployment;
      add(key('deploy'), `${label} · 守军部署`, `已记录部署选择：${name}。这是生成方案，尚不是引擎出兵回执。`, phase, batchSource, extra); changes++;
    }
    if (!changes) add(key('unchanged'), `${label} · 保持布局`, '本批记录中的桌面与连接保持不变；没有独立中间物体快照。', phase, batchSource, extra);
    const ok = b.check?.ok ?? (b.ok === true ? true : null);
    add(key('check'), `${label} · 检查结果`, ok === true ? '生成器几何检查通过。该检查不证明实际战斗中的射击有效或战术效果。' : ok === false ? `生成器几何检查未通过：${txt(b.check?.reason) || '具体原因未记录'}` : '未记录这批布局的检查结论。', phase, `真实批次技术回执 · ${batchId}`, { ...extra, kind: 'check' });
  }
  const names: Record<string, string> = { queued_not_completed: '方案已入队', submitted: '方案已提交', building: '引擎正在搭建', completed: '引擎确认建成', rejected: '引擎拒绝方案', confirmation_unknown: '等待引擎确认', superseded_unconfirmed: '旧方案已失效' };
  const receipts = list(s.receiptSteps).filter(x => typeof x === 'string').slice(0, 24);
  if (s.status && !receipts.includes(s.status)) receipts.push(s.status);
  for (const [i, status] of receipts.entries()) {
    const completed = status === 'completed';
    add(`receipt-${i}-${status}`, names[status] || status, completed ? `${txt(s.message) || '已收到完成回执。'}\n最终布局来自本关回执；线为已保存的设计路线，不是当前士兵行走路径。` : `${names[status] || status}。${status === 'rejected' ? txt(s.message) : '此状态不能认定关卡已经建成。'}`, 4, `真实引擎回执 · ${txt(s.id, 160)} · ${status}`,
      completed ? { kind: 'receipt', covers: list(s.covers).map(c => [...c]), routes: { main: list(s.routes?.main).map(p => [...p]), flank: list(s.routes?.flank).map(p => [...p]) } } : { kind: 'receipt' });
  }
  if (!receipts.length) add('receipt-missing', '尚无引擎回执', '没有引擎完成记录，不能认定关卡已经建成。', 4, '记录缺失', { kind: 'receipt' });
  return { version: 1, note: '按已保存的报告、批次操作与引擎回执回放；同批动作分步展示，非模型思维或引擎逐件施工录像。中间几何未记录时展示桌面拓扑，不以最终物体布局代替。播放速度只影响展示。', frames };
}
