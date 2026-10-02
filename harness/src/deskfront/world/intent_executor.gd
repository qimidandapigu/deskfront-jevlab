extends RefCounted
# Intent buffer and execution state only. The engine still owns immediate safety,
# navigation, aiming, projectile physics, and automatic firing.
const MOTION_PRIORITY = {"formation":10,"station":20,"fire_position":30,"bound":40,"personal":50}
const HOLD_SECONDS = 6.0
const HOLD_SOURCES = ["personal","fire_position","station"]
var motion: Dictionary = {}
var posture: Dictionary = {}
var fire: Dictionary = {}

func propose_motion(u, order_id: String, source: String, destination: Vector2, now: float) -> String:
	observe(u,now)
	var current: Dictionary = motion.get(u.id,{})
	if current.get("state","")=="holding" and current.get("order_id","")==order_id:
		if current.get("source","")!=source and int(current.get("priority",0))>=int(MOTION_PRIORITY.get(source,0)):return "rejected_owned"
		if current.get("source","")==source and Vector2(current.destination).distance_to(destination)<.02:return "retained"
	var active: bool = current.get("state","")=="executing" and current.get("order_id","")==order_id and now<float(current.get("until",0)) and not u.route.is_empty()
	if active and current.get("source","")!=source and int(current.get("priority",0))>=int(MOTION_PRIORITY.get(source,0)):
		return "rejected_owned"
	var previous: Vector2=current.get("destination",destination)
	if active and current.get("source","")==source and previous.distance_to(destination)<.02:
		return "retained"
	return "accepted"

func start_motion(u, order_id: String, source: String, destination: Vector2, now: float) -> void:
	# Repeated equivalent proposals do not extend this fixed execution deadline.
	motion[u.id]={"state":"executing","source":source,"priority":MOTION_PRIORITY.get(source,0),"order_id":order_id,"until":now+6.0,"destination":destination,"navigation_revision":u.game.field.revision,"reason":""}
	u.set_meta("motion_owner",{"source":source,"priority":MOTION_PRIORITY.get(source,0),"order_id":order_id,"until":now+6.0,"destination":[destination.x,destination.y]})

func cancel_motion(u, reason: String, now: float, order_id: String="") -> bool:
	var current: Dictionary = motion.get(u.id,{})
	if not order_id.is_empty() and current.get("order_id","")!=order_id:return false
	if current.get("state","") in ["executing","holding","suspended"]:
		current.state="cancelled";current.reason=reason;current.ended_at=now
	u.remove_meta("motion_owner")
	u.route.clear();u.goal=u.pos()
	return true

func request_posture(u, value: String, order_id: String, now: float) -> bool:
	if value not in ["auto","stand","crouch","prone"] or u.hp<=0 or now<u.safety_until:return false
	var current: Dictionary=posture.get(u.id,{})
	if current.get("order_id","")==order_id and current.get("value","")==value and current.get("state","")=="executing":return true
	u.set_meta("harness_manual_posture",false)
	u.posture_order=value
	posture[u.id]={"state":"executing","value":value,"order_id":order_id,"since":now}
	return true

func cancel_posture(u, reason: String, now: float) -> void:
	if not posture.has(u.id):return
	var current: Dictionary=posture[u.id]
	if current.get("state","")!="executing":return
	current.state="cancelled";current.reason=reason;current.ended_at=now
	u.posture_order="auto"

func note_fire(u, status: String, reason: String, target_id: String, now: float) -> void:
	# This records the engine's actual fire outcome; it never delays a shot.
	fire[u.id]={"state":status,"reason":reason,"target_id":target_id,"time":now}
	var current: Dictionary=motion.get(u.id,{})
	if current.get("state","")=="holding":
		if status=="fired":current.hold_until=now+HOLD_SECONDS
		elif status=="blocked":release_hold(u,current,"fire_position_invalid:"+reason,now)

func observe(u, now: float) -> void:
	var current: Dictionary=motion.get(u.id,{})
	if u.hp<=0:
		if current.get("state","") in ["executing","holding","suspended"]:current.state="cancelled";current.reason="unit_dead";current.ended_at=now
		if posture.has(u.id):posture[u.id].state="cancelled"
		u.remove_meta("motion_owner")
		return
	if now<u.safety_until and posture.get(u.id,{}).get("state","")=="executing":
		cancel_posture(u,"engine_safety",now)
	if current.get("state","") not in ["executing","holding"]:return
	if now<u.safety_until:
		current.state="suspended";current.reason="engine_safety";current.ended_at=now
		u.remove_meta("motion_owner")
	elif current.get("navigation_revision",u.game.field.revision)!=u.game.field.revision:
		release_hold(u,current,"navigation_changed",now)
	elif current.state=="holding":
		if not u.route.is_empty() or u.pos().distance_to(current.hold_position)>.075:
			release_hold(u,current,"position_changed",now)
		elif now>=float(current.hold_until):
			release_hold(u,current,"hold_review_due",now)
	elif u.route.is_empty():
		if current.source in HOLD_SOURCES and u.path_failure=="" and u.pos().distance_to(u.goal)<.06:
			current.state="holding";current.reason="arrived_holding";current.arrived_at=now
			current.hold_position=u.pos();current.hold_until=now+HOLD_SECONDS
		else:
			release_hold(u,current,"route_finished" if u.pos().distance_to(u.goal)<.06 else "route_ended_short",now)
	elif now>=float(current.get("until",0)):
		current.state="failed";current.reason="execution_timeout";current.ended_at=now
		u.remove_meta("motion_owner")

func release_hold(u, current: Dictionary, reason: String, now: float) -> void:
	# Release authority, not a new destination. Never replay a finished route.
	current.state="completed";current.reason=reason;current.ended_at=now
	u.remove_meta("motion_owner")

func snapshot() -> Dictionary:
	return {"motion":motion.duplicate(true),"posture":posture.duplicate(true),"fire":fire.duplicate(true)}
