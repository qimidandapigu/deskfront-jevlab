import { commentaryTooSimilar } from './commentary-style.js';
import type { PresenterExperienceCue, PresenterExperienceFact } from './presenter-experience.js';

/** Content comparison is deliberately conservative. Typed geometry, counts and
 * equipment changes are never merged just because the surrounding prose rhymes. */
const normalize = (text: string) => text.replace(/下一(?:关|段)|下关/gu, '后续')
  .replace(/准备|打算|希望|计划/gu, '拟').replace(/主路|主通路/gu, '主路')
  .replace(/侧路|侧通路/gu, '侧路').replace(/[^\p{L}\p{N}]/gu, '');
const material = (text: string) => JSON.stringify([
  text.match(/\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万]+(?=[名个辆门件段人条])/gu) ?? [],
  text.match(/不再|不|没有|未|取消|撤销|恢复|延后|提前|增加|减少|改为/gu) ?? [],
  text.match(/坦克|迫击炮手|迫击炮|炮手|火箭筒|冲锋枪|步枪|增援|被困|营救|左上|左下|右上|右下|左侧|右侧|中列|上方|下方|中部|中央桌面|前方|后方|入口|出口/gu) ?? [],
]);
const useful = (fact: PresenterExperienceFact) => !/-(?:status|sample|application|original-goal|original-change)$/u.test(fact.id);
function sameFact(a: PresenterExperienceFact, b: PresenterExperienceFact): boolean {
  if (a.evidence !== undefined || b.evidence !== undefined) return JSON.stringify(a.evidence) === JSON.stringify(b.evidence);
  if (material(a.text) !== material(b.text)) return false;
  // Compare the content after the fact's shared evidence label. Boilerplate
  // such as 拟采用的内容变化 cannot make opposite arrangements look similar.
  const content = (text: string) => text.replace(/^[^：]*：/u, '').replace(/；(?:期待观察的效果|重新考虑这段安排的条件)：.*$/u, '').replace(/；拟采用的内容变化：/u, '；');
  const aa = content(a.text), bb = content(b.text);
  return normalize(aa) === normalize(bb) || commentaryTooSimilar(aa, [bb]);
}
export function newPresentationFacts(facts: PresenterExperienceFact[], previous: PresenterExperienceFact[]): PresenterExperienceFact[] {
  return facts.filter(useful).filter(fact => !previous.some(old => sameFact(fact, old)));
}
export function samePresentationPlan(current: PresenterExperienceCue, previous?: PresenterExperienceCue): boolean {
  if (!previous || current.kind !== 'plan' || previous.kind !== 'plan') return false;
  if (current.authority?.phase !== previous.authority?.phase) return false;
  const a = current.facts.filter(useful).filter(f => !/-(?:observation|judgment|expected|reconsider|direction|uncommitted)$/u.test(f.id));
  const b = previous.facts.filter(useful).filter(f => !/-(?:observation|judgment|expected|reconsider|direction|uncommitted)$/u.test(f.id));
  return a.length > 0 && b.length > 0 && !newPresentationFacts(a, b).length && !newPresentationFacts(b, a).length;
}
