extends SceneTree
func _initialize():call_deferred("run")
func run():
 set_meta("infinite_world",true);set_meta("deskfront_map",0)
 var g=load("res://scenes/main.tscn").instantiate();root.add_child(g)
 g.set_physics_process(false);g.paused=false;g.fx.set_muted(true)
 var u=g.units[0]
 var order={"order_id":"arrival-check","mover":"","support_ids":[]}
 var target=u.pos()+Vector2(-.08,0)
 assert(g.human_squads.request_motion(u,order,"personal",target))
 for frame in range(240):
  g.elapsed+=1.0/60
  u.tick(1.0/60);u.presentation_tick(1.0/60)
  g.human_squads.intent_executor.observe(u,g.elapsed)
  await process_frame
 assert(u.route.is_empty(),"soldier must physically arrive")
 assert(g.human_squads.intent_executor.motion[u.id].state=="holding")
 var arrived=u.pos()
 for frame in range(60):
  g.elapsed+=1.0/60
  assert(not g.human_squads.request_motion(u,order,"station",arrived+Vector2(.15,0)))
  u.tick(1.0/60);u.presentation_tick(1.0/60)
  await process_frame
 assert(u.pos().distance_to(arrived)<.005,"station must not pull arrived soldier back")
 var next={"order_id":"explicit-new-order","mover":"","support_ids":[]}
 assert(g.human_squads.request_motion(u,next,"station",arrived+Vector2(.15,0)))
 assert(not u.route.is_empty(),"explicit new order must still move")
 print("ARRIVAL HOLD: actual arrival held against station; new order accepted")
 g.queue_free();await process_frame;quit()
