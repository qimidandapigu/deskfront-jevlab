import type { PresenterStageContext } from './presenter-context.js';
import { commentaryTooSimilar } from './commentary-style.js';
import { MAX_DIRECTOR_TEXT_LENGTH } from './spectator-voice.js';
import { shortIntroductionPurpose, introductionForcesIncluded } from './presenter-introduction-reasons.js';

/** The queued explanation describes this encounter, not a ten-second-old live count. */
export function introductionSnapshot(stage: PresenterStageContext): PresenterStageContext {
  return { ...stage, facts: stage.facts.map(fact => {
    if (fact.id === 'director-stage') return { ...fact, text: `第${stage.stage}关已经搭好。` };
    if (fact.id === 'director-defenders') return { ...fact, text: fact.text
      .replace('这关当前在场的红方包括', '本关已出现的红方兵种包括').replace(/\d+[名辆]/gu, '') };
    if (fact.id === 'director-support') return { ...fact, text: fact.text.replace('这关当前有', '本关部署过') };
    // Green ownership can come from capture, not only initial deployment.
    if (fact.id === 'director-friendly-support') return { ...fact, text: fact.text.replace('这关当前有', '本关曾出现') };
    if (fact.id === 'director-captive') return { ...fact, text: '本关设有营救被困队友的任务。' };
    return fact;
  }) };
}

export function introductionClaimsLiveState(text: string): boolean {
  return /当前在场|现在(?:有|还|只|剩)|还剩|只剩|存活|满血|正在|待救援|等待救援|(?:已经|又|刚)(?:开火|倒下)/u.test(text);
}

/** A bounded explanation of a completed native encounter, never a PCG preview. */
export function nativeIntroduction(stage: PresenterStageContext, previous: string[] = []): string {
  // Prefer an actual before/after difference when known. All other built
  // arrangements are peers; no permanent road/tank/person selling-point list.
  const changes = stage.facts.filter(f => f.id.startsWith('director-change-'));
  const built = stage.facts.filter(f => /^(?:director-(?:composition|reinforcements|deployed-support|support|mission|layout-detail|prop-.+))$/u.test(f.id));
  const candidates = [...changes, ...built].map(f => f.text
    .replace('这回部署的是', '我这回摆的是').replace('本关建成时有', '我在这关摆了')
    .replace('本关任务是', '这回要做的是').replace('本关建成时加入了', '我给这关添了')
    .replace('本关建成时实际部署', '我在这关摆了').replace('本关部署过', '我在这关摆过')
    .replace('这关建成的桌面摆了', '我在这关的桌面摆了').split('。')[0] + '。');
  // Novelty belongs to the visible arrangement, not a newly phrased purpose.
  const novel = candidates.filter(text => text.length <= MAX_DIRECTOR_TEXT_LENGTH && !commentaryTooSimilar(text, previous));
  for (const arrangement of novel) {
    const purpose = shortIntroductionPurpose(stage.facts, arrangement);
    if (purpose && arrangement.length + purpose.length <= MAX_DIRECTOR_TEXT_LENGTH
      && introductionForcesIncluded(arrangement + purpose, stage.facts)) return arrangement + purpose;
  }
  return novel[0] ?? '';
}

/** A misbehaving speech provider cannot occupy the introduction's deadline. */
export async function introSpeech<T>(run: (signal: AbortSignal) => Promise<T>, parent: AbortSignal, budgetMs: number): Promise<T> {
  if (budgetMs <= 0) throw new Error('intro-speech-deadline');
  const controller = new AbortController();
  const signal = AbortSignal.any([parent, controller.signal]);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancel: (() => void) | undefined;
  try {
    return await Promise.race([run(signal), new Promise<never>((_, reject) => {
      cancel = () => reject(new Error('intro-speech-cancelled'));
      signal.addEventListener('abort', cancel, { once: true });
      if (signal.aborted) cancel();
      timer = setTimeout(() => { controller.abort(); reject(new Error('intro-speech-deadline')); }, budgetMs);
    })]);
  } finally {
    if (timer) clearTimeout(timer);
    if (cancel) signal.removeEventListener('abort', cancel);
  }
}
