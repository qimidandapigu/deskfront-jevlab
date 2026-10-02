# JEP v3.0 — Jev Extension Protocol（Jev 扩展协议）

Version: 3.0 · Status: Active · 适用范围：quickplay-harness 内置游戏插件（JEP）

> 外部游戏以子进程接入时不走本规范，走 JGP（[docs/protocol.md](protocol.md)）。

本文件是本项目插件体系的**唯一权威规范**。任何游戏、决策后端、日志/观察插件的接入方式以本文档为准；文档未覆盖的写法视为不合规。规范变更必须修改本文档并升级版本号。

## 1. 术语

- **宿主（Host）**：装配和运行插件的程序（当前为 `src/cli.ts`、`src/serve.ts`（观测站，`src/viewer`）与测试）。
- **插件（Plugin）**：实现本协议某一契约的对象，目前有两类：**游戏插件**与**后端适配器**。
- **注册表（Registry）**：持有插件的实例对象，由宿主显式创建（`GameRegistry`）。**禁止模块级全局注册表。**
- **端口（Port）**：宿主核心逻辑依赖的接口（`SystemOne`、`TurnBasedGame`、`RealtimeGame`），属于 ports & adapters 架构中的 port；插件是其 adapter。

## 2. 核心条款

1. **插件是纯数据/工厂对象**。插件导出一个符合契约的对象，模块顶层**不得有副作用**（不得自动注册、不得读写 env、不得打开文件/网络）。
2. **显式装配**。宿主负责创建 Registry、注册插件、注入依赖。依赖一律通过函数参数/构造参数传递，**禁止插件 import 宿主内部实现或读取 `process.env`**。
3. **注册返回句柄**。`registry.register(plugin)` 重复 id 抛错；查询不存在的 id 抛错。错误信息使用中文并包含冲突/缺失的 id。
4. **副作用解耦**。核心循环（runner）不直接写文件、不直接操作 UI；通过回调（`onUpdate`）向外发射事件，日志、viewer 等作为订阅者挂载。
5. **配置集中校验**。后端选择等配置在宿主入口一次性从 env 读取并校验（`createSystemOne(env)`），后端名从查表解析，**禁止在业务代码中散落 env 分支**。

## 3. 游戏插件契约

定义见 `src/arena/plugin.ts`：

```ts
interface GamePlugin {
  id: string;              // 全局唯一，小写字母/数字/连字符
  name: string;            // 展示名
  mode: 'turn' | 'realtime';
  create(variant?: string): TurnBasedGame<unknown> | RealtimeGame<unknown>;
  clientScript: string;    // viewer 用客户端脚本路径
  variants?: GameVariant[];  // 可选关卡/变体列表（GameVariant = { id, name }），观测站据此渲染关卡选择
  description?: string;      // 玩法说明，观测站右侧面板展示
  optionLabels?: Record<string, string>;  // 选项 key 的中文短名（动作名），观测站概率条渲染用
  gating?: { confidence?: number; highRisk?: number };  // 每游戏门控阈值覆盖，观测站开局时透传给 runner
  humanControls?: HumanControls;  // 实时游戏"自己玩"键位（help 文案 / keys 键映射 / combos 组合键 / priority 优先级 / idle 默认值 / oneShot 点按保底动作）；缺省的实时游戏不显示"玩家"选项
}
```

- `create()` 每次调用必须返回独立新实例（同一插件可并发运行多局）。
- 回合制游戏实现 `TurnBasedGame`、实时游戏实现 `RealtimeGame`，两者均定义在 `src/arena/plugin.ts`（契约集中于此，游戏目录只放实现）。
- 标准范例：`src/games/sokoban/index.ts` 的 `sokobanPlugin`。新游戏照此结构创建目录 `src/games/<id>/`。

### 3.1 状态分组与 facts 约定

`observe` 返回**按 section 分组**的对象（`GroupedObservation`，定义见 `src/arena/observe.ts`）：
section 名各游戏自由扩展（如 sokoban 的 `board` / `entities`，boxing 的 `match` / `fighters`），
唯有 `facts` 键有固定语义：

- **`facts` 专放代码预计算的推导量**——落点、倒计时、死线布尔量等（如 jump 的
  `landingX/landingY/landingSafe/distToEdge/distToHazard/gapAhead/needsRunup`，boxing 的
  `inRange/oppAttackMsLeft/selfAttackMsLeft/timePressure`）。facts 必须由引擎代码算出，**模型不做算术**。
- 物理常量表等静态参数不随每帧观测重复发送，挪进 questions 的 instructions 文本。
- **独立请求**：每次提供必要静态上下文，地图可以放 `static`；不得假设模型记住首帧。调试字符画可按事件发送。
- **成效回喂**：游戏可在观测里带上一决策的执行成效（如 jump 的 `lastControl:
  { input, frames, progressDelta, xDelta }`——act 时记快照，observe 时 diff）；
  realtime 线统一把上一次决策耗时放进下一次观测的顶层 `timing.lastDecisionMs`。

### 3.2 标签与 danger 题约定（观测站零前端改动）

- 三种 Question 均可带 `label?: string`（题目中文短名）；观测站游戏页由插件注入
  题目标签（各问题 label 聚合）与选项标签（`plugin.optionLabels`），**禁止在 viewer 里硬编码**。
