# 发行包、公开 Harness 与私有关卡生成器

2026-10-10：按依赖导出两个独立模块，游戏仍单独提供 Windows 发行包。

| 交付物 | 包含内容 | 不包含内容 |
| --- | --- | --- |
| 游戏发行包 | 可直接运行的 EXE、资源、内置算法、32 份实际关卡布局、本机 SDK 服务 | 云端密钥、外部模型运行环境 |
| SDK／Harness 候选包 | Python／TypeScript SDK、DeepSeek 战术规划、JEV 小队与个人执行、情绪、解说、弹幕 | Godot 源码、资源、AI 关卡生成算法、设计卡、运行日志和密钥 |
| 私有关卡生成包 | 当前关分析、下一关体验目标、JEV 关卡策划、九格空间搭建与修改、生成记忆 | 游戏源码、游戏启动器 |

SDK 和 Harness 是两个职责，当前放在同一个公开候选包交付：SDK 提供通信能力，Harness 实现决策和调度。别人可以修改 Harness 怎样指挥小兵，不需要游戏源码。

2026-10-12：公开候选包增加可选 Open Annie 主播。包含可修改的适配器、带源码的 WebView2 子窗口宿主，以及单独授权的第三方 VRM／动作素材和许可；没有增加私有游戏源码或游戏美术。仅允许导出 `tools/deskfront-presenter/bin/DeskfrontAnnieHost.exe` 这一个公开源码宿主 EXE，仍禁止游戏 EXE／PCK／GD 进入公开包。主播在真实 AI 观战模式默认开启，可用 `--annie false` 关闭；需要 Windows x64、.NET Framework 4.6.2+ 和 WebView2 Runtime。构建脚本为 `scripts/build-deskfront-presenter.py`，详细链路见 `docs/deskfront-commentary.md`。本功能尚未正式发布。

## 默认运行

玩家双击 `Deskfront.exe`：内置算法战斗，真实本地关卡继续推进，不请求模型。

AI 开发者解压公开候选包，安装 Node.js 20+、Python 3.10+：

```powershell
npm install
npm start -- --backend jev --levels local --seconds 300 --requests 600
```

先配置自己的 `.env` 或 `config.local.json`。也可用 `--config <外部模型配置>`、`--env-file <外部环境配置>`，密钥文件无需放进候选包。多个游戏实例使用 `--connection <该局 connection.json>`。

这里 `local` 只指关卡来源。战术、表情、解说与弹幕仍使用 AI；`--spectator false` 单独关闭解说和弹幕。关卡是实际搭建、战斗、结算的本地内容，不是伪造模型结果。

## 显式接入私有生成器

```powershell
npm start -- --backend jev --levels ai --level-generator C:/private/deskfront-level-generator-private/provider.py --seconds 300 --requests 600
```

要从 AI 生成第一关，游戏启动时加 `--wait-for-harness`。私有模块缺失或协议不符会明确报错，不假装 AI 成功、也不悄悄启用其他生成器。

公开端只提供 `deskfront-level-provider/v1` 加载接口：私有入口导出 `PROTOCOL` 和 `create_provider(state, game)`，返回 `tick(public)`／`close()`。它收到真实 SDK 状态，沿用模型代理并通过 SDK 提交布局。私有包使用自身的相对依赖，可以放在公开包之外，不依赖原仓库源码路径。模块是可信的本地 Python 代码，不是沙箱插件。

## 执行权

无私有生成器时，Harness 仅申请两队的战术租约，`worldControl=false`；游戏的本地关卡生成持续运行。

只有显式启用私有生成器才申请绿色 `worldControl=true`，本地生成暂停让出关卡控制。结束后交还租约。本机暂停属于绿色游戏控制，不要求关卡生成权；红色租约不能暂停整局。导航、弹道、安全执行与 IntentExecutor 仍归游戏，IntentExecutor 仅是意图缓冲区＋执行状态机。

## 导出与验收

```powershell
python scripts/export-deskfront-modules.py --output output/module-exports/新的目录
python test/deskfront_module_exports_checks.py
```

导出按实际 Python／TypeScript 依赖收集，排除私有生成和无关游戏示例；两份 ZIP 分开，不复制 `.env`、模型配置、日志或游戏源码。公开包在不含私有源码的隔离 Python 进程中成功加载；私有包独立完成模型回归的九格方案生成。公开包执行 `npm install`、TypeScript 检查及真实 EXE／模型试跑。

这是可运行的本地开源候选包，尚未发布到 GitHub；许可证与署名须在正式发布前确定。当前真实运行证据在 `output/release-public-harness-20261010`，原生权限验证在 `output/release-level-authority-20261010-v2/sdk-authority.json`。这些证明拆分和运行链路，不代表所有战术表现已经优化完成。

## 与原版的差异及边界

原来的源码启动模式仍保留：`src/deskfront/host.py` 的 `infinite` 分支进入
`src/deskfront/world/host.py`，仍同时运行 AI 生成器与红绿 Harness。
拆分版复用同一套 HumanSquadController、单兵与情绪实现，但默认 `local`
改用内置关卡；这会改变布局、兵力、节奏与遭遇，不能直接用于证明与原版等价。
要对照原版，须显式接私有生成器并使用同一场景与初始条件。

源码模式使用旧 `lm` 控制方式，SDK 租约使用 `agent`。SDK 已对齐基本战斗
事实和表情接管，但原生代码仍有只检查 `lm` 的姿态保护、旗点提示等分支；
是否影响当前无尽模式须按分支条件做行为对照，不能宣称仅改变了通信方式。
候选点接口也由原文件查询改为公开 HTTP 查询，数据投影和时序尚未做全面等价验收。

本次真实试跑日志确认 `controllers=[green,red]`、`worldGeneration=false`，
红绿实际均提交了 Harness 指令；本地关卡进入第四关。测试 EXE 已正常退出，
随后 SDK 连接拒绝导致 Harness 以 error 结束，不属于请求额度耗尽或红队未接入。
游戏退出原因不能仅由 exitCode=0 判定为测试定时结束，仍需结合窗口操作及启动期限。

## 支援单位公共接口（2026-10-12）

每个 actor 的 `actionCapabilities` 声明其实际能力：自由步兵可接受 squad 意图，坦克和固定炮组提供 support 意图，人类角色（包括待救士兵）提供 `presentation.emotion`。坦克本体没有人的情绪。权限仍由团队租约及原生状态校验，界面租约标签不等于该单位已有模型任务。

`/v1/intents` 支持 `support.support_area`、`support.engage`、`support.hold_fire`；车辆另有 `support.move_area`，固定迫击炮另有 `support.release_crew`。`intent.parameters` 包括 `assetId`、`assetKind`（vehicle/equipment）、`position`（SDK 三维坐标）、`targetId`（engage 必填）。外层仍提交 context、leaseId、controlEpoch、actorIds、任务版本及游戏时间有效期。炮组 actorIds 必须与当前活着的操作成员一致。现有 `/v1/deskfront/commands` 亦支持 `support_order` 兼容提交。

回执区分接收与执行，实际支援状态只提供给所属团队或 spectator。撤销只停止本租约的对应任务；地图、成员能力或执行权变化会废弃旧模型响应。公共 Harness 的 `actor_roster`、`human_squad_support` 随依赖导出，私有关卡生成仍独立，不复制模型密钥或原生游戏源码。
