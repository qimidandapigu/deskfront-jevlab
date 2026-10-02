extends RefCounted
## Distinct stationery silhouettes, stable palettes and static material batching.
## Legacy recipe keys retain collision semantics.
const IDENTITIES={"warehouse":"archive_box","bookstack":"notebooks","concrete":"ring_binder","ruin":"notebooks","gabion":"index_cards","rubble":"mouse","tank":"glue_stick","drum":"glue_stick","pipe":"pencils","sandbag":"eraser","cabinet":"archive_box","crate":"pencil_case","barricade":"pencil_case","novel":"novel","book_city":"novel","book_atlas":"novel","mouse":"mouse","tissues":"tissues","mug":"mug","ruler":"ruler","tape":"tape","laptop":"laptop","phone":"phone","calculator":"calculator","stapler":"stapler","printer":"printer","desk_divider":"desk_divider","file_rack":"file_rack","fort_wall":"fort_wall"}
static var materials:Dictionary={}
static var cover_texture:Texture2D=null
static func material(hex:String,finish:String="matte")->Material:
	var key:String=hex+":"+finish
	if not materials.has(key):
		var m=StandardMaterial3D.new();m.albedo_color=Color(hex)
		m.roughness={"paper":.96,"fabric":.92,"matte":.78,"plastic":.40,"ceramic":.24,"metal":.30,"screen":.20}.get(finish,.78)
		m.metallic=.65 if finish=="metal" else 0.0
		materials[key]=m
	return materials[key]
static func box(p,pos,size,color,finish:String="matte"):
	var n=MeshInstance3D.new();var m=BoxMesh.new();m.size=size;n.mesh=m;n.material_override=material(color,finish);n.position=pos;p.add_child(n)
	return n
static func cylinder(p,pos,r,h,color,top:float=-1,segments:int=16,finish:String="matte"):
	var n=MeshInstance3D.new();var m=CylinderMesh.new();m.radial_segments=segments;m.top_radius=r if top<0 else top;m.bottom_radius=r;m.height=h
	n.mesh=m;n.material_override=material(color,finish);n.position=pos;p.add_child(n);return n
static func ellipsoid(p,pos,size,color,finish:String="matte"):
	var n=MeshInstance3D.new();var m=SphereMesh.new();m.radius=.5;m.height=1;m.radial_segments=14;m.rings=7
	n.mesh=m;n.material_override=material(color,finish);n.position=pos;n.scale=size;p.add_child(n);return n
static func bevel_box(p,pos,size,color,finish:String="matte"):
	# Eight-sided footprint: rubber/plastic edges, unlike paper's sharp corners.
	var x:float=size.x*.5;var z:float=size.z*.5;var b:float=minf(x,z)*.22
	var outline=[Vector2(-x+b,-z),Vector2(x-b,-z),Vector2(x,-z+b),Vector2(x,z-b),Vector2(x-b,z),Vector2(-x+b,z),Vector2(-x,z-b),Vector2(-x,-z+b)]
	var st=SurfaceTool.new();st.begin(Mesh.PRIMITIVE_TRIANGLES);st.set_smooth_group(-1)
	for i in range(8):
		var a:Vector2=outline[i];var c:Vector2=outline[(i+1)%8]
		var lo=Vector3(a.x,-size.y*.5,a.y);var hi=Vector3(a.x,size.y*.5,a.y)
		var next_lo=Vector3(c.x,-size.y*.5,c.y);var next_hi=Vector3(c.x,size.y*.5,c.y)
		for v in [hi,next_hi,Vector3(0,size.y*.5,0),lo,Vector3(0,-size.y*.5,0),next_lo,lo,next_hi,hi,lo,next_lo,next_hi]:st.add_vertex(v)
	st.generate_normals();var node=MeshInstance3D.new();node.mesh=st.commit();node.position=pos
	node.material_override=material(color,finish);p.add_child(node);return node
static func tube(p:Node3D,pos:Vector3,outer:float,inner:float,height:float,color:String):
	var st=SurfaceTool.new();st.begin(Mesh.PRIMITIVE_TRIANGLES);st.set_smooth_group(-1)
	for i in range(24):
		var a:float=TAU*i/24.0;var b:float=TAU*(i+1)/24.0
		var oa=Vector3(cos(a)*outer,height*.5,sin(a)*outer);var ob=Vector3(cos(b)*outer,height*.5,sin(b)*outer)
		var ia=Vector3(cos(a)*inner,height*.5,sin(a)*inner);var ib=Vector3(cos(b)*inner,height*.5,sin(b)*inner)
		var down=Vector3(0,height,0)
		for quad in [[oa,ob,ib,ia],[oa-down,ia-down,ib-down,ob-down],[oa-down,ob-down,ob,oa],[ia-down,ia,ib,ib-down]]:
			for index in [0,1,2,0,2,3]:st.add_vertex(quad[index])
	st.generate_normals();var n=MeshInstance3D.new();n.mesh=st.commit();n.position=pos
	n.material_override=material(color,"paper");p.add_child(n);return n
