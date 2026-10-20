import { createHash } from 'node:crypto';
import { directorAuthorshipFacts, forceNumbersGrounded } from './director-authorship.js';
import { builtIntroductionReasons } from './presenter-introduction-reasons.js';

/** Battle actions and earlier voice lines cannot authorize a design backstory.
 * This is a narrow output guard alongside typed evidence and writer instructions,
 * not a substitute for semantic validation of arbitrary natural language. */
export function directorIntentGrounded(text: string, cited: PresenterExperienceFact[]): boolean {
  if (!forceNumbersGrounded(text, cited)) return false;
  if (/我(?:们)?(?:来|刚刚?|已经|马上|亲自)?(?:命令|指挥|控制).{0,20}(?:开火|攻击|后撤|撤退|往后撤|往前冲|推进|包抄)|(?:让|叫)(?:红方|绿方|红队|绿队|守军|小兵|士兵|小队)(?:的)?(?:守军|小兵|士兵|小队|成员)?(?:先|马上|立即|开始|直接|主动|全部)?(?:开火|攻击|后撤|撤退|往后撤|往前冲|推进|包抄)/u.test(text)) return false;
  const intention = cited.some(f => /^(?:previous-)?(?:director-intro-reason-[a-z-]+|experience-(?:current-selected-intent|plan-(?:goal|change|beat-\d+|selected-intent)|review-assessment)|(?:director|experience-(?:current|plan))-authored-(?:order|enemies|reinforcements|equipment|goal|layout))$/u.test(f.id));
  // A built arrangement or a battle result cannot authorize a new future
  // arrangement just because the writer uses conversational 后面我想... .
  const futureArrangement = /(?:下一关|下关|下一段|后面|后续).{0,8}我(?:们)?(?:想|打算|准备|会|要).{0,10}(?:搭|摆|放|留|补|添|加|换|改|安排|设计|布置)|我(?:们)?(?:想|打算|准备|会|要).{0,8}(?:下一关|下关|下一段|后面|后续).{0,10}(?:搭|摆|放|留|补|添|加|换|改|安排|设计|布置)/u.test(text);
  const futureEvidence = cited.some(f => /^experience-plan-(?:goal|change|beat-\d+|selected-intent|authored-.+)$/u.test(f.id));
  if (futureArrangement && !futureEvidence) return false;
  // Native construction authorizes ownership of what was built. It does not
  // supply a missing motive, player diagnosis, or future construction plan.
  const built = cited.some(f => /^director-(?:stage|mission|task|deployment|composition|reinforcements|defenders|support|deployed-support|captive|layout|layout-detail|prop-.+|change-.+)$/u.test(f.id));
  const ownership = /我(?:们)?(?:这次|这回|现在|就|又|已经|刚刚?|亲手|亲自)?(?:(?:把|给|在)[^，。！？]{0,18})?(?:搭|摆|布置|设置|安排|设计|铺|留|放|加|添|派|部署)/u.test(text);
  if (ownership && !built && !intention) return false;
  if (!intention && /我(?:们)?(?:本来|原本|之前|当初|早就)(?:是)?(?:想|希望|打算|准备)|我(?:们)?(?:这次|这回|现在|就|又)?(?:换了?个?(?:想法|思路|节奏)|打算|准备)|这(?:关|次|回)我(?:们)?(?:想|希望)|(?:所以|因此|于是|为了).{0,22}(?:这(?:一)?关|下一关|布局|关卡).{0,16}(?:改|换|安排|设计|摆|留|铺)/u.test(text)) return false;
  if (ownership && !intention && /因为|所以|因此|于是|为了|希望|想让|想要|原本想|本来想/u.test(text)) return false;
  return true;
}

