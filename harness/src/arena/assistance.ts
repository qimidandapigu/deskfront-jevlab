import type { Answers, DecisionFeedback } from './decision.js';
import type { Question } from '../systemone/types.js';
import { invalidAnswers } from '../systemone/validation.js';

/** Ports describe capabilities, never game IDs. Tools have no access to the engine. */
export interface AssistancePorts {
  navigation?: {
    question: string;
    start: string;
    goal: string;
    /** Unweighted graph; each edge names an engine-supported command. */
    neighbors(node: string): readonly { to: string; action: string }[];
  };
  alternatives?: { question: string; choices: readonly string[] };
}
export interface AssistanceContext {
  answers: Answers;
  feedback?: DecisionFeedback;
  ports: AssistancePorts;
}
export interface AssistanceTool {
  id: string;
  requires: readonly (keyof AssistancePorts)[];
  propose(context: AssistanceContext): { answers: Answers; reason: string } | null;
}
export interface AssistanceTrace {
  tool: string;
  status: 'applied' | 'skipped' | 'rejected' | 'error';
  reason: string;
  before: Answers;
  after: Answers;
}
export interface AssistancePolicy<S> {
  /** Empty means off. Order is explicit and deterministic. */
  tools: readonly AssistanceTool[];
  ports(state: S): AssistancePorts;
}

export function assistDecision<S>(policy: AssistancePolicy<S> | undefined, state: S,
  questions: Record<string, Question>, input: Answers, feedback?: DecisionFeedback) {
  let answers = structuredClone(input);
  const trace: AssistanceTrace[] = [];
  if (!policy?.tools.length) return { answers, trace };
  for (const tool of policy.tools) {
    const before = structuredClone(answers);
    let status: AssistanceTrace['status'] = 'skipped', reason = 'not-needed';
    try {
      const ports = policy.ports(state);
      if (tool.requires.some(key => !ports[key])) reason = 'missing-capability';
      else {
        const proposal = tool.propose({ answers: structuredClone(answers), feedback: feedback && structuredClone(feedback), ports });
        if (proposal) {
          // Never permit a tool to activate an unsolicited human-only control channel.
          const extra = Object.keys(proposal.answers).find(key => !Object.hasOwn(questions, key));
          const invalid = extra ? `unexpected-question:${extra}` : invalidAnswers(questions, proposal.answers);
          if (invalid) { status = 'rejected'; reason = invalid; }
          else { answers = structuredClone(proposal.answers); status = 'applied'; reason = proposal.reason; }
        }
      }
    } catch {
      // A broken optional tool retains the last validated decision; no engine side effects.
      status = 'error'; reason = 'tool-failed';
    }
    trace.push({ tool: tool.id, status, reason, before, after: structuredClone(answers) });
  }
  return { answers, trace };
}

/** This is a deterministic controller choice, not model confidence. Raw model answers stay in execution.rawAnswers. */
function choose(answers: Answers, question: string, choice: string): Answers {
  return { ...answers, [question]: { type: 'choice', choice, confidence: 1, probabilities: { [choice]: 1 } } };
}

export function createNavigationAssist(maxNodes = 1024): AssistanceTool {
  if (!Number.isSafeInteger(maxNodes) || maxNodes < 1) throw new Error('maxNodes must be a positive integer');
  return {
    id: 'navigation.shortest-path/v1', requires: ['navigation'],
    propose({ answers, ports }) {
      const nav = ports.navigation!;
      if (nav.start === nav.goal) return null;
      const queue = [{ node: nav.start, first: '' }], seen = new Set([nav.start]);
      for (let i = 0; i < queue.length && i < maxNodes; i++) {
        const current = queue[i]!;
        for (const edge of nav.neighbors(current.node)) {
          if (seen.has(edge.to)) continue;
          const first = current.first || edge.action;
          if (edge.to === nav.goal) return { answers: choose(answers, nav.question, first), reason: 'shortest-path-to-declared-goal' };
          if (seen.size >= maxNodes) continue;
          seen.add(edge.to); queue.push({ node: edge.to, first });
        }
      }
      return null;
    },
  };
}

export function createStallRecoveryAssist(repeats = 3): AssistanceTool {
  if (!Number.isSafeInteger(repeats) || repeats < 1) throw new Error('repeats must be a positive integer');
  return {
    id: 'recovery.alternative/v1', requires: ['alternatives'],
    propose({ answers, ports, feedback }) {
      if (!feedback || feedback.status !== 'unchanged' || feedback.moved !== false || feedback.repeats < repeats) return null;
      const alternatives = ports.alternatives!, selected = answers[alternatives.question];
      if (selected?.type !== 'choice') return null;
      const next = alternatives.choices.find(choice => choice !== selected.choice);
      return next ? { answers: choose(answers, alternatives.question, next), reason: 'stalled-try-declared-alternative' } : null;
    },
  };
}
