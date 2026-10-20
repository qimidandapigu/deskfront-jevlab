/* Read-only projection of actual requests. No scoring, model calls or command construction. */
export const roleNames={commander:'DeepSeek',executor:'JEV小队',personal:'JEV个人'};
export const words={approach:'接近目标',probe:'试探接敌',engage:'交战打击',observe:'观察敌情',recover:'恢复战力',reposition:'调整位置',hold:'区域守备',continue_order:'继续当前命令',revise_order:'调整成员分工',establish_fire:'建立射位',keep_assignment:'保持原任务',hold_fire_position:'保持射位',continue_task:'继续当前任务',focus_fire:'集中攻击',throw_grenade:'投掷手榴弹',throw_satchel:'投掷炸药包',support_area:'区域支援',advance:'推进',bound:'交替推进',flank:'侧翼包抄',cover:'火力掩护',regroup:'集结重整',assault:'突击',continue_role:'继续职责',local_reposition:'局部换位',covered_advance:'借掩体推进',hold_fire:'保持射位',report_blocked:'报告受阻',fire_support:'火力支援',maneuver:'机动',opportunity_action:'机会动作',rifle:'步枪兵',smg:'冲锋枪兵',rocket:'火箭兵',mortar:'迫击炮',tank:'坦克'};
export const label=v=>words[String(v||'').split(':')[0]]||String(v||'未记录');
export const point=p=>Array.isArray(p)&&p.length>=2&&p.slice(0,2).every(Number.isFinite)?p.slice(0,2):null;
export function expand(raw){const facts=raw?.shared_facts||[];function walk(v,depth=0){if(depth>22)return null;if(Array.isArray(v))return v.map(x=>walk(x,depth+1));if(!v||typeof v!=='object')return v;if(Object.keys(v).length===1&&Number.isInteger(v.ref))return walk(facts[v.ref],depth+1);return Object.fromEntries(Object.entries(v).filter(([k])=>k!=='shared_facts').map(([k,x])=>[k,walk(x,depth+1)]));}return walk(raw||{});}
export function table(v){if(v&&Array.isArray(v.columns)&&Array.isArray(v.rows)){const rows=v.rows.map(r=>Object.fromEntries(v.columns.map((k,i)=>[k,r[i]])));return v.keys?Object.fromEntries(v.keys.map((k,i)=>[k,rows[i]])):rows;}return v||{};}
export function inChapter(call,level){if(!level)return true;if(Number.isFinite(call.stage)&&Number.isFinite(level.data?.level))return call.stage===level.data.level;return call.requestedAt>=level.time;}
export function availableCalls(data,role,faction,at,level,unit=''){return(data?.calls||[]).filter(c=>c.role===role&&c.faction===faction&&c.requestedAt<=at&&inChapter(c,level)&&(role!=='personal'||unit&&c.unitId===unit));}
// Automatic display follows finished model choices. Explicit history inspection
// may still open a pending call. The caller filters faction/chapter/unit first.
export function candidateCallSelection(rows,at,{manual=false,id=''}={}){
 const visible=rows.filter(c=>c.requestedAt<=at),latest=visible.at(-1);
 if(!latest)return{call:null,note:''};
 const returned=c=>Number.isFinite(c.returnedAt)&&c.returnedAt<=at;
 const failed=c=>Number.isFinite(c.errorAt)&&c.errorAt<=at;
 if(manual){const call=visible.find(c=>c.id===id)||latest;return{call,note:failed(call)?'本次模型请求失败。':returned(call)?'':'等待本次模型选择。'};}
 const completed=visible.filter(c=>returned(c)&&!failed(c)).at(-1),call=completed||latest;
 const note=call.id!==latest.id?(failed(latest)?'新一轮选择失败 · 保留上一轮结果。':'新一轮正在选择 · 显示上一轮结果。'):failed(call)?'本次模型请求失败。':returned(call)?'':'等待首次模型选择。';
 return{call,note};
}
const pkey=p=>Array.isArray(p)?'('+p.map(x=>Number(x)).join(',')+')':String(p||'').replace(/\s/g,'');
// Presentation only. Keep original choice keys and bindings untouched.
export function describeCandidate(plan,context={}){
 if(!plan?.bindings||typeof plan.bindings!=='object')return null;
 const entries=Object.entries(plan.bindings).filter(([,b])=>b&&typeof b==='object'),order=[...new Set([...(Array.isArray(context.living_member_ids)?context.living_member_ids:[]),...entries.map(([id])=>id)])];
 const roleText={maneuver:'机动',fire_support:'掩护',establish_fire:'建射位',keep_assignment:'保持原令'},counts=new Map();
 const members=entries.map(([id,b])=>{
  const kept=b.keep_assignment===true||b.route_id==='keep_assignment',role=kept?'保持原令':roleText[b.role]||label(b.role),key=kept?'keep_assignment':b.role;
  counts.set(key,(counts.get(key)||0)+1);
  const destination=typeof b.region_id==='string'&&b.region_id?b.region_id:Array.isArray(b.position)?pkey(b.position):'',route=typeof b.route_id==='string'?b.route_id:'';
  return{name:'兵'+(order.indexOf(id)+1),role,kind:kept?'continue_order':b.role==='fire_support'?'cover':b.role==='establish_fire'?'aim':'advance',destination:kept?'':destination,route,sourceId:id,kept};
 });
 const summary=[...counts].map(([role,n])=>n+'人'+(roleText[role]||label(role))).join(' · ');
 const purposes={screen_task:'掩护任务区',maintain_fire:'维持对敌火力',defend_area:'守住区域',recover_then_review:'恢复后重评'},purpose=purposes[plan.hold_contract?.purpose]||'';
 return{summary:summary||'成员分工未记录',members,purpose};
}
export function candidateView(call){
 if(!call)return{options:[],selected:null,context:{},facts:{},note:'本关未保存对应请求'};
 if(call.detailAvailable===false)return{options:[],selected:null,context:{},facts:{},note:'本条详情超过读取上限，请到详情版的原始记录入口核对；不补造候选。'};
 const context=expand(call.request?.context),questions=call.request?.questions||{},normal=call.response?.answers||{},wire=call.wireResponse?.answers||{},role=call.role;
 let options=[],selected=null,note='';
 if(role==='commander'){
  const regions=table(context.regions);
  options=Object.entries(regions).map(([key,value])=>({key,label:'目标 '+key,kind:'flag',detail:value}));
  const destination=wire.plan?.value?.destination??normal.plan?.value?.destination;
  if(destination!==undefined)selected=options.find(o=>pkey(o.key)===pkey(destination))?.key??null;
  note='目标卡来自本次提供的区域；阶段与完整计划见详情。';
 }else{
  const name=role==='personal'?'action':questions.intent?'intent':questions.autonomous_plan?'autonomous_plan':Object.keys(questions).find(k=>questions[k]?.type==='choice');
  const criteria=questions[name]?.criteria||{},plans=table(context.cooperation_candidates);
  options=Object.entries(criteria).map(([key,value])=>{const plan=plans[key],intent=plan?.intent||String(value).split('｜')[0],kind=role==='personal'?key.split(':')[0]:plan?.intent||intent;
   return{key,label:role==='personal'?label(key):label(plan?.intent||(key.startsWith('plan_')?intent:words[key]?key:String(value).split(/[；｜]/)[0])),kind,presentation:role==='executor'?describeCandidate(plan,context):null,detail:{criterion:value,...(plan?{binding:plan}:{})}};
  });
  const chosen=wire[name]?.choice??normal[name]?.choice;
  selected=options.some(o=>o.key===chosen)?chosen:null;
  if(chosen&&!selected)note='保存的是解码后的意图，缺少原始选项身份；不按概率或战术名称猜选中卡。';
 }
 const facts={
  route:{...pick(context,['regions','member_region_choices','candidate_sites','navigation_access']),...(context.motion_execution?{motion_execution:context.motion_execution}:{})},
  fire:pick(context,['comparison_current_members','engagement_map','execution_evidence','grenade_checks','satchel_check']),
  support:pick(context,['cooperation_candidates','cooperation_board','support_options','support_execution','cooperation_execution','coordination','local_behavior_grant','assignment'])
 };
 return{options,selected,context,facts,note:note||(!options.length?'本次菜单未保存；不补造固定选项。':'点选卡片只查看详情，不改变模型选择。')};
}
function pick(v,keys){return Object.fromEntries(keys.filter(k=>v?.[k]!==undefined).map(k=>[k,table(v[k])]));}
export function snapshotAt(data,events,at,faction,level,follow){if(data?.mode==='live'&&follow&&Math.abs(at-(data.live?.gameTime??-100))<3)return data.live?.map||null;
 const rows=events.filter(e=>e.kind==='map'&&e.faction===faction&&e.time<=at&&e.data?.time<=at&&(!level||(e.data?.stage!=null&&level.data?.level!=null?e.data.stage===level.data.level:e.index>level.index)));
 return(rows.filter(e=>e.data.source==='native_snapshot').at(-1)||rows.at(-1))?.data||null;
}
export function remainingRoute(u,r){if(!u||u.hp<=0||!r||['dead','completed','complete','cancelled','canceled','failed','arrived','finished'].includes(String(r.state||'').toLowerCase())||!point(u.position))return[];
 const pending=(r.waypoints?.length?r.waypoints:r.next?[r.next]:[]).map(point).filter(Boolean),out=[point(u.position)];if(!pending.length)return[];
 for(const p of pending)if(Math.hypot(p[0]-out.at(-1)[0],p[1]-out.at(-1)[1])>1e-6)out.push(p);return out;
}
export function gameForVideo(sync,time){if(!sync?.length)return null;const i=sync.findIndex(x=>x.video>=time);if(i<0)return sync.at(-1).game;if(!i)return sync[0].game;const a=sync[i-1],b=sync[i];return a.game+(b.game-a.game)*(time-a.video)/(b.video-a.video||1);}
export function videoForGame(sync,time){if(!sync?.length)return null;const i=sync.findIndex(x=>x.game>=time);if(i<0)return sync.at(-1).video;if(!i)return sync[0].video;const a=sync[i-1],b=sync[i];return a.video+(b.video-a.video)*(time-a.game)/(b.game-a.game||1);}