type Row = Record<string, any>;
export interface PresenterExperienceFact { id: string; text: string; evidence?: unknown }
export interface PresenterExperienceProvenance {
  runId: string; instanceId: string; operationId: string; stage: number;
  reportId: string; observedAt: number; observedStage: number; sourceOperationId: string;
  source: string; targetStage: number; scope: 'ai' | 'human' | 'unknown';
  application?: 'applicable' | 'adapted' | 'not_applicable' | 'missing';
  basisStatus?: string;
}
export interface PresenterExperienceCue {
  key: string; kind: 'intro' | 'plan' | 'review' | 'observation'; stage: number;
  facts: PresenterExperienceFact[]; provenance: PresenterExperienceProvenance;
  authority?: { phase: 'proposed' | 'planned' | 'built' | 'observed'; selectedGoal?: string;
    geometryStatus?: 'pending' | 'passed' | 'failed' | 'not_required'; verifiedRelations?: string[]; geometryEvidence?: { relation: string; evidence: unknown }[] };
}
export interface PresenterExperienceContext {
  runId: string; stage: number; operationId: string;
  introductionReasons?: PresenterExperienceFact[];
  currentDesign?: PresenterExperienceCue;
  plan?: PresenterExperienceCue;
  review?: PresenterExperienceCue;
  observation?: PresenterExperienceCue;
}

const object = (value: unknown): Row => value && typeof value === 'object' && !Array.isArray(value) ? value as Row : {};
const list = (value: unknown): Row[] => Array.isArray(value) ? value.slice(-32).map(object) : [];
const id = (value: unknown): string => typeof value === 'string' && /^[a-zA-Z0-9_.:-]{1,160}$/u.test(value) ? value : '';
const count = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
const time = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;
/** Reject oversize strings whole: clipping can erase a negation or qualification. */
function text(value: unknown, limit = 600): string {
  if (typeof value !== 'string') return '';
  const result = value.trim();
  return result && Array.from(result).length <= limit && !/[\u0000-\u001f\u007f-\u009f\u2028-\u202e\u2066-\u2069]/u.test(result) ? result : '';
}
const semanticKey = (scope: unknown[], content: unknown) => JSON.stringify(scope) + ':'
  + createHash('sha256').update(JSON.stringify(content)).digest('hex').slice(0, 20);

/** The adopted contract, not a later report or a prose planner reason, owns the
 * selected intent. Geometry checks prove arrangements, never player experience. */
function selectedExperience(value: unknown, report: Row): Row | undefined {
  const selected = object(value), scope = object(selected.source_scope), geometry = object(selected.geometry_result);
  if (selected.schema !== 'selected-experience-v1' || selected.source_report_id !== report.report_id
    || !['applicable', 'adapted', 'not_applicable'].includes(selected.application)
    || !text(selected.selected_goal) || !['pending', 'passed', 'failed', 'not_required'].includes(geometry.status)
    || geometry.basis !== 'compiled_final_geometry'
    || !['instance_id', 'run_id', 'world_revision', 'encounter_operation_id'].every(key => scope[key] === report[key])
    || !Array.isArray(selected.required_relations) || selected.required_relations.length > 8
    || !selected.required_relations.every((v: unknown) => typeof v === 'string' && /^[a-z_]{1,80}$/u.test(v))) return undefined;
  const checks = list(geometry.checks).filter(check => check.passed === true && selected.required_relations.includes(check.relation));
  const verified = checks.map(check => check.relation);
  // Keep the compiled check's small JSON evidence; relation names alone lose
  // the visible distinction between two quite different built layouts.
  const geometryEvidence = checks.flatMap(check => {
    try {
      const serialized = JSON.stringify(check.evidence);
      return serialized && serialized.length <= 4000 ? [{ relation: check.relation, evidence: JSON.parse(serialized) }] : [];
    } catch { return []; }
  });
  // A bare "passed" flag without its required checks is not verification.
  const geometryStatus = geometry.status === 'passed' && !selected.required_relations.every((v: string) => verified.includes(v))
    ? 'pending' : geometry.status;
  return { goal: text(selected.selected_goal), direction: text(selected.experience_direction), application: selected.application,
    expected: text(selected.expected), reconsider: text(selected.reconsider), geometryStatus,
    required: selected.required_relations, verified, geometryEvidence, uncommitted: Array.isArray(selected.uncommitted_details)
      ? selected.uncommitted_details.slice(0, 8).map((v: unknown) => text(v, 160)).filter(Boolean) : [] };
}

