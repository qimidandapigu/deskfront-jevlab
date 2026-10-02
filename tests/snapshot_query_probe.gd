extends SceneTree

class CountedUnit extends "res://scripts/unit.gd":
	var queries: int=0
	var clear_lane: bool=true
	func can_engage(_enemy) -> bool:
		queries+=1
		return clear_lane

func _initialize():
	var a=CountedUnit.new();a.id="a"
	var b=CountedUnit.new();b.id="b";b.clear_lane=false
	var cache: Dictionary={}
	var checks: Array=[]
	checks.append(a.snapshot_engagement(b,cache))
	checks.append(a.snapshot_engagement(b,cache) and a.queries==1)
	checks.append(not b.snapshot_engagement(a,cache) and b.queries==1 and cache.size()==2)
	a.clear_lane=false
	checks.append(not a.snapshot_engagement(b,{}) and a.queries==2)
	checks.append(not a.can_engage(b) and a.queries==3)
	print("SNAPSHOT_QUERY "+JSON.stringify({"checks":checks,"passed":not checks.has(false)}))
	a.free();b.free();quit(1 if checks.has(false) else 0)
