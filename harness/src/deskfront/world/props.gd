extends RefCounted
static func build(field,parent:Node3D,item:Array):
	var w:float=item[2];var d:float=item[3];var h:float=item[5]
	var steel=field.mat(Color(.24,.35,.40));var dark=field.mat(Color(.13,.18,.20));var brass=field.mat(Color(.79,.64,.32))
	var concrete=field.mat(Color(.53,.55,.48));var rust=field.mat(Color(.39,.27,.18))
	if item[4]=="sandbag":
		var long_x:bool=w>=d
		var length:float=maxf(w,d);var depth:float=minf(w,d)
		for row in range(2):
			var count:int=5 if row==0 else 4
			for i in range(count):
				var along:float=(float(i)-(count-1)*.5)*length*.19
				var center=Vector3(along,h*(.25+row*.46),0) if long_x else Vector3(0,h*(.25+row*.46),along)
				var size=Vector3(length*.195,h*.5,depth*.96) if long_x else Vector3(depth*.96,h*.5,length*.195)
				stone(parent,center,size,field.mat(Color(.66+float(i%2)*.08,.57+float(i%2)*.06,.36)),true)
	elif item[4]=="ruin":
		# Broken stepped masonry silhouette, warm exposed bricks and dark mortar.
		field.cube(parent,Vector3(0,h*.20,0),Vector3(w,h*.40,d),rust)
		for col in range(6):
			var rows:int=[5,5,4,3,2,3][col]
			for row in range(rows):
				var brick_h:float=h*.18
				field.cube(parent,Vector3(w*((float(col)+.5)/6-.5),brick_h*(row+.5),0),Vector3(w*.158,brick_h*.89,d*.98),field.mat(Color(.56+float(col%2)*.08,.31,.20)))
		for col in [0,1]:field.cube(parent,Vector3(w*(float(col)/6-.40),h*.94,0),Vector3(w*.015,h*.12,d*.10),dark)
	elif item[4]=="gabion":
		for i in range(15):
			var col:int=i%5;var row:int=i/5
			stone(parent,Vector3(w*(float(col)-2)*.19,h*(.18+row*.30),d*(.10 if i%2 else -.10)),Vector3(w*.20,h*.36,d*.76),field.mat(Color(.40+float(i%3)*.08,.42+float(i%3)*.06,.38)),false)
		for side in [-1,1]:
			for i in range(6):field.cube(parent,Vector3(w*(float(i)/5-.5),h*.5,d*side*.49),Vector3(w*.017,h,.002),dark)
			for y in [.04,.50,.96]:field.cube(parent,Vector3(0,h*y,d*side*.49),Vector3(w,h*.045,.002),dark)
		for x in [-.49,.49]:field.cube(parent,Vector3(w*x,h*.97,0),Vector3(w*.02,h*.04,d),dark)
	elif item[4]=="concrete":
		field.cube(parent,Vector3(0,h*.47,0),Vector3(w,h*.94,d),concrete)
		field.cube(parent,Vector3(0,h*.97,0),Vector3(w,h*.06,d),field.mat(Color(.65,.66,.58)))
	elif item[4] in ["tank","pipe"]:
		var radius:float=minf(w,d)*.39
		if item[4]=="tank":
			cylinder(field,parent,Vector3(0,h*.48,0),radius,h*.76,steel)
			for y in [.18,.76]:cylinder(field,parent,Vector3(0,h*y,0),radius*1.10,h*.045,dark)
			cylinder(field,parent,Vector3(0,h*.89,0),radius*.46,h*.10,brass)
			# Broad ladder rails and rungs read from the game camera.
			for x in [-.18,.18]:field.cube(parent,Vector3(w*x,h*.46,d*.43),Vector3(w*.045,h*.73,d*.055),brass)
			for i in range(5):field.cube(parent,Vector3(0,h*(.16+i*.14),d*.43),Vector3(w*.4,h*.027,d*.055),brass)
			for x in [-.26,.26]:field.cube(parent,Vector3(w*x,h*.065,0),Vector3(w*.15,h*.13,d*.55),dark)
		else:
			# Paired pipes with visible dark mouths, flanges and saddle supports.
			for z in [-.24,.24]:
				var r:float=minf(h*.35,d*.20)
				cylinder(field,parent,Vector3(0,h*.53,d*z),r,w*.93,steel,true)
				for x in [-.43,.43]:
					cylinder(field,parent,Vector3(w*x,h*.53,d*z),r*1.17,w*.055,brass,true)
					cylinder(field,parent,Vector3(w*x+signf(x)*w*.03,h*.53,d*z),r*.69,w*.008,dark,true)
			for x in [-.26,.26]:field.cube(parent,Vector3(w*x,h*.14,0),Vector3(w*.12,h*.28,d*.94),concrete)
	elif item[4]=="warehouse":
		field.cube(parent,Vector3(0,h*.35,0),Vector3(w,h*.7,d),steel)
		var roof=MeshInstance3D.new();var prism=PrismMesh.new();prism.size=Vector3(w,h*.30,d)
		roof.mesh=prism;roof.material_override=rust;roof.position.y=h*.85;parent.add_child(roof)
		# Large roll-up doors on both visible facades; explicitly closed solids.
		for side in [-1,1]:
			field.cube(parent,Vector3(w*side*.497,h*.28,0),Vector3(w*.006,h*.53,d*.46),dark)
			for i in range(7):field.cube(parent,Vector3(w*side*.501,h*(.06+i*.068),0),Vector3(w*.004,h*.023,d*.42),concrete)
			for z in [-.27,.27]:field.cube(parent,Vector3(w*side*.495,h*.29,d*z),Vector3(w*.01,h*.58,d*.055),brass)
			for z in [-.38,.38]:field.cube(parent,Vector3(w*side*.501,h*.56,d*z),Vector3(.002,h*.13,d*.12),dark)
		# Contrasting skylight panels follow the pitched roof, not floating labels.
		for side in [-1,1]:
			for z in [-.23,.23]:
				var panel=field.cube(parent,Vector3(w*side*.25,h*.855,d*z),Vector3(w*.27,.003,d*.26),field.mat(Color(.48,.65,.66)))
				panel.rotation.z=-side*atan2(h*.30,w*.5)
	elif item[4]=="rubble":
		# Deterministic uneven heap, no neat rows or repeated upright cubes.
		for i in range(11):
			var angle:float=i*2.39996
			var ring:float=.0 if i==0 else (.22 if i<5 else .34)
			var size=Vector3(w*(.32 if i<5 else .19),h*(.90 if i<5 else .45),d*(.43 if i<5 else .25))
			stone(parent,Vector3(cos(angle)*w*ring,size.y*.5,sin(angle)*d*ring),size,field.mat(Color(.48+float(i%3)*.08,.37+float(i%3)*.07,.28+float(i%3)*.07)),false)
	elif item[4]=="drum":
		var mesh=MeshInstance3D.new();var cylinder=CylinderMesh.new()
		cylinder.top_radius=w*.5;cylinder.bottom_radius=w*.5;cylinder.height=h;cylinder.radial_segments=12
		mesh.mesh=cylinder;mesh.material_override=field.mat(Color(.48,.20,.12));mesh.position.y=h*.5;parent.add_child(mesh)
		for y in [.15,.8]:field.cube(parent,Vector3(0,h*y,0),Vector3(w,.006,d),dark)
	elif item[4]=="cabinet":
		field.cube(parent,Vector3(0,h*.5,0),Vector3(w,h,d),steel)
		for i in range(3):
			field.cube(parent,Vector3(0,h*(i+.5)/3,d*.5+.001),Vector3(w*.82,h*.26,.002),dark)
			field.cube(parent,Vector3(0,h*(i+.5)/3,d*.5+.003),Vector3(w*.3,.004,.003),brass)
	else:
		for x in [-.35,.35]:field.cube(parent,Vector3(w*x,h*.5,0),Vector3(w*.15,h,d*.65),dark)
		for y in [.45,.85]:field.cube(parent,Vector3(0,h*y,0),Vector3(w,h*.18,d),brass)

static func cylinder(field,parent:Node3D,position:Vector3,radius:float,height:float,material:Material,horizontal:bool=false):
	var node=MeshInstance3D.new();var mesh=CylinderMesh.new()
	mesh.radial_segments=16;mesh.top_radius=radius;mesh.bottom_radius=radius;mesh.height=height
	node.mesh=mesh;node.material_override=material;node.position=position
	if horizontal:node.rotation.z=PI*.5
	parent.add_child(node)

static func stone(parent:Node3D,position:Vector3,size:Vector3,material:Material,smooth:bool):
	var node=MeshInstance3D.new();var mesh=SphereMesh.new()
	mesh.radius=.5;mesh.height=1.0;mesh.radial_segments=12 if smooth else 5;mesh.rings=6 if smooth else 2
	node.mesh=mesh;node.material_override=material;node.position=position;node.scale=size
	parent.add_child(node)
