# Deskfront

- 与用户沟通、项目文档使用中文；稳定 API 字段使用英文。
- Godot 是唯一战斗状态真相源；控制台不可伪造运行数据。
- 保留 source/blender 旧版与 source/latest 当前资源的 .blend、骨骼、动作和导出 GLB；不得用旧生成目录覆盖当前运行资源。
- 所有运行素材必须记录来源与许可。参考图只用于构图研究，不进入开源发布包。
- 更改机制后运行 tests/semantic_probe.tscn 和 Python 接口测试；发布必须验证真实 Web 输入。

## 与 Harness 共用的执行术语

- 用户确认名称为“意图执行器（IntentExecutor）”，仅包含意图缓冲区 + 执行状态机；不承担模型思考、战略区域选择或小队战术分工，不是另一套 Harness 或 SoldierBehaviorController。
- 修改指令、执行权、中断或恢复前，读取 [统一约定](harness/docs/deskfront-intent-executor.md)；若使用独立 Harness 工作树，则读取其对应的 `docs/deskfront-intent-executor.md`。当前能力仍分布于 human_squads.gd，不能声称已有完整独立类。
- 受管普通移动复用 request_motion 仲裁入口；紧急避险等未全部迁移的通道须保留安全边界，禁止恢复时盲目重放旧路线。
