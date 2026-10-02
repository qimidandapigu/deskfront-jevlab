extends Node3D
## At most one collision-free detail per nine-desk region. The selected covers
## remain the only tactical obstacles; decoration never fakes cover.
const Art=preload("res://scripts/world_props.gd")
const DETAILS=["ruled_sheet","sticky_notes","phone","two_pens","notepad","calculator","postcard","usb_drive","coaster","cartoon_roach"]
static var prop_library:Dictionary={}
const SPOTS=[Vector2(-.18,.21),Vector2(.18,-.21),Vector2(-.18,-.21),Vector2(.18,.21),Vector2(0,.26),Vector2(0,-.26),Vector2(-.18,.27),Vector2(.18,-.27),Vector2.ZERO]

func segment(p:Node3D,a:Vector3,b:Vector3,radius:float,ink:String):
	var direction:Vector3=b-a
	var piece=Art.cylinder(p,(a+b)*.5,radius,direction.length(),ink,-1,6)
	piece.quaternion=Quaternion(Vector3.UP,direction.normalized())

func curve(p:Node3D,a:Vector3,b:Vector3,c:Vector3,d:Vector3,radius:float,ink:String):
	var previous:Vector3=a
	for i in range(1,13):
		var t:float=float(i)/12.0;var u:float=1.0-t
		var point:Vector3=a*u*u*u+b*3.0*u*u*t+c*3.0*u*t*t+d*t*t*t
		segment(p,previous,point,radius,ink);previous=point

func draw_roach(p:Node3D):
	# Readable cockroach silhouette from the game's high three-quarter camera.
	# This is static desk dressing, never an enemy, collision body, or AI actor.
	var bug=Node3D.new();p.add_child(bug);bug.position.x=-.025
	Art.ellipsoid(bug,Vector3(-.025,.012,0),Vector3(.090,.024,.064),"9b765c")
	for side in [-1,1]:
		var shell=Art.ellipsoid(bug,Vector3(-.025,.024,float(side)*.013),Vector3(.086,.023,.043),"784533","plastic")
		shell.rotation.y=float(side)*.04
	curve(bug,Vector3(.012,.030,0),Vector3(-.010,.039,0),Vector3(-.044,.038,0),Vector3(-.065,.025,0),.0007,"9b765c")
	for side in [-1,1]:
		for i in range(3):
			Art.ellipsoid(bug,Vector3(-.047+i*.021,.035,side*.016),Vector3(.013,.0015,.009),"b48258")
	# Small thorax shield, with one light marking rather than a bright collar.
	Art.ellipsoid(bug,Vector3(.018,.021,0),Vector3(.046,.014,.058),"9b765c")
	Art.ellipsoid(bug,Vector3(.020,.029,0),Vector3(.018,.002,.025),"e2c29b")
	Art.ellipsoid(bug,Vector3(.044,.017,0),Vector3(.037,.028,.041),"ad7452")
	for side in [-1,1]:
		var s:float=float(side)
		Art.ellipsoid(bug,Vector3(.054,.027,s*.013),Vector3(.010,.012,.010),"f4eddb")
		Art.ellipsoid(bug,Vector3(.058,.029,s*.014),Vector3(.006,.007,.006),"53686c")
		Art.ellipsoid(bug,Vector3(.060,.031,s*.016),Vector3(.0025,.0025,.0025),"f4eddb")
		Art.ellipsoid(bug,Vector3(.058,.016,s*.013),Vector3(.003,.005,.008),"d69b91")
		# Three bent, outward-pointing legs per side; rear pair is longest.
		for j in range(3):
			var x:float=.009-float(j)*.023
			var knee=Vector3(x+(.010 if j==0 else -.004),.012,s*.043)
			var foot=Vector3(x+(.022 if j==0 else -.020 if j==2 else -.007),.003,s*(.058+float(j)*.003))
			segment(bug,Vector3(x,.011,s*.024),knee,.0025,"784533")
			segment(bug,knee,foot,.0020,"784533")
			Art.ellipsoid(bug,foot,Vector3(.008,.005,.007),"784533")
		curve(bug,Vector3(.034,.031,s*.025),Vector3(.031,.073,s*.061),Vector3(.081,.074,s*.090),Vector3(.098,.053,s*.094),.0012,"784533")
		Art.ellipsoid(bug,Vector3(.098,.053,s*.094),Vector3(.0035,.0035,.0035),"784533")
		segment(bug,Vector3(-.065,.010,s*.012),Vector3(-.077,.005,s*.020),.0016,"784533")
	curve(bug,Vector3(.061,.018,-.007),Vector3(.064,.009,-.004),Vector3(.064,.009,.004),Vector3(.061,.018,.007),.0006,"784533")

