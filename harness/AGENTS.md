# 项目协作约定

## Deskfront 意图执行器

涉及 Deskfront 指令缓冲、执行权、中断或恢复时，先读 [意图执行器约定](docs/deskfront-intent-executor.md)。这是用户确认的术语与职责边界。

- 统一称为“意图执行器（IntentExecutor）”，仅指意图缓冲区 + 执行状态机。
- 不把它扩展成 Agent、战术决策层或另一套 Harness；不要使用 SoldierBehaviorController 作为该模块的同义名。
- 区分设计约定与已实现范围；具体执行以 Godot 状态及真实回执为准。
