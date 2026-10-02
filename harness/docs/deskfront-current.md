# Deskfront 当前版：无尽推进

这是 Deskfront 的现行使用说明。旧的 1v1、三路前哨和固定战术场景仍保留给回归测试，但不再作为与当前版并列的产品模式。

## 先看结论

- 对外唯一主模式是 **无尽推进（当前版）**；后台回归使用同一规则的 `infinite-headless`。
- 页面有“第二关坦克”开关，默认开启，且只影响第二关。第一关始终正常交战；开关打开时，清场后生成坦克支援，必要时补一名火箭兵，关闭时第二关不生成坦克。
- 默认真实 AI 链路是 **火山 DeepSeek 指挥 + JEV 小队执行 + Godot 权威执行**。页面里的决策项显示为“DeepSeek 指挥 + JEV 小队执行”，请求入口值仍是 `backend: "jev"`，因为角色路由由 Harness 负责：`commander -> deepseek`，小队/个人执行 -> `jev`。
- `mock` 只用于离线规则回归，页面会明确标为“不调用模型”。它不能作为真实 AI 效果证据。
- `secondStageTankShowcase` 是单独的演示开关：它会跳过首关交火并在第二关坦克入场后暂停，不能和完整无尽推进混为一谈。
- 当前无限推进是连续生成的 AI/观战验证链路。暂停和结束已接通；玩家直接下达小队战术命令的闭环仍在后续路线中，不能把 `capabilities.human` 当成已经完成的玩家指挥体验。

## 运行

仓库需要和原生 Deskfront 游戏并列存在：

```text
C:\game\quickplay-harness
C:\game\deskfront-jevlab
```

如果目录不同，先设置原生游戏路径。Windows PowerShell 示例：

```powershell
$env:DESKFRONT_ROOT = 'C:\game\deskfront-jevlab'
$env:GODOT_BIN = 'C:\game\.artifacts\godot-4.5.1\Godot_v4.5.1-stable_win64_console.exe'
npm install
npm run typecheck
npm run serve
```

打开 <http://127.0.0.1:3777/runtime/deskfront>，选择“无尽推进（当前版）”，按需要勾选“第二关坦克（默认开启）”，再启动真实游戏。第一次配置模型可以复制 `config.local.example.json` 为根目录的 `config.local.json`，填入密钥；该文件被 `.gitignore` 忽略，不能提交。

不调用模型的离线检查：

```powershell
npm test
python test/deskfront_world_hooks_checks.py
python test/deskfront_soldier_agent_checks.py
```

`npm test` 默认不启动付费模型或长时间 Godot 对局；带 `DESKFRONT_WORLD_TEST=1` 的测试才会打开原生世界 smoke，真实模型验收仍需要已配置的 key、明确的运行预算和单独的日志检查。

CLI/API 也可以直接使用 `variant: "infinite"`。后台回归用 `variant: "infinite-headless"`；两者共用无尽推进规则和默认坦克配置，区别只有是否打开可视窗口。

## 模式边界

| 入口 | 当前用途 | 坦克规则 | 是否作为产品入口 |
|---|---|---:|---:|
| `infinite` | 完整无尽推进、实时生成、AI 战斗 | 页面开关，默认开 | 是 |
| `infinite-headless` | 同规则的自动化/CI 回归 | `secondStageTankRule`，默认开 | 后台验证 |
| `duel*`、`native`、`headless` | 历史战术、兼容性和固定场景测试 | 依测试配置 | 否 |

旧入口可以被已有测试或直接 CLI 请求调用，但它们不代表当前版能力，也不应被拿来比较无尽推进的坦克、迫击炮、解说和弹幕能力。

当前版无尽主机实际读取的产品选项只有：`teamRequestLimit`、`greenController`、`redController`、`secondStageTankRule`（默认 `true`，只影响第二关）和 `secondStageTankShowcase`（默认 `false`）。旧的 `behavior`、`modelFaction`、`opponent`、`tacticalValidation` 只属于历史回归路径，已经从当前产品目录的公开选项中移除。

## 代码职责

