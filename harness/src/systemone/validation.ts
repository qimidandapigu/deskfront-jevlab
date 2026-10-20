import type { Answer, Question } from './types.js';

const probability = (v: unknown) => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1;
/** Sparse probability maps are allowed; omitted labels have zero mass. */
export function invalidAnswers(questions: Record<string, Question>, answers: Record<string, Answer>): string | null {
  if (!answers || typeof answers !== 'object' || Array.isArray(answers)) return 'invalid-answers';
  for (const [key, q] of Object.entries(questions)) {
    const a = answers[key];
    if (!a && q.purpose === 'display') continue;
    if (!a || a.type !== q.type) return `invalid-${q.type}:${key}:missing-or-type`;
    if (a.type === 'json') { if (!a.value || typeof a.value !== 'object' || Array.isArray(a.value)) return `invalid-json:${key}`; continue; }
    if (a.confidence !== undefined && !probability(a.confidence) || a.type !== 'noul' && a.confidence === undefined) return `invalid-confidence:${key}`;
    if (a.type === 'noul') { if (!probability(a.noul)) return `invalid-noul:${key}`; continue; }
    const labels = q.type === 'choice' ? q.criteria : q.type === 'score' ? q.levels : {};
    if (a.type === 'choice' && !Object.hasOwn(labels, a.choice) && !(q.type === 'choice' && q.allowOther && a.choice === 'other')) return `invalid-choice:${key}:${a.choice}`;
    if (a.type === 'score' && (!Number.isFinite(a.score) || a.score < Math.min(...Object.keys(labels).map(Number)) || a.score > Math.max(...Object.keys(labels).map(Number)))) return `invalid-score:${key}`;
    const ps = a.probabilities;
    if (!ps || typeof ps !== 'object' || Array.isArray(ps) || !Object.keys(ps).length ||
      Object.entries(ps).some(([label, p]) => !probability(p) || !Object.hasOwn(labels, label) && !(q.type === 'choice' && q.allowOther && label === 'other')) ||
      Math.abs(Object.values(ps).reduce((sum, p) => sum + p, 0) - 1) > .02) return `invalid-probabilities:${key}`;
  }
  return null;
}
