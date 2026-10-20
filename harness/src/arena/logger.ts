import { appendFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import type { Answer } from '../systemone/types.js';
import type { FeedbackRecord } from './decision.js';

/** TurnRecord 与 RealtimeRecord 共有的可序列化结构（各自还有 turn/frame、feedback 等附加字段）。 */
export interface LogRecord {
  game: string;
  observation: unknown;
  answers: Record<string, Answer>;
  ms: number;
}

/** 对局结束时追加的结算记录（JSONL 最后一行），附 outcome 与 summary 关键字段。 */
export interface OutcomeRecord {
  type: 'outcome';
  game: string;
  outcome: string;
  [key: string]: unknown;
}

export interface SessionRecord {
  type: 'session' | 'generation' | 'generation-activated';
  game: string;
  [key: string]: unknown;
}

/** JEP v1 §6：持久化订阅者。把每条 TurnRecord / RealtimeRecord / OutcomeRecord 追加为 JSONL。 */
export function createJsonlLogger(logPath: string): (record: LogRecord | OutcomeRecord | FeedbackRecord | SessionRecord) => void {
  mkdirSync(dirname(logPath), { recursive: true });
  return record => {
    appendFileSync(logPath, JSON.stringify(record) + '\n');
  };
}