function selectedFacts(selected: Row, prefix: string, built: boolean): PresenterExperienceFact[] {
  const facts: PresenterExperienceFact[] = [{ id: prefix + '-selected-intent', text: (built
    ? '本关实际采用的目标（布局已建成，体验效果尚未验证）：' : '下一关实际采用的目标（方案已选定，尚未建成）：') + selected.goal }];
  if (selected.direction) facts.push({ id: prefix + '-direction', text: '此次选择承接的体验方向（期望，不是效果）：' + selected.direction });
  if (selected.expected) facts.push({ id: prefix + '-expected', text: '后续期待观察的效果（尚未验证）：' + selected.expected });
  if (selected.reconsider) facts.push({ id: prefix + '-reconsider', text: '重新考虑这项安排的条件：' + selected.reconsider });
  if (selected.uncommitted.length) facts.push({ id: prefix + '-uncommitted', text: '这些原想法尚未落实为生成约束，不能说已实现：' + selected.uncommitted.join('；') });
  const labels: Record<string, string> = { distinct_routes: '主路与侧路实际分开' };
  const required = selected.required.map((v: string) => labels[v]).filter(Boolean);
  if (required.length) facts.push({ id: prefix + '-geometry', evidence: selected.geometryEvidence, text: '需要落实的空间关系：' + required.join('、') + '。'
    + (!built ? '方案仍待建成和引擎确认。' : selected.geometryStatus === 'passed'
      ? '最终编译几何检查通过；只证明这些空间关系，不证明路线代价、使用效果或玩家体验。'
      : selected.geometryStatus === 'failed' ? '最终编译几何检查未通过；不能说这些关系已经建成。'
        : '最终编译几何尚未确认；不能说这些关系已经建成。') });
  return facts;
}

/** Read-only narration evidence from the same native world and director snapshot.
 * Never queries a provider, chooses a level or turns a future plan into a result.
 * Current design is bound to its own operation; only a current-scope report may
 * describe the latest future plan. A refreshed report ID is not a new intention.
 */
