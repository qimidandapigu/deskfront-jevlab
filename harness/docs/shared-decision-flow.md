# 公共决策流程（2026-09-20）

后续统一入口改造已落地：`src/arena/sessions.ts` 提供公共会话服务，`session-config.ts` 提供启动校验，`src/external` 与 `sdk` 提供对外游戏协议和 SDK。Deskfront 战斗请求也经 SDK 进入公共模型后端。当前接入方式与兼容边界见 [统一 Harness](unified-harness.md)。下文原基线数字是该轮历史验收记录。

现在是多个使用入口、共用一套 TypeScript 决策基础设施。用户入口可以不同，同类能力不再各写一份。
Deskfront 保留 Python 控制器和 Godot 引擎，通过公共执行记录格式对齐，未迁移成 TypeScript 游戏。

真实状态 → 游戏候选与事实 → 公共请求管理 → 模型回答 → 完整校验和时效检查 → 游戏执行回执 → 成效与下一轮反馈。

## 入口与共用范围

| 入口 | 共用的机制 | 保留的差异 |
|---|---|---|
| 网页、CLI、内置四游戏评测 | request、validation、decision，回合或实时 runner | 页面、终端、评测输出 |
| 主角、对手、玩家控制一人而 AI 控制队友 | 相同 dispatch、调度策略、控制权取消和回执 | 游戏决定控制哪些单位 |
| JGP 外部游戏 | 相同后端、请求管理、完整回答校验、公共审计投影 | JGP 调度、Boids 回退、子进程协议和外部引擎 |
| 玩具兵无尽生成 | 相同请求预算、超时、取消和回答校验，公共执行记录 | 关卡规划、连通性校验与低血量保护 |
| Deskfront | 公共执行审计字段；调用详情 API 返回 execution | Python 请求控制与 Godot 战斗、独立用例 |

`src/systemone/index.ts` 是后端创建入口；`src/systemone/request.ts` 是公共请求管理实现；
`src/arena/runner.ts` 与 `realtime.ts` 分别承载回合和实时玩法。没有再造一个总引擎包装所有游戏。
新增 TypeScript 功能应调用这些模块，而不是自己再写 Promise.race、lastUsage 读取和模型循环。

## 本轮统一的六件事

1. **请求生命周期**：统一超时、取消、调用预算、展示题过滤。控制权转移会中止请求等待，旧请求的 finally 不能清掉新请求；无尽会话结束和 JGP dispose 同样取消等待。
2. **完整校验与回执**：检查答案类型、候选、有限置信度、概率范围与总和、score 范围及 noul 范围。执行层只消费当前题目的答案，题外 control 不能走真人分支。游戏明确返回 accepted / retained / rejected，合法 idle 可接受；保留旧动作不会计为新动作应用。
3. **历史和解卡接口**：公共层提供有界访问历史、连续无进展计数及 recover 挂钩。推箱子使用共同历史并可选择未访问推法；辅助跳跃通过 recover 更换重复落点；玩具兵复用重复计数，仍在游戏内定义阻挡、弹药变化及绕障路径。拳击的防守保护仍根据自己的规则。没有把寻路和战斗算法提到框架里。
4. **双边调度**：主角与对手调用同一 decisionTrigger，支持动作完成、事件变化、最大等待、是否允许打断。辅助跳跃保护完整路线；拳击感知对手出招变化；玩具兵两队都按命令到期、成员变化调度。
5. **问题用途**：purpose 为 action / protection / display，缺省 action。展示题默认不请求，requests.diagnostics=true 才开启。推箱子 deadlockRisk 和拳击 danger 属于展示；needGuard 也只用于展示，不再覆盖模型动作。
6. **评测溯源**：report v2 包含实际源码及依赖锁文件摘要、Git commit、初始状态摘要、关卡、种子、控制器、参数、requestedModels 和 resolvedModels。只有供应商实际返回的模型名称才记 resolved；缺失时保留空列表，不把 jev-latest 冒充具体版本。

## 后端和请求约定

后端的 request(state, questions, {signal}) 返回原子结果：answers、usage、usageComplete、requestedModel、resolvedModel。
Jev SDK、OpenRouter、DeepSeek 和 mock 均实现；ask / lastUsage 仅保留旧调用兼容。
公共消费者不读 lastUsage：第三方仅实现 ask 时仍能运行，但使用量视为未知，以免并发串账。

