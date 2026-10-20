/* Battle Lab map and command cards. Read-only: no commands, models or path queries. */
let selectedUnit='',mapState=null,mapHits=[],unitMenuKey='',mapScope='';
const mapColors={green:'#b5d580',blue:'#83b5cf',red:'#f08d78',contact:'#f08d78',unknown:'#c4c9bb'};

// Selection/submission never changes the last confirmed assignment.
function squadOrderState(rows){
 const plans=new Map();
 for(const event of rows){
  const d=event.data||{};if(!d.orderId)continue;
  const key=(d.squadId||'')+'|'+d.orderId;
  let p=plans.get(key);if(!p){p={key,firstIndex:event.index,event,accepted:null};plans.set(key,p);}
  p.event=event;
  if(d.status==='accepted'&&!p.accepted)p.accepted=event;
 }
 const accepted=[...plans.values()].filter(p=>p.accepted).sort((a,b)=>a.accepted.index-b.accepted.index);
 const last=accepted.at(-1)||null;
 const newest=[...plans.values()].sort((a,b)=>a.firstIndex-b.firstIndex).at(-1);
 const proposal=newest&&!newest.accepted&&(!last||newest.firstIndex>last.firstIndex)?newest.event:null;
 const assignments=new Map();
 for(const p of accepted)for(const [uid,assignment]of Object.entries(p.accepted.data.assignments||{}))assignments.set(uid,{event:p.accepted,assignment});
 return{accepted:last?.accepted||null,proposal,assignments};
}
function squadTacticName(value){
 return({advance:'直接推进',bound:'交替推进',flank:'侧翼包抄',cover:'火力掩护',hold:'区域守备',regroup:'集结重整'})[value]||label(value);
}
function renderSquadTactic(state,enabled){
 const panel=$('debugSquad');if(!panel)return;
 panel.hidden=!enabled;panel.replaceChildren();if(!enabled)return;
 const heading=node('h3','JEV · 小队战术');heading.append(node('span',($('debugFaction').value==='red'?'红方':'绿方')+'全队'));panel.append(heading);
 const e=state.accepted;
 const shown=e||state.proposal;
 if(shown&&typeof recordedOrderTile==='function')panel.append(recordedOrderTile('squad',{key:shown.data.intent,status:shown.data.status,time:shown.time,unit:''}));
 if(!e)panel.append(node('p','尚无已接受方案','caption'));
 if(e){
  const counts={};for(const a of Object.values(e.data.assignments||{}))if(a.role)counts[a.role]=(counts[a.role]||0)+1;
  const roles=Object.entries(counts).map(([role,n])=>n+'人'+label(role)).join(' · ');
  if(roles)panel.append(node('p',roles,'caption'));
 }
 if(state.proposal&&e){
  const p=state.proposal,status=p.data.status==='rejected'?'未接受':p.data.status==='unknown'?'回执未明确':'待确认';
  panel.append(node('p','新方案：'+squadTacticName(p.data.intent)+' · '+status+' '+time(p.time),'squad-tactic-proposal'));
 }
}

