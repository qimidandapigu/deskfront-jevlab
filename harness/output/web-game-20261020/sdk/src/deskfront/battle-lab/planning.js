/* Planning display only. Reading this page never issues model or game commands. */
let callMenuKey='',callDetailStamp='',callDetailSerial=0;
const callRoles={commander:'总指挥',executor:'JEV小队',personal:'JEV单兵',director:'体验导演',planner:'关卡策划',builder:'空间搭建'};
function resetPlanning(){callMenuKey='';callDetailStamp='';callDetailSerial++;$('planning-call-body').replaceChildren();}
function renderPlanning(visible,level,faction){
 renderCombatChain(data,cursor,faction,level,visible);
 const calls=(data.calls||[]).filter(c=>c.requestedAt<=cursor&&(!c.faction||c.faction===faction));
 const returned=calls.filter(c=>c.returnedAt!==null&&c.returnedAt<=cursor).length;
 if(data.mode==='live'){
  const live=data.live,thinking=live?.modelStatus?.some(s=>s.pending),error=live?.modelStatus?.find(s=>s.error);
  put('planning-runtime','实况 '+time(cursor)+' · '+(thinking?'模型请求中':'引擎执行中')+' · 已用请求 '+(live?.requests??'—')+'/'+(live?.requestLimit??'—')+(error?' · 有调用异常，请展开记录核对':''));
 }else put('planning-runtime','历史回放 '+time(cursor)+' · 此时已保存 '+returned+' 份本方／生成模型返回');
 const director=visible.filter(e=>e.kind==='director').at(-1);
 put('planning-observation',director?.data.current_analysis||'等待本局体验分析返回');
 const adopted=level?.data.sourceReportId?events.find(e=>e.kind==='director'&&e.data.requestId===level.data.sourceReportId):null;
 put('applied-reason',adopted?.data.reason||'本关没有可核对的导演理由；可展开原始记录查看策划来源。');
 put('applied-stage',level?'· '+(level.data.level?'第 '+level.data.level+' 关':'建成记录')+' · '+time(level.time):'· 等待引擎回执');
 put('director-summary-status',director?time(director.time)+' · '+(level?.data.sourceReportId===director.data.requestId?'本份已用于本关':'后续提案，未确认采用'):'尚无已保存的分析报告');
 $('planning-beats').replaceChildren();
 for(const b of director?.data.experience_flow?.beats||[]){const block=document.createElement('div');block.append(node('p',b.goal||'后续目标','director'));if(b.change)block.append(node('p','安排：'+b.change));if(b.expected)block.append(node('p','希望看到：'+b.expected));if(b.reconsider)block.append(node('p','何时调整：'+b.reconsider,'caption'));$('planning-beats').append(block);}
 if(director?.data.experience_flow?.uncertainty)$('planning-beats').append(node('p','尚未确认：'+director.data.experience_flow.uncertainty,'caption'));
 if(!$('planning-beats').childElementCount)$('planning-beats').append(node('p','当前记录未保存后续体验流。','caption'));
 $('planning-full-log').href='/runtime/deskfront/prompts?session='+encodeURIComponent(id);
 const menuKey=calls.map(c=>[c.id,c.returnedAt!==null&&c.returnedAt<=cursor,c.errorAt!==null&&c.errorAt<=cursor].join(':')).join('|'),old=$('planning-call').value;
 if(menuKey!==callMenuKey){callMenuKey=menuKey;$('planning-call').replaceChildren();for(const c of [...calls].reverse()){
   const returned=c.returnedAt!==null&&c.returnedAt<=cursor,failed=c.errorAt!==null&&c.errorAt<=cursor;
   const o=node('option',time(c.requestedAt)+' · '+(callRoles[c.role]||c.role)+(c.unitId?' '+c.unitId:'')+' · '+(failed?'记录异常':returned?'有返回':data.mode==='live'?'等待返回':'未找到返回'));o.value=c.id;$('planning-call').append(o);
  }if(old&&calls.some(c=>c.id===old))$('planning-call').value=old;
 }
 if($('planning-follow').checked&&calls.length)$('planning-call').value=calls.at(-1).id;
 if(!calls.length){put('planning-call-status','该时间点还没有本方或生成调用记录。');$('planning-call-body').replaceChildren();return;}
 if($('liveLLM').open)loadPlanningCall();
}
async function loadPlanningCall(force=false){
 if(!data||!$('liveLLM').open||!$('planning-call').value)return;
 const call=$('planning-call').value,session=id,at=cursor,stamp=[session,call,Math.floor(at)].join('|');
 if(!force&&stamp===callDetailStamp)return;callDetailStamp=stamp;const serial=++callDetailSerial;
 put('planning-call-status','读取实际保存的请求与返回…');
 try{
  const r=await fetch(api+encodeURIComponent(session)+'/calls/'+encodeURIComponent(call)+'?at='+encodeURIComponent(at),{cache:'no-store'});if(!r.ok)throw Error('记录暂不可用');const value=await r.json();
  if(serial!==callDetailSerial||id!==session||$('planning-call').value!==call)return;
  put('planning-call-status',(callRoles[value.role]||value.role)+' · '+time(value.requestedAt)+(value.model?' · '+value.model:'')+(value.elapsedMs!==null?' · 记录耗时 '+(value.elapsedMs/1000).toFixed(2)+'秒':'')+' · 日志查看点 '+time(at));
  const body=$('planning-call-body');body.replaceChildren();
  const section=(title,value)=>{body.append(node('h4',title),node('pre',typeof value==='string'?value:JSON.stringify(value,null,2)));};
  if(!value.detailAvailable){section('原文范围','本条详情超过本页读取上限，请使用独立提示词入口核对。');return;}
  section('① 当时保存的输入',value.request||'本条记录没有保存请求输入，不能据返回补写。');
  section('② 模型返回',value.response||value.error||(data.mode==='live'?'此查看点尚无已保存返回。':'该时间点未找到返回记录。'));
  section('③ 明确关联的回执',value.receipts.length?value.receipts:'本条没有可明确关联的回执。部分回答只用于目标或继续任务，不直接发动作；无回执不等于执行失败。');
  body.append(node('p',value.boundary,'caption'));
 }catch(error){if(serial===callDetailSerial&&id===session)put('planning-call-status',error.message+'，可重新选择记录。');}
}
$('liveLLM').addEventListener('toggle',()=>{if($('liveLLM').open)loadPlanningCall(true);});
$('planning-call').onchange=()=>{$('planning-follow').checked=false;loadPlanningCall(true);};
$('planning-follow').onchange=()=>render();
