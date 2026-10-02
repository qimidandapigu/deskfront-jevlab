extends RefCounted

static func run(game, check: Callable) -> void:
	var objective_mode=game.config.rules.get("mode", "")
	game.config.rules.mode="legacy_cqb_contract"
	game.set_physics_process(false);game.fx.set_muted(true)
	for team in ["green","blue","red"]:
		var weapons: Array=[]
		for u in game.living(team):weapons.append(u.weapon)
		check.call(weapons==["rifle","smg","rocket"],"three weapon roles: "+team)
		game.decide(team)
		check.call(game.decisions[team].action=="cover","AI initially prefers cover: "+team)
	check.call(game.units.filter(func(u):return u.cover_id!="").size()>=7,"AI assigns protected stations instead of rushing objective")
	check.call(game.units.all(func(u):return u.actor!=null and u.actor.weapon!=null and u.actor.skeleton.find_bone("RightHand")>=0),"weapon geometry follows hand bone")
	for u in game.units:u.hp=0;u.route.clear();u.cover_id=""
	var rifle=game.units[0];var smg=game.units[1];var rocket=game.units[2];var target=game.units[6]
	rifle.hp=100;target.hp=100;rifle.position=Vector3(.45,game.field.height,.43);target.position=Vector3(.70,game.field.height,.43)
	game.fx.launch(rifle,target,"rifle",true)
	check.call(target.hp==100 and game.fx.projectiles.size()==1,"rifle damage waits for visible projectile arrival")
	game.fx.physics_tick(1)
	check.call(target.hp<100 and game.fx.impacts>0,"projectile impact applies damage and sparks")
	check.call(game.fx.visuals.size()>0,"muzzle/tracer/impact visual nodes exist")
	var tank=game.spawn_unit("test-tank","red",Vector2(.70,.43),true)
	target.hp=0
	game.fx.launch(rifle,tank,"rifle",true);game.fx.physics_tick(1)
	var rifle_damage: float=tank.max_hp-tank.hp
	tank.hp=tank.max_hp;rocket.hp=100;rocket.position=rifle.position
	game.fx.launch(rocket,tank,"rocket",true)
	check.call(game.fx.projectiles[0].duration>.20,"rocket has readable flight time")
	game.fx.physics_tick(2)
	var rocket_damage: float=tank.max_hp-tank.hp
	check.call(rocket_damage>rifle_damage*20 and rocket_damage>=100,"rocket penetrates tank armor, small arms are ineffective")
	tank.hp=0;target.hp=100
	var neighbour=game.units[7];neighbour.hp=100;neighbour.position=target.position+Vector3(.06,0,0)
	var friendly=game.units[3];friendly.faction="green";friendly.hp=100;friendly.position=neighbour.position
	check.call(not game.fx.launch(rocket,target,"rocket",true),"explosive refuses friendly beside impact")
	friendly.position=Vector3(.1,game.field.height,.43)
	game.fx.launch(rocket,target,"rocket",true)
	friendly.position=neighbour.position
	game.fx.physics_tick(2)
	check.call(target.hp<100 and neighbour.hp<100,"explosive damages both direct target and splash neighbour")
	check.call(friendly.hp==100,"explosion respects friendly-fire policy")
	for u in game.units:u.hp=0
	var counts: Array=[]
	for shooter in [rifle,smg]:
		shooter.hp=100;shooter.position=Vector3(.45,game.field.height,.43);shooter.cooldown=0;shooter.reload_timer=0;shooter.ammo=24
		target.hp=10000;target.position=Vector3(.70,game.field.height,.43)
		game.control.green="player";var before: int=game.shots
		for i in range(60):shooter.tick(1.0/60);game.fx.physics_tick(1.0/60);game.elapsed+=1.0/60
		counts.append(game.shots-before);shooter.hp=0
	check.call(counts[0]==1 and counts[1]>=6,"rifle single shots and SMG rapid fire have distinct cadences")
	smg.hp=100;smg.ammo=1;smg.cooldown=0;smg.fire(target)
	check.call(smg.ammo==0 and smg.reload_timer>0,"empty magazine enters reload")
	for i in range(160):smg.tick(1.0/60)
	check.call(smg.ammo>0,"reload restores weapon-specific magazine")
	rifle.hp=100;rifle.cooldown=0;rifle.reload_timer=1.;rifle.ammo=0;target.hp=100;target.position=rifle.position+Vector3(.05,0,0)
	var before_melee: int=int(game.fx.launched.get("bayonet",0));rifle.tick(.016)
	check.call(int(game.fx.launched.get("bayonet",0))==before_melee+1 and target.hp<100,"nearby infantry uses bayonet even during reload")
	check.call(rifle.ammo==0 and rifle.state=="melee","bayonet consumes no ammunition and reports melee state")
	target.hp=0;tank.hp=tank.max_hp;tank.position=rifle.position+Vector3(.05,0,0);rifle.cooldown=0;rifle.tick(.016)
	check.call(int(game.fx.launched.get("bayonet",0))==before_melee+1,"bayonet does not attack armor")
	var old: Vector3=game.camera_target;game.pan_by(Vector3(.15,0,.10))
	check.call(game.camera_target.distance_to(old)>.1,"RTS pan changes camera target")
	game.pan_by(Vector3(500,0,500));check.call(game.camera_target.x<=2.0001 and game.camera_target.z<=4.1001,"camera pan is bounded")
	game.set_camera("battle",true);check.call(game.camera_target.is_equal_approx(Vector3(.60,.84,-.02)),"camera recenter restores battlefield")
	game.fx.audio_enabled=true;game.fx.set_muted(false);game.fx.sound("rifle",game.camera_target)
	check.call(game.fx.audio_events>0 and game.fx.voices.size()>0,"sound uses actual AudioStreamPlayer3D")
	game.fx.set_muted(true);check.call(game.fx.voices.is_empty() and game.fx.muted,"mute stops live voices")

	game.config.rules.mode=objective_mode
