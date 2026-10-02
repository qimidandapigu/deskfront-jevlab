extends RefCounted
class EmptyArena:
 var props:Array=[]
static func vec(value,n:int) -> bool:
 if not value is Array or value.size()!=n:return false
 for x in value:
  if not (x is float or x is int) or not is_finite(float(x)):return false
 return true
static func validate(level) -> Dictionary:
 var errors:Array=[]
 if not level is Dictionary:return {"passed":false,"errors":["level_must_be_object"]}
 var source=level.get("base_map",-1)
 if not (source is int or source is float) or int(source)!=source or source<0 or source>2:return {"passed":false,"errors":["invalid_base_map"]}
 var template=JSON.parse_string(FileAccess.get_file_as_string("res://data/sandbox-maps.json")).levels[int(source)]
 for field in ["bounds","floor_color","building","at_guns","tank_spawn"]:
  if level.get(field)!=template.get(field):errors.append("fixed_template_field: "+field)
 if not level.get("scenario_id") is String or str(level.get("scenario_id","")).length()>80:errors.append("invalid_scenario_id")
 if not level.get("id") is String or not level.get("name") is String:errors.append("invalid_name")
 elif level.id!="studio-"+str(level.get("scenario_id","")):errors.append("invalid_scenario_identity")
 if not vec(level.get("objective"),2):errors.append("invalid_objective")
 if not level.get("spawns") is Array or level.spawns.size()!=3:errors.append("invalid_spawns")
 else:
  for p in level.spawns:
   if not vec(p,2):errors.append("invalid_spawn")
 var hold=level.get("hold_seconds",0)
 if not (hold is float or hold is int) or not is_finite(float(hold)) or hold<20 or hold>90:errors.append("invalid_hold_seconds")
 if not level.get("loadouts") is Dictionary:errors.append("invalid_loadouts")
 else:
  for team in ["green","blue","red"]:
   var weapons=level.loadouts.get(team)
   if not weapons is Array or weapons.size()!=3:errors.append("invalid_loadout: "+team);continue
   for w in weapons:
    if w not in ["rifle","smg","rocket","pistol"]:errors.append("invalid_weapon")
   if not weapons.has("rocket"):errors.append("anti_armor_counterplay_required")
 if not level.get("objects") is Array or level.objects.size()>64:errors.append("invalid_objects")
 else:
  var fixed=template.objects.filter(func(o):return o.kind not in ["sandbag","crate"])
  for object in fixed:
   if not level.objects.has(object):errors.append("fixed_object_changed")
  var count:int=0
  for o in level.objects:
   if fixed.has(o):continue
   count+=1
   if not o is Dictionary:errors.append("invalid_cover");continue
   for key in o:
    if key not in ["id","kind","position","size","yaw","color","collision","destructible"]:errors.append("unsupported_cover_field")
   if o.get("id")!="studio-cover-"+str(count-1):errors.append("invalid_cover_id")
   if not o.get("id") is String or o.get("kind") not in ["sandbag","crate","building"] or not vec(o.get("position"),2) or not vec(o.get("size"),3):errors.append("invalid_cover");continue
   if (not (o.get("yaw") is float or o.get("yaw") is int) or float(o.get("yaw")) not in [0.0,90.0]) or o.get("color") not in ["#b1aa83","#898775"] or o.get("collision")!=true or o.get("destructible")!=true:errors.append("invalid_cover_material")
   if o.size[0]<.08 or o.size[0]>.4 or o.size[1]<.035 or o.size[1]>(.28 if o.kind=="building" else .09) or o.size[2]<.035 or o.size[2]>(.30 if o.kind=="building" else .16):errors.append("invalid_cover_size")
  if count<4 or count>14:errors.append("cover_count_4_to_14")
 if not errors.is_empty():return {"passed":false,"errors":errors}
 var b=level.bounds;var target=Vector2(level.objective[0],level.objective[1])
 if absf(target.x-(b[0]+b[2])*.5)>.36 or absf(target.y-(b[1]+b[3])*.5)>.36:return {"passed":false,"errors":["flag_must_be_central"]}
 var config=JSON.parse_string(FileAccess.get_file_as_string("res://data/battle.json"))
 preload("res://scripts/map_rules.gd").apply(config,level)
 var field=preload("res://scripts/battlefield.gd").new();field.setup(config,EmptyArena.new())
 var routes:Array=[];var arrivals:int=0
 if not field.walkable(target):errors.append("flag_blocked")
 for i in range(3):
  var anchor=Vector2(level.spawns[i][0],level.spawns[i][1])
  if anchor.distance_to(target)<.42:errors.append("spawn_too_close_to_flag")
  for j in range(i):
   if anchor.distance_to(Vector2(level.spawns[j][0],level.spawns[j][1]))<.45:errors.append("opponents_spawn_too_close")
  for j in range(3):
   var p=anchor+Vector2((j-1)*.064,0)
   # Building geometry is fixed above this area; no authoring a spawn inside it.
   if p.x>.66 and p.y<1.7:errors.append("spawn_inside_building_zone")
   if not field.walkable(p):errors.append("spawn_blocked: %d/%d"%[i,j]);continue
   var path=field.path(p,target)
   if path.is_empty() or path[-1].distance_to(target)>.06:errors.append("flag_unreachable: %d/%d"%[i,j])
   else:routes.append(field.route_length(path))
 for angle in range(0,360,90):
  var p=target+Vector2.from_angle(deg_to_rad(angle))*.22
  if field.walkable(p) and field.segment_walkable(p,target):arrivals+=1
 if arrivals<2:errors.append("flag_needs_two_open_approaches")
 if routes.size()==9 and routes.max()/maxf(.1,routes.min())>3.8:errors.append("deployment_distance_imbalance")
 field.free()
 return {"passed":errors.is_empty(),"errors":errors,"spawn_routes":routes,"open_approaches":arrivals,"note":"导航可达性与入口指标，不代表已证明战术平衡"}
