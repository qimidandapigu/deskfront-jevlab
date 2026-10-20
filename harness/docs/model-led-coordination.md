# 模型战术权与独立问题契约（隔离 SDK 增量，2026-10-16）

基底：`deskfront-fire-reaction-stability-20261015/deskfront-sdk-harness`。本目录是候选公共 SDK，本文不代表已登记正式版本或真实对局验收。没有修改共享源码版、当前正式包、私有关卡生成器或模型服务端；没有新增模型请求。

## 已改

| 清点项 | 调整 | 保留的边界 |
| --- | --- | --- |
| bound 选项把实际支援火力作为移动必要条件 | 描述为按模型分工轮换机动，近期射击、弹药与装填是风险事实，不是队友移动许可 | 不强制选择 bound/advance；原生危险仍须复验；实际执行去门槛由配套 EXE 完成 |
| 共同任务/地图/装备/坐标规则仅在 intent.instructions | 坐标转换完成后，将整份最终契约放在共享 state.prompt_contract.shared_instructions 一次，每题明确引用 | 各题候选和真实事实不改变；不复制 N 份长说明，不增加请求 |
| 题目假设先回答 intent 再填写成员参数 | 每题说明独立读取同一状态、看不到本轮其他答案；role/route/flank/装备/支援注明自己的对象与实际消费分支 | continue_order 仍保留全部步兵任务；keep_assignment 仍忽略该兵新 role；支援参数独立执行 |
| equipment_support 题依赖未知的本轮 actor | 明确预问“假设另一人承担执行者时是否支援”；actor=unassigned、该兵就是 actor、continue_order 三种未用分支由代码忽略 | 不自动挑执行者；所用执行者/支援者、武器资格、路线、装备状态、控制权与回执照常验证 |
| current_plan.risk 容易被当作实时状态 | 记录 assessment_basis.observed_game_time（指挥请求）与 accepted_game_time（接受），两个模型视图保留；共同契约明确 risk/装备风险与理由属于该时刻判断，冲突以本轮事实为准 | 不改写模型历史理由，不臆造新理由；objective/stage 仍是当前任务；旧计划缺时间则明确未知 |
| 事实板把装填后的真实发射从 recent_fire_by_target 抹掉 | 该表现在记录确实发生的近期目标射击；当前 interruption 与 recent_uninterrupted_target_fire 分开保留 | 不把一次射击声称为持续压制、当前可发射或安全窗口；旧诊断不参与移动准入 |
| 原生 coordination 在各层摘要丢失 | 原值保留至己方小队/指挥视图与 cooperation_board.native_handoff，个人通过事实板获得 | 缺字段不制造默认值；未确认掩护不表示禁止移动，原生策略执行已选任务 |

## 候选中明确未改

- `wait_expired`、`cover_ready` 对旧等待/保护阶段的续期限制，以及同区阶段准入，属于既有任务期限与重复阶段政策，本轮没有扩大为生命周期重构。
- 原生路径候选、物理射击/友军/爆炸安全、装备可操作资格、坐标绑定、过期请求、控制 epoch、任务版本、失权、重复失败和回执接受检查没有取消。
- `flank_mover` 与 `flank_fire_base` 仍是独立选择，role 与 route 也仍独立。共享说明修复了作用域与假串行语义，不保证它们形成全局最优组合。代码仍只执行明确有效分支，不暗中替换模型路线。
- 没有把“近期开火较少”改成强制进攻信号，也没有提高 bound 选择概率或伪造模型理由。

## 后续协议提案（尚未实施）

如要求一对包抄成员必不相同，或每个 role 必须基于本轮新 route 比较，应改为同题完整方案候选，或在下一请求显式提供前一请求已选结果。完整候选容易组合膨胀；串行请求增加延迟与世界状态过期机会。当前可先以明确的独立预选、实际分支消费和真实组合回执工作，但不能把它宣传为已解决全部联合战术决策。

## 已验证

`python test/model_led_coordination_checks.py`：17/17 通过，使用候选 SDK 的真实请求构造、回答处理、命令提交和接受回执，传输是可控 Future，不调用外部模型、不启动游戏。

覆盖共同契约实际进入每题共享状态且坐标说明只一份；候选不变；火箭兵装填/空弹匣仍可选并提交 bound；hold 不被强制改写；历史计划与实时 hp/ammo/reload 分开；近期发射在装填中保留而不冒充掩护；装备条件分支；已用支援/执行者合法性；失权丢弃；继续命令保持任务；坐标不得创造落点。

另将现有 `deskfront_human_squad_checks.py`、`deskfront_equipment_assignment_checks.py`、`deskfront_coordinate_prompt_checks.py` 的相关 112 项检查导向本候选 Python 模块，全部通过。未运行旧的 `test_actor_cannot_also_support_self`：其“拒绝整单”断言已由本轮两项条件分支检查替代；未运行会写额外外部 fixture 的导出测试。

这些证明 SDK 组装与处理契约，不证明原生执行效果、模型选择改善或整局通关。仍需配套 EXE 的同队火箭装填期间推进、危险中断/恢复、真正回执和真实 JEV 对局验证。

复现入口：工作区 `output/model-led-coordination-20261016/sdk-tests/run_sdk_checks.py`。统一报告 `results.json` 与逐项日志 `run.log`，当前合计 **129/129（17 新增 + 112 原有相关检查）通过**，报告记录实际加载的候选 SDK 模块及 SHA-256。新增的两项验证真实小队/指挥请求与个人事实板保留原生 coordination，且缺字段时不伪造、敌方私有协作状态不泄露。