func clear_of_covers(bounds:Rect2,covers:Array)->bool:
	for item in covers:
		var obstacle=Rect2(Vector2(float(item[0])-float(item[2])*.5,float(item[1])-float(item[3])*.5),Vector2(float(item[2]),float(item[3])))
		if bounds.grow(.012).intersects(obstacle,true):
			return false
	return true

func detail_bounds(detail:Node3D)->Rect2:
	# Measure actual static meshes once, including the chosen yaw and antennae.
	# Fixed margins previously ignored both changed canonical sizes and rotation.
	var result:Rect2;var first:bool=true
	for mesh in detail.find_children("*","MeshInstance3D",true,false):
		var transform:Transform3D=mesh.transform;var ancestor=mesh.get_parent()
		while ancestor!=detail:
			transform=ancestor.transform*transform;ancestor=ancestor.get_parent()
		var bounds:AABB=detail.transform*transform*mesh.get_aabb()
		var footprint=Rect2(Vector2(bounds.position.x,bounds.position.z),Vector2(bounds.size.x,bounds.size.z))
		result=footprint if first else result.merge(footprint);first=false
	return result

func draw_catalogue(p:Node3D,asset:String):
	# One definition for decorative and tactical instances of the same object.
	if prop_library.is_empty():
		prop_library=JSON.parse_string(FileAccess.get_file_as_string("res://data/world-regions.json")).props
	var shape:Dictionary=prop_library[asset]
	Art.build(null,p,[0,0,shape.width,shape.depth,asset,shape.height])

func draw_detail(p:Node3D,kind:String):
	match kind:
		"ruled_sheet":
			Art.box(p,Vector3(0,.0003,0),Vector3(.16,.0006,.12),"fff8e9","paper")
			for i in range(5):Art.box(p,Vector3(0,.0007,-.038+i*.018),Vector3(.13,.0002,.0008),"7da8cc")
			Art.box(p,Vector3(-.06,.0007,0),Vector3(.001,.0002,.10),"d37e87")
			for z in [-.034,0,.034]:Art.cylinder(p,Vector3(-.073,.00075,z),.002,.0003,"c7b895")
		"sticky_notes":
			for i in range(3):Art.box(p,Vector3(i*.002,.0005+i*.0015,i*.001),Vector3(.075,.0016,.075),["ee8c99","79b9b4","ffe17c"][i],"paper")
			for i in range(2):Art.box(p,Vector3(-.006,.0044,-.014+i*.016),Vector3(.04-i*.01,.0002,.001),"a88b43")
			var fold=Art.box(p,Vector3(.032,.005,.032),Vector3(.011,.0006,.011),"fff0b6","paper");fold.rotation.z=.18
		"phone":draw_catalogue(p,"phone")
		"two_pens":draw_catalogue(p,"pipe")
		"notepad":
			# Clipboard: cork board, exposed pages and a broad chrome clip.
			Art.bevel_box(p,Vector3(0,.003,0),Vector3(.14,.006,.11),"ba8855","paper")
			Art.box(p,Vector3(.006,.0065,0),Vector3(.116,.001,.095),"fff6e3","paper")
			Art.bevel_box(p,Vector3(-.058,.008,0),Vector3(.022,.003,.047),"b6c5cf","metal")
			for i in range(4):Art.box(p,Vector3(.012,.0072,-.032+i*.018),Vector3(.082,.0002,.0008),"7b9fa9")
		"calculator":draw_catalogue(p,"calculator")
		"postcard":
			Art.box(p,Vector3(0,.0004,0),Vector3(.13,.0008,.09),"fff0db","paper")
			Art.box(p,Vector3(-.023,.001,0),Vector3(.07,.0004,.068),"60adca","paper")
			Art.cylinder(p,Vector3(-.036,.0014,-.018),.009,.0003,"ffd574")
			for i in range(3):Art.box(p,Vector3(-.047+i*.023,.0015,.015),Vector3(.018,.0003,.035-i*.008),["548b78","7ab79b","548b78"][i])
			Art.box(p,Vector3(.047,.001,-.027),Vector3(.022,.0004,.018),"d7858f")
			for i in range(3):Art.box(p,Vector3(.036,.0014,-.005+i*.012),Vector3(.040,.0003,.0008),"ae9279")
		"usb_drive":
			Art.bevel_box(p,Vector3(-.012,.005,0),Vector3(.072,.010,.029),"db6855","plastic")
			Art.box(p,Vector3(.038,.0035,0),Vector3(.030,.007,.021),"c3cbd2","metal")
			for z in [-.005,.005]:Art.box(p,Vector3(.038,.0072,z),Vector3(.007,.0003,.004),"43505e")
			Art.box(p,Vector3(.008,.0102,0),Vector3(.018,.0005,.008),"ffe4b4")
			var loop=Art.ring(p,Vector3(-.041,.005,0),.006,.0035,"c3cbd2","metal");loop.rotation.x=PI/2
		"coaster":
			Art.cylinder(p,Vector3(0,.002,0),.051,.004,"ad8053",-1,24,"paper")
			Art.ring(p,Vector3(0,.0043,0),.044,.040,"e0b980","paper").scale.y=.12
			Art.ring(p,Vector3(0,.0045,0),.028,.026,"8b634b","paper").scale.y=.12
			for angle in [0,1.7,3.6,4.5]:
				Art.box(p,Vector3(cos(angle)*.035,.0043,sin(angle)*.035),Vector3(.002,.0004,.0015),"8b634b")
		"cartoon_roach":draw_roach(p)

