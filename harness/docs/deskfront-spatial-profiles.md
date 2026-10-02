# Spatial query consumption and performance

HumanSquad in endless mode requests the `topology` profile. It shares one native
connectivity graph across units; the graph is rebuilt on run, navigation revision,
bounds, or output-path changes. No per-unit lattice, firing-point report, or sampled
path-risk report is produced by this profile. Execution validation and native
movement/fire checks remain active. Enemy perception remains faction-local.

Legacy `tick(arena, output)` callers retain the `full` report and its existing
freshness interval. Its hostile-unit selection is now faction-relative. This change
does not introduce a new squad threat planner or change model request intervals.
Do not increase topology grid spacing blindly: narrow passages depend on it.

Validation: stage the engine, copy `test/deskfront_spatial_profile.gd` to its tests
folder and run it with Godot headless. The probe checks report omission, topology
publication, navigation revision invalidation, output-path invalidation and cached
cost. Existing Python spatial freshness tests cover legacy report readers.

2026-09-23 probe on initial staged map: 297 cells, 550 edges; initial topology
5.393 ms, maximum of 1000 unchanged calls 0.020 ms. This is an isolated engine
probe, not a like-for-like replay of the previous 564 ms live battle peak. Live
verification was unavailable because the local service on port 3785 was stopped.
