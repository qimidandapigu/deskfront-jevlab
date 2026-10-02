import type { Question } from '../systemone/types.js';

/**
 * JEP v1.1 §3.1：分组观测约定。observe 返回一个按 section 分组的对象
 * （如 board / entities / match / fighters / screen …，各游戏自由扩展），
 * 其中 `facts` 键有固定语义：专放代码预计算的推导量（落点、倒计时、死线
 * 布尔量等），让模型直接消费结论而不做算术。facts 必须由引擎代码算出，
 * 不得要求模型从原始状态推导。
 */
export interface GroupedObservation {
  /** 代码预计算的推导量；模型不做算术。 */
  facts?: Record<string, unknown>;
  [section: string]: unknown;
}

/** 约定名为 danger 的 score 题为"危险/压力分"，viewer 渲染成一条通用仪表条。 */
export const DANGER_QUESTION = 'danger';

/** 构造 danger score 题（带统一中文标签），levels 为各档位中文描述。 */
export function dangerQuestion(instructions: string, levels: Record<string, string>): Question {
  return { type: 'score', purpose: 'display', label: '危险', instructions, levels };
}
