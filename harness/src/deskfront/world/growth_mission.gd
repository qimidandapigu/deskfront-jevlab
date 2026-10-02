extends RefCounted
## Mission lifecycle state machine for the infinite-growth world.
##
## This helper deliberately receives the growth controller rather than owning
## gameplay state.  The controller remains the public API and Godot remains the
## authority for units, objectives, and mission completion.

func update(growth):
	var game=growth.game
	var mission: Dictionary=growth.mission
	if mission.is_empty() or mission.status in ["completed","failed"]:return
	var squad: Array=game.living("green").filter(func(u):return not u.tank)
	if squad.is_empty():
		growth.finish_mission("failed","绿色小队已失去战斗力");growth.show_status("任务失败 / 绿色小队已失去战斗力");return
	var arrived: int=squad.filter(func(u):return u.pos().distance_to(game.objective)<.38).size()
	var nearby: int=game.living("red").filter(func(u):return u.pos().distance_to(game.objective)<.55).size()
	mission.arrived=arrived;mission.required=0;mission.enemies_remaining=nearby
	var defenders: Array=game.living("red").filter(func(u):return u.id in mission.defenders)
	mission.enemies_remaining=defenders.size()
	var clear: bool=defenders.is_empty()
	if clear:
		if mission.mission_kind=="rescue":
			var captive=game.units.filter(func(u):return u.id==mission.captive_id).front()
			if captive.deployment_phase=="captive":
				captive.deployment_phase="active";captive.posture="stand";captive.posture_order="auto"
				captive.order_mode="rescued_joined";captive.animate("idle")
				mission.rescue_status="joined";mission.friendly_added+=1
				if growth.rescue_label:growth.rescue_label.queue_free();growth.rescue_label=null
				if growth.harness_green:game.control_epochs.green+=1
				game.add_event("解救成功："+captive.id+" 加入绿色小队")
		growth.finish_mission("completed","堡垒友军获救" if mission.mission_kind=="rescue" else "全部本段守军已清除");game.add_event("任务完成："+mission.name)
		growth.show_status("任务完成 / "+mission.name+" · 准备下一段");return
	var distance: float=0
	for u in squad:distance+=u.pos().distance_to(game.objective)
	distance/=squad.size()
	var enemy_hp: float=0
	for u in game.living("red"):enemy_hp+=u.hp
	if distance<float(mission.best_distance)-.08 or enemy_hp<float(mission.least_enemy_hp)-10:
		mission.best_distance=minf(distance,mission.best_distance);mission.least_enemy_hp=minf(enemy_hp,mission.least_enemy_hp);mission.last_progress=game.elapsed
	if mission.status=="regrouping":
		if game.elapsed<float(mission.regroup_until):return
		mission.status="active";mission.last_progress=game.elapsed
		if not growth.harness_green:
			for u in squad:u.route.clear()
		game.add_event("重整结束，尝试侧路推进")
	if game.elapsed-float(mission.last_progress)>(45 if growth.harness_green else 25):
		if int(mission.recovery_count)>=2:
			growth.finish_mission("failed","两次重整后仍无进展");growth.show_status("远征受阻 / 保留失败记录，不虚报通关");return
		mission.recovery_count+=1;mission.status="regrouping";mission.regroup_until=game.elapsed+8
		if not growth.harness_green:
			for u in squad:u.route.clear()
		game.add_event("任务受阻：退回入口重整，保留现有队伍重新组织")
		growth.show_status("任务受阻 / 退回入口重整 8 秒");return
	growth.show_status("第 %d 段 / %s\n剩余守军 %d · 清除守军后展开下一段"%[growth.revision,mission.name,defenders.size()])

func team_summary(growth,team:String)->Dictionary:
	var troops:Array=growth.game.living(team);var hp:float=0
	for u in troops:hp+=u.hp
	return {"alive":troops.size(),"hp_total":snappedf(hp,.1)}

func finish(growth,status:String,reason:String):
	var mission: Dictionary=growth.mission
	var game=growth.game
	mission.status=status;mission.reason=reason;mission.ended_at=game.elapsed
	if status=="completed":mission.completed_at=game.elapsed
	else:mission.failed_at=game.elapsed
	var remaining:int=game.living("red").filter(func(u):return u.id in mission.defenders).size()
	mission.enemies_remaining=remaining
	var row={"index":mission.get("index",growth.revision),"option":mission.option,"operation_id":mission.get("operation_id",""),"mission_kind":mission.get("mission_kind","assault"),"support_type":mission.get("support_type","infantry"),"support_status":mission.get("support_status","none"),"captive_id":mission.get("captive_id",""),"rescue_status":mission.get("rescue_status","none"),"status":status,"reason":reason,"started":mission.started,"ended":game.elapsed,"duration_seconds":snappedf(maxf(0,game.elapsed-mission.started),.1),"green_before_reinforcement":mission.get("green_before_reinforcement",{}),"green_start":mission.get("green_start",{}),"green_end":team_summary(growth,"green"),"friendly_added":mission.get("friendly_added",0),"enemies_initial":mission.get("enemies_initial",mission.defenders.size()),"enemies_remaining":remaining}
	if not growth.mission_results.any(func(old):return old.operation_id==row.operation_id and old.index==row.index):growth.mission_results.append(row)
	while growth.mission_results.size()>6:growth.mission_results.pop_front()
