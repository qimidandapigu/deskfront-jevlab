import {point,remainingRoute} from './lab-model.js';
export const paths={
 flag:'M5 22V2m0 1h14l-4 5 4 5H5',point:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
 arrow:'M3 12h18m-7-6 7 6-7 6',support:'M2 12h5m10 0h5M8 7l4 2 4-2v6c0 3-4 5-4 5s-4-2-4-5Z',
 flank:'M3 20V9a5 5 0 0 1 5-5h12m-5-3 5 3-5 4M11 12h5v8h-5Z',
 keep:'M5 8a8 8 0 1 1-1 8M5 3v5h5M10 12h6',
 hold:'M5 3h14v8c0 5-7 10-7 10S5 16 5 11ZM9 12h6',
 revise:'M3 7h17m-4-4 4 4-4 4M21 17H4m4-4-4 4 4 4',
 gather:'M4 4l5 5m-5 0h5V4m11 16-5-5m5 0h-5v5M20 4l-5 5m0-5v5h5M4 20l5-5m-5 0h5v5',
 recover:'M4 12h4l3-7 3 14 3-7h4',
 person:'M16 6a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM5 22v-3a7 7 0 0 1 14 0v3Z',
 eye:'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
 list:'M5 3h14v19H5ZM8 7h8M8 11h8M8 15h8M8 19h5',
 chip:'M6 6h12v12H6Zm4 4h4v4h-4ZM9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4',
 play:'m7 3 14 9-14 9Z',feedback:'M4 18v-6m7 6V8m7 10V3M3 22h19',aim:'M12 2v4m0 12v4M2 12h4m12 0h4M19 12a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z',
 bound:'M5 5a2 2 0 1 1 0 4 2 2 0 0 1 0-4Zm7 0a2 2 0 1 1 0 4 2 2 0 0 1 0-4ZM2 17v-4a3 3 0 0 1 6 0v4m1 0v-4a3 3 0 0 1 6 0v4m2-6h6m-3-3 3 3-3 3',
 rifle:'M2 9h20v3H9l-2 8H4l2-8H2Zm12-2v8m4-8v5',smg:'M2 8h17v4H9l-3 6H3l3-6H2Zm9 4v7h4v-7m4-4h3',
 rocket:'M2 8h17l3 2-3 2H2Zm8 4v7h3v-7m-8 0-2 5',mortar:'m8 4 4 1-5 13-4-1Zm2 8 9 8m-9-8 3 10M1 22h9m5 0h7',
 tank:'M3 14h18l2 5-3 3H4l-3-3Zm4 0V8h10v6m-4-6V3m0 5h10'
};
export function icon(key){return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="'+(paths[key]||paths.arrow)+'"/></svg>';}
export function optionIcon(kind){return({bound:'bound',flank:'flank',cover:'support',hold:'hold',regroup:'gather',recover:'recover',revise_order:'revise',continue_order:'keep',continue_role:'keep',report_blocked:'aim',hold_fire:'aim',aim:'aim'})[kind]||'arrow';}
/* FAST_MAP_BACKGROUND */
const mapBackgrounds=new WeakMap();
export function drawMap(canvas,m,{faction='green',selectedUnit='',command=null,squad=null,coordinates={model:false,scale:1}}={}){
 const ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height,hits=[];ctx.clearRect(0,0,w,h);ctx.fillStyle='#19261d';ctx.fillRect(0,0,w,h);
 const cssWidth=canvas.getBoundingClientRect().width||w,uiScale=w/cssWidth,fontPx=16*uiScale;
 if(!m?.bounds?.every(Number.isFinite)){ctx.fillStyle='#b9c7b4';ctx.font=`${18*uiScale}px sans-serif`;ctx.textAlign='center';ctx.fillText('等待本关真实地图',w/2,h/2);return hits;}
 const b=m.bounds,rangeX=b[2]-b[0],rangeY=b[3]-b[1];if(rangeX<=0||rangeY<=0)return hits;
 const left=Math.max(54,fontPx*3.5),right=fontPx*1.4,top=fontPx*2.6,bottom=fontPx*1.5;
 const scale=Math.min((w-left-right)/rangeX,(h-top-bottom)/rangeY),dx=left+(w-left-right-rangeX*scale)/2,dy=top+(h-top-bottom-rangeY*scale)/2;
 const xy=p=>[dx+(p[0]-b[0])*scale,dy+(p[1]-b[1])*scale],inside=p=>point(p)&&p[0]>=b[0]&&p[0]<=b[2]&&p[1]>=b[1]&&p[1]<=b[3];
 const backgroundKey=JSON.stringify([w,h,uiScale,b,coordinates.model,coordinates.scale,m.terrainKey||m.covers]);
 const background=mapBackgrounds.get(canvas);
 if(background?.key===backgroundKey)ctx.drawImage(background.image,0,0);
 else {
 ctx.strokeStyle='#304134';ctx.fillStyle='#afbea9';ctx.font=`${fontPx}px sans-serif`;ctx.textAlign='center';
 const axisScale=coordinates.model?coordinates.scale:1;
 const axis=(lo,hi,start,length,horizontal)=>{
  const count=Math.max(2,Math.floor(length/uiScale/70)),raw=(hi-lo)*axisScale/count;
  const magnitude=10**Math.floor(Math.log10(Math.max(raw,.000001))),step=coordinates.model?Math.max(1,([1,2,5,10].find(n=>n*magnitude>=raw)||10)*magnitude):raw;
  const first=coordinates.model?Math.ceil((lo*axisScale-1e-6)/step)*step:lo;
  for(let v=first,n=0;v<=hi*axisScale+1e-6&&n<100;n++,v=first+n*step){
   const offset=(v/axisScale-lo)/(hi-lo)*length,position=start+offset;
   ctx.beginPath();if(horizontal){ctx.moveTo(position,dy);ctx.lineTo(position,dy+rangeY*scale);}else{ctx.moveTo(dx,position);ctx.lineTo(dx+rangeX*scale,position);}ctx.stroke();
   const label=coordinates.model?String(Math.round(v)):v.toFixed(2);
   ctx.textAlign=horizontal?'center':'right';ctx.fillText(label,horizontal?position:dx-fontPx*.4,horizontal?dy-fontPx*.6:position+fontPx*.3);
  }
 };
 axis(b[0],b[2],dx,rangeX*scale,true);axis(b[1],b[3],dy,rangeY*scale,false);ctx.textAlign='center';
 ctx.fillText(coordinates.model?'模型格子坐标':'世界坐标 · 模型格号绑定缺失',w/2,fontPx*1.15);ctx.fillText('X',w-fontPx*.7,fontPx*1.15);ctx.fillText('Y',fontPx*.6,fontPx*1.15);
 ctx.save();ctx.beginPath();ctx.rect(dx,dy,rangeX*scale,rangeY*scale);ctx.clip();
 const seen=new Set();for(const c of m.covers||[]){if(!point(c.position)||!point(c.size)||seen.has(c.id))continue;seen.add(c.id);ctx.save();ctx.translate(...xy(c.position));ctx.rotate(-(c.yaw||0));ctx.fillStyle=c.height>.12?'#56664d':'#778567';ctx.fillRect(-c.size[0]*scale/2,-c.size[1]*scale/2,c.size[0]*scale,c.size[1]*scale);ctx.restore();}
 ctx.restore();
 const image=canvas.ownerDocument.createElement('canvas');image.width=w;image.height=h;
 image.getContext('2d',{alpha:false}).drawImage(canvas,0,0);mapBackgrounds.set(canvas,{key:backgroundKey,image});
 }
 ctx.save();ctx.beginPath();ctx.rect(dx,dy,rangeX*scale,rangeY*scale);ctx.clip();
 const units=(m.units||[]).filter(u=>!(u.hp<=0)&&inside(u.position)),team=units.filter(u=>u.faction===faction);
 if(m.coordinateFrame==='native-world')for(const u of team){const route=remainingRoute(u,m.actualRoutes?.find(r=>r.unitId===u.id));if(route.length<2)continue;ctx.strokeStyle='#8bd5ab';ctx.lineWidth=2.3;ctx.beginPath();route.map(xy).forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.stroke();const end=xy(route.at(-1)),prev=xy(route.at(-2)),a=Math.atan2(end[1]-prev[1],end[0]-prev[0]);ctx.beginPath();ctx.moveTo(end[0]-9*Math.cos(a-.5),end[1]-9*Math.sin(a-.5));ctx.lineTo(...end);ctx.lineTo(end[0]-9*Math.cos(a+.5),end[1]-9*Math.sin(a+.5));ctx.stroke();}
 if(m.coordinateFrame==='native-world'&&squad){
  for(const link of squad.data?.cooperation||[])for(const sid of link.supporter_ids||[])for(const mid of link.assisted_member_ids||[]){const a=team.find(u=>u.id===sid),z=team.find(u=>u.id===mid);if(!a||!z)continue;ctx.strokeStyle='#86b8f2';ctx.lineWidth=1.8;ctx.setLineDash([6,6]);ctx.beginPath();ctx.moveTo(...xy(a.position));ctx.lineTo(...xy(z.position));ctx.stroke();ctx.setLineDash([]);}
  const taskPoints=new Set();for(const[uid,a]of Object.entries(squad.data?.assignments||{})){const u=team.find(u=>u.id===uid),p=point(a.position);if(!u||!inside(p)||Math.hypot(p[0]-u.position[0],p[1]-u.position[1])*scale<5)continue;const pointKey=p.map(v=>Math.round(v*1e6)).join(',');if(taskPoints.has(pointKey))continue;taskPoints.add(pointKey);ctx.strokeStyle='#86b8f2';ctx.lineWidth=2;ctx.beginPath();ctx.arc(...xy(p),8,0,Math.PI*2);ctx.stroke();}
 }
 const goal=m.coordinateFrame==='native-world'&&inside(command?.data?.position)?command.data.position:m.objective;
 if(inside(goal)){const p=xy(goal);ctx.strokeStyle='#e3c478';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(p[0],p[1]+5);ctx.lineTo(p[0],p[1]-19);ctx.lineTo(p[0]+15,p[1]-15);ctx.lineTo(p[0],p[1]-9);ctx.stroke();}
 for(const u of units){const p=xy(u.position),color=u.faction==='green'?'#a1dc9d':u.faction==='red'||u.faction==='contact'?'#f0a08d':'#c1cabb';ctx.fillStyle='#142019';ctx.strokeStyle=color;ctx.lineWidth=u.id===selectedUnit?3:1.5;ctx.beginPath();if(u.faction==='red'||u.faction==='contact'){ctx.moveTo(p[0],p[1]-15);ctx.lineTo(p[0]+15,p[1]+12);ctx.lineTo(p[0]-15,p[1]+12);ctx.closePath();}else ctx.arc(...p,14,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.save();ctx.translate(p[0]-9,p[1]-9);ctx.scale(.75,.75);ctx.stroke(new Path2D(paths[u.kind==='tank'?'tank':u.weapon||u.kind]||paths.person));ctx.restore();if(u.faction===faction)hits.push({id:u.id,p});}
 for(const u of units){const pulse=firingPulse(u,m);if(!pulse)continue;
  const p=xy(u.position),color=u.faction==='green'?'#a1dc9d':'#f0a08d',r=18+3*pulse;
  ctx.save();ctx.strokeStyle=color;ctx.lineWidth=2.5;ctx.globalAlpha=.55+.45*pulse;
  for(let n=0;n<4;n++){const a=Math.PI/4+n*Math.PI/2;ctx.beginPath();ctx.moveTo(p[0]+r*Math.cos(a),p[1]+r*Math.sin(a));ctx.lineTo(p[0]+(r+6)*Math.cos(a),p[1]+(r+6)*Math.sin(a));ctx.stroke();}ctx.restore();
 }
 ctx.restore();return hits;
}
/* WEB_MAP_STABILITY */
/* Read-only presentation state. Transport health does not invalidate pixels
 * already rendered by this same verified game instance. */
export function frameDecision(frame,{instanceId,runId,previous=null}={}){
  if(!frame||frame.instanceId!==instanceId)return 'ignore';
  if(frame.failure==='instance_conflict')return 'clear';
  if(!runId||frame.runId!==runId)return 'clear';
  if(frame.map?.runId!==frame.runId||frame.map?.time!==frame.time||
     !Number.isFinite(frame.tick)||!Number.isFinite(frame.time)||
     !Array.isArray(frame.map?.bounds)||frame.map.bounds.length!==4||
     !frame.map.bounds.every(Number.isFinite)||frame.map.bounds[2]<=frame.map.bounds[0]||
     frame.map.bounds[3]<=frame.map.bounds[1]||
     (frame.stage!=null&&frame.map.stage!==frame.stage))return 'ignore';
  if(previous?.boot===frame.boot&&previous.runId===frame.runId&&frame.tick<previous.tick)return 'ignore';
  return 'accept';
}

export function coordinateBinding(){
  let key='',binding=null;
  return {
    resolve(map,coordinates,faction){
      const next=JSON.stringify([map?.runId,map?.stage,faction,map?.coordinateFrame,map?.bounds]);
      if(next!==key){key=next;binding=null;}
      // A navigation revision changes paths, not the verified world/grid scale.
      if(coordinates.model)binding=coordinates;
      return coordinates.model?coordinates:binding||coordinates;
    },
    reset(){key='';binding=null;}
  };
}

export function frameScheduler(draw,request=callback=>requestAnimationFrame(callback)){
  let pending=false;
  return ()=>{
    if(pending)return;
    pending=true;
    request(()=>{pending=false;draw();});
  };
}

// A short indication of native firing, not an inferred hit or aim solution.
export function firingPulse(unit,map){
  const age=map.time-unit.last_shot_at;
  return !map.paused&&Number.isFinite(unit.last_shot_at)&&unit.last_shot_at>=0&&age>=0&&age<.14?1-age/.14:0;
}
