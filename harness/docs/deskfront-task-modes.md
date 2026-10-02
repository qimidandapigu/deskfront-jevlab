# Mode-specific task contracts

`src/deskfront/task_modes.py` is the registry for command/completion pairs. `capture` supports flag control; `clear_exit` supports holding until a named enemy dies and excludes flag completion. Both reuse the same controller, execution tools and completion evaluators.

Selection uses explicit `state.task_mode`, then `scenario.kind`, then generated-world detection, otherwise capture. Unknown mode IDs fail closed. Prompt instructions and validation consume the same registry. Validated tasks carry their mode; progress invalidates tasks when modes change. Target IDs, actual death, arrival and recovery remain checked against game state.

To add a mode, register its allowed pairs and goal text, and provide its ID from the scenario adapter. New completion semantics require an implementation in commander_plan.progress and tests; this is a Python extension point, not runtime loading of arbitrary scripts. Engine win/loss and scenario-specific candidate generation remain separate adapters, not yet fully plugin-driven.

Plan rejection and provider failures now have separate UI messages. Existing active sessions retain loaded code; start a new session to use this contract.
