import { directorIntentGrounded, type PresenterExperienceCue, type PresenterExperienceFact } from './presenter-experience.js';
export { directorIntentGrounded } from './presenter-experience.js';
import { publicSpectatorText } from './spectator-observation.js';
import { directorIntroductionGrounded } from './presenter-context.js';
import { forceNumbersGrounded } from './director-authorship.js';

/** Cheap boundary checks, not a semantic proof. The writer must still ground
 * each claim in typed evidence; a planning record cannot prove a combat result.
 */
export function directorNarrationGrounded(text: string, cue: PresenterExperienceCue, cited: PresenterExperienceFact[]): boolean {
  if (!publicSpectatorText(text)) return false;
  if (!directorIntentGrounded(text, cited)) return false;
  if (!forceNumbersGrounded(text, cited)) return false;
  const selected = cited.filter(f => cue.facts.some(source => source.id === f.id));
  // A built-stage introduction may simply mention its native deployment. It
  // need not recite a design intention just to qualify as an introduction.
  const builtFact = cue.kind === 'intro' && cited.some(f => /^director-(?:deployment|composition|reinforcements|mission|defenders|support|deployed-support|captive|layout|layout-detail|prop-.+|change-.+)$/u.test(f.id));
  const meaningfulSelection = selected.some(f => !/-(?:sample|status|application)$/u.test(f.id));
  if (!builtFact && !meaningfulSelection) return false;
  if (builtFact && !meaningfulSelection && !directorIntroductionGrounded(text, cited)) return false;
  // Protocol weapon codes and their Chinese names denote the same kind, not
  // a new decision or a deployed count. Boundaries avoid matching substrings.
  const names: Record<string, string> = { rifle: '步枪', smg: '冲锋枪', rocket: '火箭筒', tank: '坦克', mortar: '迫击炮' };
  const support = cited.map(f => f.text).join('\n').replace(/\b(rifle|smg|rocket|tank|mortar)\b/gu, code => names[code]!);
  if (/我(?:们)?(?:来|刚刚?|已经|马上|亲自)?(?:让|叫|命令|指挥|控制).{0,12}(?:绿队|红队|小兵|士兵|小队|开火|攻击|撤退)/u.test(text)) return false;
  // Do not require a particular phrase such as "原本"; natural paraphrases are
  // valid. Reject an explicit claim that a recorded rejected goal was adopted.
  if (cue.kind === 'intro' && cue.provenance.application === 'not_applicable'
    && /(?:已经|实际|这次)(?:完全|全部)?采用了?(?:原|这个|这份)(?:目标|计划)/u.test(text)) return false;
  if (/下一关|下关|下一段/u.test(text) && cue.kind !== 'plan') return false;
  if (cue.kind === 'plan' && /(?:下一关|下关|下一段|后面).{0,18}(?:已经|已|成功).{0,8}(?:生成|建成|搭好|部署|出现|完成|奏效)|我已经.{0,8}(?:生成|搭好|安排好)/u.test(text)) return false;
  if (cue.kind === 'plan' && /我(?:们)?(?:这次|这回|已经|刚刚?)?(?:(?:把|给|在)[^，。！？]{0,18})?(?:搭了|搭好|摆了|布置了|安排好了|铺了|留了|部署了)/u.test(text)) return false;
  if (cue.kind === 'plan' && cue.authority?.phase === 'proposed'
    && /(?:已经|已|这次)(?:正式)?(?:选定|确定|采用|决定)|下一关就(?:是|用|按)/u.test(text)) return false;
  if (cue.kind === 'intro' && cue.authority?.phase === 'built') {
    if (!cue.authority.verifiedRelations?.includes('distinct_routes') && !cited.some(f => f.id === 'director-layout-detail' || f.id === 'director-change-route-fork')
      && /(?:铺|建|搭|安排|有|形成).{0,8}(?:两条路|两路|主路和.{0,3}侧路)|(?:主路|侧路).{0,10}(?:分开|分离|不同|已经建成)/u.test(text)
      && !/(?:还没|尚未|没有)(?:确认|建成|形成|实现|证明)|尚待验证/u.test(text)) return false;
    // Distinct routes do not prove different cost, safer cover or short sight.
    if (/(?:这关|这次|已经|已建成).{0,32}(?:代价不一样|代价不同|视野短|掩体多|掩体少)/u.test(text)
      && !/(?:希望|打算|期待|待验证|还要|尚未)/u.test(text)) return false;
  }
  if (cue.authority?.phase !== 'observed' && /(?:已经|成功|果然).{0,10}(?:找回主动权|得到喘息|恢复心流|体验奏效|让玩家|达成体验)/u.test(text)) return false;
  for (const noun of [/坦克|装甲/u, /迫击炮|炮台|炮位|炮组/u, /火箭/u, /冲锋枪/u, /救援|营救|被困/u, /增援|补员/u]) {
    if (noun.test(text) && !noun.test(support)) return false;
  }
  if (cue.provenance.scope !== 'human' && /玩家(?:已经|现在|一定)?(?:觉得|感到|很|非常)(?:开心|无聊|沉浸|挫败)|你(?:已经|一定|现在)(?:很开心|很无聊|沉浸其中)/u.test(text)) return false;
  return true;
}
