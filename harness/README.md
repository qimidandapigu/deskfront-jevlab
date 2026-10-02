# quickplay-harness

**统一入口与外部接入 SDK**：网页和 CLI 使用同一套会话服务。新增外部游戏提供 `game.json` 与 Python/JavaScript SDK 适配，执行 `npm run jev -- register <game.json>` 即可进入目录，无需修改 Harness 核心。
详见 [统一 Harness 接入说明](docs/unified-harness.md) 与 [公共游戏协议](docs/external-game-protocol.md)。Deskfront 已作为公共协议接入样例，原有 JGP 保留兼容。

游戏 AI 竞技场：harness 用 TypeSafe **Jev** 模型（System One，毫秒级类型化
应答，`client.systemOne({ state, questions })`）做决策。下列两类原有实现已由公共会话服务托管；新外部游戏统一使用上面的 SDK 接入：

1. **内置玩具游戏（JEP 插件）** — `src/games/<id>/{engine,adapter,client.js,index.ts}`
   插件体系：sokoban（回合制）、boxing / jump / soldiers（实时）。由 `src/arena` 的
   runner 驱动，`src/viewer` 提供浏览器观测站。SystemOne 后端在
   `src/systemone`：mock（离线确定性）/ deepseek（logprobs）/ jev（真实 SDK）/
   openrouter（OpenRouter 网关模型）。
2. **外部游戏接入（JGP 协议）** — `src/jgp/`：游戏作为子进程通过
   **stdio + NDJSON** 上报 WorldState、接收 Action（`docs/protocol.md`）。
   决策引擎含 Boids 规则层、群体脑（swarm brain）、节流与请求失败回退、
   弃权动作兜底（`actionGate` 配置）、逐实体记忆、
   JSONL 决策日志。自带玩具兵打枪 demo（`src/jgp/sim.ts`：
   1 个躲在沙袋工事后面的脚本玩家小兵 + 3 个端步枪的敌方玩具兵，含掩体
   遮挡视线与弹道曳光渲染）。

## 架构（简）

```
内置线:  src/games 插件 ──► src/arena runner ──► SystemOne (mock|deepseek|jev|openrouter)
                            └─► src/viewer 观测站 (npm run serve)

外部线:  游戏进程 ──stdout NDJSON──► src/jgp/stdio.ts (GameAdapter)
                ◄──stdin NDJSON─── src/jgp/engine.ts (快脑: Jev + Boids 回退)
```

## Quick start

```bash
npm install
npm run typecheck     # tsc --noEmit, strict
npm test              # node --test（全部测试，含 JGP conformance）

npm run play          # 内置 sokoban 一局（JEP 插件线，npm start 同效）
npm run play -- boxing --backend mock --max-ticks 300
npm run jev -- list   # 所有已注册游戏与能力
npm run jev -- register examples/counter/game.json
npm run play -- counter-demo --backend mock
npm run jev -- inspect <game> [variant]   # 打印该游戏 initialState 的 observe+questions JSON（不开对局、不调 API）
npm run serve         # 浏览器观测站（boxing/jump 实时观战）
npm run demo          # 玩具兵打枪 ASCII demo，DEMO_SECONDS 后自动退出（默认 8）
npm run jev -- run -- node your-game.js   # 接入外部游戏（JGP stdio）
```

### Deskfront 当前版

Deskfront 的对外产品入口已经统一为**无尽推进**；页面提供“第二关坦克”开关，默认开启且只影响第二关，后台回归使用同一规则的 `infinite-headless`。旧的 duel/tactics 入口仅供兼容测试，不代表当前版能力。产品使用、目录布局、模型角色、默认配置和验收边界见 [Deskfront 当前版](docs/deskfront-current.md)；代码职责和依赖边界见 [Deskfront 模块边界](docs/deskfront-module-map.md)，所有权与事实源见 [所有权与模块化边界](docs/deskfront-ownership-boundary.md)。

Windows 最小启动方式：

```powershell
$env:DESKFRONT_ROOT = 'C:\game\deskfront-jevlab'
$env:GODOT_BIN = 'C:\game\.artifacts\godot-4.5.1\Godot_v4.5.1-stable_win64_console.exe'
npm run serve
```

然后打开 `http://127.0.0.1:3777/runtime/deskfront`。页面的真实 AI 选项是“DeepSeek 指挥 + JEV 小队执行”；`mock` 只作离线规则回归。

## 协议

**JGP（Jev Game Protocol）v1**：游戏 → harness 只发 `hello` / `state`，
harness → 游戏只回 `hello_ack` / `actions` / `error`；stdio 主传输，每行
一个 JSON，stdout 只走协议、日志走 stderr。完整契约与 JS/Python 接入示例
见 **[docs/protocol.md](docs/protocol.md)**。

## 置信度与埋点约定（内置线）

- **观测分组与 facts**：observe 返回按 section 分组的对象（约定见
  `src/arena/observe.ts` 与 docs/plugin-api.md §3.1）；`facts` 键专放代码
  预计算的推导量（落点、倒计时、死线布尔量），模型不做算术。物理常量等
  静态参数放 questions 的 instructions，不随观测重复发送。