- 约定名为 **`danger`** 的 score 题为"危险/压力分"，观测站渲染成一条通用仪表条
  （可用 `src/arena/observe.ts` 的 `dangerQuestion()` 构造）。
- 观测站右侧面板由 record 字段驱动渲染门控徽章：`hesitation`（犹豫）/ `capped`（降级
  from→to）/ `blocked`（风险标记，未拦截）/ `abstained`（弃权）与 `usage`（token 用量），游戏无关。

## 4. 后端（SystemOne）契约

定义见 `src/systemone/types.ts` 的 `SystemOne` 端口。接入新后端的规范：

1. 在 `src/systemone/<name>.ts` 导出 `create<Name>SystemOne(options): SystemOne`；
2. 在 `src/systemone/index.ts` 的 `backends` 查表中登记一行；
3. 所需配置（apiKey 等）在该后站的工厂函数内从传入的 env 读取并立即校验，缺失时抛出包含变量名的中文错误。

## 5. 注册表 API

`src/arena/registry.ts`：

```ts
const registry = createGameRegistry();   // 每次新建，实例间互不影响
registry.register(plugin);               // 重复 id 抛错
registry.get('sokoban');                 // 未注册抛错
registry.list();                         // GamePlugin[]
```

便捷入口：`src/games/index.ts` 的 `createDefaultRegistry()` 返回已注册全部内置游戏的注册表。

## 6. 事件与订阅

runner 每回合产生 `TurnRecord` 并通过 `options.onUpdate(record, snapshot)` 发射。订阅者规范：

- 订阅者是纯消费者，不得修改 record；
- 持久化订阅者范例：`src/arena/logger.ts` 的 `createJsonlLogger(logPath)`；
- 对局结束时调用方往同一 JSONL 追加一条 `OutcomeRecord`（`{ type: 'outcome',
  game, outcome, ...summary 关键字段 }`），回放/统计消费者按 `type` 字段区分。

## 7. 版本与兼容

- 本规范遵循 SemVer：契约字段的新增为 minor，破坏性变更为 major。
- 变更流程：修改本文档 → 升版本号 → 更新 `src/arena/plugin.ts` 等可执行契约 → 更新范例插件与测试。

## 8. v2 公共执行契约

v2 将实时门控从“只打标”改为实际执行安全动作，并拒绝不属于本次题目选项的模型答案。
旧调用方若依赖未经声明的按键答案，必须更新问题集；真人输入继续通过游戏的 control 接口执行。

游戏实现可选 `decision: DecisionHooks<S>`；本仓库四款游戏及其模型对手均已实现。
类型定义以 `src/arena/decision.ts` 为准：

- capture：返回独立的进展分与位置签名；用于计算成效，不代替胜负判断。
- describe：返回真实执行指令、绝对物理帧 expiresAt 和本地调整原因。
- contextKey：用于复活或阶段切换作废旧观察；maxAgeMs 指游戏时间中的最大观察年龄。
- release：释放本侧控制输入；已经发射的弹道、换弹等仍由游戏规则处理。

主侧和对手侧使用相同的校验、门控、过期与执行审计。控制器的 setControl / applyExternal
先使旧请求失效，再允许外部输入。没有挂钩的第三方插件仍可运行，但成效标为 unknown；
无法凭空保证其输入到期释放。GamePlugin.create 的可选第二参数接收 seed。

TurnRecord / RealtimeRecord 新增 execution，包含 rawAnswers、executedAnswers、action、
requestedAt、resolvedAt、side、status、reason。实时成效通过 onFeedback 发出独立事件，
用 decisionId 关联原记录；终局/接管时尚未返回的请求由 onDiscard 记取消事件。
调用方应将这两个回调及 onRivalUpdate 也接入日志，最后再写 outcome。

不要把应用指令看成任务完成：execution.status=applied 只说明指令已交给规则层；
feedback 和引擎终局才说明实际进展。指标定义与迁移边界见 [公共决策流程](shared-decision-flow.md)。


## 9. v3 请求、调度与完整校验

v3 严格校验有限数值、概率及所有必需题目；旧测试或后端输出的非归一化概率必须修正。
Question 增加 purpose: action / protection / display，默认 action，display 只在 requests.diagnostics 开启时发送。
新增后端应使用 responseBackend 实现 request(state, questions, {signal})，返回本次 answers、usage、usageComplete、requestedModel、resolvedModel。
旧 ask 可兼容，但公共层不再读取 lastUsage；必须迁移 request 才能可信记录费用。

DecisionHooks 新增可选 schedule（ready、eventKey、maxWaitMs、canInterrupt）和 recover。
主角及对手共用调度；ready=false 且不可打断时保护动作段。recover 返回经过游戏规则选择的答案及原因，公共层会再次校验。
describe 返回 disposition: accepted / retained / rejected；合法 idle 可 accepted，保留旧路线需 retained。
不要按 state 引用是否相同推断执行是否成功。ExecutionRecord 新增 schema、trigger 和 pending 状态。
新增第三方适配器必须提供执行语义；旧适配器省略 disposition 时仍按原来 act 接受处理。

共同生命周期和跨语言审计的具体边界见 [公共决策流程](shared-decision-flow.md)。