公共默认请求期限 10 秒；运行器通过 requests.timeoutMs 配置。无尽生成每局最多 100 次、单次 8 秒。
时间上限是真实墙钟时间；动作时效则按游戏帧计算，两者不能混淆。
公共层不自动重试网络请求。DeepSeek 保留每题一次解析修复，且同受外部取消和期限控制；
修复前一次调用的 token 不完整时 usageComplete=false。请求预算是逻辑决策次数，不是 HTTP 次数或硬金额上限。
取消本地等待不保证供应商撤销已经接受的计费请求。

## 执行记录

共同标识：quickplay-execution-v1。字段为 id、side、requestedAt、resolvedAt、status、rawAnswers、
executedAnswers、action、reason；实时结果通过 feedback 的 decisionId 关联。

- rawAnswers 始终保留模型原答案；executedAnswers 是校验/保护/解卡后交给游戏的输入。
- action 是游戏实际采用的指令、expiresAt 和 disposition。retained 映射 skipped，rejected 映射 rejected，二者 executedAnswers 为 null。
- applied 只表示规则层接受指令，不表示取得进展。效果由下一次观测、到期、替换或终局结算。
- JGP 返回命令后仍是 pending，proposedAction 保留待执行命令；没有外部引擎回执不能写 applied。
- Deskfront 的 `/api/lm/calls/<id>` 返回 execution。尚在请求或排队时为 null；只有 Godot accepted 回执才投影 applied。缺少引擎 tick 时 resolvedAt 为 null，不伪造时钟；没有效果证据时 feedback 为 null。
- 无尽模式生成完成记 pending；玩家实际进入下一关才改为 applied，保留模型原规划、保护修改及最终关卡计划。
- 各引擎的回答/命令载荷保留自己的结构。TypeScript 使用帧或回合，无尽使用关卡序号，Deskfront/JGP 使用引擎 tick；不要跨时钟直接比较。

## 成效与边界

| 游戏 | 进展值 | 位置签名 |
|---|---|---|
| 推箱子 | 已占目标数 | 推箱局面 |
| 跳跃 | 金币、钥匙、机关、胜利减死亡 | 角色坐标 |
| 拳击 | 双方生命差 | 本侧横坐标 |
| 玩具兵 | 两队总生命差 | 本侧单位坐标及弹药 |

统一反馈 progressed / regressed / unchanged / unknown、progressDelta、moved、repeats、reason。
暂时离开目标、移动或重新装弹不一定是坏策略，因此通用 unchanged 不自动触发任意游戏的安全动作。
现有第三方插件未声明 describe.disposition 时沿用 act 接受的旧行为；四款内置游戏已提供明确描述。

JGP 和 Deskfront 没有接入内置四游戏 bench；保留各自协议/接口用例。Godot 的战斗真相不会被控制台推测替代。
模型切换、复活、阶段变化与候选变化仍使用各游戏 contextKey、最大观察年龄和执行前候选检查。

## 评测与验收

```powershell
npm run typecheck
npm test
npm run bench -- --seeds 42,43 --max-ticks 6000 --max-requests 1000 --out output/unification-baseline-final
```

默认只跑 mock；显式选 jev / deepseek / openrouter 才调用真实后端。bench 使用环境或 .env，
显式付费后端现已使用与网页相同的模型配置解析器，可读取 config.local.json；默认 mock 不读取该文件或密钥。价格必须显式给出；未知价格、不完整用量、在途请求会产生 null 成本。
只有玩具兵消费随机种子，其他游戏使用确定性关卡。辅助跳跃使用本地验证路线，不能当作独立模型按键控制。

本轮 8 局离线基线：推箱子、辅助跳跃、玩具兵各 2 胜，拳击 2 负；零非法动作、零运行错误。
这是当前规则基线，不是付费模型能力或胜率提升证明。报告见 `output/unification-baseline-final/report.json`。

类型检查与 252 项 TypeScript 测试通过。验收包含回答数值、题外输入、并发用量、超时预算、控制权恢复、旧 finally、双边调度、保留动作、
回合取消、JGP dispose，以及原有网页/CLI/引擎用例。
Deskfront 相关 35 项接口用例通过；全量 Python 的 61 项中有 5 项环境/清理错误：4 项临时 SQLite 文件未关闭导致 Windows 删除失败，1 项找不到 Godot。
本轮没有修改 Godot 游戏机制，也未宣称完成真实 Godot 或付费模型验收。

## 执行策略更新

不再按概率或置信度过滤、降级任何合法动作，旧阈值配置不生效。other 在有候选时必须转成一个实际动作。拳击仅按气、冷却、空中状态等游戏条件修正不可执行动作，保留原始回答并记录替换原因。动作命中与否仍由物理引擎判定。
