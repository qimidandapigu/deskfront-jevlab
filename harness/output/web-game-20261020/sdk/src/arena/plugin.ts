import type { Answer, Question } from '../systemone/types.js';
import type { DecisionHooks } from './decision.js';

/** JEP v1 §3：回合制游戏契约。observe 的 recent/feedback 由 runner 维护。 */
export interface TurnResult<S> {
  state: S;
  feedback: string | null;
  /** 本动作的画面播放时长毫秒（宏动作走位动画等）；runner 开 playMsPacing 时会等播完再进入下一回合。 */
  playMs?: number;
}
export interface TurnBasedGame<S> {
  decision?: DecisionHooks<S>;
  id: string;
  initialState(): S;
  observe(state: S, ctx: { turn: number; recent: string[]; feedback: string | null }): unknown;
  questions(state: S): Record<string, Question>;
  /** 人类玩家专用的问题集（如推箱子人走 UDLR、AI 选推箱宏动作）；缺省用 questions。 */
  humanQuestions?(state: S): Record<string, Question>;
  act(state: S, answers: Record<string, Answer>): TurnResult<S>;
  isTerminal(state: S): boolean;
  renderText(state: S): string;
  /** Optional explicit terminal result; legacy turn plugins default to won. */
  outcome?(state: S): 'won' | 'lost' | 'draw' | null;
}

export interface RealtimeGame<S> {
  decision?: DecisionHooks<S>;
  id: string;
  tickMs: number;
  /** 决策间隔毫秒；缺省由 runner 的 options.decisionMs（默认 200）决定。 */
  decisionMs?: number;
  /** 动作段到期时再决策；undefined 回退到固定 decisionMs。 */
  decisionReady?(state: S): boolean | undefined;
  /** Human controls one unit while the self model controls companions. */
  humanCompanion?: { start(state: S, model: boolean): S };
  initialState(): S;
  /** live: 观战端逐帧直播用——不消耗观测瘦身的一次性标记（如 jump 的 staticSent）。 */
  observe(state: S, opts?: { live?: boolean }): unknown;
  questions(state: S): Record<string, Question>;
  act(state: S, answers: Record<string, Answer>): S;
  step(state: S): S;
  /** 对手位 AI 钩子：提供后观测站可为右侧选模型（模型对模型）；缺省时右侧由游戏内置 Bot 驱动。 */
  rival?: {
    decision?: DecisionHooks<S>;
    /** 从对手视角的镜像观测（self/opponent 互换）。 */
    observe(state: S): unknown;
    /** 对手位问题集；缺省复用主 questions（对称对抗如打拳 1v1）。 */
    questions?(state: S): Record<string, Question>;
    act(state: S, answers: Record<string, Answer>): S;
  };
  isTerminal(state: S): boolean;
  /** 终局胜负：won/lost/draw；缺省或返回 null 时 runner 记 finished。 */
  outcome?(state: S): 'won' | 'lost' | 'draw' | null;
}

export type AnyGame =
  | { mode: 'turn'; create(variant?: string): TurnBasedGame<unknown> }
  | { mode: 'realtime'; create(variant?: string): RealtimeGame<unknown> };

export interface GameVariant { id: string; name: string; rival?: boolean; }

export interface GameOption {
  type: 'string' | 'number' | 'integer' | 'boolean';
  description?: string;
  default?: string | number | boolean;
  enum?: (string | number | boolean)[];
  min?: number;
  max?: number;
}

/** 实时游戏"自己玩"的键位方案：观测站据此渲染帮助文案，并把按键翻译成 control 输入。 */
export interface HumanControls {
  /** 帮助文案，如 '← → 或 A/D 移动，↑ / W / 空格跳' */
  help: string;
  /** KeyboardEvent.key（单字符按小写匹配）→ 动作名 */
  keys: Record<string, string>;
  /** 组合输入：'a+b'（动作同时按住）→ control 值，优先于单动作 */
  combos?: Record<string, string>;
  /** 多动作同时按住时的优先级：取第一个被按住的，动作名即 control 值 */
  priority: string[];
  /** 无按键时的 control 值，默认 'idle' */
  idle?: string;
  /** 点按型动作（出招等）：即使快速点按也至少保留 150ms，保证服务器至少消费一个 tick */
  oneShot?: string[];
  /** Edge-triggered controls, consumed once rather than held. */
  events?: string[];
}

export interface GamePlugin {
  options?: Record<string, GameOption>;
  capabilities?: { seed?: boolean };
  id: string;
  name: string;
  mode: 'turn' | 'realtime';
  create(variant?: string, options?: { seed?: number; gameOptions?: Record<string, unknown> }): TurnBasedGame<unknown> | RealtimeGame<unknown>;
  clientScript: string;
  /** 可选关卡/变体列表；观测站据此渲染关卡选择。 */
  variants?: GameVariant[];
  /** 玩法说明，观测站右侧面板展示。 */
  description?: string;
  /** 玩家入口文案；与模型提示及调试信息分开。 */
  experience?: { genre: string; duration: string; goal: string; tip: string; accent: string; symbol: string };
  /** 选项 key 的中文短名（动作名），观测站概率条渲染用。 */
  optionLabels?: Record<string, string>;
  /** 每游戏门控阈值覆盖，观测站开局时透传给 runner。 */
  gating?: { confidence?: number; highRisk?: number };
  /** 实时游戏"自己玩"键位；缺省的实时游戏不显示"玩家"选项（回合制默认支持）。 */
  humanControls?: HumanControls;
  /** 模型对模型时两侧的称呼（打拳=左/右，玩具兵=绿/红）；缺省 左/右。 */
  sideLabels?: { self: string; rival: string };
}
