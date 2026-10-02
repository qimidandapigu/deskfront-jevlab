extends SceneTree

class FakeUnit extends RefCounted:
	var id="green-1"
	var hp=50.0
	var game={"field":{"revision":1}}
	var path_failure=""
	var position=Vector2.ZERO
	var safety_until=0.0
	var posture_order="auto"
	var grenade_time=-1.0
	var route=PackedVector2Array([Vector2(.5,.5)])
	var goal=Vector2(.5,.5)
	func pos() -> Vector2:return position
	func move_to(destination: Vector2, _precise: bool=false) -> void:
		goal=destination;route=PackedVector2Array([destination])
	func occupy(slot: Dictionary) -> void:move_to(slot.position)

class FakeGame extends RefCounted:
	var elapsed=1.0

func _initialize() -> void:
	assert(load("res://scripts/human_squads.gd")!=null)
	assert(load("res://scripts/harness_unit.gd")!=null)
	var squads=load("res://scripts/human_squads.gd").new()
	var fake_game=FakeGame.new()
	squads.game=fake_game
	var managed=FakeUnit.new()
	var order={"order_id":"team-1","mover":"","support_ids":[]}
	assert(squads.request_motion(managed,order,"station",Vector2(.5,.5)))
	assert(squads.request_motion(managed,order,"station",Vector2(.51,.5)))
	assert(absf(squads.intent_executor.snapshot().motion[managed.id].until-7.0)<.001)
	assert(not squads.request_motion(managed,order,"formation",Vector2(.7,.5)))
	assert(squads.request_motion(managed,order,"fire_position",Vector2(.6,.5)))
	assert(squads.intent_executor.snapshot().motion[managed.id].source=="fire_position")
	squads.free()
	var executor=load("res://scripts/intent_executor.gd").new()
	var u=FakeUnit.new()
	assert(executor.propose_motion(u,"order-1","formation",Vector2(.5,.5),1)=="accepted")
	executor.start_motion(u,"order-1","formation",Vector2(.5,.5),1)
	assert(executor.propose_motion(u,"order-1","formation",Vector2(.51,.5),2)=="retained")
	assert(absf(executor.snapshot().motion[u.id].until-7.0)<.001)
	assert(executor.propose_motion(u,"order-1","station",Vector2(.6,.5),2)=="accepted")
	executor.start_motion(u,"order-1","station",Vector2(.6,.5),2)
	assert(executor.propose_motion(u,"order-1","formation",Vector2(.7,.5),3)=="rejected_owned")
	u.safety_until=5
	executor.observe(u,3)
	assert(executor.snapshot().motion[u.id].state=="suspended")
	assert(not u.has_meta("motion_owner"))
	u.safety_until=0
	assert(executor.propose_motion(u,"order-1","station",Vector2(.6,.5),5)=="accepted")
	executor.start_motion(u,"order-1","station",Vector2(.6,.5),5)
	assert(not executor.cancel_motion(u,"stale",5,"order-0"))
	assert(executor.cancel_motion(u,"new_order",5,"order-1"))
	assert(u.route.is_empty() and executor.snapshot().motion[u.id].state=="cancelled")
	assert(executor.request_posture(u,"stand","order-2",5))
	assert(u.posture_order=="stand")
	u.safety_until=7
	executor.observe(u,6)
	assert(u.posture_order=="auto")
	assert(executor.snapshot().posture[u.id].reason=="engine_safety")
	u.safety_until=0
	assert(executor.request_posture(u,"stand","order-2",7))
	executor.cancel_posture(u,"new_order",7)
	assert(u.posture_order=="auto")
	executor.note_fire(u,"blocked","ally_blocks_muzzle","red-1",5)
	assert(executor.snapshot().fire[u.id].reason=="ally_blocks_muzzle")
	# Arrival is a persistent execution phase, not permission to walk back.
	u.position=Vector2(.5,.5);u.move_to(u.position)
	executor.start_motion(u,"hold-1","personal",u.position,10)
	u.route.clear();executor.observe(u,11)
	assert(executor.motion[u.id].state=="holding")
	assert(executor.propose_motion(u,"hold-1","formation",Vector2.ZERO,12)=="rejected_owned")
	assert(executor.propose_motion(u,"hold-1","station",Vector2.ZERO,12)=="rejected_owned")
	assert(executor.propose_motion(u,"hold-1","personal",u.position,12)=="retained")
	assert(executor.motion[u.id].hold_until==17)
	# Explicit changes and new tasks remain authorized.
	assert(executor.propose_motion(u,"hold-1","personal",Vector2.ONE,12)=="accepted")
	assert(executor.propose_motion(u,"hold-2","formation",Vector2.ZERO,12)=="accepted")
	executor.note_fire(u,"fired","","red-1",16)
	executor.observe(u,18);assert(executor.motion[u.id].state=="holding")
	executor.note_fire(u,"blocked","muzzle_cover","red-1",19)
	assert(executor.motion[u.id].reason=="fire_position_invalid:muzzle_cover")
	assert(executor.propose_motion(u,"hold-1","station",Vector2.ZERO,19)=="accepted")
	executor.start_motion(u,"hold-1","personal",u.position,20)
	executor.observe(u,20);executor.observe(u,27)
	assert(executor.motion[u.id].reason=="hold_review_due")
	executor.start_motion(u,"hold-1","personal",u.position,28)
	executor.observe(u,28);u.safety_until=30;executor.observe(u,29)
	assert(executor.motion[u.id].state=="suspended")
	u.safety_until=0
	executor.start_motion(u,"hold-1","personal",u.position,31)
	executor.observe(u,31);u.game.field.revision=2;executor.observe(u,32)
	assert(executor.motion[u.id].reason=="navigation_changed")
	executor.start_motion(u,"hold-1","personal",u.position,33)
	executor.observe(u,33);u.position=Vector2.ONE;executor.observe(u,34)
	assert(executor.motion[u.id].reason=="position_changed")
	u.hp=0
	executor.observe(u,6)
	assert(executor.snapshot().posture[u.id].state=="cancelled")
	print("INTENT_EXECUTOR: all checks passed")
	quit()
