import {LiveGameSurface} from './generation-game.js';
import {roleNames,label,defaultUnit,personalSelection,availableCalls,candidateCallSelection,candidateView,snapshotAt,mapCoordinates,gameForVideo,videoForGame} from './lab-model.js';
import {icon,optionIcon,drawMap} from './lab-map.js';
const $=id=>document.getElementById(id),el=(tag,text,cls)=>Object.assign(document.createElement(tag),{textContent:text??'',className:cls||''}),put=(id,value)=>{const node=$(id),text=String(value??'');if(node.textContent!==text)node.textContent=text;};
document.querySelectorAll('[data-icon]').forEach(e=>e.insertAdjacentHTML('afterbegin',icon(e.dataset.icon)));
const params=new URLSearchParams(location.search),api='/api/deskfront/overview/';
let session=params.get('session')||'',tab=params.get('tab')==='generation'?'generation':'combat',role='executor',unit='',callId='',data=null,events=[],cursor=Number(params.get('at'))||0,follow=!params.has('at'),level=null,map=null,hits=[],call=null,view=null,inspected='',refreshSerial=0,callSerial=0,mediaSession='',mediaKey='',frameSession='',timer=null,previewBusy=false,unitSignature='',lastCallKey='',callTimer=null,frameReady=false;
const liveSurface=new LiveGameSurface($('preview'),state=>{if(liveSurface.session!==session)return;if(liveSurface.hasFrame)$('empty-screen').hidden=true;if(state==='reconnecting')put('media-source','画面重连中 · 保留同局上一帧。');});
let selectionNote='';
let displayedScope='',displayedAt=-Infinity,menuSignature='';
function currentCallScope(){return [session,$('faction').value,level?.data?.operationId||level?.index||'',role,role==='personal'?unit:''].join('|');}
const cache=new Map(),time=v=>Number.isFinite(v)?Math.floor(v/60)+':'+String(Math.floor(v%60)).padStart(2,'0'):'—';
let initialSeek=true,manualCall=false;
const json=v=>v===null||v===undefined?'未记录':JSON.stringify(v,null,2);
function updateUrl(){const q=new URLSearchParams({view:'lab',tab,session});if(!follow)q.set('at',cursor.toFixed(1));history.replaceState(null,'','?'+q);$('details-link').href='/?view=overview&session='+encodeURIComponent(session);localStorage.setItem('deskfront-lab-session',session);}
function signalFrame(){const f=$('generation-frame');if(frameReady)f.contentWindow?.postMessage({type:'deskfront-surface-visibility',active:tab==='generation'&&!document.hidden},location.origin);}
function setTab(next){tab=next;document.body.dataset.tab=tab;for(const key of ['combat','generation']){$(key+'-panel').hidden=key!==tab;$(key+'-tab').setAttribute('aria-selected',String(key===tab));$(key+'-tab').tabIndex=key===tab?0:-1;}
 if(tab==='generation'){$('video').pause();liveSurface.pause();ensureFrame();}else if(data)updateMedia();signalFrame();updateUrl();}