func build(_game,spec:Dictionary,left:float,z:float,desks:Array)->Dictionary:
	if desks.is_empty():return {"status":"skipped","reason":"no_desks"}
	var revision:int=desks[0].get_meta("region_index")
	# Independent schedules: an easter egg must never replace the same asset.
	var kind:String=DETAILS[posmod(revision,DETAILS.size())]
	var detail=Node3D.new()
	detail.rotation.y=deg_to_rad(float(posmod(revision,5)-2)*6.0)
	draw_detail(detail,kind)
	var footprint:Rect2=detail_bounds(detail)
	var panels:Dictionary={}
	for panel in desks:
		var cell:Vector2i=panel.get_meta("cell")
		panels[cell.x*3+cell.y]=panel
	var report:Dictionary={"kind":kind,"status":"skipped","reason":"no_clear_space","checked_positions":0}
	for offset in range(9):
		var index:int=posmod(7+revision*4+offset,9)
		if not panels.has(index):continue
		var panel=panels[index]
		var cell:Vector2i=panel.get_meta("cell")
		var cx:float=(cell.x+.5)*.6
		var cz:float=(cell.y-1)*.7
		var desk_bounds=Rect2(Vector2(cx-.3,cz-.35),Vector2(.6,.7)).grow(-.012)
		for step in range(SPOTS.size()):
			var spot:Vector2=SPOTS[(index*3+revision+step)%SPOTS.size()]
			var bounds=Rect2(footprint.position+Vector2(cx,cz)+spot,footprint.size)
			report.checked_positions+=1
			if not desk_bounds.encloses(bounds) or not clear_of_covers(bounds,spec.covers):continue
			detail.name="DeskDetail_%d_%d"%[cell.x,cell.y];add_child(detail)
			detail.position=Vector3(left+cx+spot.x,float(panel.get_meta("desk_top"))+.002,z+cz+spot.y)
			detail.set_meta("desk_detail",kind)
			report.merge({"status":"placed","reason":"","cell":[cell.x,cell.y],"position":[cx+spot.x,cz+spot.y],"bounds":[bounds.position.x,bounds.position.y,bounds.size.x,bounds.size.y]},true)
			Art.batch(self)
			return report
	detail.free()
	return report