static func ring(p,pos,outer:float,inner:float,color:String,finish:String="matte"):
	var n=MeshInstance3D.new();var mesh=TorusMesh.new()
	mesh.inner_radius=inner;mesh.outer_radius=outer;mesh.rings=20;mesh.ring_segments=8
	n.mesh=mesh;n.material_override=material(color,finish);n.position=pos;p.add_child(n);return n
static func mouse_surface_y(x:float,z:float,w:float,d:float,h:float)->float:
	var radius:float=1.0-pow(x/(w*.5),2)-pow(z/(d*.5),2)
	return h*.47+h*.44*sqrt(maxf(.02,radius))
static func mouse_button_patch(p:Node3D,w:float,d:float,h:float,side:int):
	var tool=SurfaceTool.new();tool.begin(Mesh.PRIMITIVE_TRIANGLES)
	for row in range(8):
		for column in range(4):
			var x0=w*lerpf(.07,.38,float(row)/8);var x1=w*lerpf(.07,.38,float(row+1)/8)
			var z0=side*d*lerpf(.035,.25,float(column)/4);var z1=side*d*lerpf(.035,.25,float(column+1)/4)
			var a=Vector3(x0,mouse_surface_y(x0,z0,w,d,h)+h*.012,z0)
			var b=Vector3(x1,mouse_surface_y(x1,z0,w,d,h)+h*.012,z0)
			var c=Vector3(x0,mouse_surface_y(x0,z1,w,d,h)+h*.012,z1)
			var e=Vector3(x1,mouse_surface_y(x1,z1,w,d,h)+h*.012,z1)
			for point in [a,b,c,b,e,c]:tool.add_vertex(point)
	tool.generate_normals()
	var patch=MeshInstance3D.new();patch.mesh=tool.commit()
	var ink:StandardMaterial3D=material("f8f5ec");ink.cull_mode=BaseMaterial3D.CULL_DISABLED
	patch.material_override=ink;p.add_child(patch)
static func soft_case(p,pos,size,color):
	var n=MeshInstance3D.new();var m=CapsuleMesh.new();m.radius=.5;m.height=2.5;m.radial_segments=16;m.rings=6
	n.mesh=m;n.material_override=material(color,"fabric");n.position=pos;n.rotation.z=PI/2
	n.scale=Vector3(size.y,size.x/2.5,size.z);p.add_child(n);return n
static func label(words:String,width:float,color:String)->Label3D:
	var n=Label3D.new();n.text=words;n.font_size=128
	var longest=1
	for line in words.split("\n"):longest=maxi(longest,line.length())
	n.pixel_size=width/maxf(longest*122.0,128.0)
	n.modulate=Color(color);n.outline_size=0;n.no_depth_test=false
	n.billboard=BaseMaterial3D.BILLBOARD_DISABLED
	return n
static func text_top(p,words:String,pos:Vector3,width:float,color:String="26384a"):
	var n=label(words,width,color);n.rotation.x=-PI/2;n.position=pos;p.add_child(n)
static func text_front(p,words:String,pos:Vector3,width:float,color:String="26384a"):
	var n=label(words,width,color);n.position=pos;p.add_child(n)
static func printed_cover_top(p:Node3D,w:float,d:float,y:float):
	var art=MeshInstance3D.new();var quad=QuadMesh.new();quad.size=Vector2(w,d);art.mesh=quad
	if cover_texture==null:
		var photo=Image.load_from_file("res://assets/deskfront/book-hengda-cover.png")
		photo.generate_mipmaps()
		cover_texture=ImageTexture.create_from_image(photo)
	var ink=StandardMaterial3D.new();ink.albedo_texture=cover_texture
	ink.roughness=.92;ink.texture_filter=BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS
	art.material_override=ink;art.rotation.x=-PI/2;art.position=Vector3(0,y,0);p.add_child(art)
