# TODO — 从 Jev 生态（jev-ultrafast / fast-jev-compaction）移植的改进

来源：2026-09-18 对 jev-ultrafast（决策扇出/埋点/边界）与 fast-jev-compaction（阈值决策/失败安全/离线测试）的分析。

## 高优先

- [ ] **1. 决策埋点（usage + latency）**
  `SystemOne.ask` 返回或后端暴露 `usage`（input/output tokens）；`runner.ts` 把每轮的 `usage`、各题概率、confidence 写进 JSONL 日志。
  目的：mock / deepseek-logprobs / jev 三后端切换时成本与延迟自动可对比（对齐 jev-ultrafast 每步记录 `latency_ms`/`usage` 的做法）。

- [ ] **2. 置信度进入控制流**
  runner 增加规则：`action.confidence < 阈值`（建议先 0.5）时记录"犹豫"事件进日志。
  目的：为级联留挂钩点；也是规划模型（`src/systemone/planner.ts` 占位）的第一个真实用途——执行模型犹豫时交给规划模型拆子目标。
  参考：fast-jev-compaction 的 `keepThreshold` 分级决策。

- [ ] **3. 问题经济学：按需提问**
  sokoban `questions()` 中，当轮 `legalMoves` 不含推箱动作时跳过 `deadlockRisk`（或仅在低置信度时追问）。
  目的：logprobs 路线每题 = 一次 API 调用；当前每轮 2 题 → 可省近一半调用。
  参考：jev-ultrafast 投机扇出中"未选中的头不产生动作"，问题数即成本。

## 中优先

- [ ] **4. state 瘦身**
  `adapter.ts` 的 `observe()`：把不变说明（如 `coordinates` 坐标系说明）从每轮 state 挪进 instructions 常量，砍掉与当轮决策无关的字段。
  参考：snapshot.js "只送可见文本"，输入 token 每轮都在计费。

- [ ] **5. bench 模式**
  加一个评测入口：同一地图 × N 局 × 各后端（mock/deepseek/jev），输出胜率 / 回合数 / 成本 / 延迟表（依赖第 1 项的埋点）。
  目的：后端选型依据；将来开源时作为 README 的性能证据（对齐 jev-ultrafast 的 performance.md：公开每次运行、失败、测量边界）。

- [ ] **6. mock 升级为启发式基线**（来自 jev-trader）
  给 sokoban 写贪婪启发式 mock（优先推箱朝最近目标、避开死角），替代现在"永远选第一个"的桩。
  目的：bench 时有意义的地板线（"AI 决策 vs 简单规则"的真实差距）；无 API key 也能跑完整对局。
  参考：jev-trader 的 mock 是动量启发式，dry-run 数据因此有基线价值。

- [ ] **7. 影子模式**（来自 jev-trader dry-run）
  接真 API 后先跑"主后端执行 + 另一后端只记录不执行"，攒分歧数据再决定信谁。
  是级联（第 2 项）上线前的标准验证动作。

## 实施细节备忘

- 做第 2 项（置信度接管）时遵守 **capped 模式**：系统覆盖模型决策时，日志同时保留模型原始概率和实际执行动作（参考 jev-trader：`capped: true` + 原始 probabilities）。
- 做第 1/5 项时指标格式用"**每局成本 / 每次胜利成本**"，不只是胜率（参考 jev-trader 把 jevUsd / gasUsd / pnlUsd 记在同一事件里）。

## 保持现状（已做对的，勿回退）

- 终局判断由引擎 `won()` 独立判定，不让模型/规划器宣布胜利（jev-ultrafast 不信任模型的 DONE）。
- 新后端一律先过注入 `fetchImpl` 的假传输层离线测试（对齐 fast-jev-compaction 的假 Jev 单测）。
- `maxInvalid` 连续无效停机（对应 fast-jev-compaction 的失败回退）。