export function presenterExperienceContext(worldValue: unknown, directorValue: unknown): PresenterExperienceContext | undefined {
  const world = object(worldValue), director = object(directorValue);
  const growth = object(world.world_growth), mission = object(growth.mission);
  const identity = object(object(director.current_encounter).identity);
  const runId = id(world.run_id), operationId = id(mission.operation_id), instanceId = id(identity.instance_id);
  const stage = growth.revision;
  if (!runId || !operationId || !instanceId || !count(stage) || stage < 1 || stage > 1_000_000
    || mission.index !== stage || !['active', 'regrouping', 'completed'].includes(mission.status)
    || (mission.run_id !== undefined && mission.run_id !== runId)
    || (world.instance_id !== undefined && world.instance_id !== instanceId)
    || director.run_id !== runId || identity.run_id !== runId || identity.world_revision !== stage
    || identity.encounter_operation_id !== operationId || !time(world.time)) return undefined;

  const context: PresenterExperienceContext = { runId, stage, operationId };
  function generationBound(row: Row, inputStage: number, targetOperation?: string): boolean {
    const scope = object(row.generation_scope);
    return scope.run_id === runId && scope.instance_id === instanceId && scope.input_world_revision === inputStage
      && scope.target_world_revision === inputStage + 1 && !!id(scope.operation_id)
      && (!targetOperation || scope.operation_id === targetOperation);
  }
  function basisEligible(row: Row, report: Row, inputStage: number, targetOperation?: string): boolean {
    if (report.report_id !== row.macro_call || ['missing', 'stale', 'analysis_busy', 'analysis_failed'].includes(row.experience_basis_status)) return false;
    if (row.generation_scope !== undefined && !generationBound(row, inputStage, targetOperation)) return false;
    if (row.experience_basis_status === 'prior_encounter_intent') {
      const scope = object(report.source_scope);
      return report.requires_adaptation === true && report.source_report_id === report.report_id
        && report.world_revision <= inputStage && generationBound(row, inputStage, targetOperation)
        && ['instance_id', 'run_id', 'world_revision', 'encounter_operation_id'].every(key => scope[key] === report[key]);
    }
    return report.world_revision === inputStage;
  }
  function provenance(report: Row, targetStage: number): PresenterExperienceProvenance | undefined {
    if (!id(report.report_id) || report.run_id !== runId || report.instance_id !== instanceId
      || !count(report.world_revision) || !id(report.encounter_operation_id)
      || !time(report.observed_at) || report.observed_at > world.time) return undefined;
    return { runId, instanceId, operationId, stage, reportId: report.report_id,
      observedAt: report.observed_at, observedStage: report.world_revision,
      sourceOperationId: report.encounter_operation_id, source: id(report.source), targetStage,
      scope: report.source === 'bot_battle_observation' ? 'ai'
        : report.source === 'player_observation' ? 'human' : 'unknown' };
  }
  function factsFor(report: Row, prefix: string): PresenterExperienceFact[] {
    const flow = object(report.experience_flow), goal = object(report.next_goal);
    const facts: PresenterExperienceFact[] = [];
    const add = (key: string, label: string, value: unknown) => {
      const clean = text(value); if (clean) facts.push({ id: `${prefix}-${key}`, text: `${label}：${clean}` });
    };
    facts.push({ id: `${prefix}-sample`, text: `这份分析采样于第${report.world_revision}关、游戏时间${report.observed_at}秒；只代表当时已观察到的片段，不能把关中采样概括为整关结果。` });
    add('observation', '分析记录引用的经历（待与实战证据核对）', flow.observation);
    add('judgment', '体验判断（模型假设，不代表玩家感受已被证实）', flow.hypothesis || report.current_analysis);
    add('reason', '分析记录给出的安排理由', report.reason);
    add('goal', '希望带来的体验', goal.experience);
    add('change', '为这个目标提出的关卡变化（意图）', goal.layout_change);
    add('uncertainty', '分析保留的不确定性', flow.uncertainty);
    return facts;
  }

  // growth_revision is the input revision of the construction command. Native
  // operation identity proves which built encounter this frozen basis belongs to.
  const records = list(director.history).filter(row => row.operation_id === operationId
    && row.growth_revision === stage - 1 && row.status === 'completed'
    && (row.run_id === undefined || row.run_id === runId));
  const record = records.length === 1 ? records[0] : undefined;
  const basis = object(record?.experience_basis), designProvenance = provenance(basis, stage);
  const selection = selectedExperience(record?.selected_experience, basis);
  if (record && designProvenance && selection && basisEligible(record, basis, stage - 1, operationId)) {
    const application = object(record.experience_application);
    const status = selection.application;
    const facts = factsFor(basis, 'experience-current');
    {
      for (const fact of facts) {
        if (fact.id === 'experience-current-goal' || fact.id === 'experience-current-change') {
          fact.id = fact.id.replace('current-', 'current-original-');
          fact.text = '分析阶段曾提出的原想法（实际采用内容以selected-intent为准）：' + fact.text;
        }
      }
    }
    facts.unshift(...selectedFacts(selection, 'experience-current', true));
    const native = object(record.construction);
    if (native.director_order_id === record.director_order_id) facts.push(...directorAuthorshipFacts(
      { ...record, ...native }, 'experience-current', true, { runId, instanceId, operationId }));
    if (record.experience_basis_status === 'prior_encounter_intent') facts.push({ id: 'experience-current-source',
      text: `本关沿用了第${basis.world_revision}关提出、后来才返回的未来意图，并重新适配；这不是当前关的新观察，也不能将当时的战况当作当前状态。` });
    const labels: Record<string, string> = {
      applicable: '策划记录采用了这份体验目标；关卡已建成，体验是否奏效仍需实战反馈。',
      adapted: '策划记录调整了这份原目标，不能把原目标的全部内容说成本关已采用。',
      not_applicable: '策划记录未采用这份原目标，不能把原目标说成本关实际设计。',
    };
    facts.push({ id: 'experience-current-application', text: status ? labels[status]!
      : '这是本关生成时引用的体验目标；没有记录是否完整采用，不能据此宣称全部兑现。' });
    if (text(application.reason, 240)) facts.push({ id: 'experience-current-adaptation', text: '策划记录的采用或调整理由：' + application.reason.trim() });
    const fixedRules: Record<string, string> = { opening_rescue: '首关固定营救', second_stage_tank: '次关固定坦克' };
    const fixed = [...new Set(list(record.generation_rules).filter(rule => rule.source === 'demo_rule'
      && Object.hasOwn(fixedRules, rule.key)).map(rule => fixedRules[rule.key]))];
    if (fixed.length) facts.push({ id: 'experience-current-fixed-rules',
      text: '本关记录包含演示固定安排：' + fixed.join('、') + '；这些来自预设规则，不能归因于体验分析或玩家表现。' });
    if (facts.some(f => !/-(?:sample|application)$/u.test(f.id))) context.currentDesign = {
      key: semanticKey([runId, instanceId, stage, operationId, 'intro'], [basis.report_id, status, facts]),
      kind: 'intro', stage, facts, provenance: { ...designProvenance, application: status, basisStatus: record.experience_basis_status },
      authority: { phase: 'built', selectedGoal: selection.goal, geometryStatus: selection.geometryStatus, verifiedRelations: selection.verified, geometryEvidence: selection.geometryEvidence },
    };
  }

  const introductionReasons = builtIntroductionReasons(record, { runId, instanceId, operationId, stage }, context.currentDesign);
  if (introductionReasons.length) context.introductionReasons = introductionReasons;

  // A frozen next encounter may intentionally reuse a late prior-encounter
  // intention. Keep that selected plan separate from a newer analyst draft.
  const prepared = object(director.prepared), preparedBasis = object(prepared.experience_basis);
  const preparedAuthored = prepared.revision === stage ? directorAuthorshipFacts(prepared, 'experience-plan', false,
    { runId, instanceId }) : [];
  const preparedProvenance = provenance(preparedBasis, stage + 1);
  const preparedSelected = selectedExperience(prepared.selected_experience, preparedBasis);
  const preparedBound = prepared.revision === stage && preparedProvenance && preparedSelected
    && basisEligible(prepared, preparedBasis, stage);
  if (preparedBound) {
    const facts = selectedFacts(preparedSelected, 'experience-plan', false);
    facts.push(...preparedAuthored);
    facts.push({ id: 'experience-plan-status', text: '这是已经选定、尚未建成的下一关方案，体验效果仍待观察。' });
    if (prepared.experience_basis_status === 'prior_encounter_intent') facts.push({ id: 'experience-plan-source',
      text: `此方案采用了第${preparedBasis.world_revision}关提出的未来意图，经重新适配；不能把它说成当前关的新观察。` });
    context.plan = { kind: 'plan', stage, facts, provenance: { ...preparedProvenance,
      application: preparedSelected.application, basisStatus: prepared.experience_basis_status },
      authority: { phase: 'planned', selectedGoal: preparedSelected.goal },
      key: semanticKey([runId, instanceId, stage, operationId, 'plan'], [preparedSelected, facts]),
    };
  }
  const report = object(director.experience), currentProvenance = provenance(report, stage + 1);
  if (!currentProvenance || report.world_revision !== stage || report.encounter_operation_id !== operationId) return context;
  const flow = object(report.experience_flow), goal = object(report.next_goal);
  const beats = list(flow.beats).slice(0, 3).flatMap(beat => text(beat.goal, 80) ? [{
    goal: text(beat.goal, 80), change: text(beat.change), expected: text(beat.expected), reconsider: text(beat.reconsider),
  }] : []);
  if (text(goal.experience) || beats.length) {
    const facts = factsFor(report, 'experience-plan');
    let preparedSelection: unknown = null;
    facts.unshift({ id: 'experience-plan-status', text: '以下是最新分析对后续体验的安排意图，仍可能调整；并非已经生成的关卡，更不是已达成的体验。' });
    beats.forEach((beat, index) => {
      facts.push({ id: `experience-plan-beat-${index}`, text: `后续第${index + 1}段拟安排的体验：${beat.goal}`
        + (beat.change ? `；拟采用的内容变化：${beat.change}` : '')
        + (beat.expected ? `；期待观察的效果：${beat.expected}` : '')
        + (beat.reconsider ? `；重新考虑这段安排的条件：${beat.reconsider}` : '') });
    });
    if (preparedBound && prepared.macro_call === report.report_id
      && preparedBasis.report_id === report.report_id && preparedBasis.run_id === runId
      && preparedBasis.instance_id === instanceId && preparedBasis.world_revision === stage
      && preparedBasis.encounter_operation_id === operationId) {
      const application = object(prepared.experience_application);
      const statuses: Record<string, string> = { applicable: '已选用当前体验目标', adapted: '调整后选用，不能把原目标全部说成将会实现',
        not_applicable: '未采用原目标，不能将原分析当作已经选定的下一关方案' };
      const missions: Record<string, string> = { rescue: '营救队友', assault: '突破守军' };
      const support: Record<string, string> = { infantry: '步兵', rocket_team: '火箭兵', tank: '坦克', mortar: '迫击炮' };
      const adoption = Object.hasOwn(statuses, application.status) ? application.status : '';
      const missionName = Object.hasOwn(missions, prepared.mission_kind) ? missions[prepared.mission_kind] : '';
      const supportName = Object.hasOwn(support, prepared.support_type) ? support[prepared.support_type] : '';
      const reason = text(application.reason, 240);
      preparedSelection = { adoption, missionName, supportName, reason, selected: preparedSelected };
      facts.push(...selectedFacts(preparedSelected!, 'experience-plan', false));
      facts.push(...preparedAuthored);
      facts.push({ id: 'experience-plan-selection', text: '同一报告对应的下一关策划方案已经选定，尚未建成。'
        + (adoption ? `目标采用情况：${statuses[adoption]}。` : '未记录目标采用情况。')
        + (missionName ? `选定任务：${missionName}。` : '') + (supportName ? `拟配置支援：${supportName}，实际部署仍待引擎确认。` : '')
        + (reason ? `策划采用或调整的理由：${reason}。` : '') });
    }
    context.plan = { kind: 'plan', stage, facts, provenance: currentProvenance,
      authority: preparedSelection ? { phase: 'planned', selectedGoal: preparedSelected!.goal } : { phase: 'proposed' },
      // Changes to observations, report IDs or refresh times alone must not
      // replay the same plan. Goal, proposed content and reconsideration do.
      key: semanticKey([runId, instanceId, stage, operationId, 'plan'], [text(goal.experience), text(goal.layout_change), beats, preparedSelection]),
    };
  }
  const review = text(flow.review);
  if (review) {
    const facts: PresenterExperienceFact[] = [{ id: 'experience-review-assessment',
      text: '最新分析对之前安排的复盘（模型判断，不自动等于引擎验证的体验效果）：' + review }];
    const outcome = list(growth.mission_results).reverse().find(row => row.operation_id === operationId
      && ['completed', 'failed'].includes(row.status) && (row.run_id === undefined || row.run_id === runId));
    if (outcome) {
      facts.push({ id: 'experience-review-result', text: '本关引擎任务回执：' + (outcome.status === 'completed' ? '任务完成。' : '任务失败。')
        + (time(outcome.duration_seconds) ? `耗时${outcome.duration_seconds}秒。` : '') });
      if (count(outcome.green_start?.alive) && count(outcome.green_end?.alive)) facts.push({
        id: 'experience-review-roster', text: `本关回执记录绿方起始${outcome.green_start.alive}人、结束${outcome.green_end.alive}人；这是人数变化，不据此推断真实玩家感受。`,
      });
    }
    context.review = { key: semanticKey([runId, instanceId, stage, operationId, 'review'], facts),
      kind: 'review', stage, facts, provenance: currentProvenance, authority: { phase: 'observed' } };
  }
  // An analyst can notice a meaningful change before forming a future plan.
  // Reuse that report; this projection never triggers an extra analysis call.
  {
    const facts = factsFor(report, 'experience-observation').filter(f => /-(?:sample|observation|judgment|uncertainty)$/u.test(f.id));
    if (facts.some(f => /-(?:observation|judgment)$/u.test(f.id))) context.observation = {
      kind: 'observation', stage, facts, provenance: currentProvenance, authority: { phase: 'observed' },
      key: semanticKey([runId, instanceId, stage, operationId, 'observation'], facts.filter(f => !f.id.endsWith('-sample'))),
    };
  }
  return context;
}