function renderMapAndDebug(visible,level,faction){
 const current=e=>(!level||e.index>level.index)&&e.faction===faction;
 const samples=visible.filter(e=>e.kind==='map'&&e.faction===faction&&(!level||(level.data.level!=null&&e.data.stage!=null?e.data.stage===level.data.level:e.index>level.index))&&e.data.time<=cursor);
 const sample=samples.filter(e=>e.data.source==='native_snapshot').at(-1)||samples.at(-1);
 const live=data.mode==='live'&&follow&&Math.abs(cursor-(data.live?.gameTime??-1))<3;
 mapState=live?data.live?.map:sample?.data;
 const orders=visible.filter(e=>e.kind==='squad'&&current(e));
 const decisions=visible.filter(e=>e.kind==='soldier'&&current(e));
 const squadState=squadOrderState(orders),latestOrders=squadState.assignments,latestDecisions=new Map();
 const personalChoices=typeof tacticalOrdersState==='function'?tacticalOrdersState(visible,cursor,faction,level).personal:[];
 for(const r of personalChoices)latestDecisions.set(r.unit,r);
 const units=(mapState?.units||[]).filter(u=>u.faction===faction&&(u.hp===undefined||u.hp>0)),ids=[...new Set([...units.map(u=>u.id),...latestOrders.keys(),...latestDecisions.keys()])].sort();
 const scope=JSON.stringify([data.sessionId??data.id??'',mapState?.runId??'',mapState?.stage??level?.index??'',faction,mapState?.navigationRevision??'']);
 if(scope!==mapScope){selectedUnit='';mapScope=scope;}
 const selectableIds=units.map(u=>u.id).sort();
 if(selectedUnit&&!selectableIds.includes(selectedUnit))selectedUnit='';
 const side=faction==='green'?'绿方':'红方';$('debugFaction').value=faction;
 const menuKey=faction+'|'+selectableIds.join('|');if(menuKey!==unitMenuKey){unitMenuKey=menuKey;$('debugUnit').replaceChildren(node('option',side+'全部单位'));$('debugUnit').firstChild.value='';for(const uid of selectableIds){const option=node('option',uid);option.value=uid;$('debugUnit').append(option);}}
 $('debugUnit').value=selectedUnit;
 const enabled=$('debugToggle').checked;$('debugDecisions').hidden=!enabled;renderSquadTactic(squadState,enabled);
 put('mapMode',mapState?(live?'实时状态':(mapState.provenance==='native-verification'?'验证回放 ':mapState.source==='native_snapshot'?'记录 ':'历史观测 ')+time(mapState.time)):'等待本关观测');
 put('mapSource',mapState?(live||mapState.source==='native_snapshot'?'快照 · ':'实际请求观测 · ')+time(mapState.time)+' · 第 '+(mapState.stage??'—')+' 关'+(live||mapState.source==='native_snapshot'?' · 本关观战采样':' · '+(faction==='green'?'绿':faction==='red'?'红':'蓝')+'方视野采样，位置随采样更新')+(mapState.provenance==='native-verification'?' · 验证场景，非原对局':''):'当前时间点没有本关地图观测；不沿用上一关地图。');
 $('source-diagram').hidden=!mapState?.diagram;put('mapDiagram',mapState?.diagram||'暂无记录');
 put('debugStatus',mapState?(live?'执行状态 · ':'观测 '+time(mapState.time)+' · ')+side+' · '+'全部成员'+'；下方选择与回执截止 '+time(cursor):'等待本关观测；已有指令仍可核对。');
 const knownRoutes=units.map(u=>({unit:u,actual:mapState?.actualRoutes?.find(r=>r.unitId===u.id)})).filter(x=>x.actual);
 const routeCount=knownRoutes.filter(x=>remainingRoute(x.unit,x.actual).length>1).length,missing=units.length-knownRoutes.length;
 const routeStatus=routeCount?routeCount+'人有接下来要走的路线'+(missing?'；'+missing+'人未记录':'')+'。箭头为方向，空心圆为落点。':missing?(mapState?.source==='recorded_model_observation'?'这段历史未保存实际剩余路线。':'实际剩余路线未记录。'):'当前没有待走路线。';
 put('mapRouteStatus',!enabled?'路线显示已收起':!mapState?side+'全队 · 等待本关路线记录':side+'全队 · '+routeStatus);
 drawBattleMap(mapState,enabled,faction);
 if(!enabled)return;
 const openDetails=new Set([...$('debugDecisions').querySelectorAll('details[open]')].map(d=>d.dataset.unit));
 $('debugDecisions').replaceChildren();
 for(const uid of ids){
  const u=units.find(u=>u.id===uid),order=latestOrders.get(uid),choice=latestDecisions.get(uid),execution=mapState?.execution?.[uid],actual=mapState?.actualRoutes?.find(r=>r.unitId===uid);
  const card=node('div','','debug-unit'+(uid===selectedUnit?' selected':''));card.dataset.unit=uid;
  const weapon=u?label(u.kind==='tank'?'tank':u.weapon||u.kind):'单位';
  card.append(node('strong',weapon+(order?.assignment.role?' · '+label(order.assignment.role):' · 分工待确认')));
  const health=node('p','','member-health'),heart=document.createElementNS('http://www.w3.org/2000/svg','svg');heart.setAttribute('viewBox','0 0 24 24');heart.setAttribute('aria-hidden','true');heart.innerHTML='<path d="M20.8 4.6a5.4 5.4 0 0 0-7.6 0L12 5.8l-1.2-1.2a5.4 5.4 0 0 0-7.6 7.6L12 21l8.8-8.8a5.4 5.4 0 0 0 0-7.6Z"/>';
  health.append(heart,node('span',u?(typeof u.hp==='number'?'生命 '+u.hp+(u.max_hp?' / '+u.max_hp:''):'生命未记录'):'本次观测未包含该单位位置'));card.append(health);
  card.append(node('p','JEV · 最近个人选择','member-choice-label'));
  // Explain the role at the decision's own time, not a later reassignment.
  const decisionOrder=choice?squadOrderState(orders.filter(e=>e.index<=choice.event.index&&e.time<=choice.time)).assignments.get(uid):null;
  if(choice&&typeof recordedOrderTile==='function')card.append(recordedOrderTile('personal',{...choice,assignmentRole:decisionOrder?.assignment.role}));
  else card.append(node('p','暂无本兵记录','member-choice-empty'));
  const detailsNode=document.createElement('details');detailsNode.dataset.unit=uid;detailsNode.open=openDetails.has(uid);
  detailsNode.append(node('summary','编号与执行细节'),node('p',uid));card.append(detailsNode);
  if(u?.position)detailsNode.append(node('p','位置 ['+u.position.map(v=>v.toFixed(3)).join(', ')+']'));
  if(actual)detailsNode.append(node('p',actual.waypoints?.length?'待走路线 '+actual.waypoints.length+' 点'+(actual.next?' · 下一步 ['+actual.next.map(v=>v.toFixed(3)).join(', ')+']':''):'记录：没有待走路点'));
  else detailsNode.append(node('p','剩余路线未记录，不推断已经到位或原地驻守。'));
  if(order){detailsNode.append(node('p',squadTacticName(order.event.data.intent)+' · '+label(order.assignment.role)+' · 已接受 '+time(order.event.time)));
   detailsNode.append(node('small',(order.event.data.orderId||'')+' · 目标区 '+(order.assignment.region_id||'未记录')+(Array.isArray(order.assignment.route_positions)?' · 计划 '+order.assignment.route_positions.length+' 点':'')));}
  if(choice)detailsNode.append(node('p','个人选择状态：'+(tacticalStatuses[choice.status]||choice.status)+' · '+time(choice.time)));
  if(u?.lm_reason)detailsNode.append(node('small','指令依据：'+u.lm_reason));
  if(execution){const detail=[];if(execution.stationary_seconds!==undefined)detail.push('已静止 '+execution.stationary_seconds+' 秒');if(execution.fire_block_reason)detail.push('射击：'+execution.fire_block_reason);if(execution.coverExecution?.phase)detail.push('掩体状态：'+execution.coverExecution.phase);if(detail.length)detailsNode.append(node('p',detail.join(' · ')));}
  if(typeof u?.suppression==='number')detailsNode.append(node('p','压制 '+Math.round(u.suppression*100)+'% · 掩体 '+(u.cover_id||'未记录')+' · 目标 '+(u.target_id||'未记录')));
  $('debugDecisions').append(card);
 }
 if(!ids.length)$('debugDecisions').append(node('p','本关尚未收到逐兵指令记录。','caption'));
}

