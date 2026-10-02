"""Human squad gameplay hook installation."""
from pathlib import Path
import shutil

from .stage_contract import apply_hooks

def _patch_squads(destination: Path, here: Path):
    squads = destination / 'scripts/human_squads.gd'
    if squads.exists():
        code=squads.read_text(encoding='utf-8')
        from . import visibility_cache
        code=visibility_cache.patch(code)
        code=apply_hooks(code,[dict(name='support fire after duty observation',
            before='\tupdate_duties(s,members)\n\tvar center: Vector2=game.tactics_ai.squad_center(members)',
            after='\tupdate_duties(s,members)\n\tif s.intent in ["advance","bound","flank","hold","cover"]:\n\t\tfor member in members:\n\t\t\tvar assigned_role: String=str(s.get("assignments",{}).get(member.id,{}).get("role",""))\n\t\t\t# Establish-fire members must get the same native muzzle-lane check\n\t\t\t# during advance/bound/flank; otherwise they only form up and never\n\t\t\t# attempt a short local firing adjustment when contact is blocked.\n\t\t\tif assigned_role=="establish_fire" or support_fire.eligible(self,member,s):maintain_fire_position(member,s)\n\tvar center: Vector2=game.tactics_ai.squad_center(members)'),
            dict(name='avoid duplicate support fire maintenance',
            before='\t\t\tmaintain_fire_position(u,s)\n\t\t# cover 是一个可完成的保护动作',
            after='\t\t\tif not support_fire.eligible(self,u,s):maintain_fire_position(u,s)\n\t\t# cover 是一个可完成的保护动作'),
            dict(name='stop support before it overruns a clear long firing lane',
            before='\tif not u.route.is_empty() or u.reload_timer>0:\n\t\tstatus.since=game.elapsed',
            after='\tif support_fire.eligible(self,u,s) and game.elapsed>=float(status.get("hold_check_at",0)):\n\t\tstatus.hold_check_at=game.elapsed+.25\n\t\tif support_fire.hold_if_firing(self,u,s,status):status.since=game.elapsed;return\n\tif not u.route.is_empty() or u.reload_timer>0:\n\t\tstatus.since=game.elapsed'),
            dict(name='hold active support firing site',
            before='\t\tstatus.since=game.elapsed;status.state="engaging";return',
            after='\t\tstatus.since=game.elapsed;status.state="engaging";return'),
            dict(name='actual muzzle lane before declaring fire available',
            before='\tif (game.find_target(u)!=null and str(u.get_meta("fire_block_reason","")).is_empty()) or game.elapsed-u.last_shot_at<4:',
            after='\tvar immediate_target=game.find_target(u)\n\tif (immediate_target!=null and u.firing_solution_at(immediate_target,u.pos(),u.posture).clear) or game.elapsed-u.last_shot_at<4:'),
            dict(name='seek local support firing site',
            before='\tstatus.next_check=game.elapsed+8\n\t# hold 只报告',
            after='\tstatus.next_check=game.elapsed+8\n\tif support_fire.recover(self,u,s,status):return\n\t# hold 只报告'),
            dict(name='bounded infantry fire recovery',
            before='\tstatus.state="unavailable"\n\temit("participation_gap",s.faction,s.squad_id,u.id,{"reason":"no_safe_firing_position","weapon":u.weapon})',
            after='\tif s.intent!="cover" and local_fire_recovery(u,s,"no_fire_lane"):\n\t\tstatus.state="relocating";status.since=game.elapsed;return\n\tstatus.state="unavailable"\n\temit("participation_gap",s.faction,s.squad_id,u.id,{"reason":"no_safe_firing_position","weapon":u.weapon})')])
        # An abandoned cover slot being exposed is not a current failure of
        # the soldier or its order. Current danger is handled by the unit;
        # physical destruction rebuilds navigation and is observed separately.
        code=apply_hooks(code,[dict(name='remove abandoned cover invalidation',
            before='\t\tif prev.cover!="" and u.cover_id!=prev.cover:\n'
                   '\t\t\tvar intact: bool=game.field.covers.any(func(c):return c.id==prev.cover and c.alive)\n'
                   '\t\t\tvar former_position: Vector2=prev.get("cover_position",u.pos())\n'
                   '\t\t\tvar flanked: bool=threat_points(s.faction).any(func(p):return game.field.line_of_sight(former_position,p) and game.field.protection(former_position,p)<.2)\n'
                   '\t\t\tif not intact or flanked:emit("cover_invalidated",s.faction,sid,uid,{"cover_id":prev.cover,"reason":"destroyed" if not intact else "flanked"})\n',
            after='')])
        code=apply_hooks(code,[dict(name='intent executor instance',
            before='var game\nvar squads: Dictionary={}',
            after='var game\nvar intent_executor=preload("res://scripts/intent_executor.gd").new()\nvar squads: Dictionary={}'),
            dict(name='motion arbitration and fixed lease',
            before='\tvar priorities: Dictionary={"formation":10,"station":20,"fire_position":30,"bound":40,"personal":50}\n\tvar current: Dictionary=u.get_meta("motion_owner",{})\n\tvar valid: bool=current.get("order_id")==s.get("order_id") and game.elapsed<float(current.get("until",0)) and not u.route.is_empty()\n\tif valid and current.get("source")!=source and int(current.get("priority",0))>=int(priorities.get(source,0)):return false\n\tif slot.is_empty():u.move_to(destination,source=="fire_position")\n\telse:u.occupy(slot)\n\tu.set_meta("motion_owner",{"source":source,"priority":priorities.get(source,0),"order_id":s.get("order_id"),"until":game.elapsed+6,"destination":[destination.x,destination.y]})',
            after='\tvar decision: String=intent_executor.propose_motion(u,str(s.get("order_id","")),source,destination,game.elapsed)\n\tif decision=="rejected_owned":return false\n\tif decision=="retained":return true\n\tif slot.is_empty():u.move_to(destination,source=="fire_position")\n\telse:u.occupy(slot)\n\tintent_executor.start_motion(u,str(s.get("order_id","")),source,destination,game.elapsed)'),
            dict(name='mortar capture owns selected soldier',
            before='\tif u.hp<=0 or game.elapsed<u.safety_until or u.grenade_time>=0:return false',
            after='\tif u.hp<=0 or game.elapsed<u.safety_until or u.grenade_time>=0:return false\n\tif str(u.get_meta("harness_mortar_capture_id",""))!="":return false'),
            dict(name='mortar capture bypasses personal cleanup',
            before='\t\tvar u=matches[0]\n\t\tvar reason: String=""',
            after='\t\tvar u=matches[0]\n\t\tif str(u.get_meta("harness_mortar_capture_id",""))!="":continue\n\t\tvar reason: String=""'),
            dict(name='new order cancels old execution',
            before='if game.elapsed>=u.safety_until and not personal_owned(u,s):u.route.clear();u.goal=u.pos()\n\t\ts.last[u.id]',
            after='if game.elapsed>=u.safety_until and not personal_owned(u,s) and str(u.get_meta("harness_mortar_capture_id",""))=="":intent_executor.cancel_motion(u,"new_order",game.elapsed);intent_executor.cancel_posture(u,"new_order",game.elapsed)\n\t\ts.last[u.id]'),
            dict(name='personal timeout cancels owned route',
            before='if reason in ["movement_timeout","assignment_changed"] and game.elapsed>=u.safety_until:u.route.clear();u.goal=u.pos()',
            after='if reason in ["movement_timeout","assignment_changed"] and game.elapsed>=u.safety_until:intent_executor.cancel_motion(u,reason,game.elapsed,str(row.order_id))'),
            dict(name='support interruption cancels mover route',
            before='if game.elapsed>=mover.safety_until:mover.route.clear();mover.goal=mover.pos();local_cover(mover,s,mover.pos(),.18)',
            after='if game.elapsed>=mover.safety_until and str(mover.get_meta("harness_mortar_capture_id",""))=="":intent_executor.cancel_motion(mover,"support_lost",game.elapsed,str(s.order_id));local_cover(mover,s,mover.pos(),.18)'),
            dict(name='execution observation',
            before='\tupdate_perception()\n\tfor sid in squads.keys():',
            after='\tfor u in game.units:intent_executor.observe(u,game.elapsed)\n\tupdate_perception()\n\tfor sid in squads.keys():'),
            dict(name='execution snapshot',optional=True,
            before='"events":events.duplicate(true)}',
            after='"events":events.duplicate(true),"intent_executor":intent_executor.snapshot()}')])
        code=apply_hooks(code,[dict(name='support fire evaluator instance',
            before='var intent_executor=preload("res://scripts/intent_executor.gd").new()\nvar squads: Dictionary={}',
            after='var intent_executor=preload("res://scripts/intent_executor.gd").new()\nvar support_fire=preload("res://scripts/support_fire_position.gd").new()\nvar squads: Dictionary={}')])
        code=code.replace('if motion.get("order_id")==previous.order_id:motion.order_id=order',
            'if motion.get("order_id")==previous.order_id:motion.order_id=order\n\t\t\tvar active_execution: Dictionary=intent_executor.motion.get(u.id,{})\n\t\t\tif active_execution.get("order_id")==previous.order_id:active_execution.order_id=order')
        code=code.replace('\t\tassignments[uid]=row.duplicate(true)',
                          '\t\tif not valid_member_assignment(row):return "invalid_member_route"\n\t\tassignments[uid]=row.duplicate(true)')
        code=code.replace('for uid in s.unit_ids:owners.erase(uid)\n\t\t\tsquads.erase(sid)',
            'for uid in s.unit_ids:\n\t\t\t\towners.erase(uid)\n\t\t\t\tfor u in game.units:\n\t\t\t\t\tif u.id==uid and u.hp>0 and game.elapsed>=u.safety_until:intent_executor.cancel_motion(u,"authority_cancelled",game.elapsed,str(s.order_id));intent_executor.cancel_posture(u,"authority_cancelled",game.elapsed)\n\t\t\tsquads.erase(sid)')
        code=code.replace('if game.elapsed>=u.safety_until and not personal_owned(u,s):u.route.clear();u.goal=u.pos()',
                          'if game.elapsed>=u.safety_until and not personal_owned(u,s) and str(u.get_meta("harness_mortar_capture_id",""))=="":intent_executor.cancel_motion(u,"contact_pivot",game.elapsed,str(s.order_id))')
        anchor='\t\tfor u in members:\n\t\t\tif game.elapsed>=u.safety_until:'
        if code.count(anchor)!=1:
            raise RuntimeError('Unsupported establish-fire execution hook')
        code=code.replace(anchor,'\t\tfor u in members:\n\t\t\tif harness_establish_fire(u,s):continue\n\t\t\tif game.elapsed>=u.safety_until:')
        code=code.replace('u.firing_solution_at(enemy,point,"crouch").clear','(u.firing_solution_at(enemy,point,"crouch").clear or u.firing_solution_at(enemy,point,"stand").clear)')
        code=apply_hooks(code,[dict(name='formation motion stability',
            before='\tif slot.is_empty():u.move_to(destination,source=="fire_position")',
            after='\tif source=="formation" and slot.is_empty() and preload("res://scripts/formation_stability.gd").retain(u,s.get("order_id"),destination,game.elapsed):return true\n\tif slot.is_empty():u.move_to(destination,source=="fire_position")')])
        code=apply_hooks(code,[dict(name='fire position hold stops an existing forward route',
            before='\tif decision=="retained":return true\n\tif source=="formation"',
            after='\tif decision=="retained":\n\t\tif source=="fire_position" and destination.distance_to(u.pos())<.025 and not u.route.is_empty():u.route.clear();u.goal=u.pos()\n\t\treturn true\n\tif source=="formation"'),
            dict(name='fire position at current actor site bypasses move dedup',
            before='\tif slot.is_empty():u.move_to(destination,source=="fire_position")\n\telse:u.occupy(slot)',
            after='\tif source=="fire_position" and destination.distance_to(u.pos())<.025:\n\t\tu.route.clear();u.goal=u.pos()\n\telif slot.is_empty():u.move_to(destination,source=="fire_position")\n\telse:u.occupy(slot)')])
        code=apply_hooks(code,[dict(name='stable formation heading',
            before='\tvar side := Vector2(-heading.y,heading.x)',
            after='\theading=preload("res://scripts/formation_stability.gd").heading(s,heading,game.elapsed)\n\tvar side := Vector2(-heading.y,heading.x)'),
            dict(name='stable narrow formation',
            before='\ts.shape="column" if narrow else "wedge";',
            after='\tnarrow=preload("res://scripts/formation_stability.gd").narrow(s,narrow,game.elapsed)\n\ts.shape="column" if narrow else "wedge";')])
        code=apply_hooks(code,[dict(name='per-member region arrival',
            before='if s.arrived or members.all(func(u):return u.pos().distance_to(s.goal)<=s.radius):',
            after='if s.arrived or members.all(func(u):return member_arrived(s,u)):'),
            dict(name='per-member station',
            before='\tif local_cover(u,s,s.goal):protection_status(u,s,true);return\n\tprotection_status(u,s,false)\n\tif not threat_points(s.faction).is_empty() and s.goal.distance_to(game.objective)+s.radius>game.config.rules.capture_radius:return',
            after='\tvar assigned_goal: Vector2=member_final_goal(s,u)\n\tif local_cover(u,s,assigned_goal):protection_status(u,s,true);return\n\tprotection_status(u,s,false)\n\tif not threat_points(s.faction).is_empty() and assigned_goal.distance_to(game.objective)+s.radius>game.config.rules.capture_radius:return'),
            dict(name='per-member station destination',
            before='\t\t\tvar dest: Vector2=s.goal+Vector2(cos(angle),sin(angle))*ring if sample<24 else u.pos()\n\t\t\tif dest.distance_to(s.goal)>s.radius',
            after='\t\t\tvar dest: Vector2=assigned_goal+Vector2(cos(angle),sin(angle))*ring if sample<24 else u.pos()\n\t\t\tif dest.distance_to(assigned_goal)>s.radius'),
            dict(name='per-member formation destination',
            before='\t\tvar dest: Vector2=game.field.soft_offset(future,future+offset,.15)\n\t\tfor shift in [Vector2.ZERO,side*.045,-side*.045,-heading*.06]:\n\t\t\tvar alternative: Vector2=game.field.soft_offset(future,dest+shift,.15)\n\t\t\tif not used.any(func(p):return p.distance_to(alternative)<.035):dest=alternative;break',
            after='\t\tvar dest: Vector2=game.field.soft_offset(future,future+offset,.15)\n\t\tif member_has_route(s,u):\n\t\t\tdest=member_next_goal(s,u)\n\t\telse:\n\t\t\tfor shift in [Vector2.ZERO,side*.045,-side*.045,-heading*.06]:\n\t\t\t\tvar alternative: Vector2=game.field.soft_offset(future,dest+shift,.15)\n\t\t\t\tif not used.any(func(p):return p.distance_to(alternative)<.035):dest=alternative;break'),
            dict(name='per-member bound continuation',
            before='mover.pos().distance_to(s.goal)>s.radius',
            after='not member_arrived(s,mover)')])
        if code.count('candidate.pos().move_toward(s.goal,.16)')!=2:
            raise RuntimeError('Unsupported per-member bound short-step hooks')
        code=code.replace('candidate.pos().move_toward(s.goal,.16)',
                          'candidate.pos().move_toward(member_next_goal(s,candidate),.16)')
        code=code.replace('next.distance_to(s.goal)>=candidate.pos().distance_to(s.goal)',
                          'next.distance_to(member_final_goal(s,candidate))>=candidate.pos().distance_to(member_final_goal(s,candidate))')
        code=code.replace('slot.position.distance_to(s.goal)>=u.pos().distance_to(s.goal)-.025',
                          'slot.position.distance_to(member_final_goal(s,u))>=u.pos().distance_to(member_final_goal(s,u))-.025')
        code=apply_hooks(code,[dict(name='selected soldier actions',
            before='\tif intent not in ["adjust_position","take_cover","wait_support","report_blocked"]:return "invalid_soldier_intent"',
            after='\tif intent in ["move_to_site","rush_to_site","prone_approach","occupy_cover","peek_fire","focus_fire","satchel"]:return accept_selected_personal(c,s,u)\n\tif intent not in ["adjust_position","take_cover","wait_support","report_blocked"]:return "invalid_soldier_intent"'),
            dict(name='revalidate suspended selected action',
            before='"unit_ids":[uid],"intent":row.intent})',
            after='"unit_ids":[uid],"intent":row.intent,"site_id":row.get("site_id",""),"candidate_query_id":row.get("candidate_query_id",""),"target_id":row.get("target_id","")})'),
            dict(name='keep focus action until deadline',
            before='\t\telif row.intent=="wait_support" and not supporting_members(u,members).is_empty():reason="support_available"',
            after='\t\telif row.intent=="focus_fire" and game.elapsed<float(row.until):continue\n\t\telif row.intent=="wait_support" and not supporting_members(u,members).is_empty():reason="support_available"'),
            dict(name='release approved antiarmor charge on a safe throwing frame',
            before='\t\tif row.order_id!=s.order_id:reason="assignment_changed"',
            after='\t\tif row.order_id==s.order_id and try_auto_satchel_on_charge(row,u):continue\n\t\tif row.order_id!=s.order_id:reason="assignment_changed"')])
        code=code.replace('reason="arrived" if u.in_cover() else "position_unresolved"',
                          'reason="arrived" if personal_site_arrived(row,u) or (not row.has("position") and u.in_cover()) else "position_unresolved"')
        code=code.replace('personal_transition(row,reason,reason)\n\t\t\tif reason in ["movement_timeout"',
                          'personal_transition(row,reason,reason)\n\t\t\tfinish_selected_personal(row,u,reason)\n\t\t\tif reason in ["movement_timeout"')
        code=code.replace('reason="wait_expired" if row.intent=="wait_support" else "movement_timeout"',
                          'reason="wait_expired" if row.intent=="wait_support" else "focus_complete" if row.intent=="focus_fire" else "movement_timeout"')
        squads.write_text(code+'\n'+(here/'fire_progress.gd').read_text(encoding='utf-8')+
                          (here/'member_routes.gd').read_text(encoding='utf-8')+
                          (here/'personal_actions.gd').read_text(encoding='utf-8'),encoding='utf-8')
        perception = destination / 'scripts/human_squad_perception.gd'
        if perception.exists():
            perception.write_text(visibility_cache.patch(perception.read_text(encoding='utf-8')), encoding='utf-8')
        snapshot = destination / 'scripts/human_squad_snapshot.gd'
        if snapshot.exists():
            snapshot_code = snapshot.read_text(encoding='utf-8')
            snapshot_code = snapshot_code.replace(
                '"events":host.events.duplicate(true)}',
                '"events":host.events.duplicate(true),"intent_executor":host.intent_executor.snapshot()}',
                1,
            )
            snapshot.write_text(snapshot_code, encoding='utf-8')
        shutil.copyfile(here/'formation_stability.gd',destination/'scripts/formation_stability.gd')
        shutil.copyfile(here/'intent_executor.gd',destination/'scripts/intent_executor.gd')
        shutil.copyfile(here/'support_fire_position.gd',destination/'scripts/support_fire_position.gd')


