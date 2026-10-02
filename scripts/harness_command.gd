extends RefCounted
## Harness command protocol facade.
##
## This adapter owns only the Harness-owned command vocabulary and the
## human-squad command branches.  Game.gd remains the authority for world
## validation, combat, navigation and command receipts; this class delegates
## accepted changes back to that game instance.

var game

const TACTICAL_ACTIONS: Array = [
	"soldier_order", "unit_emotion", "squad_order",
	"move", "capture", "flank", "cover", "hold", "retreat", "attack",
	"grenade", "posture", "man_at_gun", "leave_gun", "garrison", "leave_building",
]

func setup(owner) -> void:
	game = owner

func tactical_actions() -> Array:
	return TACTICAL_ACTIONS.duplicate()

## Handle commands introduced by the Harness human-squad protocol.
##
## The caller still owns ack(), so the public receipt shape and all existing
## command entry points remain in game.gd.  A false `handled` means that the
## native game command dispatcher should continue with its normal branches.
func handle_special(command: Dictionary, team: String, ids: Array) -> Dictionary:
	var action: String = str(command.get("action", ""))
	if action == "unit_emotion":
		if not game.human_squad or str(command.get("source", "console")) != "lm":
			return _handled(false, "emotion_authority_required")
		if game.winner != "":
			return _handled(false, "match_finished")
		if ids.size() != 1 or command.get("emotion", "") not in ["calm", "alert", "nervous", "afraid", "determined", "relieved"]:
			return _handled(false, "invalid_emotion")
		var members: Array = game.living(team).filter(func(unit): return unit.id == ids[0])
		if members.is_empty():
			return _handled(false, "invalid_unit_authority")
		var member = members[0]
		member.emotion = command.emotion
		member.emotion_until = game.elapsed + 12.0
		return _handled(true, "emotion_applied")

	if action == "soldier_order":
		if not game.human_squad or str(command.get("source", "console")) != "lm":
			return _handled(false, "soldier_authority_required")
		if game.winner != "":
			return _handled(false, "match_finished")
		var personal_result: String = game.human_squads.accept_personal(command)
		return _handled(personal_result == "applied", personal_result)

	if action == "squad_order":
		if not game.human_squad:
			return _handled(false, "human_squad_disabled")
		var source: String = str(command.get("source", "console"))
		if source not in ["lm", "agent"]:
			return _handled(false, "squad_authority_required")
		if game.winner != "":
			return _handled(false, "match_finished")
		var squad_result: String = game.human_squads.accept(command)
		return _handled(squad_result == "applied", squad_result)

	return {"handled": false}

## Handle the Harness-only runtime switch while leaving native parameter
## updates in game.gd.  This keeps the second dispatcher branch explicit.
func handle_config(command: Dictionary) -> Dictionary:
	if str(command.get("key", "")) != "human_squad":
		return {"handled": false}
	var value: float = float(command.get("value", 0))
	if not is_finite(value):
		return _handled(false, "invalid_parameter")
	game.human_squad = value >= .5
	game.get_tree().set_meta("human_squad", game.human_squad)
	for faction in game.control:
		game.tactics_ai.cancel(faction)
		if game.human_squads:
			game.human_squads.cancel(faction)
	return _handled(true, "applied")

func on_control_mode_changed(team: String, mode: String) -> void:
	if game.human_squads and game.control[team] != mode:
		game.human_squads.cancel(team)

func squad_snapshot() -> Dictionary:
	return game.human_squads.snapshot() if game.human_squads else {}

func _handled(accepted: bool, message: String) -> Dictionary:
	return {"handled": true, "accepted": accepted, "message": message}
