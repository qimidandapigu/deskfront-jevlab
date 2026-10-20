/** Short, read-only labels for one recorded generation. Never infer player traits. */
import { completedForceDeployment, equipmentFaction, forceManifest } from './director-authorship.js';
export type GenerationTag = {
  key: string; label: string; kind: 'observation' | 'hypothesis' | 'intent' | 'confirmed' | 'unknown';
  source: string; referenceId: string; detail?: string;
};
export type GenerationExperience = {
  scope: 'ai' | 'human' | 'unknown';
  provenance?: ExperienceProvenance;
  insights: GenerationTag[]; evidence: GenerationTag[]; goals: GenerationTag[];
  beats: GenerationTag[];
  changes: { purpose: GenerationTag; features: GenerationTag[] }[];
  checks: GenerationTag[];
};
export type ExperienceIdentity = {
  run_id: string | null; instance_id: string | null;
  world_revision: number | null; encounter_operation_id: string | null;
};
export type ExperienceProvenance = ExperienceIdentity & {
  report_id: string | null; observed_at: number | null; source: string | null;
  observedStage: number | null; targetStage: number | null; includesFinalResult: boolean | null;
};
export type GenerationTags = { version: 1; before: GenerationTag[]; next: GenerationTag[]; context?: GenerationTag[]; experience?: GenerationExperience };
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const count = (v: unknown): v is number => Number.isSafeInteger(v) && typeof v === 'number' && v >= 0;
const identifier = (v: unknown) => typeof v === 'string' && /^[a-zA-Z0-9_:-]{1,160}$/.test(v) ? v : '';
// Native run IDs include a fractional timestamp; keep reference ID rules separate.
const identityIdentifier = (v: unknown) => typeof v === 'string' && /^[a-zA-Z0-9_.:-]{1,160}$/.test(v) ? v : '';
const list = (v: unknown): any[] => Array.isArray(v) ? v : [];
const tag = (key: string, label: string, kind: GenerationTag['kind'], source: string, referenceId: unknown): GenerationTag =>
  ({ key, label, kind, source, referenceId: identifier(referenceId) });

/** Preserve only terminal, per-encounter counts from the bound analyst request. */
export function generationTagEvidence(context: any) {
  const humanSamples = context?.human_sample_count;
  return { ...(Number.isSafeInteger(humanSamples) && humanSamples >= 0 ? {humanSamples} : {}),
    missionResults: list(context?.recent_mission_results).slice(-4).flatMap(r =>
    count(r?.index) && ['completed','failed'].includes(r?.status) && count(r?.green_start?.alive) && count(r?.green_end?.alive)
      ? [{ index:r.index, status:r.status, greenStartAlive:r.green_start.alive, greenEndAlive:r.green_end.alive }] : []) };
}

const object = (v: any): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v);
/** Whole labels only: truncation can remove a negation or the result of a choice. */
function shortLabel(value: unknown): string {
  if (typeof value !== 'string') return '';
  const text = value.trim();
  return text && Array.from(text).length <= 12 && !/[\u0000-\u001f\u007f-\u009f\u2028-\u202e\u2066-\u2069]/u.test(text) ? text : '';
}
function labels(values: unknown, limit: number): string[] {
  return [...new Set(list(values).slice(0, 32).map(shortLabel).filter(Boolean))].slice(0, limit);
}
const detail = (value: unknown) => typeof value === 'string' ? value.trim().slice(0, 600) : '';

/** Identity is copied from recorded fields, never inferred from report order. */
export function experienceIdentity(value: any): ExperienceIdentity {
  return {run_id: identityIdentifier(value?.run_id) || null, instance_id: identityIdentifier(value?.instance_id) || null,
    world_revision: Number.isSafeInteger(value?.world_revision) && value.world_revision >= 0 ? value.world_revision : null,
    encounter_operation_id: identityIdentifier(value?.encounter_operation_id) || null};
}
export function experienceProvenance(report: any, targetStage?: number | null): ExperienceProvenance {
  const identity = experienceIdentity(report);
  // world_revision counts built stages: revision 1 is the first encounter.
  const observedStage = identity.world_revision !== null && identity.world_revision > 0 ? identity.world_revision : null;
  return {...identity, report_id: identifier(report?.report_id) || null,
    observed_at: finite(report?.observed_at) && report.observed_at >= 0 ? report.observed_at : null,
    source: identifier(report?.source) || null, observedStage,
    targetStage: targetStage === undefined ? observedStage === null ? null : observedStage + 1
      : Number.isSafeInteger(targetStage) && targetStage! > 0 ? targetStage! : null,
    includesFinalResult: typeof report?.includes_final_result === 'boolean' ? report.includes_final_result : null};
}

