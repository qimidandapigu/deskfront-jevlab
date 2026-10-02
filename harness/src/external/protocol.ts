import type { ModelResponse, Question } from '../systemone/types.js';
import type { SessionConfig } from '../arena/session-config.js';

export const GAME_PROTOCOL = 'quickplay-game/v1' as const;
export type GameMessage =
  | { type: 'ready'; protocol: typeof GAME_PROTOCOL }
  | { type: 'state'; observation: unknown; payload?: unknown }
  | { type: 'request'; id: string; state: unknown; questions: Record<string, Question>; role?: string }
  | { type: 'record'; record: Record<string, unknown> }
  | { type: 'end'; outcome: string; error?: string };
export type HarnessMessage =
  | { type: 'start'; protocol: typeof GAME_PROTOCOL; sessionId: string; config: SessionConfig }
  | { type: 'response'; id: string; response?: ModelResponse; error?: string }
  | { type: 'input' | 'action'; body: Record<string, unknown> }
  | { type: 'stop' };

export function validateQuestions(value: unknown): asserts value is Record<string, Question> {
  if (!value || typeof value !== 'object' || Array.isArray(value) || !Object.keys(value).length) throw new Error('questions must be a nonempty object');
  for (const q of Object.values(value)) {
    if (!q || typeof q !== 'object' || !['choice', 'score', 'noul', 'json'].includes(q.type) || typeof q.instructions !== 'string') throw new Error('Invalid question');
    const entries = q.type === 'choice' ? q.criteria : q.type === 'score' ? q.levels : undefined;
    if (!['noul','json'].includes(q.type) && (!entries || typeof entries !== 'object' || Array.isArray(entries) || !Object.keys(entries).length || Object.values(entries).some(v => typeof v !== 'string'))) throw new Error('Invalid question options');
  }
}