function ensureFrame(){if(!session)return;const f=$('generation-frame');$('generation-empty').hidden=true;f.hidden=false;if(frameSession!==session){frameSession=session;frameReady=false;f.src='/?view=generation&embed=1&session='+encodeURIComponent(session)+(params.get('stage')?'&stage='+encodeURIComponent(params.get('stage')):'');}}
$('generation-frame').addEventListener('load',()=>{frameReady=true;signalFrame();});
for(const key of ['combat','generation'])$(key+'-tab').onclick=()=>setTab(key);
document.querySelector('.surface-tabs').addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();setTab(e.key==='Home'?'combat':e.key==='End'?'generation':tab==='combat'?'generation':'combat');$(tab+'-tab').focus();});
window.addEventListener('message',e=>{if(e.origin!==location.origin||e.source!==$('generation-frame').contentWindow)return;if(e.data?.type==='deskfront-generation-session'&&/^deskfront-[a-zA-Z0-9-]+$/.test(e.data.session)&&e.data.session!==session)choose(e.data.session);});
function own(e){return e.faction===$('faction').value&&(!level||e.index>level.index);}
function last(kind){return events.filter(e=>e.time<=cursor&&e.kind===kind&&own(e)).at(-1);}
function latestAccepted(){return events.filter(e=>e.time<=cursor&&e.kind==='squad'&&own(e)&&e.data.status==='accepted').at(-1)||null;}
function render(){
 if(!data)return;const faction=$('faction').value,visible=events.filter(e=>e.time<=cursor);level=visible.filter(e=>e.kind==='deployment').at(-1)||null;if(level)$('chapter').value=String(level.time);
 map=snapshotAt(data,events,cursor,faction,level,follow);const team=(map?.units||[]).filter(u=>u.faction===faction&&!(u.hp<=0));
 const nextUnit=defaultUnit(team,events,data.calls,{current:unit,faction,at:cursor,level});if(unit!==nextUnit){unit=nextUnit;manualCall=false;callId='';lastCallKey='';}
 const sig=faction+'|'+team.map(u=>[u.id,u.weapon,u.kind].join(':')).join('|');if(sig!==unitSignature){unitSignature=sig;$('unit').replaceChildren(el('option','暂无本方单位'));$('unit').firstChild.value='';$('map-units').replaceChildren();for(const [index,u] of team.entries()){const o=el('option',label(u.kind==='tank'?'tank':u.weapon||u.kind)+' · '+u.id);o.value=u.id;$('unit').append(o);const b=el('button','');b.title=(index+1)+' · '+label(u.kind==='tank'?'tank':u.weapon||u.kind)+' · '+u.id;b.setAttribute('aria-label',b.title);b.insertAdjacentHTML('beforeend',icon(u.kind==='tank'?'tank':u.weapon||u.kind||'person'));b.append(el('small',String(index+1)));b.type='button';b.dataset.unit=u.id;b.onclick=()=>selectUnit(u.id);$('map-units').append(b);}}
 $('unit').value=unit;for(const b of $('map-units').children)b.setAttribute('aria-pressed',String(b.dataset.unit===unit));
 const c=last('command'),s=last('squad'),personal=personalSelection(events,{faction,unit,at:cursor,level}),p=personal.event;
 put('commander-source',c?.data.sourceType==='human-autonomous-plan'?'目标 · JEV自主':'目标 · DeepSeek');put('commander-value',c?label(c.data.stage):'未记录');$('commander-value').title=c?.data.objective||'本关未记录目标';
 put('commander-time',c?time(c.time)+' · '+(c.data.region_id||'区域未记录'):'本关未记录');
 put('executor-value',s?label(s.data.intent):'未记录');put('executor-time',s?time(s.time)+' · '+({accepted:'已接单',submitted:'已提交',rejected:'未接单',unknown:'回执未明确'}[s.data.status]||'记录状态未明确'):'本关未记录');
 put('personal-value',p?label(p.data.behavior||p.data.choice):'未记录');put('personal-time',unit?unit+(p?' · '+time(p.time)+(personal.previous?' · 上次选择，等待更新':''):' · 等待首次选择'):'暂无本方单位');$('personal-value').title=personal.previous?'上次选择记录，仅供查看；当前动作以引擎状态为准。':p?'模型选择记录；执行结果另看回执。':'';
 const counts={green:0,red:0};for(const u of map?.units||[])if(!(u.hp<=0)){if(u.faction==='green')counts.green++;else if(['red','contact'].includes(u.faction))counts.red++;}
 put('map-counts',map?'绿方 '+counts.green+' · 红方／接触 '+counts.red:'');
 const coordinates=mapCoordinates(map,events,cursor,faction,level);
 put('map-source',map?(map.source==='native_snapshot'?'观战采样':'当时请求观测')+' · '+time(map.time)+(map.provenance==='native-verification'?' · 验证场景':'')+(coordinates.model?' · 模型格号':' · 未保存模型格号绑定，显示世界坐标')+(c?.data.position?' · 旗帜为声明目标':' · 旗帜为关卡目标'):'没有本关观测，不沿用旧关地图。');
 hits=drawMap($('battle-map'),map,{faction,selectedUnit:unit,command:c,squad:latestAccepted(),coordinates});
 put('clock',time(cursor));$('timeline').max=String(Math.max(1,data.live?.gameTime||data.lastGameTime||1));$('timeline').value=String(cursor);
 put('native-status',s?.data.status==='accepted'?'已接单 '+time(s.time)+' · 不代表战术完成':s?'最近分工记录 '+time(s.time)+' · '+({submitted:'已提交',rejected:'未接单',unknown:'回执未明确'}[s.data.status]||'状态未记录'):'本关尚无小队反馈');
 if(map?.source==='recorded_model_observation')put('native-status',$('native-status').textContent+'；这份请求观测未保存实际剩余路线。');
 else if(map?.actualRoutes){const n=map.actualRoutes.filter(r=>r.waypoints?.length&&team.some(u=>u.id===r.unitId)).length;put('native-status',$('native-status').textContent+'；'+n+'个单位有剩余路线记录。');}
 $('unit-label').hidden=role!=='personal';for(const b of document.querySelectorAll('[data-role]'))b.setAttribute('aria-pressed',String(b.dataset.role===role));
 renderCalls();updateMedia();updateUrl();
}
function selectUnit(id){manualCall=false;unit=id;role='personal';callId='';inspected='';lastCallKey='';render();}
for(const b of document.querySelectorAll('[data-role]'))b.onclick=()=>{manualCall=false;role=b.dataset.role;callId='';inspected='';lastCallKey='';render();};
$('unit').onchange=()=>selectUnit($('unit').value);
$('battle-map').onclick=e=>{const r=$('battle-map').getBoundingClientRect(),x=(e.clientX-r.left)*$('battle-map').width/r.width,y=(e.clientY-r.top)*$('battle-map').height/r.height;const hit=hits.map(h=>({...h,d:Math.hypot(h.p[0]-x,h.p[1]-y)})).sort((a,b)=>a.d-b.d)[0];if(hit&&hit.d<24)selectUnit(hit.id);};
function renderCalls(){
 const rows=availableCalls(data,role,$('faction').value,cursor,level,unit),signature=rows.map(c=>c.id).join('|');put('candidate-title',roleNames[role]+' · 本次候选');
 if($('call').dataset.rows!==signature){$('call').dataset.rows=signature;$('call').replaceChildren();for(const c of [...rows].reverse()){const o=el('option',time(c.requestedAt)+' · '+(c.unitId||roleNames[c.role]));o.value=c.id;$('call').append(o);}if(!rows.length){const o=el('option','本关暂无对应调用');o.value='';$('call').append(o);}}
 const display=candidateCallSelection(rows,cursor,{manual:manualCall,id:callId});selectionNote=display.note;callId=display.call?.id||'';$('call').value=callId;
 const summary=rows.find(c=>c.id===callId),returned=summary?.returnedAt!=null&&summary.returnedAt<=cursor,key=[session,callId,returned,summary?.errorAt!=null&&summary.errorAt<=cursor,(summary?.receiptTimes||[]).filter(t=>t<=cursor).join(',')].join('|');
 if(!summary){callSerial++;clearTimeout(callTimer);lastCallKey='';clearCall(role==='personal'&&!unit?'暂无本方单位':'本关未保存对应请求');return;}
 if(key!==lastCallKey){
  const retain=!manualCall&&call&&view&&displayedScope===currentCallScope()&&cursor>=displayedAt&&rows.some(c=>c.id===call.id);
  lastCallKey=key;callSerial++;clearTimeout(callTimer);
  if(retain){$('call').value=call.id;put('candidate-state','更新中 · 暂显示上次请求候选');}
  else clearCall('读取本次请求…');
  $('candidates').setAttribute('aria-busy','true');
  if(cache.has(key))loadCall(summary,key);else callTimer=setTimeout(()=>loadCall(summary,key),100);
 }
 else if($('candidates').getAttribute('aria-busy')==='true'&&call){$('call').value=call.id;}
 else if(call&&call.id===callId){call.receipts=(cache.get(key)?.receipts||call.receipts||[]).filter(r=>r.at<=cursor);renderCandidateState();}
}
function clearCall(note){call=null;view=null;inspected='';displayedScope='';displayedAt=-Infinity;menuSignature='';$('candidates').removeAttribute('aria-busy');$('candidates').replaceChildren(el('p',note,'empty'));put('candidate-count','');put('candidate-state','');put('candidate-raw','点选卡片查看实际保存字段。');for(const n of ['route','fire','support'])put('fact-'+n,'未记录');for(const n of ['request','response','receipt'])put(n+'-raw','未记录');}
async function loadCall(summary,key){
 const token=++callSerial,scope=session,at=cursor,displayScope=currentCallScope();
 try{let value=cache.get(key);if(!value||value.readAt<at&&summary.returnedAt!=null&&summary.returnedAt>value.readAt){const r=await fetch(api+encodeURIComponent(scope)+'/calls/'+encodeURIComponent(summary.id)+'?at='+encodeURIComponent(at),{cache:'no-store'});if(!r.ok)throw Error('本次请求详情暂不可用');value={...await r.json(),readAt:at};cache.set(key,value);if(cache.size>60)cache.delete(cache.keys().next().value);}
  if(token!==callSerial||scope!==session||key!==lastCallKey||displayScope!==currentCallScope())return;
  if(call?.id!==value.id)inspected='';
  call={...value,response:value.returnedAt!=null&&value.returnedAt<=cursor?value.response:null,wireResponse:value.returnedAt!=null&&value.returnedAt<=cursor?value.wireResponse:null,receipts:(value.receipts||[]).filter(r=>r.at<=cursor)};
  displayedScope=displayScope;displayedAt=cursor;$('call').value=call.id;$('candidates').removeAttribute('aria-busy');
  view=candidateView(call);renderCandidates();put('request-raw',json(call.request));put('response-raw',json(call.wireResponse||call.response||call.error));put('receipt-raw',call.receipts.length?json(call.receipts):'无明确身份关联的回执；不按临近时间猜配。');
  put('call-status',roleNames[role]+' · 请求 '+time(call.requestedAt)+(call.returnedAt!=null?' · 返回 '+time(call.returnedAt):' · 此查看点未保存返回')+(call.model?' · '+call.model:''));
  for(const n of ['route','fire','support'])put('fact-'+n,Object.keys(view.facts[n]||{}).length?json(view.facts[n]):'本次请求未记录这类事实。');
 }catch(e){if(token===callSerial&&key===lastCallKey){
  $('candidates').removeAttribute('aria-busy');lastCallKey='';
  if(call&&view&&displayedScope===currentCallScope()&&cursor>=displayedAt){$('call').value=call.id;put('candidate-state','更新暂时失败 · 保留上次请求候选。'+e.message);}
  else clearCall(e.message);
 }}
}
function renderCandidateState(){const chosen=view?.options.find(o=>o.key===view.selected);put('candidate-state',selectionNote+(selectionNote?' ':'')+(chosen?'本次已选：'+chosen.label+(chosen.presentation?'（'+chosen.presentation.summary+'）':'')+'。 ':'')+(view?.note||''));}
function renderCandidates(){
 const signature=JSON.stringify([call.id,view.options,view.selected]);
 if(signature===menuSignature){renderCandidateState();return;}
 const scrollTop=$('candidates').scrollTop,fragment=document.createDocumentFragment();
 put('candidate-count',view.options.length?view.options.length+' 项':'');
 for(const o of [...view.options].sort((a,b)=>Number(b.key===view.selected)-Number(a.key===view.selected))){const b=el('button','', 'option-card'+(o.key===view.selected?' is-chosen':''));b.type='button';b.dataset.key=o.key;const p=o.presentation,subtitle=p?.summary||(role==='executor'?'查看方案详情':o.key);b.setAttribute('aria-label',o.label+'，'+subtitle+(o.key===view.selected?'，模型已选':''));b.insertAdjacentHTML('beforeend',icon(optionIcon(o.kind)));b.append(el('b',o.label),el('small',subtitle,'candidate-summary'));
 // Cards show the plan abstraction; per-member tasks and coordinates remain in candidate-detail.
 if(o.key===view.selected)b.append(el('span','已选','selection-label'));
 b.onclick=()=>{inspected=o.key;for(const node of $('candidates').children)node.classList.toggle('is-inspected',node.dataset.key===inspected);const readable=p?[o.label+' · '+p.summary,...p.members.map(m=>m.name+'（'+m.sourceId+'）：'+m.role+(m.destination?'；目标 '+m.destination:'')+(m.route?'；路线 '+m.route:'')),p.purpose,'','原始记录（含方案编号）：'].filter(x=>x!==undefined).join('\n')+'\n':'';put('candidate-raw',readable+json({key:o.key,...o.detail}));$('candidate-detail').open=true;};fragment.append(b);}
 if(!view.options.length)fragment.append(el('p','本次候选未记录；不补造固定菜单。','empty'));$('candidates').replaceChildren(fragment);$('candidates').scrollTop=scrollTop;menuSignature=signature;renderCandidateState();
}
$('call').onchange=()=>{manualCall=true;callId=$('call').value;lastCallKey='';render();};
$('open-input').onclick=()=>{$('call-detail').open=true;$('call-detail').scrollIntoView({block:'start',behavior:'instant'});};
function chapterMenu(){const old=$('chapter').value,built=events.filter(e=>e.kind==='deployment'),seen=new Set();$('chapter').replaceChildren();for(const e of built){if(seen.has(e.data.operationId))continue;seen.add(e.data.operationId);const o=el('option','第'+(e.data.level??seen.size)+'关 · '+time(e.time));o.value=String(e.time);$('chapter').append(o);}if(!built.length){const o=el('option','尚无建成记录');o.value='';$('chapter').append(o);}if([...$('chapter').options].some(o=>o.value===old))$('chapter').value=old;}
async function load(reset=false){
 if(!session)return;const mine=++refreshSerial,scope=session;$('refresh').disabled=true;
 try{const r=await fetch(api+encodeURIComponent(scope)+(reset?'':'?after='+(events.at(-1)?.index??-1)),{cache:'no-store'});if(!r.ok)throw Error(r.status===404?'未找到这局记录，请切换对局。':'记录读取失败，请刷新重试。');const next=await r.json();if(mine!==refreshSerial||scope!==session)return;
 data=next;if(next.beginner){follow=true;document.body.classList.add('is-live-game');const option=[...$('session').options].find(o=>o.value===session);if(option)option.textContent='实时 · 小白版 · '+session.slice(-8);}else document.body.classList.remove('is-live-game');if(reset)events=[];events.push(...next.events);chapterMenu();put('connection',next.beginner?(next.beginner.status==='running'?'实时对局 · 最多10关':next.beginner.status==='starting'?'正在启动':'本局已结束'):next.mode==='live'?'实时记录':'历史记录 · 只读');
 if(follow){cursor=next.live?.gameTime??next.lastGameTime??0;if(reset&&next.mode!=='live'&&next.media?.sync?.length){const first=events.find(e=>e.kind==='squad'&&e.faction===$('faction').value&&e.data.status==='accepted');cursor=first?.time??cursor;follow=false;}}
 put('notice','');render();if(reset&&data.media){const seek=()=>{const t=videoForGame(data.media.sync,cursor);if(t!==null)$('video').currentTime=t;};if($('video').readyState>=1)seek();else $('video').addEventListener('loadedmetadata',seek,{once:true});}
 }catch(e){if(mine===refreshSerial&&scope===session){put('notice',e.message);put('connection','连接中断 · 已保存记录');if(!data)clearCall('没有可用记录');}}
 finally{if(mine===refreshSerial)$('refresh').disabled=false;}
}
function updateMedia(){
 const v=$('video'),available=data?.liveFrameUrl?'stream':data?.mode==='live'&&data?.previewAvailable?'preview':data?.media?.url?'video':'none',key=session+'|'+available+'|'+(data?.media?.url||'');
 if(mediaKey!==key){liveSurface.reset();mediaKey=key;mediaSession=session;v.pause();v.removeAttribute('src');v.load();v.hidden=true;$('preview').hidden=true;$('empty-screen').hidden=available!=='none';
  if(available==='video'){v.src=data.media.url;v.hidden=false;put('media-source',data.media.sync?.length?'真实录像 · 按保存的游戏时钟对齐。':'真实录像缺少时钟对齐；时间轴单独核对日志。');}
  else if(available==='stream'){$('preview').hidden=true;$('empty-screen').hidden=!liveSurface.hasFrame;put('media-source','同局实时画面 · 连续传帧，声音由游戏窗口播放。');}
  else if(available==='preview'){$('preview').hidden=false;put('media-source',data?.frameSource==='native-viewport'?'同局实时画面 · 声音由游戏窗口播放。':'同局OBS镜像 · 低频采样，完整画面在游戏窗口。');}
  else put('media-source','没有关联实录；未用模拟画面替代。');resetZoom();
 }
 if(available==='stream'&&tab==='combat'&&!document.hidden){liveSurface.connect(data.liveFrameUrl,session);$('preview').hidden=true;$('empty-screen').hidden=liveSurface.hasFrame;}
 if(data?.beginner)put('media-source',['running','starting'].includes(data.beginner.status)?'同局实时画面 · 连续传帧，声音由游戏窗口播放。':'本局已结束 · 保留最后游戏画面。');
 const video=available==='video';$('play').disabled=!video;$('sound').disabled=!video;$('zoom-in').disabled=available==='none';$('play').textContent=v.paused?'播放':'暂停';$('sound').textContent=v.muted?'开启声音':'关闭声音';put('playback-position',time(cursor));$('timeline').disabled=!data||!!data?.beginner;$('timeline').closest('label').hidden=!!data?.beginner;$('play').hidden=!!data?.beginner;$('sound').hidden=!!data?.beginner;$('chapter').disabled=!!data?.beginner;$('screen').setAttribute('aria-label',data?.beginner?'同局实时游戏视窗，可缩放和平移':'游戏录像视窗，可缩放和平移');
}
async function choose(id){
 liveSurface.reset();refreshSerial++;callSerial++;session=id;data=null;events=[];cursor=initialSeek?Number(params.get('at'))||0:0;follow=!initialSeek||!params.has('at');initialSeek=false;manualCall=false;unit='';callId='';map=null;level=null;lastCallKey='';cache.clear();mediaKey='';unitSignature='';clearTimeout(callTimer);$('video').pause();$('video').removeAttribute('src');$('video').load();$('video').hidden=true;$('preview').hidden=true;$('empty-screen').hidden=false;clearCall('读取本局记录…');hits=drawMap($('battle-map'),null);for(const r of ['commander','executor','personal']){put(r+'-value','未记录');put(r+'-time','本关未记录');}updateUrl();if(tab==='generation')ensureFrame();await load(true);
}
$('session').onchange=()=>choose($('session').value);$('refresh').onclick=()=>load(true);$('latest').onclick=()=>{manualCall=false;follow=true;cursor=data?.live?.gameTime??data?.lastGameTime??0;callId='';lastCallKey='';const v=videoForGame(data?.media?.sync,cursor);if(v!==null)$('video').currentTime=v;render();};$('faction').onchange=()=>{manualCall=false;unit='';callId='';lastCallKey='';callSerial++;render();};
$('chapter').onchange=()=>{if(!$('chapter').value)return;follow=false;cursor=Number($('chapter').value)+.01;callId='';lastCallKey='';const v=videoForGame(data?.media?.sync,cursor);if(v!==null)$('video').currentTime=v;render();};
$('timeline').oninput=()=>{follow=false;cursor=Number($('timeline').value);const v=videoForGame(data?.media?.sync,cursor);if(v!==null)$('video').currentTime=v;render();};
$('play').onclick=()=>{const v=$('video');if(v.paused)v.play().catch(()=>put('notice','浏览器未允许自动播放，请使用录像播放控件。'));else v.pause();};$('sound').onclick=()=>{$('video').muted=!$('video').muted;updateMedia();};
$('video').muted=true;for(const type of ['play','pause','volumechange','ended'])$('video').addEventListener(type,updateMedia);
let lastVideoRender=0;$('video').addEventListener('timeupdate',()=>{if(tab!=='combat'||!data?.media?.sync?.length||performance.now()-lastVideoRender<120)return;lastVideoRender=performance.now();const at=gameForVideo(data.media.sync,$('video').currentTime);if(at!==null){follow=false;cursor=at;render();}});
let scale=1,panX=0,panY=0,drag=null;
function paintZoom(){const r=$('screen').getBoundingClientRect(),x=(scale-1)*r.width/2,y=(scale-1)*r.height/2;panX=Math.max(-x,Math.min(x,panX));panY=Math.max(-y,Math.min(y,panY));for(const e of [$('video'),$('preview'),liveSurface.canvas])e.style.transform='translate('+panX+'px,'+panY+'px) scale('+scale+')';$('screen').classList.toggle('is-zoomed',scale>1);put('zoom-reset',Math.round(scale*100)+'%');$('zoom-out').disabled=scale<=1;}
function zoom(next){scale=Math.max(1,Math.min(4,next));paintZoom();}function resetZoom(){scale=1;panX=panY=0;paintZoom();}
$('zoom-in').onclick=()=>zoom(scale+.25);$('zoom-out').onclick=()=>zoom(scale-.25);$('zoom-reset').onclick=resetZoom;
$('screen').addEventListener('wheel',e=>{if($('video').hidden&&$('preview').hidden&&liveSurface.canvas.hidden)return;e.preventDefault();zoom(scale+(e.deltaY<0?.25:-.25));},{passive:false});
$('screen').addEventListener('pointerdown',e=>{if(scale<=1||e.button!==0||e.target.closest('button,a'))return;drag={id:e.pointerId,x:e.clientX,y:e.clientY,panX,panY};$('screen').setPointerCapture(e.pointerId);$('screen').classList.add('is-dragging');});
$('screen').addEventListener('pointermove',e=>{if(!drag||e.pointerId!==drag.id)return;panX=drag.panX+e.clientX-drag.x;panY=drag.panY+e.clientY-drag.y;paintZoom();});
for(const type of ['pointerup','pointercancel','lostpointercapture'])$('screen').addEventListener(type,()=>{drag=null;$('screen').classList.remove('is-dragging');});
$('screen').addEventListener('keydown',e=>{if(e.target!==$('screen'))return;if(['+','=','-','0'].includes(e.key)){e.preventDefault();if(e.key==='0')resetZoom();else zoom(scale+(e.key==='-'?-.25:.25));}});
$('fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await $('battle-player').requestFullscreen();}catch{put('notice','浏览器未允许全屏，请使用页面缩放。');}};
new ResizeObserver(paintZoom).observe($('screen'));
async function init(){setTab(tab);try{const r=await fetch(api+'sessions',{cache:'no-store'});if(!r.ok)throw Error('对局列表读取失败');const rows=(await r.json()).sessions||[];if(session&&!rows.some(x=>x.id===session))rows.unshift({id:session,mode:'recording'});$('session').replaceChildren();for(const r of rows){const o=el('option',(r.mode==='live'?'实时 · ':'记录 · ')+r.id.slice(-8)+(r.hasVideo?' · 有录像':''));o.value=r.id;$('session').append(o);}if(!rows.length){put('connection','暂无记录');clearCall('先运行一局，再查看决策记录。');return;}session=session||rows[0].id;$('session').value=session;await choose(session);}catch(e){put('notice',e.message);}}
timer=setInterval(()=>{if(!document.hidden&&tab==='combat'&&data?.mode==='live')load();},2500);
let lastPreviewAt=0;
setInterval(async()=>{if(document.hidden||tab!=='combat'||data?.mode!=='live'||!data.previewAvailable||data.liveFrameUrl||previewBusy)return;if(Date.now()-lastPreviewAt<(data.frameSource==='native-viewport'?180:1900))return;lastPreviewAt=Date.now();previewBusy=true;const scope=session;try{const r=await fetch(api+encodeURIComponent(scope)+'/preview',{cache:'no-store'});if(!r.ok)return;const url=URL.createObjectURL(await r.blob());if(scope!==session){URL.revokeObjectURL(url);return;}const old=$('preview').src;$('preview').src=url;if(old.startsWith('blob:'))URL.revokeObjectURL(old);}catch{/* Keep the last verified frame while the live connection retries. */}finally{previewBusy=false;}},200);
document.addEventListener('visibilitychange',()=>{if(document.hidden){$('video').pause();liveSurface.pause();signalFrame();}else if(data?.mode==='live'&&tab==='combat')load();});init();