const validMapPoint=p=>Array.isArray(p)&&p.length>=2&&Number.isFinite(p[0])&&Number.isFinite(p[1]);
const routeTerminal=state=>['dead','completed','complete','cancelled','canceled','failed','arrived','finished'].includes(String(state||'').toLowerCase());
function remainingRoute(unit,actual){
 if(!unit||unit.hp<=0||!actual||routeTerminal(actual.state)||!validMapPoint(unit.position))return [];
 const waypoints=(actual.waypoints||[]).filter(validMapPoint);
 const pending=waypoints.length?waypoints:validMapPoint(actual.next)?[actual.next]:[];
 if(!pending.length)return [];
 const points=[unit.position];
 for(const p of pending)if(Math.hypot(p[0]-points.at(-1)[0],p[1]-points.at(-1)[1])>1e-6)points.push(p);
 return points;
}

function drawBattleMap(m,enabled,faction=$('faction').value||'green'){
 const canvas=$('map'),ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height;mapHits=[];ctx.clearRect(0,0,w,h);ctx.fillStyle='#1c281f';ctx.fillRect(0,0,w,h);
 if(!m){ctx.fillStyle='#c1c8b8';ctx.font='15px sans-serif';ctx.textAlign='center';ctx.fillText('等待本关真实地图观测',w/2,h/2);return;}
 const b=m.bounds,scale=Math.min((w-30)/(b[2]-b[0]),(h-30)/(b[3]-b[1])),dx=(w-(b[2]-b[0])*scale)/2,dy=(h-(b[3]-b[1])*scale)/2;
 const point=p=>[dx+(p[0]-b[0])*scale,dy+(p[1]-b[1])*scale];const inside=p=>p&&p[0]>=b[0]&&p[0]<=b[2]&&p[1]>=b[1]&&p[1]<=b[3];
 ctx.save();ctx.beginPath();ctx.rect(dx,dy,(b[2]-b[0])*scale,(b[3]-b[1])*scale);ctx.clip();
 ctx.strokeStyle='#303c31';ctx.lineWidth=1;for(let i=0;i<=12;i++){ctx.beginPath();const x=dx+(w-2*dx)*i/12,y=dy+(h-2*dy)*i/12;ctx.moveTo(x,dy);ctx.lineTo(x,h-dy);ctx.moveTo(dx,y);ctx.lineTo(w-dx,y);ctx.stroke();}
 const seen=new Set();for(const c of m.covers||[]){if(seen.has(c.id)||!c.position||!c.size)continue;seen.add(c.id);const p=point(c.position);ctx.save();ctx.translate(...p);ctx.rotate(-(c.yaw||0));ctx.fillStyle=c.height>0.12?'#55634a':'#78846a';ctx.fillRect(-c.size[0]*scale/2,-c.size[1]*scale/2,c.size[0]*scale,c.size[1]*scale);ctx.restore();}
 const route=(points,color)=>{
  if(points.length<2)return;
  ctx.beginPath();ctx.strokeStyle=color;ctx.lineWidth=1.6;ctx.lineJoin='round';ctx.lineCap='round';ctx.setLineDash([]);
  points.forEach((p,i)=>{const q=point(p);i?ctx.lineTo(...q):ctx.moveTo(...q);});ctx.stroke();ctx.setLineDash([]);
  // Arrowheads follow real segments; never smooth across corners or obstacles.
  let distanceToArrow=28;
  for(let i=1;i<points.length;i++){
   const a=point(points[i-1]),b=point(points[i]),length=Math.hypot(b[0]-a[0],b[1]-a[1]);if(length<.01)continue;
   const ux=(b[0]-a[0])/length,uy=(b[1]-a[1])/length;
   for(;distanceToArrow<length;distanceToArrow+=52){const x=a[0]+ux*distanceToArrow,y=a[1]+uy*distanceToArrow;ctx.beginPath();ctx.moveTo(x-ux*6-uy*4,y-uy*6+ux*4);ctx.lineTo(x,y);ctx.lineTo(x-ux*6+uy*4,y-uy*6-ux*4);ctx.stroke();}
   distanceToArrow-=length;
  }
  const end=point(points.at(-1));ctx.fillStyle='#1c281f';ctx.beginPath();ctx.arc(...end,7,0,Math.PI*2);ctx.fill();ctx.stroke();
 };
 if(enabled&&m.coordinateFrame==='native-world'){
  const team=(m.units||[]).filter(u=>u.faction===faction&&!(u.hp<=0));
  for(const u of team)route(remainingRoute(u,(m.actualRoutes||[]).find(r=>r.unitId===u.id)),mapColors[faction]);
 }

 if(inside(m.objective)){const p=point(m.objective);ctx.strokeStyle='#cabc85';ctx.lineWidth=1;ctx.setLineDash([3,4]);ctx.beginPath();ctx.arc(...p,16,0,Math.PI*2);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#d1bd76';ctx.beginPath();ctx.moveTo(p[0],p[1]-6);ctx.lineTo(p[0]+5,p[1]);ctx.lineTo(p[0],p[1]+6);ctx.lineTo(p[0]-5,p[1]);ctx.fill();}
 for(const u of m.units||[]){if(u.hp<=0||!inside(u.position))continue;const p=point(u.position);if(u.faction===faction)mapHits.push({id:u.id,p});ctx.fillStyle=mapColors[u.faction]||mapColors.unknown;ctx.strokeStyle=ctx.fillStyle;ctx.lineWidth=1.5;{ctx.beginPath();if(u.faction==='red'||u.faction==='contact'){ctx.moveTo(p[0],p[1]-6);ctx.lineTo(p[0]+5.5,p[1]+4.5);ctx.lineTo(p[0]-5.5,p[1]+4.5);ctx.closePath();}else ctx.arc(...p,4.5,0,Math.PI*2);u.visible===false?ctx.stroke():ctx.fill();}if(u.id===selectedUnit){ctx.strokeStyle='#f4e1a1';ctx.beginPath();ctx.arc(...p,10,0,Math.PI*2);ctx.stroke();ctx.fillStyle='#f1e9cb';ctx.font='12px sans-serif';ctx.textAlign='left';ctx.fillText(u.id,Math.min(w-130,p[0]+13),Math.max(18,p[1]-8));}}
 ctx.restore();ctx.strokeStyle='#536145';ctx.strokeRect(dx,dy,w-2*dx,h-2*dy);
}
$('debugToggle').onchange=()=>render();$('debugUnit').onchange=()=>{selectedUnit=$('debugUnit').value;render();};
$('debugFaction').onchange=()=>{$('faction').value=$('debugFaction').value;$('faction').dispatchEvent(new Event('change',{bubbles:true}));};
$('map').onclick=event=>{const r=$('map').getBoundingClientRect(),x=(event.clientX-r.left)*$('map').width/r.width,y=(event.clientY-r.top)*$('map').height/r.height;const hit=mapHits.map(u=>({...u,d:Math.hypot(u.p[0]-x,u.p[1]-y)})).sort((a,b)=>a.d-b.d)[0];selectedUnit=hit&&hit.d<14?hit.id:'';render();};
