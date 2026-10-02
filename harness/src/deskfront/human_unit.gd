extends "res://scripts/unit.gd"

# Mechanical posture hysteresis. Real threat observations extend recovery;
# repeated orders or polling never extend the fixed minimum dwell.
const HARNESS_PRONE_MIN_SECONDS: float=3.0
const HARNESS_PRONE_QUIET_SECONDS: float=1.5
var harness_prone_hold_until: float=-1.0
var harness_prone_hit_pending: bool=false
var harness_prone_reason: String=""

func harness_antiarmor_commit_active() -> bool:
	if not game.human_squad or tank or hp<=0 or game.elapsed>=float(get_meta("harness_antiarmor_charge_until",0.0)):
		return false
	if hp/max_hp<.35 or suppression>=.72 or game.elapsed<safety_until or game.elapsed<explosive_until:
		return false
	if order_mode!="soldier_rush_to_site":return false
	var committed_target: String=str(get_meta("harness_antiarmor_target_id",""))
	if committed_target.is_empty():return false
	for enemy in game.living():
		if enemy.id==committed_target and enemy.tank and enemy.faction!=faction:return true
	return false

func harness_note_prone_hit() -> void:
	harness_prone_hit_pending=true

func harness_prone_hold_active() -> bool:
	return not tank and hp>0 and harness_prone_hold_until>=0 and (game.elapsed<harness_prone_hold_until or game.elapsed-last_threat_at<HARNESS_PRONE_QUIET_SECONDS or suppression>game.config.tactics.recover_pressure)

func harness_manual_posture() -> bool:
	return bool(get_meta("harness_manual_posture",false)) and game.control[faction]=="player" and posture_order!="auto"

func harness_apply_posture_order(value: String, manual: bool) -> void:
	set_meta("harness_manual_posture",manual and value!="auto")
	if manual or not harness_prone_hold_active():posture_since=-10
	posture_order=value
	update_posture(not route.is_empty())

func update_firing_awareness() -> void:
	# Native firing awareness can write posture directly; it must not make the
	# soldier stand up to clear a muzzle while the same threat episode is held.
	if harness_prone_hold_active() and not harness_manual_posture():return
	super.update_firing_awareness()

func update_posture(moving: bool) -> void:
	var previous: String=posture
	var previous_since: float=posture_since
	var previous_clip: String=last_clip
	var threatened: bool=game.elapsed-last_threat_at<1.5
	if not threatened:harness_prone_hit_pending=false
	var pinned: bool=suppression>=game.config.tactics.prone_pressure
	var recovering: bool=posture=="prone" and suppression>game.config.tactics.recover_pressure and threatened
	var crawl: bool=not game.human_squad and not tank and posture_order=="auto" and moving and not in_cover() and cqb_stance not in ["hide","peek"] and garrison_phase=="" and (pinned or (game.elapsed<safety_until and threatened) or recovering)
	super.update_posture(false if crawl else moving)
	if tank or hp<=0:
		harness_prone_hold_until=-1;harness_prone_hit_pending=false
		return
	if harness_manual_posture():
		harness_prone_hold_until=-1;harness_prone_hit_pending=false
		return
	if harness_antiarmor_commit_active():
		# A brief anti-armor charge remains upright through ordinary hits.
		# Critical damage, heavy suppression and imminent shells still take over.
		harness_prone_hold_until=-1;harness_prone_hit_pending=false;harness_prone_reason=""
		return
	# These native actions need their own pose or fast travel. Retain the
	# remaining recovery window, so arriving at safety can settle back down.
	if garrison_phase!="" or gun_id!="" or grenade_time>=0 or game.elapsed<melee_until or (actor and actor.stepping):
		harness_prone_hit_pending=false
		return
	if moving and game.elapsed<safety_until and order_mode in ["evade_explosive","self_preserve","retreat"]:
		posture="crouch";locomotion="crouch_run"
		if previous==posture:posture_since=previous_since;last_clip=previous_clip
		else:posture_since=game.elapsed;last_clip=""
		return
	var armor_pinned: bool=game.human_squad and order_mode=="pinned" and safety_reason=="armor_outmatched"
	var fire_pinned: bool=game.human_squad and order_mode=="pinned" and game.elapsed<safety_until and safety_reason in ["incoming_fire","flanked","suppressed","low_health"]
	var wants_prone: bool=crawl or harness_prone_hit_pending or posture=="prone" or (pinned and threatened) or armor_pinned or fire_pinned
	if wants_prone and (harness_prone_hit_pending or threatened or pinned or armor_pinned or fire_pinned) and harness_prone_hold_until<0:
		harness_prone_hold_until=game.elapsed+HARNESS_PRONE_MIN_SECONDS
		harness_prone_reason="hit" if harness_prone_hit_pending else ("armor_pinned" if armor_pinned else ("fire_pinned" if fire_pinned else "incoming_fire"))
	harness_prone_hit_pending=false
	if harness_prone_hold_active():wants_prone=true
	else:harness_prone_hold_until=-1;harness_prone_reason=""
	if wants_prone:
		posture="prone";locomotion="crawl" if moving else "idle"
		# super computes a candidate pose but does not animate it. Preserve the
		# actual transition clock and clip when that candidate is rejected.
		if previous=="prone":posture_since=previous_since;last_clip=previous_clip
		else:posture_since=game.elapsed;last_clip=""

func harness_posture_snapshot() -> Dictionary:
	return {"minimum_seconds":HARNESS_PRONE_MIN_SECONDS,"quiet_seconds":HARNESS_PRONE_QUIET_SECONDS,"hold_active":harness_prone_hold_active(),"minimum_remaining":maxf(0,harness_prone_hold_until-game.elapsed),"quiet_remaining":maxf(0,HARNESS_PRONE_QUIET_SECONDS-(game.elapsed-last_threat_at)),"reason":harness_prone_reason}
