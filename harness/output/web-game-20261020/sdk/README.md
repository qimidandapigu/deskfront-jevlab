# Deskfront SDK + Harness (open-source candidate)

Game EXE is distributed separately. This package observes and commands the
binary through the public loopback SDK. It does not contain Godot code/assets,
AI level generation algorithms, design cards, provider keys or recorded games.
Local real levels continue inside the game, independently of AI tactical control.

The current EXE reports `ammo_infinite: true` for unlimited gun/cannon ammunition
without reloading. The nominal `ammo` capacity remains a compatibility field;
combat requests carry the explicit rule instead of interpreting it as ammunition
remaining. Grenades retain their independent finite inventory. Historical
observations without the flag keep their recorded magazine/reload semantics.

Requirements: Node.js 20+, Python 3.10+, the player release v10 or newer.

1. Extract and start Deskfront.exe.
2. Run `npm install` here.
3. Copy `.env.example` to `.env` and configure your own JEV/DeepSeek/voice keys.
4. Run `npm start -- --backend jev --levels local --seconds 180 --requests 600`.
5. For multiple games add `--connection <the game's connection.json>`.
   Existing credentials can stay outside this package with
   `--config <model-config.json> --env-file <voice-and-provider.env>`.

For a fresh complete AI run, use `--game <Deskfront.exe>` instead of `--connection`.
The Harness prepares its server, starts the binary with `--wait-for-harness`, and
attaches immediately. Manual delay over 30 seconds lets the game start a local
opening map. Use `--levels ai --level-generator <private provider.py>` and verify
an actual completed world receipt; the configured levelSource alone is not proof.
Game ownership stays with the player; closing Harness does not terminate it.

The public starter controls both teams. Emotion, commentary and danmaku use
existing controllers; `--spectator false` disables commentary/danmaku/presenter.
AI spectator sessions also embed the optional Open Annie avatar in the native
game window. `--annie false` disables only the avatar. Windows x64, .NET
Framework 4.6.2+ and Edge WebView2 Runtime are required for this component.
It reuses native commentary audio; JEV picks face/gesture once per utterance.
The included third-party avatar and animations carry their own licenses under
`src/deskfront/annie-assets/`; they are not private game art. See
`docs/deskfront-commentary.md`. Rebuild the public-source host with
`python scripts/build-deskfront-presenter.py`.
Edit `src/deskfront/human_squad*.py`, `soldier_agents.py` and emotion modules
to change decisions without modifying the closed game. Native navigation,
ballistics, immediate safety and IntentExecutor remain game responsibilities.

AI levels are optional and PRIVATE. Only with a separately obtained trusted
provider can you use `--levels ai --level-generator <private/provider.py>`.
Never load an untrusted Python provider. The module is local executable code.
The generic interface is `deskfront-level-provider/v1`, documented in MODULES.md.

This is a local export candidate, not an already published open-source release.
Select a license and review authorship/dependency notices before publication.
No keys are shipped; credentials remain in your external Harness.
