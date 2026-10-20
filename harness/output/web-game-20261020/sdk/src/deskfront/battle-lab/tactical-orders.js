/* Tactical vocabulary from the registered public contracts. Read-only display. */
const tacticalCatalog={
 commander:[
  ['approach','接近目标','向所选目标区域接近，完成条件由指挥官明确。','move'],
  ['engage','交战打击','围绕阶段目标建立交战，是否开火、命中另看记录。','target'],
  ['recover','恢复战力','选择有期限的恢复阶段；不代表已经恢复或获得补员。','recover'],
  ['reposition','调整位置','改变阶段位置，比较新的射位或通路。','move'],
  ['hold','区域守备','守住所选区域，并按实际条件重新评估。','hold'],
  ['equipment:reconnoitre','侦察炮位','侦察已发现的炮位，不把未见炮手说成已发现。','scope',true],
  ['equipment:attack_crew','打击炮组','以已知炮手或警戒兵为目标，不把炮体当作人员。','target',true],
  ['equipment:capture','夺取炮位','决定夺炮阶段，小队再选择执行者、支援者与路线。','capture',true],
  ['equipment:support_fire','利用炮火','把已知炮位用于阶段支援；实际接管、开炮分别核对。','target',true],
  ['equipment:defer','暂缓夺炮','保留已知装备任务，暂缓处理并按条件复评。','hold',true],
 ],
 squad:[
  ['advance','结伴推进','按整套成员分工和合法路线接近目标。','move'],
  ['cover','建立掩护','到所选区域建立并维护火力掩护。','cover'],
  ['bound','交替推进','绑定支援者与机动者，进行有明确支援关系的推进。','bound'],
  ['flank','牵制侧击','一组支援共同威胁，另一组从侧路机动；效果由实战核对。','flank'],
  ['hold','原地守备','在所选区域保持，带有目的、关注对象与复评条件。','hold'],
  ['regroup','重新集结','调整队伍位置与射位，准备重新组织行动。','recover'],
  ['continue_order','继续任务','明确保留已有成员任务、路线、游标和原截止时间。','move'],
  ['revise_order','调整分工','只更改明确指定的成员，其他成员完整保持原任务。','bound'],
  ['support:support_area','区域火力支援','命令坦克或迫击炮支援阶段区域，按规则自动瞄准。','target',true],
  ['support:engage','指定目标打击','命令支援装备集中攻击一个已知目标。','target',true],
  ['support:move_area','坦克前往区域','坦克向阶段区域移动，途中保留合法自卫射击。','move',true],
  ['support:hold_fire','支援装备停火','明确停止支援装备开火并保持位置；不同于个人保持射位。','hold',true],
  ['support:release_crew','炮组撤离','离开炮位，存活炮手随后重新参与步兵任务。','recover',true],
 ],
 personal:[
  ['continue_role','继续职责','继续本兵职责、有效路线与自保，不另下换位命令。','move'],
  ['covered_advance','借掩体推进','在已授权走廊内接近；掩体线索不等于全程安全。','cover'],
  ['local_reposition','局部换位','在本兵职责内调整射位或掩体，不改队友任务。','flank'],
  ['occupy_cover','占据掩体','进入选中的可用掩体位置。','cover'],
  ['peek_fire','探头射击','进入所选掩体，针对已验证射线的敌人探头攻击。','scope'],
  ['hold_fire','保持射位','短时保持有效射位并继续合法射击，保留原路线；不是停火。','hold'],
  ['focus_fire','集中射击','短时集中射击指定目标，会取消当前移动执行。','target'],
  ['grenade','投掷手雷','向验证可投的可见敌步兵投雷；准备不等于已投出。','grenade'],
  ['breach_cover','火箭破障','向选中的可破坏障碍发射一发火箭，复验枪口与安全。','rocket'],
  ['move_to_site','移动选点','移动到当前候选位置，可用于接近、横移或短撤。','move',true],
  ['rush_to_site','短距冲刺','快速移动到候选点，只移动，不自动投弹。','move',true],
  ['prone_approach','匍匐接近','卧姿向候选点接近，移动较慢并降低身体暴露。','cover',true],
  ['approach_satchel','接近后投弹','沿已验证的反坦克候选路段接近指定坦克，再复验投弹。','grenade',true],
  ['satchel','投掷炸药包','近距离向可见敌坦克投掷炸药包，受冷却和检查约束。','grenade',true],
  ['opportunity_action','利用局部机会','在授权内比较一次火力或道具机会，实际动作和结果另核对。','target',true],
  ['report_blocked','报告受阻','报告本兵受阻，请求复评；本身不移动或改目标。','recover',true],
  ['vehicle:continue_task','坦克继续任务','继续小队指定的坦克支援任务与目标。','move',true],
  ['vehicle:hold_position','坦克短停交火','有限短停，保留父任务并继续合法射击。','hold',true],
  ['vehicle:reverse','坦克倒车拉开','选择验证的附近倒车候选，保留小队攻击目标。','move',true],
  ['vehicle:reposition','坦克附近换位','选择验证的附近换位候选，不指定任意坐标。','flank',true],
  ['vehicle:report_blocked','坦克报告受阻','报告坦克局部任务受阻，不自行更改支援目标。','recover',true],
 ],
};
const tacticalIcons={move:'<path d="M4 12h16m-6-6 6 6-6 6"/>',target:'<circle cx="12" cy="12" r="7"/><path d="M12 2v6m0 8v6M2 12h6m8 0h6"/>',scope:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6M10 7v6m-3-3h6"/>',cover:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/>',hold:'<path d="M8 4v16M16 4v16"/>',recover:'<path d="M5 8a8 8 0 1 1-1 7M5 3v5h5"/>',flank:'<path d="M4 20V9h15m-5-5 5 5-5 5"/>',bound:'<path d="M4 18V6h9m-3-3 3 3-3 3M20 6v12h-9m3-3-3 3 3 3"/>',grenade:'<path d="M11 6V3h5M16 3l3 3"/><circle cx="11" cy="14" r="7"/>',rocket:'<path d="m4 20 6-6M8 16l-3-3L17 2l5 5-11 12-3-3M16 4l4 4"/>',capture:'<path d="M5 22V3m0 0h14l-3 5 3 5H5"/>'};
const tacticalStatuses={planned:'指挥意图',selected:'模型选择',submitted:'已提交',accepted:'接受',rejected:'拒绝',queued:'已入队',queue_rejected:'入队拒绝',unknown:'状态未知'};
const tacticalManeuvers={advance:'推进',flank:'侧击',bound:'交替推进',hold:'守备',regroup:'重整',engage:'交战',recover:'恢复',reconnoitre:'侦察'};
const tacticalStepLabels={move:'移动',attack:'攻击',suppress:'压制',capture:'占领／夺取',support:'支援',hold:'守备',reconnoitre:'侦察',recover:'恢复'};
function tacticalOrdersState(visible,at,faction,level){
 const scoped=(visible||[]).filter(e=>e.time<=at&&e.faction===faction&&(!level||e.index>level.index));
 const result={commander:[],squad:[],personal:[],plan:'',autonomous:false};
 const c=scoped.filter(e=>e.kind==='command').at(-1);
 if(c){
  result.autonomous=c.data.source==='jev_autonomous'||c.data.sourceType==='human-autonomous-plan';
  if(!result.autonomous){
   if(c.data.stage)result.commander.push({key:c.data.stage,status:'planned',time:c.time,unit:'',event:c});
   if(c.data.equipment_goal?.phase)result.commander.push({key:'equipment:'+c.data.equipment_goal.phase,status:'planned',time:c.time,unit:'',event:c});
   const b=c.data.tactical_brief;
   if(b)result.plan=[tacticalManeuvers[b.maneuver]||'',(b.steps||[]).map(s=>tacticalStepLabels[s.action]||s.action).join(' → ')].filter(Boolean).join(' · ');
  }
 }
 const s=scoped.filter(e=>e.kind==='squad').at(-1);
 if(s)result.squad.push({key:s.data.intent,status:s.data.status,time:s.time,unit:'',event:s});
 const supports=new Map();for(const e of scoped.filter(e=>e.kind==='support'))supports.set(e.data.assetId,e);
 for(const e of supports.values())result.squad.push({key:'support:'+e.data.mode,status:e.data.status,time:e.time,unit:e.data.assetId,event:e});
 const personal=new Map();for(const e of scoped.filter(e=>e.kind==='soldier'&&e.data.status!=='unlinked_receipt')){
  // Legacy soldier receipts lack decision identity. Keep a receipt in its own
  // viewer; never attach it to the nearest preceding model choice.
  if(!['selected','queued','queue_rejected'].includes(e.data.status)&&!e.data.linkedDecision)continue;
  personal.set(e.data.unitId,e);
 }
 for(const e of personal.values()){
  const d=e.data;
  let key=d.unitKind==='tank'?'vehicle:'+d.choice:d.choice==='continue_task'?(d.behavior||'continue_role'):d.choice==='hold_fire_position'?'hold_fire':d.choice;
  if(!tacticalCatalog.personal.some(r=>r[0]===key)&&d.behavior)key=d.behavior;
  result.personal.push({key,status:d.status,time:e.time,unit:d.unitId,event:e});
 }
 return result;
}
let tacticalRendered=false,tacticalState=null;
const tacticalDetailSelection={};
function tacticalDefinition(role,key){return tacticalCatalog[role].find(row=>row[0]===key);}

// One recorded choice, using the same vocabulary and icons as the commander.
// This is a disclosure of saved evidence, never an actionable game command.
function recordedChoiceMeaning(role,record){
 const definition=tacticalDefinition(role,record.key);
 if(role!=='personal'||record.key!=='continue_role')return{title:definition?.[1]||'未分类选择',description:definition?.[2]||'原始选择：'+record.key};
 const duties={fire_support:'火力支援',maneuver:'机动推进',establish_fire:'建立射位'};
 const duty=duties[record.assignmentRole];
 return{title:duty?'继续'+duty:'继续已分配任务',description:duty?'继续选择当时已分配的“'+duty+'”任务，保留有效路线和自保；这是任务选择，不表示已经到位或正在开枪。':'继续当时已分配的任务；本条选择缺少可核对的职责记录，不用之后的新分工补写。'};
}
function recordedOrderTile(role,record){
 const definition=tacticalDefinition(role,record.key),meaning=recordedChoiceMeaning(role,record),wrap=document.createElement('details');
 wrap.className='recorded-order';wrap.dataset.record=[role,record.unit||'',record.key,record.time].join('|');
 wrap.open=recordedOrderOpen.has(wrap.dataset.record);
 wrap.ontoggle=()=>{if(wrap.open)recordedOrderOpen.add(wrap.dataset.record);else recordedOrderOpen.delete(wrap.dataset.record);};
 const tile=node('summary','','order-tile recorded-tile');tile.dataset.role=role;tile.dataset.command=record.key;
 tile.dataset.issued='true';tile.dataset.state=record.status;
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
 svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.innerHTML=tacticalIcons[definition?.[3]||'move'];
 const copy=node('span','','order-copy');copy.append(node('strong',meaning.title),node('small',(tacticalStatuses[record.status]||'状态未记录')+' · '+time(record.time)));
 tile.append(svg,copy);
 wrap.append(tile,node('p',meaning.description,'recorded-explain'));
 return wrap;
}
const recordedOrderOpen=new Set();

function renderTacticalOrders(visible,at,faction,level){
 tacticalState=tacticalOrdersState(visible,at,faction,level);
 if(!tacticalRendered){tacticalRendered=true;
  for(const [role,title] of [['commander','DeepSeek · 指挥官']]){
   const group=node('section','','orders-role');group.dataset.role=role;
   const heading=node('h3',title);heading.append(node('span',role==='commander'?'阶段与装备意图':role==='squad'?'整套配合与支援':'本兵授权内选择'));group.append(heading);
   const grid=node('div','','orders-grid'),more=document.createElement('details'),extra=node('div','','orders-grid');more.className='orders-extra';more.append(node('summary',role==='commander'?'装备任务':role==='squad'?'坦克／迫击炮支援指令':'更多动作与坦克指令'),extra);
   for(const [key,label,description,icon,optional] of tacticalCatalog[role]){
    const button=document.createElement('button');button.type='button';button.className='order-tile';button.dataset.role=role;button.dataset.command=key;button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls','order-detail-'+role);button.title=description;
    const line=node('span','','order-label'),svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.innerHTML=tacticalIcons[icon];line.append(svg,node('span',label));button.append(line);button.onclick=()=>{tacticalDetailSelection[role]=tacticalDetailSelection[role]===key?null:key;renderTacticalDetail(role);};(optional?extra:grid).append(button);
   }
   const status=node('p','','orders-status');status.id='order-status-'+role;
   const plan=node('p','','orders-plan');plan.id='order-plan-'+role;
   const detail=node('div','','orders-explain');detail.id='order-detail-'+role;detail.hidden=true;
   group.append(grid,more,status,plan,detail);$('orders-groups').append(group);
  }
 }
 for(const role of ['commander']){
  const rows=tacticalState[role];
  for(const button of document.querySelectorAll('.order-tile[data-role="'+role+'"]')){
   const matched=rows.filter(r=>r.key===button.dataset.command),recent=matched.at(-1);
   button.dataset.issued=String(matched.length>0);button.dataset.state=recent?.status||'';
   button.querySelector('small')?.remove();if(recent)button.append(node('small',(tacticalStatuses[recent.status]||recent.status)+(matched.length>1?' · '+matched.length+'人':'')));
  }
  const descriptions=[...new Set(rows.map(r=>{const d=tacticalDefinition(role,r.key);return(d?.[1]||'未分类指令')+' · '+(tacticalStatuses[r.status]||r.status)+' · '+time(r.time);}))];
  put('order-status-'+role,descriptions.length?'最近记录：'+descriptions.join('；'):role==='commander'&&tacticalState.autonomous?'本段由 JEV 自主选择目标，未冒称 DeepSeek 指令。':'本关此时暂无可核对的指令记录。');
  put('order-plan-'+role,role==='commander'&&tacticalState.plan?'指挥示意：'+tacticalState.plan:'');
  // Show selected equipment/vehicle actions without hiding their highlight in "more".
  const group=document.querySelector('.orders-role[data-role="'+role+'"]'),more=group.querySelector('.orders-extra');
  if(rows.some(r=>tacticalDefinition(role,r.key)?.[4]))more.open=true;
  renderTacticalDetail(role);
 }
}
function renderTacticalDetail(role){
 const key=tacticalDetailSelection[role],detail=$('order-detail-'+role),definition=tacticalDefinition(role,key);
 for(const b of document.querySelectorAll('.order-tile[data-role="'+role+'"]'))b.setAttribute('aria-expanded',String(b.dataset.command===key));
 detail.hidden=!definition;detail.replaceChildren();if(!definition)return;
 const entries=tacticalState[role].filter(r=>r.key===key);detail.append(node('strong',definition[1]),node('p',definition[2]));
 if(entries.length)for(const r of entries)detail.append(node('small',(r.unit?r.unit+' · ':'')+time(r.time)+' · '+(tacticalStatuses[r.status]||r.status)));
 else detail.append(node('small','这是当前协议中的指令；本关此时未见本方最近选择它。'));
}
