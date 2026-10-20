import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { completedForceDeployment, forceManifest, manifestSummary } from './director-authorship.js';
import { assemblyGeometry, generationReplay, recordedAssembly, recordedBuilderStep } from './director-replay.js';
import { experienceIdentity, experienceProvenance, experienceTags, generationTagEvidence, generationTags, type ExperienceIdentity, type GenerationTags } from './generation-tags.js';

const legacySession = 'deskfront-bc7f433f-d880-40aa-a6ea-89465b718377';
// Literal asset URLs let the SDK dependency closure include only the audited
// manifests; their media files are not needed by the native assembly replay.
const legacyManifests = new Map([
  ['93340699-e29e-460b-ae06-7455000fe80d', new URL('./director-assets/assembly-93340699-e29e-460b-ae06-7455000fe80d.json', import.meta.url)],
  ['100fc605-0708-409d-859d-1e3d9c140c45', new URL('./director-assets/assembly-100fc605-0708-409d-859d-1e3d9c140c45.json', import.meta.url)],
]);
const assemblyCache = new Map<string, any>();
const geometryDigest = (covers: any[][]) => createHash('sha256').update(covers.map(p=>p.map(v=>typeof v==='number'?v.toFixed(6):v).join('|')).join('\n')).digest('hex').slice(0,12);
/** Only two previously audited offline artifacts may enrich this historical run.
 * Missing/mismatched cache is harmless; never launch a compiler or navigation. */