static func build(_f,p:Node3D,a:Array):
	var w:float=a[2];var d:float=a[3];var h:float=a[5]
	var root=Node3D.new();p.add_child(root)
	if w<d:root.rotation.y=PI/2;var swap=w;w=d;d=swap
	var identity:String=IDENTITIES.get(str(a[4]),"pencil_case");p.set_meta("stationery_identity",identity)
	# Fixed physical dimensions also mean fixed visual scale. A desk position
	# must never introduce a random yaw and compensating shrink-to-fit.
	match identity:
		"fort_wall":
			# Three authored silhouettes share collision semantics, not one brick skin.
			if h<.15:
				# Yellow memo-paper bundles with broad colored side tabs.
				for i in range(3):
					var y:float=h*(i+.5)/3.0
					box(root,Vector3(0,y,0),Vector3(w*.96,h*.30,d*.95),"ffeca5","paper")
					box(root,Vector3(0,y+h*.145,0),Vector3(w*.96,h*.018,d*.95),"d4ad54","paper")
					box(root,Vector3(w*(-.25+i*.25),y,d*.48),Vector3(w*.18,h*.20,d*.03),["e28b76","64b4a1","769bc8"][i],"paper")
				box(root,Vector3(0,h*.984,0),Vector3(w*.06,h*.025,d*.95),"e28b76","fabric")
			elif w<.25:
				# Upright lever-arch files: spine labels and metal finger holes.
				for i in range(3):
					var x:float=w*(i-1)*.32
					var tint:String=["415897","b3633f","458e7c"][i]
					box(root,Vector3(x,h*.49,0),Vector3(w*.29,h*.98,d*.95),tint,"plastic")
					box(root,Vector3(x,h*.985,0),Vector3(w*.22,h*.008,d*.79),"f5e9ce","paper")
					box(root,Vector3(x,h*.66,d*.478),Vector3(w*.22,h*.35,.001),"f5e9ce","paper")
					for j in range(2):box(root,Vector3(x,h*(.62+j*.10),d*.48),Vector3(w*.15,h*.02,.001),tint)
					var hole=ring(root,Vector3(x,h*.22,d*.485),minf(w*.085,h*.068),minf(w*.056,h*.044),"c1cbd2","metal")
					hole.rotation.x=PI/2
			else:
				# Flat lever-arch binders with curved exposed rings and spine bands.
				var count:int=2 if w<.4 else 4
				for bundle in range(count):
					var x:float=w*(-.5+(bundle+.5)/count);var bw:float=w/count*.93
					for layer in range(3):
						var y:float=h*(layer+.5)/3.0
						var tint:String=["385f79","468576","a95763"][(bundle+layer)%3]
						box(root,Vector3(x,y,0),Vector3(bw,h*.29,d*.91),"f3e9d3","paper")
						box(root,Vector3(x,y+h*.148,0),Vector3(bw,h*.019,d*.98),tint,"plastic")
						box(root,Vector3(x,y,d*.455),Vector3(bw,h*.29,d*.07),tint,"plastic")
						box(root,Vector3(x,y,d*.492),Vector3(bw*.55,h*.15,.001),"f3e9d3","paper")
					box(root,Vector3(x,h*.985,0),Vector3(bw*.54,h*.015,d*.30),"c1cbd2","metal")
					for z in [-.16,.16]:
						var rings=ring(root,Vector3(x-bw*.33,h*.956,d*z),minf(bw*.09,h*.036),minf(bw*.06,h*.024),"c1cbd2","metal")
						rings.rotation.x=PI/2
		"notebooks":
			# Blue spiral notebook: one readable binding, not another book pile.
			box(root,Vector3(0,h*.43,0),Vector3(w*.94,h*.78,d*.92),"f7f0d8","paper")
			for y in [.035,.84]:box(root,Vector3(0,h*y,0),Vector3(w*.98,h*.045,d*.98),"2864c5","plastic")
			box(root,Vector3(w*.39,h*.44,0),Vector3(w*.12,h*.86,d*.98),"203e83")
			for i in range(6):
				var spiral=ring(root,Vector3(w*.39,h*.89,d*(-.38+i*.15)),minf(h*.10,w*.045),minf(h*.065,w*.029),"c4ccd5","metal")
				spiral.rotation.x=PI/2
			box(root,Vector3(-w*.13,h*.869,-d*.12),Vector3(w*.46,h*.012,d*.27),"f7f0d8","paper")
			for i in range(3):box(root,Vector3(-w*.10,h*.878,d*(-.18+i*.063)),Vector3(w*.32,.0004,d*.009),"5477a5")
		"index_cards":
			# Plum card tray with high colored index tabs and exposed white cards.
			box(root,Vector3(0,h*.15,0),Vector3(w*.98,h*.30,d*.96),"77528c","plastic")
			box(root,Vector3(0,h*.56,0),Vector3(w*.88,h*.57,d*.79),"fff3db","paper")
			for i in range(5):
				var z:float=d*(-.30+i*.14)
				box(root,Vector3(0,h*.82,z),Vector3(w*.86,h*.028,d*.019),"cbbca7")
				box(root,Vector3(w*(-.28+i*.14),h*.90,z),Vector3(w*.17,h*.18,d*.06),["e78739","52a9b2","d77598","97b85e","dfb94a"][i])
		"ring_binder":
			# Plum lever-arch binder: real spine, page inset and chrome finger ring.
			box(root,Vector3(0,h*.48,0),Vector3(w*.88,h*.90,d*.84),"f6ecd3","paper")
			for z in [-.46,.46]:box(root,Vector3(0,h*.49,d*z),Vector3(w*.97,h*.98,d*.065),"78466e","plastic")
			box(root,Vector3(w*.46,h*.49,0),Vector3(w*.065,h*.98,d*.97),"512f59","plastic")
			box(root,Vector3(w*.495,h*.61,0),Vector3(.0007,h*.35,d*.63),"fff3d8","paper")
			var finger=ring(root,Vector3(w*.496,h*.21,0),minf(d*.23,h*.10),minf(d*.15,h*.064),"bdc9d3","metal")
			finger.rotation.z=PI/2
			box(root,Vector3(w*.12,h*.69,d*.495),Vector3(w*.45,h*.24,.001),"b78baf","paper")
		"archive_box":
			box(root,Vector3(0,h*.45,0),Vector3(w*.95,h*.90,d*.94),"bf8849","paper")
			box(root,Vector3(0,h*.94,0),Vector3(w*.99,h*.10,d*.98),"dbad66","paper")
			box(root,Vector3(0,h*.996,0),Vector3(w*.19,h*.004,d*.98),"eccc89","paper")
			box(root,Vector3(0,h*.63,d*.472),Vector3(w*.19,h*.50,.001),"eccc89","paper")
			# Die-cut handle, broad shipping sticker, and bottom corrugation.
			box(root,Vector3(-w*.24,h*.74,d*.474),Vector3(w*.22,h*.075,.001),"584128")
			box(root,Vector3(w*.27,h*.43,d*.474),Vector3(w*.32,h*.30,.001),"fff4db","paper")
			for i in range(7):box(root,Vector3(w*(.15+i*.036),h*.39,d*.476),Vector3(w*(.011 if i%2 else .019),h*.17,.0005),"3b4750")
			box(root,Vector3(-w*.24,h*.996,-d*.16),Vector3(w*.25,h*.004,d*.35),"376899")
			for side in [-1,1]:box(root,Vector3(side*w*.48,h*.04,0),Vector3(w*.008,h*.055,d*.88),"91633e")
		"eraser":
			bevel_box(root,Vector3(0,h*.5,0),Vector3(w,h*.96,d*.96),"efafa8")
			box(root,Vector3(-w*.08,h*.5,0),Vector3(w*.64,h,d),"326f9a")
			box(root,Vector3(-w*.08,h+.0007,0),Vector3(w*.5,.001,d*.64),"f5f0df")
			text_top(root,"ERASER",Vector3(-w*.08,h+.0024,0),w*.40)
			box(root,Vector3(w*.17,h+.0007,0),Vector3(w*.026,.001,d*.98),"dd6657")
			# Two broad rubbed facets distinguish the exposed rubber from its sleeve.
			for z in [-.22,.22]:box(root,Vector3(w*.39,h*.984,d*z),Vector3(w*.14,h*.008,d*.065),"f6c8bd")
		"glue_stick":
			var r=minf(w,d)*.49
			cylinder(root,Vector3(0,h*.37,0),r*.94,h*.74,"f5eee0",-1,16,"plastic")
			cylinder(root,Vector3(0,h*.43,0),r*.945,h*.30,"b6538e",-1,16,"paper")
			cylinder(root,Vector3(0,h*.87,0),r,h*.26,"d08d32",-1,16,"plastic")
			cylinder(root,Vector3(0,h*.065,0),r,h*.13,"e2a744",-1,16,"plastic")
			for i in range(10):
				var angle=TAU*i/10;box(root,Vector3(cos(angle)*r*.96,h*.87,sin(angle)*r*.96),Vector3(r*.055,h*.19,r*.055),"ffd26d")
			box(root,Vector3(0,h*.44,r*.945),Vector3(r*.9,h*.19,r*.01),"fff2d5","paper")
			text_top(root,"GLUE",Vector3(0,h+.0002,0),r*1.35,"674b2d")
		"pencils":
			# Exposed hexagonal shafts and tips, no rectangular slab underneath.
			for i in range(2):
				var pen=Node3D.new();root.add_child(pen);pen.position=Vector3(0,h*.56,d*(-.24+i*.48));pen.rotation.z=-PI/2
				var r=minf(h*.42,d*.23)
				cylinder(pen,Vector3(0,-w*.06,0),r,w*.72,"f4bd35" if i==0 else "3976b6",-1,6,"plastic")
				box(pen,Vector3(r*.82,-w*.10,0),Vector3(r*.08,w*.57,r*.60),"ffe59b" if i==0 else "81b1de")
				cylinder(pen,Vector3(0,w*.37,0),r,w*.14,"d9b68c",0,6)
				cylinder(pen,Vector3(0,w*.455,0),r*.23,w*.03,"303a48",0,6)
				cylinder(pen,Vector3(0,-w*.45,0),r,w*.06,"d07872",-1,6)
				cylinder(pen,Vector3(0,-w*.405,0),r*1.01,w*.035,"b9bcc0",-1,6)
		"pencil_case":
			soft_case(root,Vector3(0,h*.50,0),Vector3(w*.98,h*.94,d*.94),"ca725b")
			box(root,Vector3(0,h*.96,0),Vector3(w*.77,h*.017,d*.08),"483f3e")
			for i in range(12):box(root,Vector3(w*(-.35+i*.063),h*.977,0),Vector3(w*.017,.001,d*.055),"edc15f")
			box(root,Vector3(w*.31,h*.985,0),Vector3(w*.07,.002,d*.15),"bfaa86")
			box(root,Vector3(-w*.1,h*.54,d*.475),Vector3(w*.34,h*.21,.001),"e4d1af")
			text_front(root,"PENS",Vector3(-w*.1,h*.54,d*.477),w*.27,"36434b")
			for x in [-.37,.37]:
				var seam=ring(root,Vector3(w*x,h*.50,0),1,.94,"e7a18b","fabric")
				seam.rotation.z=PI/2;seam.scale=Vector3(h*.32,w*.005,d*.39)
		"mouse":
			# A broad smooth shell keeps the silhouette solid in RTS view. Two
			# raised buttons and the central wheel mark it as a wireless mouse.
			# No rectangular mouse pad: the oval shell is the identity.
			var mw:float=w*.84;var md:float=d*.70;var mh:float=h*.79
			ellipsoid(root,Vector3(-w*.025,h*.12,0),Vector3(mw*.96,h*.11,md*.92),"657173")
			var body=Node3D.new();root.add_child(body);body.position=Vector3(-w*.025,h*.12,0)
			ellipsoid(body,Vector3(0,mh*.47,0),Vector3(mw,mh*.88,md),"e5e2d9","plastic")
			for side in [-1,1]:mouse_button_patch(body,mw,md,mh,side)
			var wheel=cylinder(body,Vector3(mw*.26,mh*.92,0),minf(mw*.055,mh*.10),md*.12,"3f5158",-1,12)
			wheel.rotation.x=PI/2
		"novel":
			# Separate book silhouettes; no shared three-volume stack.
			var book_kind:String=str(a[4])
			if book_kind=="book_atlas":
				# An open atlas: two sloped pages, central crease, colored map blocks.
				box(root,Vector3(0,h*.08,0),Vector3(w*.98,h*.12,d*.98),"397550","fabric")
				for side in [-1,1]:
					var page=Node3D.new();root.add_child(page)
					page.position=Vector3(side*w*.235,h*.51,0);page.rotation.z=side*.05
					box(page,Vector3.ZERO,Vector3(w*.46,h*.86,d*.92),"fff2d0","paper")
					box(page,Vector3(0,h*.431,0),Vector3(w*.40,h*.012,d*.76),"a8ca88","paper")
					for i in range(3):
						box(page,Vector3(w*(-.12+i*.10),h*.443,d*(-.20+i*.15)),Vector3(w*.11,h*.012,d*.19),"71a4c7")
						box(page,Vector3(0,h*.455,d*(-.24+i*.22)),Vector3(w*.37,h*.008,d*.017),"f4e6bb")
					box(page,Vector3(w*.09,h*.465,0),Vector3(w*.013,h*.008,d*.72),"bb6e49")
				box(root,Vector3(0,h*.87,0),Vector3(w*.018,h*.013,d*.94),"877656")
				box(root,Vector3(w*.08,h*.14,d*.43),Vector3(w*.05,h*.02,d*.10),"df725e","fabric")
			else:
				build_closed_book(root,w,d,h,book_kind)
		"tissues":
			box(root,Vector3(0,h*.38,0),Vector3(w*.99,h*.76,d*.96),"b19aca","paper")
			box(root,Vector3(0,h*.765,0),Vector3(w,h*.03,d),"f2e9f3","paper")
			box(root,Vector3(0,h*.783,0),Vector3(w*.48,h*.008,d*.18),"514b68")
			var tissue_y:float=minf(h*.86,h-.001-h*.105*cos(.19)-w*.145*sin(.19))
			var left_tissue=Node3D.new();root.add_child(left_tissue)
			left_tissue.position=Vector3(-w*.09,tissue_y,0);left_tissue.rotation.z=-.19
			box(left_tissue,Vector3.ZERO,Vector3(w*.29,h*.21,.001),"fffaf3","paper")
			var right_tissue=Node3D.new();root.add_child(right_tissue)
			right_tissue.position=Vector3(w*.09,tissue_y,0);right_tissue.rotation.z=.19
			box(right_tissue,Vector3.ZERO,Vector3(w*.29,h*.21,.001),"eee9f0","paper")
			box(root,Vector3(0,h*.43,d*.482),Vector3(w*.75,h*.56,.001),"f8f0ed")
			box(root,Vector3(0,h*.58,d*.483),Vector3(w*.63,h*.04,.001),"8c62aa")
			text_front(root,"SOFT",Vector3(0,h*.43,d*.486),w*.55,"805798")
		"mug":
			var r:float=minf(w*.34,d*.46)
			cylinder(root,Vector3(-w*.08,h*.45,0),r,h*.86,"188b94",-1,16,"ceramic")
			ring(root,Vector3(-w*.08,h*.90,0),r,r*.80,"d8f0e6","ceramic")
			cylinder(root,Vector3(-w*.08,h*.87,0),r*.78,h*.012,"513727")
			var handle=ring(root,Vector3(w*.29,h*.52,0),minf(w*.20,h*.28),minf(w*.125,h*.17),"188b94","ceramic")
			handle.rotation.x=PI/2
		"ruler":
			# Actual desk scale: a flat thirty-centimetre ruler, not a little wall.
			bevel_box(root,Vector3(0,h*.50,0),Vector3(w*.98,h*.92,d*.94),"f0c456","plastic")
			box(root,Vector3(0,h*.964,-d*.23),Vector3(w*.87,h*.014,d*.10),"ffe4a0","plastic")
			box(root,Vector3(0,h*.955,-d*.43),Vector3(w*.98,h*.016,d*.05),"b98945")
			for i in range(19):
				var long_tick:bool=i%5==0
				box(root,Vector3(w*(-.45+i*.05),h*.97,d*(.13 if long_tick else -.01)),Vector3(maxf(.0004,w*.005),h*.008,d*(.45 if long_tick else .18)),"35414a")
			for i in range(4):text_top(root,str(i*5),Vector3(w*(-.45+i*.25),h*.985,d*.30),w*.075,"35414a")
			text_top(root,"cm",Vector3(w*.36,h*.985,d*.30),w*.11,"35414a")
		"tape":
			var r:float=minf(w,d)*.46
			tube(root,Vector3(-w*.015,h*.48,0),r,r*.67,h*.94,"e8bd58")
			tube(root,Vector3(-w*.015,h*.50,0),r*.67,r*.58,h*.97,"fff3d5")
			for ratio in [.78,.9]:
				var winding=ring(root,Vector3(-w*.015,h*.954,0),r*ratio,r*(ratio-.013),"cb9f46","paper")
				winding.scale.y=.12
			box(root,Vector3(w*.36,h*.18,0),Vector3(w*.23,h*.10,d*.28),"e8bd58","paper")
		"laptop":
			box(root,Vector3(0,h*.14,-d*.035),Vector3(w,h*.17,d*.88),"c3cbd4","metal")
			box(root,Vector3(0,h*.230,-d*.045),Vector3(w*.80,h*.009,d*.63),"3a4454")
			for row in range(3):
				for col in range(8):box(root,Vector3(w*(-.32+col*.09),h*.242,d*(-.15+row*.17)),Vector3(w*.065,h*.009,d*.065),"f0f2ee")
			box(root,Vector3(0,h*.239,d*.32),Vector3(w*.20,h*.003,d*.11),"f0f2ee")
			var lid=Node3D.new();root.add_child(lid)
			lid.position=Vector3(0,h*.235,-d*.35);lid.rotation.x=-.16
			box(lid,Vector3(0,h*.38,0),Vector3(w*.96,h*.76,d*.055),"707f97","metal")
			box(lid,Vector3(0,h*.39,d*.029),Vector3(w*.87,h*.65,.001),"164b83","screen")
			box(lid,Vector3(0,h*.66,d*.031),Vector3(w*.78,h*.028,.001),"52c4df")
			box(lid,Vector3(-w*.19,h*.40,d*.031),Vector3(w*.31,h*.37,.001),"258fbf")
			box(lid,Vector3(w*.18,h*.47,d*.031),Vector3(w*.25,h*.18,.001),"efa967")
			for i in range(3):box(lid,Vector3(w*.18,h*(.33+i*.046),d*.032),Vector3(w*.24,h*.012,.001),"f0f2ee")
		"phone":
			bevel_box(root,Vector3(0,h*.50,0),Vector3(w*.98,h*.90,d*.96),"30394b","metal")
			box(root,Vector3(0,h*.96,0),Vector3(w*.88,h*.012,d*.84),"457fc3","screen")
			box(root,Vector3(-w*.22,h*.969,0),Vector3(w*.34,h*.008,d*.79),"54b5c7")
			for row in range(2):
				for col in range(3):box(root,Vector3(w*(-.29+col*.29),h*.981,d*(-.15+row*.28)),Vector3(w*.15,h*.008,d*.12),["ffd786","eef6ef","e99094"][col])
			box(root,Vector3(0,h*.99,-d*.38),Vector3(w*.13,h*.008,d*.025),"202e42")
		"calculator":
			bevel_box(root,Vector3(0,h*.49,0),Vector3(w*.98,h*.94,d*.96),"394957","plastic")
			box(root,Vector3(0,h*.97,-d*.31),Vector3(w*.77,h*.008,d*.22),"b6cc99","screen")
			text_top(root,"123.45",Vector3(0,h*.984,-d*.31),w*.66,"334732")
			for row in range(3):
				for col in range(4):
					box(root,Vector3(w*(-.30+col*.20),h*.975,d*(-.04+row*.16)),Vector3(w*.12,h*.008,d*.09),"ece6db" if col<3 else "e89446","plastic")
		"stapler":
			box(root,Vector3(0,h*.12,0),Vector3(w*.98,h*.23,d*.86),"343944","metal")
			box(root,Vector3(w*.06,h*.27,0),Vector3(w*.72,h*.09,d*.55),"bac6ce","metal")
			box(root,Vector3(-w*.34,h*.49,0),Vector3(w*.20,h*.65,d*.72),"943c49")
			var arm=box(root,Vector3(w*.03,h*.69,0),Vector3(w*.85,h*.29,d*.93),"d34b55","plastic")
			arm.rotation.z=-.10
			box(root,Vector3(w*.28,h*.72,0),Vector3(w*.23,h*.04,d*.74),"ed8080","plastic")
		"printer":
			# Stepped scanner lid, dark output mouth and an actual paper sheet.
			box(root,Vector3(0,h*.40,-d*.025),Vector3(w*.94,h*.70,d*.90),"edece4","plastic")
			box(root,Vector3(0,h*.09,-d*.025),Vector3(w*.96,h*.18,d*.92),"485361")
			box(root,Vector3(0,h*.79,-d*.06),Vector3(w*.98,h*.11,d*.85),"c4ced3","plastic")
			box(root,Vector3(-w*.07,h*.885,-d*.10),Vector3(w*.78,h*.08,d*.65),"273d4b","screen")
			box(root,Vector3(-w*.07,h*.942,-d*.10),Vector3(w*.83,h*.034,d*.69),"e8ebe6","plastic")
			box(root,Vector3(0,h*.40,d*.43),Vector3(w*.72,h*.19,d*.045),"26303a")
			box(root,Vector3(0,h*.28,d*.32),Vector3(w*.80,h*.045,d*.34),"526776")
			box(root,Vector3(-w*.03,h*.32,d*.30),Vector3(w*.57,h*.012,d*.38),"fffaf0","paper")
			for i in range(3):box(root,Vector3(-w*.03,h*.328,d*(.33+i*.04)),Vector3(w*.39,.0005,d*.008),"8aabc2")
			box(root,Vector3(w*.35,h*.852,d*.19),Vector3(w*.18,h*.015,d*.18),"227aa4","screen")
			box(root,Vector3(w*.35,h*.865,d*.34),Vector3(w*.08,h*.02,d*.055),"e9a743","plastic")
			for i in range(4):box(root,Vector3(w*.472,h*(.32+i*.06),-d*.12),Vector3(.001,h*.012,d*.25),"798c98")
		"desk_divider":
			# A freestanding fabric privacy screen, mounted all the way down to
			# the desk so its opaque tactical cover matches the visible panel.
			box(root,Vector3(0,h*.50,0),Vector3(w*.95,h*.96,d*.54),"6675a3","fabric")
			box(root,Vector3(0,h*.96,0),Vector3(w*.99,h*.055,d*.61),"354258")
			for side in [-1,1]:
				box(root,Vector3(side*w*.46,h*.50,0),Vector3(w*.035,h*.90,d*.64),"354258")
				box(root,Vector3(side*w*.37,h*.055,0),Vector3(w*.20,h*.10,d*.98),"354258")
			box(root,Vector3(-w*.20,h*.68,d*.285),Vector3(w*.31,h*.24,.001),"fff1a5")
			box(root,Vector3(w*.21,h*.43,d*.285),Vector3(w*.28,h*.33,.001),"ecb6b0")
			for i in range(3):box(root,Vector3(w*.21,h*(.35+i*.065),d*.287),Vector3(w*.20,h*.009,.001),"965b6e")
			cylinder(root,Vector3(-w*.20,h*.80,d*.29),w*.018,h*.008,"dca45e")
		"file_rack":
			# Upright folders in a weighted desktop organizer; books remain flat.
			box(root,Vector3(0,h*.06,0),Vector3(w*.97,h*.12,d*.96),"34404b")
			box(root,Vector3(0,h*.51,-d*.44),Vector3(w*.93,h*.82,d*.09),"46515e")
			for side in [-1,1]:box(root,Vector3(side*w*.45,h*.51,0),Vector3(w*.08,h*.82,d*.96),"46515e")
			for i in range(4):
				var x:float=w*(-.29+i*.19)
				var tall:float=h*(.72+.045*(i%3))
				var tint:String=["e2b854","db7355","559dac","879a55"][i]
				box(root,Vector3(x,h*.12+tall*.5,0),Vector3(w*.16,tall,d*.79),tint)
				box(root,Vector3(x,h*.22,d*.405),Vector3(w*.11,h*.12,.001),"e9e4d4")
			box(root,Vector3(0,h*.11,d*.49),Vector3(w*.82,h*.10,.001),"384e55")
	batch(root)
