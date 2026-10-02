extends SceneTree
class Soldier extends RefCounted:
	var goal=Vector2(.2,0)
	var route=PackedVector2Array([Vector2(.2,0)])
	var path_failure=""
	var no_progress_seconds=0.0
	var order_mode="squad_formation"
	var id="one"
	var game={"field":{"revision":1}}
	var route_revision=1
	var tank=false
	var safety_until=-1.0
	var position=Vector2.ZERO
	func pos():return position

func _initialize():
	var policy=load(get_script().resource_path.get_base_dir()+"/../src/deskfront/world/formation_stability.gd")
	var u=Soldier.new()
	assert(not policy.retain(u,"a",Vector2(.2,0),0))
	assert(policy.retain(u,"a",Vector2(.24,0),.2))
	assert(policy.retain(u,"a",Vector2(.16,0),.4))
	# The lock has a fixed deadline: polling cannot extend it forever.
	assert(not policy.retain(u,"a",Vector2(.24,0),.9))
	assert(not policy.retain(u,"b",Vector2(.24,0),1.0))
	u.path_failure="no_safe_route"
	assert(not policy.retain(u,"b",Vector2(.24,0),1.1))
	u.path_failure="";u.no_progress_seconds=1
	assert(not policy.retain(u,"b",Vector2(.24,0),1.2))
	u.no_progress_seconds=0
	assert(not policy.retain(u,"b",Vector2(.5,0),1.3))
	u.route.clear();u.position=Vector2(.2,0)
	assert(policy.retain(u,"b",Vector2(.24,0),2))
	assert(policy.retain(u,"b",Vector2(.265,0),2.1))
	assert(not policy.retain(u,"b",Vector2(.28,0),2.2))
	u.order_mode="soldier_retreat"
	assert(not policy.retain(u,"b",Vector2(.24,0),2.3))
	var s={}
	assert(policy.heading(s,Vector2.RIGHT,0).is_equal_approx(Vector2.RIGHT))
	var direction=policy.heading(s,Vector2.LEFT,.2)
	assert(absf(Vector2.RIGHT.angle_to(direction))<=.401)
	assert(policy.narrow(s,true,0))
	assert(policy.narrow(s,false,.4))
	assert(not policy.narrow(s,false,.9))
	var other=Soldier.new();other.id="two";other.position=Vector2(.22,0)
	u.position=Vector2(.2,0)
	# Near a waypoint, repulsion cannot invert the requested direction.
	for distance in [.001,.003,.01,.03,.1]:
		var target=u.pos()+Vector2(distance,0)
		var steered=policy.separation(u,other,target,.03,3)
		assert((steered-u.pos()).dot(target-u.pos())>0)
		assert(steered.distance_to(target)<=distance*.351)
	assert(policy.separation(u,other,u.pos(),.03,3)==u.pos())

	u.safety_until=5
	assert(policy.separation(u,other,Vector2(.3,0),.03,4).is_equal_approx(Vector2(.292,0)))
	u.order_mode="squad_formation";u.route=PackedVector2Array([u.goal]);u.safety_until=-1
	assert(not policy.retain(u,"revision-test",u.goal,6))
	assert(policy.retain(u,"revision-test",u.goal,6.1))
	u.game.field.revision=2
	assert(not policy.retain(u,"revision-test",u.goal,6.2))
	u.route_revision=2;u.safety_until=8
	assert(not policy.retain(u,"revision-test",u.goal,6.3))
	print("FORMATION_STABILITY: all checks passed")
	quit()
