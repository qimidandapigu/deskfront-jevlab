# Deskfront 模块边界

模块化边界和事实源见 [所有权与模块化边界](deskfront-ownership-boundary.md)。原生游戏中用户自己的改动也属于可重构范围；上游未改动代码和 Godot 引擎保持不变。

这份文档是当前实现的维护入口。它描述已经存在的职责边界，不把设计目标写成已实现能力。

## 运行分层

```text
页面与 HTTP
  viewer/server.ts
  viewer/http.ts
  viewer/*-routes.ts
        |
会话与模式
  arena/sessions.ts
  deskfront/runtime.ts
  deskfront/host.py
        |
模型与战术
  deskfront/world/director.py
  deskfront/tactics.py
  deskfront/human_squad.py
        |
意图与真实执行
  deskfront/world/intent_executor.gd
  deskfront/world/growth.gd
  Godot 原生移动、碰撞、射击、伤亡和任务结算
        |
观测与展示
  deskfront/commentary*.ts
  deskfront/danmaku*.ts
  deskfront/page.ts
```

## 模块职责

| 模块 | 只负责 | 不负责 |
|---|---|---|
| `viewer/http.ts` | HTTP body、JSON 和响应头 | 会话状态、模型请求 |
| `viewer/*-routes.ts` | 路由匹配和协议适配 | 运行器生命周期、战斗决策 |
| `viewer/page-templates.ts` | 首页、模型配置、回放和游戏页面渲染 | 会话运行和路由匹配 |
| `human_squad_contract.py` | 小队意图、事件和提示词常量 | 调度、引擎调用 |
| `human_squad_context.py` | 观测和上下文投影 | 选择战术、执行移动 |
| `human_squad_model.py` | 请求、预算、超时和陈旧结果处理 | 改写引擎状态 |
| `human_squad_orders.py` | 命令提交和版本检查 | 模型提示词生成 |
| `human_squad_receipts.py` | 引擎回执归一化 | 决定下一条战术 |
| `human_squad_snapshot.py` | 对外快照 | 运行调度 |
| `tactics_policy.py` | 协调策略常量和纯策略函数 | 模型请求、引擎状态 |
| `tactics_payload.py` | 协调器的模型 payload 投影 | 提交命令、改变引擎 |
| `tactics_coordination.py` | 小队计划、路线、预约和命令协调 | 页面渲染、HTTP |
| `tactics_controller.py` | Harness 控制器和模型客户端生命周期 | Godot 物理实现 |
| `deskfront-jevlab/scripts/human_squads.gd` | 原生小队入口、动作协调和兼容包装 | 模型调用、Harness HTTP |
| `deskfront-jevlab/scripts/human_squad_perception.gd` | 原生小队感知、可见敌人和威胁投影 | 指挥决策、执行权仲裁 |
| `deskfront-jevlab/scripts/human_squad_snapshot.gd` | 原生小队只读快照投影 | 改写战斗状态 |
| `deskfront-jevlab/scripts/battlefield_navigation.gd` | 原生网格重建、寻路、战术寻路和路线工具 | 掩体事实、伤害、视觉构建 |
| `deskfront-jevlab/scripts/combat_ballistics.gd` | 纯弹道散布与爆炸预警几何 | 碰撞、伤害、VFX 和音频 |
| `deskfront-jevlab/scripts/harness_command.gd` | Harness 小队/情绪/配置命令分支 | 原生世界校验、回执和物理执行 |
| `deskfront-jevlab/scripts/unit_presentation.gd` | 单位动画映射、展示刷新和暂停展示 | 单位状态、射击、命中、意图执行 |
| `deskfront-jevlab/tools/command_protocol.py` | 原生命令协议结构校验 | HTTP 服务生命周期、Godot 状态 |
| `deskfront-jevlab/tools/lm_provider.py` | Provider 配置、请求载荷和客户端 | 小队战术、游戏状态写入 |
| `world/director_contract.py` | 世界导演宏观合同和验证 | 调度、模型调用 |
| `world/macro_bridge.py` | 宏观选择到导演状态的桥接 | 引擎移动、战斗 |
| `world/stage.py` | 对外 staging API | 具体复制阶段实现 |
| `world/stage_pipeline.py` | 临时副本、补丁、资产和自动加载装配 | 战斗规则 |
| `world/stage_source.py` | 原生源树复制 | 补丁和战斗逻辑 |
| `world/stage_overlay.py` | UI、表情、弹幕和自动加载覆盖 | 单兵行为 |
| `world/stage_squads.py` | 小队脚本补丁 | 页面路由 |
| `world/stage_unit.py` | 单位脚本补丁 | 关卡策划 |
| `world/stage_combat.py` | 战斗和弹道脚本补丁 | 生成决策 |
| `world/stage_world.py` | 世界脚本、资产和测试装配 | HTTP 会话 |
| `world/growth_visual.gd` | 桌面/文具表现构建 | 任务、战斗和区域生命周期 |
| `world/growth_staging.gd` | 坦克/迫击炮站位及 staging 几何辅助 | 模型决策、引擎结算 |
| `world/growth_mission.gd` | 遭遇任务更新和结果记录 | 内容生成、模型调用 |
| `world/growth_retirement.gd` | 有界区域卸载、占用保护和导航刷新 | 战术选择、传送单位 |
| `world/growth_local_ai.gd` | 明确配置为本地 Bot 时的战斗计划 | Harness/真实模型替代 |
| `world/intent_executor.gd` | 意图缓冲和执行状态机 | 模型调用、战术选择 |

## 依赖规则

1. 页面只能调用公开 HTTP 协议，不能直接 import Python 控制器。
2. 路由只能调用会话服务或展示服务，不能修改 Godot 状态。
3. 纯合同、记录和校验模块不依赖模型 SDK、HTTP 或 Godot。
4. IntentExecutor 不调用模型、不选择区域、不重新分配职责。
5. Godot 是移动、碰撞、射击、伤亡和任务完成的事实来源。
6. staging 只能写临时副本；不能修改 `C:\\game\\deskfront-jevlab`。
7. `queued`、模型返回和 HTTP 202 都不是完成证据；完成必须有引擎回执或任务结果。

## 维护顺序

大文件继续拆分时，先抽纯函数和记录，再抽有状态服务，最后才移动生命周期。每次拆分都必须保留原有公开导入路径和日志字段，并通过 TypeScript、Python、Godot staged 检查。不要为了文件变小而把同一份状态复制到第二套真相源。
