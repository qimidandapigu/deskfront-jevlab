import type { PresenterExperienceCue, PresenterExperienceFact } from './presenter-experience.js';
import { completedForceDeployment } from './director-authorship.js';

type Row = Record<string, any>;
const object = (v: unknown): Row => v && typeof v === 'object' && !Array.isArray(v) ? v as Row : {};
const clean = (v: unknown): string => typeof v === 'string' && v.trim() && v.length <= 1200
  && !/[\u0000-\u001f\u007f-\u009f\u2028-\u202e\u2066-\u2069]/u.test(v) ? v.trim() : '';
const useful = (v: string) => v.length >= 6 && !/^(?:依据|根据)(?:当前|现有)(?:状态|事实|情况)(?:生成|安排|策划)?[。；]?$/u.test(v);

/** Reasons belong to this completed operation, never the newest analyst draft.
 * This read-only projection also covers autonomous JEV plans with no analyst.
 * A purpose authorizes "I wanted to...", never a claim that it worked. */
export function builtIntroductionReasons(record: Row | undefined,
  scope: { runId: string; instanceId: string; operationId: string; stage: number },
  adopted?: PresenterExperienceCue): PresenterExperienceFact[] {
  if (!record || record.status !== 'completed' || record.operation_id !== scope.operationId
    || record.growth_revision !== scope.stage - 1 || record.run_id !== undefined && record.run_id !== scope.runId) return [];
  const native = object(record.construction);
  if (native.operation_id !== scope.operationId || native.index !== scope.stage - 1 || !completedForceDeployment(native)) return [];
  const binding = object(record.generation_scope);
  if (record.generation_scope !== undefined && (binding.run_id !== scope.runId || binding.instance_id !== scope.instanceId
    || binding.operation_id !== scope.operationId || binding.input_world_revision !== scope.stage - 1
    || binding.target_world_revision !== scope.stage)) return [];
  const facts: PresenterExperienceFact[] = [];
  const add = (key: string, value: unknown, source: string) => {
    const reason = clean(value); if (!useful(reason)) return;
    facts.push({ id: 'director-intro-reason-' + key, text: '本关已采用方案的设计目的（想做什么，不代表效果已实现）：' + reason,
      evidence: { source, runId: scope.runId, instanceId: scope.instanceId, operationId: scope.operationId,
        stage: scope.stage, purpose: reason, ...(adopted && key.startsWith('adopted-') ? { sourceReportId: adopted.provenance.reportId,
          sourceObservedStage: adopted.provenance.observedStage, sourceObservedAt: adopted.provenance.observedAt,
          sourceOperationId: adopted.provenance.sourceOperationId } : {}) } });
  };
  // These facts were already validated against selected_experience and its
  // frozen report. Original/rejected goals and new future plans are excluded.
  if (adopted?.authority?.phase === 'built') {
    const direction = adopted.facts.find(f => f.id === 'experience-current-direction');
    const prefix = '此次选择承接的体验方向（期望，不是效果）：';
    if (adopted.provenance.application === 'applicable' && direction?.text.startsWith(prefix)) add('adopted-direction', direction.text.slice(prefix.length), 'completed.selected_experience.experience_direction');
    add('adopted-goal', adopted.authority.selectedGoal, 'completed.selected_experience.selected_goal');
  }
  // The final clause is the selected tactical approach. Earlier catalogue
  // clauses can list optional guards; do not present those as built forces.
  const intent = clean(record.reason), approach = intent.split('；').at(-1)?.trim();
  if (approach) add('planner-approach', approach, 'completed.reason:last_selected_approach');
  const brief = object(record.layout_brief);
  add('planner-scene', brief.scene_intent, 'completed.layout_brief.scene_intent');
  if (!facts.length) add('planner-setting', brief.programme_intent, 'completed.layout_brief.programme_intent');
  return facts.slice(0, 4);
}

export const introductionReasonFacts = (facts: PresenterExperienceFact[]) => facts.filter(f => /^director-intro-reason-[a-z-]+$/u.test(f.id));

/** A motive can discuss a considered weapon that was never deployed. Mentioning
 * a force in a built-stage introduction therefore also needs native roster /
 * equipment evidence, not just the purpose or an authored wish. */
export function introductionForcesIncluded(text: string, cited: PresenterExperienceFact[]): boolean {
  const built = cited.filter(f => /^director-(?:composition|reinforcements|deployed-support|support|friendly-support|defenders)$/u.test(f.id)).map(f => f.text).join('\n');
  for (const noun of [/坦克|装甲/u, /迫击炮|炮手|炮组|曲射/u, /火箭/u, /步枪/u, /冲锋枪/u, /增援|补员|援军/u]) {
    if (noun.test(text) && !noun.test(built)) return false;
  }
  return true;
}

/** Citation and a natural purpose clause are required when a usable reason is
 * present. This is a narrow format guard, not semantic proof of arbitrary prose. */
export function introductionReasonIncluded(text: string, cited: PresenterExperienceFact[], available: PresenterExperienceFact[]): boolean {
  const reasons = introductionReasonFacts(available);
  if (!reasons.length) return true;
  const used = cited.filter(f => reasons.some(r => r.id === f.id));
  if (!used.length || !/因为|所以|为了|好让|想|希望|试试|试一试|尝试|免得|省得|这样(?:就|才|能)|让.{2,}|给.{1,12}(?:机会|空间|时间)/u.test(text)) return false;
  const support = used.map(f => object(f.evidence).purpose).join('\n');
  // Do not turn an old sampling fragment into a diagnosis of the last level,
  // or invent a strength/feeling diagnosis from the number of enemies.
  if (/上一关/u.test(text) && used.some(f => {
    const e = object(f.evidence); return Number.isInteger(e.sourceObservedStage) && e.sourceObservedStage !== e.stage - 1;
  })) return false;
  for (const diagnosis of [/太强|太厉害/u, /太弱/u, /太轻松|过得轻松/u, /无聊/u]) {
    if (diagnosis.test(text) && !diagnosis.test(support)) return false;
  }
  return true;
}

/** Only an intact short purpose is usable without a writing model. Never clip
 * a long explanation: that could remove a negation, condition or alternative. */
export function shortIntroductionPurpose(facts: PresenterExperienceFact[], arrangement?: string): string | undefined {
  for (const fact of introductionReasonFacts(facts)) {
    const purpose = clean(object(fact.evidence).purpose).replace(/[。！？]$/u, '');
    if (purpose.length < 6 || purpose.length > 38 || /[。！？；：]|JEV|模型|验证|射界|回执|几何|可增加|可能|尚未|不是|不代表|不能|若|如果|待/u.test(purpose)) continue;
    // Do not bolt an unrelated tactical motive onto a roster or rescue line.
    const topics = [/坦克|装甲/u, /迫击炮|炮手|曲射/u, /火箭/u, /补员|增援|援军/u,
      /营救|救援|救队友|被困/u, /通路|路线|侧路|两路|主路|绕|通道|掩体|遮挡|推进|前沿|后卫|接敌|接触/u,
      /步枪|冲锋枪|兵种|守军|人数/u];
    if (arrangement && !topics.some(topic => topic.test(purpose) && topic.test(arrangement))) continue;
    return /^(?:让|给|把|先|留|多|少|减少|增加|试用|对照|逐段)/u.test(purpose) ? '我想' + purpose + '。' : '我想试试' + purpose + '。';
  }
  return undefined;
}