static func build_closed_book(root:Node3D,w:float,d:float,h:float,kind:String):
	var jacket:String="8a354e" if kind=="novel" else "df8343"
	box(root,Vector3(0,h*.49,0),Vector3(w*.92,h*.85,d*.90),"f0e4c8","paper")
	for y in [.03,.96]:box(root,Vector3(0,h*y,0),Vector3(w*.98,h*.045,d*.98),jacket,"fabric")
	box(root,Vector3(-w*.465,h*.5,0),Vector3(w*.055,h*.96,d*.98),jacket,"fabric")
	for i in range(3):box(root,Vector3(0,h*(.26+i*.20),d*.451),Vector3(w*.90,h*.012,.0005),"c8b795")
	if kind=="novel":
		printed_cover_top(root,w*.76,d*.73,h*.988)
		box(root,Vector3(0,h*.993,-d*.32),Vector3(w*.90,.0005,d*.23),"8a354e")
		text_top(root,"恒大传奇",Vector3(0,h*.999,-d*.32),w*.74,"ffedc4")
		box(root,Vector3(w*.27,h*.18,d*.47),Vector3(w*.07,h*.02,d*.06),"be984e","fabric")
	else:
		box(root,Vector3(0,h*.988,d*.12),Vector3(w*.83,.0005,d*.48),"274f72")
		for i in range(6):box(root,Vector3(w*(-.32+i*.127),h*.994,d*(.12-.02*(i%3))),Vector3(w*.085,.0005,d*(.21+.06*(i%3))),"ffe4a9")
		text_top(root,"纸上城市",Vector3(0,h*.999,-d*.29),w*.74,"fff0d4")
