# Public Deskfront Harness

The game and AI level generator are distributed separately. Use the public
SDK; do not add dependencies on the private game source or generator.
IntentExecutor means only intent buffer + execution state machine, owned by
the engine. It is not an Agent or a tactical decision layer.
Model intent, accepted command, engine execution and actual completion are
distinct. Preserve real receipts and visibility. Never ship credentials.
See MODULES.md and docs/open-source/deskfront-module-packaging.md.
