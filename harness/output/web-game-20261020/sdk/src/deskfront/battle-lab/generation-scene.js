/* Isometric geometry, not guessed game art. All X/Z footprints come from saved records. */
// One gun glyph per saved infantry deployment. Fixed orientation is symbolic,
// not observed aiming; the anchor and assembly timing remain unchanged.
function drawInfantry(c,foot,width,color){
 c.save();c.translate(foot[0],foot[1]-5);c.scale(width/28,width/28);
 c.beginPath();
 // Stock, receiver, handguard and barrel, with a distinct grip and magazine.
 const points=[[-13,-6],[-8,-5],[-6,-8],[5,-8],[5,-10],[8,-10],[8,-8],[14,-8],[14,-5],[5,-5],[3,-2],[2,3],[-2,2],[-2,-2],[-5,-2],[-7,3],[-10,2],[-8,-3],[-10,-3],[-13,0]];
 points.forEach((p,i)=>i?c.lineTo(...p):c.moveTo(...p));c.closePath();
 c.lineJoin='round';c.strokeStyle='#101811';c.lineWidth=3.5;c.stroke();c.fillStyle=color;c.fill();
 c.beginPath();c.moveTo(-4,-6);c.lineTo(5,-6);c.strokeStyle='#edf0da';c.lineWidth=1;c.stroke();
 c.restore();
}
export function drawGeneration(canvas,scene,{abstract=false,animate=false,time=30,view={scale:1,x:0,y:0}}={}) {
  const box=canvas.getBoundingClientRect(),w=Math.max(1,box.width),h=Math.max(1,box.height),ratio=Math.min(devicePixelRatio||1,2);
  if(canvas.width!==Math.round(w*ratio)||canvas.height!==Math.round(h*ratio)){canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);}
  const c=canvas.getContext('2d');c.setTransform(ratio,0,0,ratio,0,0);c.clearRect(0,0,w,h);
  c.fillStyle=abstract?'#171e18':'#29372e';c.fillRect(0,0,w,h);
  if(!scene||scene.missing){c.fillStyle='#b8c1b0';c.textAlign='center';c.font='18px system-ui';c.fillText(scene?.note||'尚无已保存的几何布局',w/2,h/2);return;}
  c.translate(w/2+(view.x||0),h/2+(view.y||0));c.scale(view.scale||1,view.scale||1);c.translate(-w/2,-h/2);
  const g=scene.geometry,covers=g.covers||[],floors=g.floors||[],paths=[scene.routes?.main||[],scene.routes?.flank||[]];
  const bounds=[];
  for(const p of covers){bounds.push([p[0]-p[2]/2,p[1]-p[3]/2],[p[0]+p[2]/2,p[1]+p[3]/2]);}
  for(const p of floors)bounds.push([p[0],p[1]],[p[2],p[3]]);
  for(const path of paths)bounds.push(...path);
  for(const u of scene.units||[])bounds.push(u.position);
  if(!bounds.length)return;
  const minX=(scene.bounds?.[0]??Math.min(...bounds.map(p=>p[0])))-.04,maxX=(scene.bounds?.[2]??Math.max(...bounds.map(p=>p[0])))+.04,minZ=(scene.bounds?.[1]??Math.min(...bounds.map(p=>p[1])))-.04,maxZ=(scene.bounds?.[3]??Math.max(...bounds.map(p=>p[1])))+.04;
  const midX=(minX+maxX)/2,midZ=(minZ+maxZ)/2;
  const raw=(x,z,y=0)=>[(x-midX)*.88-(z-midZ)*.56,(x-midX)*.40+(z-midZ)*.59-y];
  const corners=[[minX,minZ],[minX,maxZ],[maxX,minZ],[maxX,maxZ]].map(p=>raw(...p));
  const x0=Math.min(...corners.map(p=>p[0])),x1=Math.max(...corners.map(p=>p[0])),z0=Math.min(...corners.map(p=>p[1]))-.42,z1=Math.max(...corners.map(p=>p[1]))+.36;
  const scale=Math.min((w-28)/(x1-x0),(h-32)/(z1-z0));
  const point=(x,z,y=0)=>{const p=raw(x,z,y);return[(p[0]-(x0+x1)/2)*scale+w/2,(p[1]-(z0+z1)/2)*scale+h/2];};
  const poly=(pts,fill,stroke='#353d32')=>{c.beginPath();pts.forEach((p,i)=>i?c.lineTo(...p):c.moveTo(...p));c.closePath();c.fillStyle=fill;c.fill();c.strokeStyle=stroke;c.lineWidth=.6;c.stroke();};
  const cuboid=(x,z,sx,sz,height,colors,lift=0,angle=0)=>{const p=[[x-sx/2,z-sz/2],[x+sx/2,z-sz/2],[x+sx/2,z+sz/2],[x-sx/2,z+sz/2]].map(p=>[x+(p[0]-x)*Math.cos(angle)-(p[1]-z)*Math.sin(angle),z+(p[0]-x)*Math.sin(angle)+(p[1]-z)*Math.cos(angle)]),base=p.map(p=>point(...p,lift)),top=p.map(p=>point(...p,height+lift));poly([base[1],base[2],top[2],top[1]],colors[1]);poly([base[2],base[3],top[3],top[2]],colors[2]);poly(top,colors[0]);};
  const slabs=scene.tiles||((floors.length?floors:[[minX,minZ,maxX,maxZ]]).map(rect=>({rect,progress:1})));
  for(const tile of [...slabs].sort((a,b)=>(a.rect[0]+a.rect[1])-(b.rect[0]+b.rect[1]))){const p=tile.rect,f=tile.progress;if(f<=0)continue;const x=(p[0]+p[2])/2,z=(p[1]+p[3])/2,lift=tile.lift??0,sx=p[2]-p[0]-.008,sz=p[3]-p[1]-.008;
    const top=(tile.col+tile.row)%2?'#78816e':'#6c7766';
    for(const dx of [-1,1])for(const dz of [-1,1])cuboid(x+dx*(sx/2-.035),z+dz*(sz/2-.035),.022,.022,.27,['#626b59','#35422f','#46523d'],-.30+lift);
    cuboid(x,z,sx,sz,.035,abstract?[top,'#414b3d','#56604c']:['#d4b879','#887349','#a58b56'],-.035+lift);
  }
  const line=(path,color)=>{if(path.length<2)return;const lengths=path.slice(1).map((p,i)=>Math.hypot(p[0]-path[i][0],p[1]-path[i][1]));let remaining=lengths.reduce((a,b)=>a+b,0)*(scene.routeProgress??1);c.beginPath();c.moveTo(...point(...path[0],.015));for(let i=1;i<path.length;i++){const f=lengths[i-1]?Math.min(1,Math.max(0,remaining/lengths[i-1])):1;if(!f)break;const a=path[i-1],b=path[i];c.lineTo(...point(a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f,.015));remaining-=lengths[i-1];}c.strokeStyle='#101b17';c.lineWidth=abstract?5:7;c.lineCap='round';c.stroke();c.strokeStyle=color;c.lineWidth=abstract?2.8:4;c.stroke();};
  if(scene.showRoutes!==false){line(paths[0],abstract?'#84b2cb':'#6fba93');line(paths[1],abstract?'#b5a26a':'#d5af59');}
  const sorted=(scene.props||covers.map(row=>({row,lift:0,scale:1}))).slice().sort((a,b)=>(a.row[0]+a.row[1])-(b.row[0]+b.row[1]));
  if(scene.showCovers!==false)sorted.forEach(item=>{const p=item.row,height=p[5]*item.scale,lift=item.lift;
    const palettes=abstract?['#b4baac','#727d6b','#919b84']:/wall|partition|folder/.test(p[4])?['#88717f','#59444f','#6b5261']:/laptop|printer/.test(p[4])?['#b9c3b7','#687f80','#849b97']:['#c6b98d','#877f5a','#a29771'];
    cuboid(p[0],p[1],p[2]*item.scale,p[3]*item.scale,height,palettes,lift,item.rotation||0);
  });
  let drawnInfantry=0;
  if(scene.showUnits!==false)for(const u of scene.units||[]){const age=Math.max(0,time-u.start),f=Math.min(1,age/.75),smooth=f*f*(3-2*f),fall=.34*(1-smooth),ground=point(...u.position,.01),color=u.faction==='green'?'#afd98a':'#f1a18c';
    if(age<1.35){c.beginPath();c.ellipse(ground[0],ground[1],(9+age*5),4+age*2,0,0,Math.PI*2);c.strokeStyle=color;c.lineWidth=2;c.globalAlpha=1-age/1.35;c.stroke();c.globalAlpha=1;}
    if(u.kind==='infantry'){
      const height=Math.max(26,Math.min(30,scale*.14)),foot=point(...u.position,.014+fall);
      c.beginPath();c.ellipse(ground[0],ground[1],height*.30,height*.11,0,0,Math.PI*2);c.fillStyle='#172017';c.fill();c.strokeStyle=color;c.lineWidth=1.5;c.stroke();
      drawInfantry(c,foot,height,color);drawnInfantry++;
    }else cuboid(u.position[0],u.position[1],u.kind==='tank'?.105:.05,u.kind==='tank'?.065:.05,.045,[color,'#455943','#6d8363'],.015+fall);
  }
  canvas.dataset.infantry=String(drawnInfantry);canvas.dataset.infantryStyle='faction-gun';
  if(abstract&&time>=18.4&&g.entry){const p=point(...g.entry,.02);c.fillStyle='#b4d695';c.beginPath();c.arc(...p,5,0,7);c.fill();}
  if(abstract&&time>=18.4&&g.exit){const p=point(...g.exit,.02);poly([[p[0],p[1]-6],[p[0]+5,p[1]],[p[0],p[1]+6],[p[0]-5,p[1]]],'#d5bf82');}
  canvas.dataset.tiles=String(slabs.filter(t=>t.progress>0).length);canvas.dataset.props=String(sorted.length);canvas.dataset.units=String(scene.units?.length||0);
}