# Merge decorative geometry by shared material. No per-frame asset logic.
static func batch(root:Node3D):
	var groups:Dictionary={}
	for child in root.find_children("*","MeshInstance3D",true,false):
		var mat=child.material_override
		if mat==null:continue # Keep the imported model's authored surface materials.
		if mat is StandardMaterial3D and mat.albedo_texture!=null:continue # Retain cover UVs.
		if not groups.has(mat):groups[mat]=SurfaceTool.new();groups[mat].begin(Mesh.PRIMITIVE_TRIANGLES)
		var transform=child.transform;var parent=child.get_parent()
		while parent!=root:transform=parent.transform*transform;parent=parent.get_parent()
		# SurfaceTool append_from mixes index buffers incorrectly when an
		# unindexed custom mesh precedes an indexed BoxMesh. Normalize first:
		# otherwise the custom surface vanishes when the group's indices appear.
		var mesh:Mesh=child.mesh
		var indices=mesh.surface_get_arrays(0)[Mesh.ARRAY_INDEX]
		if indices==null or indices.is_empty():
			var indexed=SurfaceTool.new();indexed.create_from(mesh,0);indexed.index();mesh=indexed.commit()
		groups[mat].append_from(mesh,0,transform)
		child.get_parent().remove_child(child);child.free()
	for mat in groups:
		var node=MeshInstance3D.new();node.mesh=groups[mat].commit();node.material_override=mat;root.add_child(node)