function legacyAssembly(sessionId: string, record: any, covers: any[][]) {
  const operation = record.operation_id;
  const manifestUrl = legacyManifests.get(operation);
  if (sessionId !== legacySession || record.status !== 'completed' || !manifestUrl) return null;
  if (!assemblyCache.has(operation)) {
    try {
      const manifest = JSON.parse(readFileSync(manifestUrl,'utf8'));
      const history = JSON.parse(readFileSync(new URL('./director-assets/assembly-history-cache.json', import.meta.url),'utf8'));
      const batches = (Array.isArray(manifest.provenance?.batches) ? manifest.provenance.batches : []).slice(0,16).flatMap((b:any)=>{
        const row = (Array.isArray(history.batches) ? history.batches : []).find((j:any)=>j.id === b.id && j.operationId === operation);
        const geometry = assemblyGeometry({covers:row?.covers},'offline_reconstruction_cache');
        return history.version === 1 && history.sourceSession === legacySession && geometry && b.source === 'offline_reconstruction_cache'
          && row.source === b.source && row.coversDigest === b.coversDigest && geometryDigest(geometry.covers) === b.coversDigest ? [{id:b.id,covers:geometry.covers}] : [];
      });
      assemblyCache.set(operation,manifest.operationId === operation && manifest.provenance?.sourceLog === legacySession+'.jsonl'
        ? {coversDigest:manifest.coversDigest,batchIds:(manifest.provenance.batches || []).map((b:any)=>b.id),batches,deployment:manifest.deployment} : null);
    } catch { assemblyCache.set(operation,null); }
  }
  const cache = assemblyCache.get(operation), ids = Array.isArray(record.builder_calls) ? record.builder_calls : [];
  return cache && cache.coversDigest === geometryDigest(covers) && cache.batchIds.length === ids.length
    && cache.batchIds.every((id:string,i:number)=>id === ids[i]) ? cache : null;
}
type PlanningDecision = {
  key: string; label: string; choice: string; choiceLabel: string;
  optionCount: number | null; selection: 'fixed' | 'choice' | 'unknown';
  options: {id:string;label:string}[]; optionsSource: 'recorded_choice_trace' | 'recorded_answer_keys' | null;
};
const decisionKeys = {
  mission_kind: '任务', force_package: '兵力方案', defender_mix: '守军编成',
  support_type: '支援兵种', tactical_approach: '战术关系', scene_shape: '空间布局',
};
// Reuse the presentation vocabulary in director_display.py (TASKS, SUPPORT, SCENES).
// Other recorded choice IDs stay literal rather than acquiring invented meanings.
const decisionLabels: Record<string, Record<string, string>> = {
  mission_kind: { rescue: '营救队友', assault: '突破守军' },
  // generation_agents.py approach menu, shortened only for presentation.
  tactical_approach: { screened_advance: '沿掩体推进', flank_pressure: '正面牵制、侧路绕行', layered_defense: '前后分层防线', short_contact: '缩短接敌距离' },
  support_type: { infantry: '步兵', rocket_team: '火箭兵', tank: '坦克' },
  scene_shape: { north_hook: '北侧迂回', south_hook: '南侧迂回', split_lanes: '两路接近', central_breach: '中央突破', offset_pockets: '交错掩护', defended_corner: '侧角据点' },
};
const choiceId = (v: unknown): string => typeof v === 'string' && /^[a-zA-Z0-9_:-]{1,80}$/.test(v) ? v : '';
const object = (v: any): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v);
const choiceLabel = (key: string, choice: string): string => {
  const labels = decisionLabels[key];
  return labels && Object.hasOwn(labels, choice) ? labels[choice] || choice : choice;
};
function recordedPlannerDecisions(r: any): PlanningDecision[] {
  return Object.entries(decisionKeys).flatMap(([key, label]) => {
    const alias = key === 'mission_kind' ? 'mission' : key;
    const answer = r.answers?.[key] ?? r.answers?.[alias];
    const trace = r.plan?.choice_trace?.[key] ?? r.plan?.choice_trace?.[alias];
    const choice = choiceId(answer?.choice ?? trace?.selected ?? r.plan?.[key] ?? r.plan?.[alias]
      ?? (key === 'scene_shape' ? r.plan?.layout_brief?.scene_shape : undefined));
    if (!choice) return [];
    // New traces preserve the offered menu. Older answer records preserve its
    // keys in probabilities; probability values do not establish adaptation.
    const explicitMenu = trace?.options !== undefined;
    const menu = explicitMenu ? trace.options : answer?.probabilities;
    const keys = object(menu) ? Object.keys(menu) : [];
    const validMenu = keys.length > 0 && keys.length <= 64 && keys.every(id => !!choiceId(id))
      && keys.includes(choice) && (!explicitMenu || trace.selected === choice)
      && (explicitMenu || keys.every(id => typeof menu[id] === 'number' && Number.isFinite(menu[id]) && menu[id] >= 0 && menu[id] <= 1));
    const optionCount = validMenu ? keys.length : null;
    return [{ key, label, choice, choiceLabel: choiceLabel(key, choice),
      optionCount, options:validMenu?keys.map(id=>({id,label:choiceLabel(key,id)})):[],
      optionsSource:validMenu?(explicitMenu?'recorded_choice_trace':'recorded_answer_keys'):null,
      selection: optionCount === null ? 'unknown' : optionCount === 1 ? 'fixed' : 'choice' } as PlanningDecision];
  });
}
function plannerDecisions(planner: any): PlanningDecision[] {
  if (!Array.isArray(planner.decisions)) return recordedPlannerDecisions(planner);
  // Re-whitelist public facts even if a live snapshot supplied the projection.
  return Object.entries(decisionKeys).flatMap(([key, label]) => {
    const row = planner.decisions.slice(0, 6).find((item: any) => item?.key === key);
    const choice = choiceId(row?.choice);
    if (!choice) return [];
    const optionCount = Number.isInteger(row.optionCount) && row.optionCount > 0 && row.optionCount <= 64 ? row.optionCount : null;
    const ids = Array.isArray(row.options) && row.options.length <= 64 ? row.options.map((v:any)=>choiceId(v?.id)) : [];
    const valid = ids.length > 0 && ids.length === optionCount && ids.every(Boolean) && new Set(ids).size === ids.length
      && ids.includes(choice) && ['recorded_choice_trace','recorded_answer_keys'].includes(row.optionsSource);
    return [{ key, label, choice, choiceLabel: choiceLabel(key, choice),
      options:valid?ids.map((id:string)=>({id,label:choiceLabel(key,id)})):[],optionsSource:valid?row.optionsSource:null,
      optionCount, selection: optionCount === null ? 'unknown' : optionCount === 1 ? 'fixed' : 'choice' } as PlanningDecision];
  });
}