/** Project the same bound analysis. No keyword inference, classification or model calls. */
export function experienceTags(report: any, sample: any, targetStage?: number | null): GenerationExperience | undefined {
  const flow = report?.experience_flow;
  const referenceId = identifier(report?.report_id);
  if (!referenceId || !object(flow)) return undefined;
  const display = object(flow.presentation) ? flow.presentation : {};
  const make = (values: unknown, limit: number, prefix: string, kind: GenerationTag['kind'], source: string, full: unknown) =>
    labels(values, limit).map((label, index) => ({...tag(`${prefix}_${index}`, label, kind, source, referenceId),
      ...(detail(full) ? {detail: detail(full)} : {})}));
  // Legacy short fields can be shown verbatim; never manufacture a short insight
  // by clipping a long analysis, matching words or substituting casualty counts.
  const insights = make(display.insights ?? [flow.hypothesis], 2, 'insight', 'hypothesis', 'bound_experience_hypothesis', flow.hypothesis);
  const evidence = make(display.evidence ?? [flow.observation], 3, 'evidence', 'observation', 'bound_model_observation', flow.observation);
  const goals = make(display.goals ?? [report.next_goal?.experience], 2, 'goal', 'intent', 'bound_experience_goal', report.next_goal?.experience);
  const canonical = list(flow.beats).slice(0, 3);
  // A separate display timeline must not move a later beat into the first slot.
  const beats = canonical.length && canonical.every(b => object(b) && shortLabel(b.goal))
    ? canonical.map((b, index) => ({...tag(`beat_${index}`, shortLabel(b.goal), 'intent', 'bound_experience_beat', referenceId),
      detail: detail(b.change)})) : [];
  const changes: GenerationExperience['changes'] = [];
  const purposes = new Set<string>();
  for (const row of list(display.changes).slice(0, 12)) {
    if (!object(row)) continue;
    const purpose = shortLabel(row.purpose);
    const features = make(row.features, 2, `change_${changes.length}`, 'intent', 'bound_experience_design_intent', canonical[0]?.change);
    if (!purpose || !features.length || purposes.has(purpose)) continue;
    purposes.add(purpose);
    changes.push({purpose: tag(`purpose_${changes.length}`, purpose, 'intent', 'bound_experience_design_intent', referenceId), features});
    if (changes.length === 3) break;
  }
  const checks = make(display.checks ?? [canonical[0]?.expected], 2, 'check', 'intent', 'bound_experience_expected', canonical[0]?.expected);
  if (![insights, evidence, goals, beats, changes, checks].some(rows => rows.length)) return undefined;
  const humans = sample?.generationTagEvidence?.humanSamples;
  const scope = Number.isSafeInteger(humans) && humans >= 0 ? humans > 0 ? 'human' : 'ai'
    : report.source === 'bot_battle_observation' ? 'ai' : report.source === 'player_observation' ? 'human' : 'unknown';
  return {scope, provenance:experienceProvenance(report,targetStage), insights, evidence, goals, beats, changes, checks};
}

