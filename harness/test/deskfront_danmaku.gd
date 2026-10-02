extends SceneTree
class Battle:
 extends Node
 var run_id="r"
 var paused=false
 var growth={"revision":1}
func _initialize():call_deferred("run")
func command(data):
 var file=FileAccess.open(OS.get_environment("QUICKPLAY_OUTPUT_DIR").path_join("danmaku-command.json"),FileAccess.WRITE)
 file.store_string(JSON.stringify(data));file.close()
func run():
 var g=Battle.new();root.add_child(g);current_scene=g
 var overlay=root.get_node("HarnessDanmaku");overlay.set_process(false)
 var now=Time.get_unix_time_from_system()*1000
 var items=[]
 for i in range(5):items.append({"id":str(i),"text":"双方都还在场上😮","at":now-100,"expires":now+20000})
 command({"session":"danmaku-test","enabled":true,"run_id":"r","revision":1,"items":items})
 overlay._process(0);assert(overlay.active.size()==3);assert(overlay.pending.size()==2)
 overlay._process(8);assert(overlay.active.size()==2);assert(overlay.displayed==5)
 overlay._process(8);overlay.next_poll=0;overlay._process(0);assert(overlay.active.is_empty());assert(overlay.displayed==5)
 g.paused=true;overlay._process(0);assert(not overlay.badge.visible);assert(overlay.pending.is_empty())
 g.paused=false;g.growth.revision=2;overlay.next_poll=0;overlay._process(0);assert(overlay.active.is_empty());assert(not overlay.badge.visible)
 command({"session":"danmaku-test","enabled":true,"run_id":"r","revision":2,"items":items})
 overlay.next_poll=0;overlay._process(0);assert(overlay.active.size()==3)
 command({"session":"danmaku-test","enabled":false,"items":[]})
 overlay.next_poll=0;overlay._process(0);assert(overlay.active.is_empty());assert(overlay.pending.is_empty())
 print("DANMAKU_NATIVE_PASS: cap, expiry, no replay, pause, revision, disable")
 quit()