const completeIdentity = (identity: ExperienceIdentity) => identity.run_id !== null && identity.instance_id !== null
  && identity.world_revision !== null && identity.encounter_operation_id !== null;
const sameIdentity = (a: ExperienceIdentity, b: ExperienceIdentity) => completeIdentity(a) && completeIdentity(b)
  && a.run_id === b.run_id && a.instance_id === b.instance_id && a.world_revision === b.world_revision
  && a.encounter_operation_id === b.encounter_operation_id;
const publicNumber = (value: any, max = Number.MAX_SAFE_INTEGER) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= max ? value : null;
const publicCount = (value: any) => Number.isSafeInteger(value) && value >= 0 ? value : null;
const publicText = (value: any) => typeof value === 'string' ? value.slice(0,2400) : '';

/** Bounded public choices for the generation view, never infer from prose. */
export function generationForceIntent(value: any) {
  if (!object(value) || !['force-intent/v1','force-intent/v2'].includes(value.schema)
    || !['very_easy','easy','normal','hard','very_hard'].includes(value.difficulty)
    || typeof value.reinforce !== 'boolean') return null;
  const kinds = (v: any) => Array.isArray(v) && v.length <= 5 && v.every(x => ['rifle','smg','rocket','tank','mortar'].includes(x)) ? [...new Set(v)] : null;
  const enemy = kinds(value.enemy_kinds), reinforcement = kinds(value.reinforcement_kinds);
  if (!enemy || !enemy.length || !reinforcement || !['auto','specified'].includes(value.reinforcement_mode)) return null;
  return {schema:value.schema,difficulty:value.difficulty,reinforce:value.reinforce,
    enemy_kinds:enemy,reinforcement_mode:value.reinforcement_mode,reinforcement_kinds:reinforcement};
}

/** Recorded planner adoption and engine build status are independent facts. */
function experienceApplicationMetadata(record: any) {
  const application = object(record.experience_application) ? record.experience_application : {};
  const status = ['applicable','adapted','not_applicable'].includes(application.status) ? application.status : null;
  const reason = typeof application.reason === 'string' ? application.reason.trim() : '';
  const rules = Array.isArray(record.generation_rules) ? record.generation_rules : [];
  const keys = [...new Set(rules.filter((row: any) => object(row) && row.source === 'demo_rule'
    && ['opening_rescue','second_stage_tank'].includes(row.key)).map((row: any) => row.key))];
  return {experienceApplication:{status,
    reason:status && reason && Array.from(reason).length <= 240 && !/[\u0000-\u001f\u007f-\u009f\u2028-\u202e\u2066-\u2069]/u.test(reason) ? reason : null},
    basisStatus:['current_director_order','current_final','current_observation','prior_encounter_intent','missing','stale','analysis_busy','analysis_failed'].includes(record.experience_basis_status)
      ? record.experience_basis_status : null,
    generationRules:keys.map(key => ({key,source:'demo_rule'}))};
}

/** Separate current native facts from the last completed model judgement.
 * The caller supplies current_encounter from the current engine snapshot. A
 * report cannot establish its own currentness, and build order is not a clock.
 */