/** Caller supplies this stage's bound records, never the latest global analysis. */
export function generationTags(stage: any, record: any, observation: any, boundReport: any, assembly: any): GenerationTags {
  const operationId = stage.id, reportId = identifier(stage.reportId);
  const context: GenerationTag[] = [];
  const basisLabels: Record<string,string> = {missing:'生成时无可用分析',stale:'生成时旧分析未采用',analysis_busy:'生成时分析未返回',analysis_failed:'生成时分析失败',current_observation:'依据当时关中观察',prior_encounter_intent:'沿用本局体验建议'};
  if (Object.hasOwn(basisLabels,record.experience_basis_status)) context.push(tag('basis_status',basisLabels[record.experience_basis_status]!,
    'unknown','generation_basis_status',operationId));
  const ruleLabels: Record<string,string> = {opening_rescue:'首关固定营救',second_stage_tank:'次关固定坦克'};
  for (const rule of list(record.generation_rules)) {
    if (rule?.source==='demo_rule' && Object.hasOwn(ruleLabels,rule.key))
      context.push(tag(rule.key,ruleLabels[rule.key]!,'intent','demo_rule',operationId));
  }
  if (['adapted','not_applicable'].includes(record.experience_application?.status))
    context.unshift(tag('goal_not_applied','旧目标未直接采用','unknown','planner_goal_application',operationId));
  const sample = reportId ? observation : null;
  const report = reportId && boundReport?.report_id === reportId ? boundReport
    : record.experience_basis && identifier(record.experience_basis.report_id)
      && (!reportId || record.experience_basis.report_id === reportId) ? record.experience_basis : null;
  const before: GenerationTag[] = [], next: GenerationTag[] = [];
  if (record.construction?.index === 0 || record.growth_revision === 0)
    before.push(tag('opening','首关开场','observation','opening_stage',operationId));
  else {
    // A full engine mission result avoids interpreting a disappearing unit or
    // a rolling cross-stage sample as a casualty. Counts indicate net attrition.
    const outcome = list(sample?.generationTagEvidence?.missionResults).find(r => r?.index === stage.index - 2
      && ['completed','failed'].includes(r.status) && count(r.greenStartAlive) && count(r.greenEndAlive));
    const lost = outcome ? outcome.greenStartAlive - outcome.greenEndAlive : null;
    const health = sample?.teams?.green?.hp_fraction;
    if (lost !== null && lost >= 2 && lost >= outcome.greenStartAlive / 2)
      before.push(tag('heavy_losses','损失惨重','observation','bound_mission_result',reportId));
    else if (lost !== null && lost > 0) before.push(tag('casualties','出现减员','observation','bound_mission_result',reportId));
    else if (finite(health) && health >= 0 && health <= .5 && sample?.teams?.green?.alive > 0)
      before.push(tag('low_health','血量偏低','observation','bound_observation',reportId));
    else if (finite(health) && health >= .85 && health <= 1 && sample?.teams?.green?.alive > 0)
      before.push(tag('healthy','血量充足','observation','bound_observation',reportId));
    else if (outcome?.status === 'completed') before.push(tag('completed','上一关完成','observation','bound_mission_result',reportId));
    else before.push(tag('unobserved','尚待观察','unknown','missing_observation',reportId));
  }
  const choice = (key: string, fallback: unknown): { value: string; source: string; referenceId: unknown } => {
    const decision = list(stage.planning?.decisions).find(r => r?.key === key && identifier(r?.choice));
    if (decision && identifier(stage.plannerId)) return {value:decision.choice,source:'bound_planner_choice',referenceId:stage.plannerId};
    const selected = record.choice_trace?.[key]?.selected;
    return {value:identifier(selected || fallback),source:'recorded_stage_plan',referenceId:operationId};
  };
  const support = choice('support_type',record.support_type);
  const mission = choice('mission_kind',record.mission_kind);
  const scene = choice('scene_shape',record.layout_brief?.scene_shape);
  const approach = choice('tactical_approach',undefined);
  const c = record.construction;
  const actualForces = c && completedForceDeployment(c) ? forceManifest(c.force_manifest) : undefined;
  const plannedForces = forceManifest(record.force_manifest);
  const actualTanks = actualForces?.enemies.filter(u => u.kind === 'tank').length;
  const plannedTanks = plannedForces?.enemies.filter(u => u.kind === 'tank').length;
  const tankId = Number.isInteger(c?.index) && c.index >= 0 ? `red-tank-${c.index}` : '';
  const spawned = list(c?.spawned);
  const tankConfirmed = record.status === 'completed' && (
    !!actualTanks || c?.support_type === 'tank' && c.support_status === 'deployed' && !!tankId && spawned.includes(tankId)
    || assembly?.operationId === operationId && assembly?.status === 'completed'
      && list(assembly.units).some(u => u?.kind === 'tank' && u.faction === 'red' && spawned.includes(u.id)));
  const tankRejected = record.status === 'completed' && c?.support_type === 'tank'
    && typeof c.support_status === 'string' && !!c.support_status && c.support_status !== 'deployed';
  if (tankRejected) next.push(tag('tank_not_deployed','坦克未部署','confirmed','completed_support_receipt',operationId));
  else if (tankConfirmed) next.push(tag('tank_boss',actualTanks ? `${actualTanks}辆坦克` : '坦克 BOSS','confirmed','completed_tank_deployment',operationId));
  else if (plannedTanks) next.push(tag('tank_boss',`${plannedTanks}辆坦克`,'intent','recorded_force_manifest',operationId));
  else if (support.value === 'tank') next.push(tag('tank_boss','坦克 BOSS','intent',support.source,support.referenceId));
  else if (mission.value === 'rescue') next.push(tag('rescue','营救队友','intent',mission.source,mission.referenceId));
  else if (support.value === 'rocket_team') next.push(tag('rocket_team','火箭兵支援','intent',support.source,support.referenceId));
  const forces = actualForces ?? plannedForces;
  if (forces) {
    const kind = actualForces ? 'confirmed' : 'intent', source = actualForces ? 'completed_force_deployment' : 'recorded_force_manifest';
    const friendlyTanks = forces.reinforcements.filter(unit => unit.kind === 'tank').length;
    const enemyTanks = forces.enemies.filter(unit => unit.kind === 'tank').length;
    const heavy: GenerationTag[] = [];
    for (const side of ['red', 'green'] as const) {
      const guns = forces.equipment.filter(gun => equipmentFaction(forces, gun) === side).length;
      const tanks = side === 'red' ? enemyTanks : friendlyTanks;
      const label = [tanks ? `${tanks}辆坦克` : '', guns ? `${guns}门迫击炮` : ''].filter(Boolean).join('＋');
      if (label) heavy.push(tag(side === 'red' ? tanks ? 'tank_boss' : 'red_mortar' : 'friendly_support',
        `${side === 'red' ? '敌方' : '友方'}${label}`, kind, source, operationId));
    }
    // Keep the existing two-chip layout while making a paired challenge/support
    // plan visible; separate gun tags used to be truncated after the tank chip.
    if (heavy.length) next.splice(0, next.length, ...heavy, ...next.filter(item => item.key !== 'tank_boss'));
  }

  const sceneLabels: Record<string,string> = { north_hook:'迂回通路',south_hook:'迂回通路',split_lanes:'双路接近',central_breach:'中央突破',offset_pockets:'交错掩护',defended_corner:'据点突破' };
  const approachLabels: Record<string,string> = { flank_pressure:'迂回通路',screened_advance:'掩体推进',layered_defense:'纵深防线',short_contact:'快速接敌' };
  const spatial = Object.hasOwn(sceneLabels,scene.value) ? {...scene,label:sceneLabels[scene.value]!}
    : Object.hasOwn(approachLabels,approach.value) ? {...approach,label:approachLabels[approach.value]!} : null;
  // These remain design intents even if final routes coincide. Do not promote
  // geometry or a model label into actual movement, line of sight or enjoyment.
  if (spatial) {
    const label = scene.value === 'split_lanes' && assembly?.operationId === operationId && assembly?.routes?.shared === true
      ? '双路待验证' : spatial.label;
    next.push(tag('spatial_design',label,'intent',spatial.source,spatial.referenceId));
  }
  else if (report?.next_goal?.route_preference === 'flank')
    next.push(tag('flank_goal','迂回通路','intent','bound_experience_goal',report.report_id));
  if (!next.length && mission.value === 'assault') next.push(tag('assault','清除守军','intent',mission.source,mission.referenceId));
  if (!next.length) next.push(tag('undocumented','设计待记录','unknown','missing_plan',operationId));
  const experience = experienceTags(report, sample, stage.index);
  // An old observation can remain useful while its proposed mission was not
  // adopted. Do not render its timeline as the built stage's experience plan.
  if (experience && ['adapted','not_applicable'].includes(record.experience_application?.status)) {
    experience.goals=[];experience.beats=[];experience.changes=[];experience.checks=[];
  }
  return {version:1,before,next:next.slice(0,2),...(context.length ? {context:context.slice(0,2)} : {}),...(experience ? {experience} : {})};
}
