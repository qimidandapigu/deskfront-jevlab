extends SceneTree
func _initialize():call_deferred("run")
func run():
 set_meta("infinite_world",true);set_meta("deskfront_map",0)
 var g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
 g.set_physics_process(false);g.paused=false;g.fx.set_muted(true)
 for u in g.units:
  u.set_physics_process(false)
  if u.actor:u.actor.set_physics_process(false)
 var squad=g.units.filter(func(u):return u.faction=="green")
 var turns: Dictionary={}
 var previous: Dictionary={}
 var out=FileAccess.open("res://jitter-frames.jsonl",FileAccess.WRITE)
 for i in range(squad.size()):
  var u=squad[i];u.position.x=1.1;u.position.z=2.0+i*.035
  u.actor.global_position=u.global_position;u.move_to(Vector2(1.25,2.1))
 for frame in range(360):
  g.elapsed+=1.0/60
  for u in squad:
   u.tick(1.0/60);u.presentation_tick(1.0/60)
   if previous.has(u.id) and absf(angle_difference(float(previous[u.id]),u.rotation.y))>1.0:turns[u.id]=int(turns.get(u.id,0))+1
   previous[u.id]=u.rotation.y
   out.store_line(JSON.stringify({"f":frame,"id":u.id,"p":[u.pos().x,u.pos().y],"yaw":u.rotation.y,"goal":[u.goal.x,u.goal.y],"route":u.route.size(),"mode":u.order_mode}))
  await process_frame
 out.close()
 for u in squad:
  assert(int(turns.get(u.id,0))==0,"high-frequency reversal: "+u.id)
  assert(u.route.is_empty(),"failed to arrive: "+u.id)
 print("CROWDED ARRIVAL: no large reversals; all four arrived")
 g.queue_free();await process_frame;quit()