function currentExperience(d: any) {
  const current = object(d.current_encounter) ? d.current_encounter : {};
  const identity = experienceIdentity(current.identity);
  const sample = object(current.observation) ? current.observation : {};
  const time = publicNumber(sample.time);
  const encounter = object(sample.encounter) ? sample.encounter : {};
  const teamObservation = (team: string) => {
    const row = object(sample.teams?.[team]) ? sample.teams[team] : {};
    return {alive:publicCount(row.alive),health:publicNumber(row.hp_fraction,1),
      controller:['lm','agent','harness','player','local'].includes(row.controller) ? row.controller : null};
  };
  const teams = {green:teamObservation('green'),red:teamObservation('red')};
  const observationMatches = encounter.revision === identity.world_revision
    && (!sample.run_id || sample.run_id === identity.run_id)
    && (!sample.instance_id || sample.instance_id === identity.instance_id)
    && (!encounter.operation_id || encounter.operation_id === identity.encounter_operation_id);
  const observation = completeIdentity(identity) && observationMatches && time !== null ? {
    source:'native_observation',time,tick:publicCount(sample.tick),stage:identity.world_revision,
    status:['active','encounter','fighting','regrouping','completed','failed','ready','building'].includes(encounter.status) ? encounter.status : null,
    enemiesRemaining:publicCount(encounter.enemies_remaining),shotsTotal:publicCount(sample.shots),teams,
  } : null;
  const reports = [...(object(d.reports) ? Object.values(d.reports) : []),d.experience].filter(object);
  const report = observation ? reports.filter(row => {
    const provenance = experienceProvenance(row);
    return sameIdentity(identity,provenance) && provenance.report_id !== null && provenance.observed_at !== null
      && provenance.observed_at <= observation.time;
  }).sort((a,b) => b.observed_at-a.observed_at)[0] : undefined;
  const activity = object(d.analysis_activity) ? d.analysis_activity : {};
  const activityIdentity = experienceIdentity(activity);
  const activityMatches = sameIdentity(identity,activityIdentity);
  const busy = d.analysis_busy === true && activityMatches;
  const error = activityMatches ? publicText(d.analysis_error) : '';
  const provenance = report ? experienceProvenance(report) : null;
  const experience = report ? experienceTags(report,d.observations?.[report.report_id]) : undefined;
  const presentationTags: GenerationTags = {version:1,before:[],next:[],...(experience ? {experience} : {})};
  const status = !observation ? 'unverified' : error ? 'failed' : busy ? 'analyzing'
    : report ? 'ready' : reports.length ? 'stale' : 'waiting';
  return {version:1,status,busy,error,identity,observation,
    activity:{...activityIdentity,appliesToCurrent:activityMatches,workerBusy:d.analysis_busy === true,
      request_id:choiceId(activity.request_id) || null,
      status:['started','running','completed','failed'].includes(activity.status) ? activity.status : null},
    analysis:report ? {...provenance,text:publicText(report.current_analysis),reason:publicText(report.reason),
      assessment:publicText(report.assessment),review:publicText(report.experience_flow?.review),
      uncertainty:publicText(report.experience_flow?.uncertainty)} : null,
    presentationTags};
}
/** Public presentation projection. Never exports prompts, credentials or generator algorithms. */
export function directorView(d: any = {}, meta: { id: string; mode: string; status?: string }) {
  d ||= {};
  const text = (v: unknown) => typeof v === 'string' ? v.slice(0, 2400) : '';
  const num = (v: unknown) => typeof v === 'number' && Number.isFinite(v) ? v : null;
  const pickGoal = (g: any = {}) => ({ experience: text(g.experience), tactical_problem: text(g.tactical_problem), layout_change: text(g.layout_change), avoid: text(g.avoid), route_preference: text(g.route_preference) });
  const e = d.experience || {}, o = d.latest_observation || {}, history = Array.isArray(d.history) ? d.history : [];
  const stages = history.slice(-24).map((r: any) => {
    const design = r.construction?.design || {}, brief = r.layout_brief || {};
    // A later report must never be presented as the cause of an earlier build.
    const report = d.reports?.[r.macro_call] || (r.macro_call && e.report_id === r.macro_call ? e : null);
    const sample = d.observations?.[r.macro_call];
    const planner = d.planners?.[r.jev_call];
    const actualForces = completedForceDeployment(r.construction) ? forceManifest(r.construction.force_manifest) : undefined;
    const plannedForces = forceManifest(r.force_manifest);
    const covers = (Array.isArray(design.covers)?design.covers:[]).filter((p:any)=>Array.isArray(p)&&p.length>=6&&[p[0],p[1],p[2],p[3],p[5]].every(v=>typeof v==='number'&&Number.isFinite(v))&&typeof p[4]==='string').slice(0,200).map((p:any)=>p.slice(0,6));
    const digest = createHash('sha256').update(covers.map((p:any[])=>p.map(v=>typeof v==='number'?v.toFixed(6):v).join('|')).join('\n')).digest('hex').slice(0,12);
    const ops = Array.isArray(design.build_operations) ? design.build_operations : Array.isArray(r.build_operations) ? r.build_operations : [];
    const ports = ops.find((x: any) => x.op === 'set_ports') || {};
    const points = (v:any) => (Array.isArray(v)?v:[]).filter((p:any)=>Array.isArray(p)&&p.length>=2&&p.slice(0,2).every((n:any)=>typeof n==='number'&&Number.isFinite(n))).slice(0,100).map((p:any)=>p.slice(0,2));
    const stage = {
      id: text(r.operation_id || r.command_id), index: (num(r.construction?.index) ?? num(r.growth_revision) ?? 0) + 1,
      status: text(r.status), mission: text(r.mission_kind), support: text(r.support_type),
      ...experienceApplicationMetadata(r),
      enemies: Array.isArray(r.construction?.spawned) ? r.construction.spawned.length : plannedForces?.enemies.length ?? num(r.enemy_count), enemiesConfirmed: Array.isArray(r.construction?.spawned),
      friendlies: actualForces?.reinforcements.length ?? plannedForces?.reinforcements.length ?? num(r.friendly_count), generationMs: num(r.generation_ms),
      forceSummary: manifestSummary(actualForces ?? plannedForces) ?? '', forcesConfirmed: !!actualForces,
      forceIntent:generationForceIntent(r.force_intent),
      reason: text(r.reason), intent: text(brief.scene_intent || brief.programme_intent || brief),
      reportId: text(r.macro_call), message: text(r.receipt?.message || r.construction?.evidence),
      analysis: report ? { text: text(report.current_analysis), time: num(report.observed_at), provenance:experienceProvenance(report,(num(r.construction?.index) ?? num(r.growth_revision) ?? 0)+1), goal: pickGoal(report.next_goal), axes: ['pressure','recovery','expansion','teaching','novelty'].map(key=>({key,value:num(report.hormones?.[key])})) } : null,
      observation: sample ? { time:num(sample.time), stage:num(sample.stage), enemies:num(sample.encounter?.enemies_remaining), greenAlive:num(sample.teams?.green?.alive), health:num(sample.teams?.green?.hp_fraction), redHealth:num(sample.teams?.red?.hp_fraction) } : null,
      routes: { main:points(design.main_route), flank:points(design.flank) },
      deployment: { defenders:points(design.defenders), candidates:points(design.defender_slots), friendly:points(design.friendly_slots), support:points(design.support) },
      buildSteps: (r.builder_calls||[]).flatMap((id:string)=>d.builders?.[id]?[d.builders[id]]:[]),
      receiptSteps: d.receiptSteps?.[r.operation_id]||[],
      planning: planner ? { model:text(planner.resolvedModel), elapsedMs:num(planner.elapsed_ms), intent:text(planner.plan?.intent), decisions:plannerDecisions(planner) } : null,
      plannerId: text(r.jev_call), builderIds: (Array.isArray(r.builder_calls)?r.builder_calls:[]).map(text),
      covers, reconstruction: covers.length && /^[a-zA-Z0-9-]+$/.test(r.operation_id) ? 'level-'+r.operation_id+'-'+digest : null,
      entry: text(ports.entry), exit: text(ports.exit),
      cells: ops.filter((x: any) => x.op === 'place_region' && /^c[0-2]r[0-2]$/.test(x.cell)).map((x: any) => ({
        id: text(x.cell), template: text(x.module), rotation: num(x.rotation),
        purpose: text(brief.desks?.[x.cell]?.purpose), role: text(brief.desks?.[x.cell]?.role),
        assets: (Array.isArray(brief.desks?.[x.cell]?.hero_assets) ? brief.desks[x.cell].hero_assets : []).map(text).slice(0,8),
      })),
      connections: ops.filter((x: any) => x.op === 'connect_regions').map((x: any) => text(x.edge)).filter((v: string) => /^c[0-2]r[0-2]__c[0-2]r[0-2]$/.test(v)),
    };
    const assembly = recordedAssembly(r,stage.buildSteps,legacyAssembly(meta.id,r,covers));
    return { ...stage, replay: generationReplay(stage), assembly, presentationTags:generationTags(stage,r,sample,report,assembly) };
  });
  const p = d.prepared;
  let prepared = null;
  if (p) {
    const record = {...p,...p.command,status:'prepared',construction:undefined,
      growth_revision:p.revision ?? p.growth_revision ?? p.command?.growth_revision};
    const planner = d.planners?.[record.jev_call];
    const report = d.reports?.[record.macro_call] || (record.macro_call && e.report_id === record.macro_call ? e : null);
    const tagStage = {id:text(record.operation_id),index:(num(record.growth_revision) ?? NaN)+1,
      reportId:text(record.macro_call),plannerId:text(record.jev_call),
      planning:planner ? {decisions:plannerDecisions(planner)} : null};
    const plannedForces = forceManifest(record.force_manifest);
    prepared = {reason:text(p.reason),mission:text(record.mission_kind),support:text(record.support_type),enemies:plannedForces?.enemies.length ?? num(record.enemy_count),
      friendlies:plannedForces?.reinforcements.length ?? num(record.friendly_count), forceSummary:manifestSummary(plannedForces) ?? '', forcesConfirmed:false,
      ...experienceApplicationMetadata(record),
      presentationTags:generationTags(tagStage,record,d.observations?.[record.macro_call],report,null)};
  }
  return { ...meta, directorStatus: text(d.status), connected: !!d.status || !!history.length,
    busy: !!d.analysis_busy, error: text(d.error), analysisError: text(d.analysis_error),
    phase: text(e.phase || d.phase), requests: num(d.requests_used), requestLimit: num(d.request_limit),
    observation: { time: num(o.time), stage: num(o.encounter?.revision), enemies: num(o.encounter?.enemies_remaining),
      quietSeconds: num(o.encounter?.seconds_without_progress),
      greenAlive: num(o.teams?.green?.alive), health: num(o.teams?.green?.hp_fraction), },
    analysis: { text: text(e.current_analysis), reason: text(e.reason), assessment: text(e.assessment), time: num(e.observed_at), reportId: text(e.report_id), source: text(e.source) },
    goal: pickGoal(e.next_goal),
    axes: ['pressure','recovery','expansion','teaching','novelty'].map(key => ({ key, value: num(e.hormones?.[key]) })),
    currentExperience:currentExperience(d),
    prepared,
    stages,
  };
}