- **独立请求与回喂**：每次请求携带所需地图和规则，不能假设模型记住首帧；
  仅调试字符画可按需发送。运行器追加统一的 `decisionFeedback`，实时线
  追加 `timing.lastDecisionMs`。跳跃还保留游戏自己的成效信息。
- **结算落盘**：对局结束时往 JSONL 追加一条 `{ type: 'outcome', game,
  outcome, ...summary 关键字段 }` 记录（`OutcomeRecord`，见
  `src/arena/logger.ts`），viewer AI/真人局与 CLI 均在收尾处落这条。
- **标签与危险分**：问题可带 `label`（题目中文短名），插件可带
  `optionLabels`（选项中文名）与 `gating`（兼容旧配置，阈值不再参与执行）；观测站
  全部从插件注入，新游戏零前端改动。约定名为 `danger` 的 score 题渲染为
  通用危险仪表条（display 题默认关闭请求，诊断模式可启用）；执行与回退徽章与 token 用量由 record
  字段驱动渲染。
- **usage**：`SystemOne` 后端可在 `lastUsage` 暴露最近一次 `ask` 的 token
  用量（`promptTokens` / `completionTokens` / `totalTokens`）。deepseek /
  jev / openrouter 会从响应里取，mock 不提供。runner / realtime 把它写进
  每条 TurnRecord / RealtimeRecord 的 `usage` 字段。
- **概率不参与拦截**：回合、实时双方和 JGP 对所有合法 choice 照常执行；即使置信度为 0，也不会因此降级、跳过或强制格挡。旧 confidence/highRisk 阈值仅保留配置兼容，不生效。
- **记录真实执行**：原始回答在 `execution.rawAnswers`，执行答案在 `execution.executedAnswers`，最终指令在 `execution.action`。拳击必杀气不足等物理条件不满足时，明确改用靠近或刺拳，记录原因；真人键位仍遵守原游戏规则。
- **other 弃权**：优先使用有效 safeAction，否则从真实候选按概率排名选一个（无最低概率要求）；JGP 无 safeAction 时执行本地规则动作。存在可选动作时不会因 other 空过。
- **有效性仍校验**：未知动作、畸形响应、过期回复、已结束会话不会被当作有效新决策。概率数值与总和校验是响应格式检查，不是概率门槛。

## 环境变量

| 变量 | 作用 |
|---|---|
| `SYSTEMONE_BACKEND` | 内置线后端：`mock`（默认）/ `deepseek` / `jev` / `openrouter` |
| `JEV_BACKEND` | JGP 兼容入口的后端覆盖；未设置时使用公共默认后端，无配置时 mock |
| `MODEL_API_KEY` / `MODEL_CHAT_URL` / `MODEL_NAME` | deepseek 后端配置 |
| `TYPESAFE_API_KEY` | Jev 真实后端必需（`SYSTEMONE_BACKEND=jev`，或 JGP demo/run 用真 Jev） |
| `TYPESAFE_BASE_URL` / `TYPESAFE_DEFAULT_MODEL` | Jev SDK 覆盖项（默认模型 `jev-latest`） |
| `DEMO_SECONDS` | 玩具兵打枪 demo 运行时长（默认 8） |
| `JEV_RUN_SECONDS` | `jev run` 运行时长上限（默认不限，子进程退出或 Ctrl+C 结束） |

## 非目标

无 OCR、无寻路（直线移动 + Boids）、无重型框架；JGP v1 不含 WS 服务端
实现（协议保留 WS 作为将来可选传输）；慢脑（strategist）默认 disabled，
只注入静态 mission 指令。

## 公共决策流程与评测（2026-09-20）

多个使用入口共用一套 TypeScript 决策底座：请求管理、完整答案校验、双边调度、执行回执、历史/解卡接口和评测溯源。
四款内置游戏使用同一套执行审计与成效契约，回合和实时运行器共用答案校验与门控；
AI 对 AI、真人对模型的模型侧均使用公共实时运行器。物理持续推进，动作到期释放，
过时观察、复活、候选变化或控制权切换后的回复不会覆盖当前控制。

跳跃大厅默认是“模型选择落脚点＋本地物理寻路执行”的辅助模式，不能当作模型独立按键通关。
Deskfront 是 `deskfront-jevlab/` 下独立的 Godot 战术游戏；JGP、Deskfront、无尽关卡生成
保留各自的执行方式；JGP 和无尽生成已复用公共请求/校验，Deskfront 已对齐审计回执。详见 [公共流程、指标与接入边界](docs/shared-decision-flow.md)。

`npm run bench` 默认只跑 mock，不读取密钥、不调用付费模型。例：

`npm run bench -- --seeds 42,43 --repeats 2 --max-ticks 1200 --max-requests 40`

输出每局 JSONL 和 report.json，包含结果、无效动作、丢弃回复、成效、延迟、请求、token 和成本。
价格或用量未知时成本为 null，失败局保留。默认短局上限用于验证流程，不代表完整游戏胜率。
