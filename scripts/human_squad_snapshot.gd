extends RefCounted
## 人类小队快照投影。
## 只读地把运行时状态映射到稳定的 Harness 协议，不改变战斗状态。

var host

func _init(owner) -> void:
	host=owner

func write() -> Dictionary:
	var game=host.game
	var result: Dictionary={"enabled":game.human_squad,"squads":{},"perception":{},"event_seq":host.event_seq,"events":host.events.duplicate(true)}
	for sid in host.squads:
		var s: Dictionary=host.squads[sid]
		result.squads[sid]={"faction":s.faction,"unit_ids":s.unit_ids,"order_id":s.order_id,"intent":s.intent,"phase":s.phase,"reason":s.reason,"goal":[s.goal.x,s.goal.y],"radius":s.radius,"progress":s.progress,"mover":s.mover,"support_ids":s.get("support_ids",[]),"shape":s.shape,"protection":s.get("protection",{}),"duties":{},"fire_positions":s.get("fire_positions",{}),"cover_detours":s.get("cover_detours",{}),"personal":s.get("personal",{}),"assignments":s.get("assignments",{})}
		for uid in s.get("duties",{}):
			var d: Dictionary=s.duties[uid]
			result.squads[sid].duties[uid]={"role":d.role,"reason":d.reason,"unresolved_for_s":game.elapsed-float(d.progress_at),"attempts":d.failures}
	for team in host.perception:result.perception[team]={"contacts":host.perception[team].values().duplicate(true)}
	return result