// Display focus only: never issues or changes a soldier command.
export function defaultUnit(team,events,calls,{current='',faction,at,level}={}){
 const alive=team.filter(u=>u.faction===faction&&!(u.hp<=0)),ids=new Set(alive.map(u=>u.id));
 if(ids.has(current))return current;
 const decisions=events.filter(e=>e.kind==='soldier'&&e.faction===faction&&e.time<=at&&(!level||e.index>level.index)&&ids.has(e.data?.unitId)&&['selected','queued'].includes(e.data?.status));
 const decided=decisions.reduce((last,e)=>!last||e.time>last.time?e:last,null);
 if(decided)return decided.data.unitId;
 const requests=(calls||[]).filter(c=>c.role==='personal'&&c.faction===faction&&c.requestedAt<=at&&inChapter(c,level)&&ids.has(c.unitId));
 const requested=requests.reduce((last,c)=>!last||c.requestedAt>last.requestedAt?c:last,null);
 return requested?.unitId||alive[0]?.id||'';
}

// Display axes only. The original positions, routes and request records remain unchanged.
export function mapCoordinates(map,events,at,faction,level){
 if(map?.coordinateFrame==='request-grid')return{model:true,scale:1,source:'request'};
 const scaleOf=m=>{
  if(m?.coordinateFrame!=='native-world'||m.source!=='recorded_model_observation'||typeof m.diagram!=='string')return null;
  const lines=m.diagram.split('\n'),rows=lines.filter(s=>s.includes('|')),row=rows[0],cols=row?.split('|')[1]?.trim().split(/\s+/).length;
  const width=m.bounds?.[2]-m.bounds?.[0],scale=cols/width,header=lines.find(s=>s.trim()&&!s.includes('|'));
  const originX=Number(header?.trim().split(/\s+/)[0]),originY=Number(row?.split('|')[0]?.trim());
  return cols>0&&Number.isFinite(scale)&&scale>0&&Number.isFinite(originX)&&Number.isFinite(originY)&&
   Math.abs(m.bounds[0]*scale-originX)<.001&&Math.abs(m.bounds[1]*scale-originY)<.001&&
   Math.abs((m.bounds[3]-m.bounds[1])*scale-rows.length)<.001?scale:null;
 };
 const ownScale=scaleOf(map);if(ownScale)return{model:true,scale:ownScale,source:'request'};
 const rows=events.filter(e=>e.kind==='map'&&e.faction===faction&&e.time<=at&&e.data?.time<=map?.time&&
  (!level||e.index>level.index)&&e.data?.stage===map?.stage&&
  (map?.navigationRevision==null||e.data?.navigationRevision===map.navigationRevision));
 for(let i=rows.length-1;i>=0;i--){const scale=scaleOf(rows[i].data);if(scale)return{model:true,scale,source:'same-stage-request'};}
 return{model:false,scale:1,source:'missing-binding'};
}

// Recorded choice only; holding the card never resumes a former engine action.
export function personalSelection(events,{faction,unit,at,level}={}){
 const event=unit?(events||[]).findLast(e=>e.kind==='soldier'&&e.faction===faction&&e.time<=at&&e.data?.unitId===unit&&['selected','queued'].includes(e.data.status)):null;
 return {event:event||null,previous:!!event&&!!level&&event.index<=level.index};
}