```text
src/external/runtime.ts       公共会话、预算、进程和角色请求路由
src/deskfront/world/host.py   Deskfront 无尽主机；启动 staged Godot、转发回执、收尾
src/deskfront/world/director.py
                              体验理解、遭遇策划、空间生成与建成回执
src/deskfront/human_squad_contract.py
                              意图、事件和提示词协议常量；无运行时状态
src/deskfront/human_squad_context.py
                              观测、区域导航和模型上下文投影
src/deskfront/human_squad_model.py
                              请求调度、预算、超时和陈旧结果处理
src/deskfront/human_squad_orders.py
                              命令提交、版本和执行前检查
src/deskfront/human_squad_receipts.py
                              引擎回执归一化和战斗事件记录
src/deskfront/human_squad_snapshot.py
                              对外小队快照和状态投影
src/deskfront/human_squad_records.py
                              CallLog/SharedRequestBudget；无引擎依赖
src/deskfront/human_squad_validation.py
                              位置与规划校验；无模型/引擎依赖
src/deskfront/human_squad.py  小队控制器兼容入口和协调外壳
src/deskfront/tactics.py       战术控制兼容入口
src/deskfront/tactics_policy.py
                              协调策略常量和纯策略函数
src/deskfront/tactics_payload.py
                              战术模型输入投影
src/deskfront/tactics_coordination.py
                              小队路线、预约和命令协调
src/deskfront/tactics_controller.py
                              战术控制器和模型客户端生命周期
src/deskfront/world/director.py
                              世界导演生命周期兼容入口
src/deskfront/world/director_contract.py
                              宏观阶段、激素和目标合同
src/deskfront/world/macro_bridge.py
                              宏观选择到导演状态的桥接
src/deskfront/world/growth_visual.gd
                              无尽区域的桌面/文具表现构建；不负责任务或战斗
src/deskfront/world/growth_staging.gd
                              坦克/迫击炮 staging 几何与反坦克站位辅助
src/deskfront/world/growth_mission.gd
                              遭遇任务状态、完成/失败和结果记录
src/deskfront/world/growth_retirement.gd
                              有界后方区域卸载、占用保护和导航刷新
src/deskfront/world/growth_local_ai.gd
                              明确配置为本地 Bot 时的原有战斗计划
src/deskfront/world/intent_executor.gd
                              意图缓冲区 + 执行状态机，不调用模型、不做战术决策
src/deskfront/world/stage.py  staging 对外兼容入口，不改原生游戏仓库
src/deskfront/world/stage_contract.py
                              staging 补丁合同和兼容锚点
src/deskfront/world/stage_pipeline.py
                              临时副本、资产、脚本、自动加载和测试装配阶段
src/viewer/deskfront-routes.ts
                              Deskfront 解说/弹幕 HTTP 路由；不拥有对局生命周期
src/viewer/http.ts           通用 HTTP body、JSON 和响应辅助
src/viewer/config-routes.ts  配置、模型列表和试连路由
src/viewer/match-routes.ts   会话、回放和对局协议路由
src/viewer/static-routes.ts  静态资源和 Kaplay 资源路由
src/viewer/page-templates.ts 页面模板兼容汇总入口
src/viewer/theme.ts           通用视觉主题
src/viewer/home-page.ts       首页和模型配置页面
src/viewer/replay-page.ts     回放页面
src/viewer/game-page.ts       游戏运行页面
src/viewer/runtime-page.ts    外部运行时页面
src/deskfront/commentary*.ts  AI 战况解说、字幕/语音状态
src/deskfront/danmaku*.ts     AI 弹幕及密度控制
src/deskfront/page.ts         当前版网页入口和轮询展示
```

Godot 仍然是移动、碰撞、姿态、射击、弹道、伤亡和任务完成的权威。模型回复、HTTP 202 和“已提交”都不是完成证据；要看引擎快照、执行回执和最终任务状态。每局的模型请求、原始回答、执行结果和结束原因落在 `logs/<session-id>/`。

## 维护规则

1. 新的产品能力先落在 `infinite`，再补 `infinite-headless` 回归；不要再为同一能力新建一个页面模式。
2. 旧 `duel*` 只用于兼容测试。若必须修改，注明它与当前无尽版的差异，不能把旧结果写成当前版证据。
3. 所有引擎改动必须通过 `stage.py` 进入临时副本；不要编辑 `C:\game\deskfront-jevlab`。
4. 回归分为 Python/TypeScript 合同、Godot 原生行为、真实模型请求、可视试玩四层报告，不能把其中一层冒充另一层。

目前 `src/viewer/server.ts` 仍是大厅、页面生成和运行器装配入口，`src/deskfront/human_squad.py` 仍是兼容外壳，但 HTTP 路由、小队上下文/模型/命令/回执/快照、staging 流水线和区域表现已经分别抽出。后续只在决策/生成模块仍混合多个职责的地方继续按相同规则拆分，保持协议和日志格式不变。