/* Local inspection only. Never issues game, navigation or model requests. */
export function clampView(view, width, height, content = {width, height}) {
  const scale = Math.max(1, Math.min(4, Number(view.scale) || 1));
  const x = Math.max(0, (content.width * scale - width) / 2);
  const y = Math.max(0, (content.height * scale - height) / 2);
  return {scale, x: Math.max(-x, Math.min(x, Number(view.x) || 0)) || 0, y: Math.max(-y, Math.min(y, Number(view.y) || 0)) || 0};
}

export class ViewportControls {
  constructor({viewport, prefix, fullscreen, onChange, contentSize}) {
    this.viewport = viewport; this.fullscreen = fullscreen; this.onChange = onChange;
    this.contentSize = contentSize; this.view = {scale:1,x:0,y:0}; this.enabled = false; this.drag = null;
    this.buttons = Object.fromEntries(['in','out','reset','fullscreen'].map(key => [key,document.getElementById(prefix+key)]));
    this.buttons.in.onclick = () => this.zoom(this.view.scale+.25);
    this.buttons.out.onclick = () => this.zoom(this.view.scale-.25);
    this.buttons.reset.onclick = () => this.reset();
    this.buttons.fullscreen.onclick = async () => {
      if (!this.enabled) return;
      try { if(document.fullscreenElement === fullscreen) await document.exitFullscreen(); else await fullscreen.requestFullscreen(); }
      catch { this.buttons.fullscreen.title = '浏览器未允许全屏，仍可用放大和拖动查看。'; }
    };
    viewport.addEventListener('wheel',e => {
      if(!this.enabled) return; e.preventDefault();
      this.zoom(this.view.scale+(e.deltaY<0?.25:-.25),e.clientX,e.clientY);
    },{passive:false});
    viewport.addEventListener('pointerdown',e => {
      if(!this.enabled || this.view.scale<=1 || e.button!==0) return;
      this.drag = {id:e.pointerId,x:e.clientX,y:e.clientY,px:this.view.x,py:this.view.y};
      viewport.setPointerCapture(e.pointerId); viewport.classList.add('is-dragging');
    });
    viewport.addEventListener('pointermove',e => {
      if(!this.drag || this.drag.id!==e.pointerId) return;
      this.view.x=this.drag.px+e.clientX-this.drag.x; this.view.y=this.drag.py+e.clientY-this.drag.y; this.paint();
    });
    for(const name of ['pointerup','pointercancel','lostpointercapture']) viewport.addEventListener(name,() => {
      this.drag=null; viewport.classList.remove('is-dragging');
    });
    viewport.addEventListener('keydown',e => {
      if(e.target!==viewport || !this.enabled) return;
      if(['+','=','-','0','Home'].includes(e.key)) {
        e.preventDefault(); if(['0','Home'].includes(e.key))this.reset(); else this.zoom(this.view.scale+(e.key==='-'?-.25:.25));
      } else if(e.key.startsWith('Arrow') && this.view.scale>1) {
        e.preventDefault(); this.view.x+=e.key==='ArrowLeft'?40:e.key==='ArrowRight'?-40:0;
        this.view.y+=e.key==='ArrowUp'?40:e.key==='ArrowDown'?-40:0; this.paint();
      }
    });
    document.addEventListener('fullscreenchange',() => {this.buttons.fullscreen.textContent=document.fullscreenElement===fullscreen?'退出全屏':'全屏';this.paint();});
    new ResizeObserver(() => this.paint()).observe(viewport);
    this.paint();
  }
  setEnabled(enabled) { this.enabled=!!enabled; this.paint(); }
  zoom(next,clientX,clientY) {
    if(!this.enabled) return;
    const rect=this.viewport.getBoundingClientRect(),scale=Math.max(1,Math.min(4,next)),factor=scale/this.view.scale;
    const x=Number.isFinite(clientX)?clientX-rect.left-rect.width/2:0,y=Number.isFinite(clientY)?clientY-rect.top-rect.height/2:0;
    this.view={scale,x:x+(this.view.x-x)*factor,y:y+(this.view.y-y)*factor};this.paint();
  }
  reset() {this.view={scale:1,x:0,y:0};this.paint();}
  paint() {
    const rect=this.viewport.getBoundingClientRect(),size=this.contentSize?.(rect)||{width:rect.width,height:rect.height};
    this.view=clampView(this.view,rect.width,rect.height,size);
    this.buttons.reset.textContent='还原 '+Math.round(this.view.scale*100)+'%';
    for(const b of Object.values(this.buttons))b.disabled=!this.enabled;
    this.buttons.out.disabled=!this.enabled||this.view.scale<=1;this.buttons.in.disabled=!this.enabled||this.view.scale>=4;
    this.viewport.classList.toggle('is-zoomed',this.enabled&&this.view.scale>1);
    this.onChange?.(this.view);
  }
}