/** Reconstruct only recorded facts; no fabricated live state or default analysis. */
export function applyDirectorRecord(d: any, r: any) {
  if (r.type === 'world-experience-updated') {
    d.experience = r.report;
    if(r.report?.report_id)(d.reports ||= {})[r.report.report_id]=r.report;
  }
  if(r.type==='world-builder' && r.requestId){
    (d.builders ||= {})[r.requestId]=recordedBuilderStep(r);
  }
  if(r.type==='world-planner' && r.requestId)(d.planners ||= {})[r.requestId]={plan:{intent:r.plan?.intent},resolvedModel:r.resolvedModel,elapsed_ms:r.elapsed_ms,decisions:recordedPlannerDecisions(r)};
  if (r.type === 'world-macro' && r.model_context) {
    const c = r.model_context;
    d.latest_observation = { time: c.time ?? c.recent_observations?.at(-1)?.to_time, stage:c.construction?.revision, teams: c.teams, encounter: c.mission,
      generationTagEvidence:generationTagEvidence(c) };
    if(r.requestId)(d.observations ||= {})[r.requestId]=d.latest_observation;
  }
  if (r.type === 'world-receipt' || r.type === 'world-submitted') {
    d.receiptSteps ||= {};
    const steps=(d.receiptSteps[r.operation_id] ||= []);
    if(!steps.includes(r.status))steps.push(r.status);
    d.history ||= [];
    const index = d.history.findIndex((x: any) => x.operation_id === r.operation_id);
    if (index < 0) d.history.push(r); else d.history[index] = r;
    d.history = d.history.slice(-24);
    d.status = r.status;
  }
  if (r.type === 'world-analysis-error') d.analysis_error = r.error;
  if (r.type === 'world-experience-updated') d.analysis_error = '';
}
