# Module boundary

Public: SDK; DeepSeek stage/region plans; JEV squad/personal decisions;
emotion evidence/scheduling; commentary, TTS adapter, danmaku, real playback receipts.
Private: AI current-level analysis; next-level experience goals; layout selection
and editing; generation memory; authored design cards; private level provider.
Closed game: scene construction, offline levels, assets, navigation, ballistics.

Optional trusted provider.py exports PROTOCOL='deskfront-level-provider/v1'
and create_provider(state, game). The returned provider implements tick(public)
and close(). `public` is the real SDK spectator state/context. `state` submits
commands through the public SDK and actual worldControl lease. `game.ask` uses
the existing model broker; `game.record` writes actual evidence.
The public host renews/releases leases. Provider never launches/stages a game.
Without a provider the host takes no worldControl lease and imports no generator.

Current weapon behavior slots live in `src/deskfront/weapon_behavior.py`.
They are advisory profiles keyed by each actor's current weapon: role tendency,
spacing, approach/stop trade-offs and review conditions. They compose into the
existing squad and personal requests, preserve all existing legal choices,
and do not add a tactical controller or model request. Unknown weapons have no
implicit rifle profile. Late responses are invalidated when weapons change;
a real observed change wakes one existing personal review subject to its
normal cooldown and budget, without changing the accepted squad assignment.

`hold_fire_position` is offered only when the current native snapshot reports
`combat.personal_action_capabilities.hold_fire_position.supported` and
`available` as true. Its no-target/no-site command carries an `action_id` from
the real provider `requestId`, with a logged stable local decision ID fallback
for older/mock responses. Native admission still decides whether the action
can execute. Its fixed maximum is three game seconds and it preserves the
accepted route/cursor/deadline; native danger, invalidation and expiry take
precedence. `combat.firing_hold` supplies actual state and terminal reasons.
The existing `focus_fire` cancels current motion and is explicitly described
with that cost. This public package does not implement either native action.
