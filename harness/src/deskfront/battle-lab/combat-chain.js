/* Display only: no commands, provider calls or inference from unreturned models. */
function combatChainView(record, at, faction, level) {
 const calls=(record?.calls||[]).filter(c=>c.requestedAt<=at&&c.faction===faction&&(!level||c.requestedAt>=level.time));
 const roleNames={commander:'总指挥',executor:'小队快脑',personal:'个人快脑'};
 const roles={};
 for(const role of Object.keys(roleNames)){
  const rows=calls.filter(c=>c.role===role),latest=rows.at(-1);
  const returned=rows.filter(c=>c.returnedAt!==null&&c.returnedAt<=at).at(-1);
  const failed=latest?.errorAt!==null&&latest?.errorAt<=at&&latest?.errorAt!==undefined;
  const state=!latest?'本关未保存调用':failed?'最近调用异常':latest.returnedAt!==null&&latest.returnedAt<=at?'最近调用已有返回':record.mode==='live'?'最近调用等待返回':'此时未保存返回';
  roles[role]=[returned?.model?'已返回型号 '+returned.model:'型号未记录',state].join(' · ');
 }
 const controls={harness:'Harness 接入',local:'本地算法'};
 const live=record?.mode==='live'?record.live:null;
 const controllers=Object.fromEntries(['green','red'].map(team=>[team,live?(controls[live.controllers?.[team]]||'控制方式未记录'):'历史记录 · 未保存控制方式']));
 const native=live?(live.paused?'当前已暂停':live.status==='running'?'对局运行中 · 算法持续执行': '状态 '+(live.status||'未记录')):'历史回放 · 不驱动当前游戏';
 return {roles,controllers,native,source:(record?.mode==='live'?'本局运行记录':'历史调用记录')+' · 仅展示'+(faction==='red'?'红方':'绿方')+'战术调用；未返回的型号不提前显示。'};
}
function renderCombatChain(record,at,faction,level,visible=[]){
 const value=combatChainView(record,at,faction,level);
 renderTacticalOrders(visible,at,faction,level);
 put('teamLabel',faction==='red'?'红方':'绿方');
 for(const role of ['commander','executor','personal'])put('chain-'+role,value.roles[role]);
 for(const team of ['green','red'])put('chain-'+team,value.controllers[team]);
 put('chain-native',value.native);put('chain-source',value.source);
 $('chainFaction').value=faction;
 const source=$('chapter'),target=$('chainChapter'),signature=[...source.options].map(o=>o.value+':'+o.text).join('|');
 if(target.dataset.options!==signature){target.replaceChildren(...[...source.options].map(o=>o.cloneNode(true)));target.dataset.options=signature;}
 target.disabled=target.options.length<2;
 target.value=level?String(level.time):'';
 const sample=visible.filter(e=>e.kind==='map'&&e.faction===faction&&(!level||e.index>level.index)).at(-1);
 const live=record?.mode==='live'?record.live:null;
 const rows=(live?.units||sample?.data?.units||[]).filter(u=>u.faction===faction&&(u.alive===true||u.hp>0));
 const weapons={rifle:'步枪',smg:'冲锋枪',rocket:'火箭筒',tank:'坦克',mortar:'迫击炮'},counts={};
 for(const u of rows){const kind=u.kind==='tank'?'tank':u.weapon||u.kind;if(weapons[kind])counts[kind]=(counts[kind]||0)+1;}
 put('chainLoadout',Object.entries(counts).map(([k,n])=>n+'×'+weapons[k]).join(' / ')||'未观测');
 $('chainLoadout').title=live?'最近观测':sample?'本方观测采样 '+time(sample.time):'本关暂无本方装备记录';
 put('chain-runtime',(record?.mode==='live'?'实时观测':'历史回放')+' · 模型异步判断，算法持续执行。');
}
if(typeof document!=='undefined'){
 $('chainFaction').onchange=()=>{$('faction').value=$('chainFaction').value;$('faction').dispatchEvent(new Event('change',{bubbles:true}));};
 $('chainChapter').onchange=()=>{if(!$('chainChapter').value)return;$('chapter').value=$('chainChapter').value;$('chapter').dispatchEvent(new Event('change',{bubbles:true}));};
 document.querySelectorAll('[data-chain-open]').forEach(button=>button.onclick=()=>{
  const key=button.dataset.chainOpen;
  const targets={commander:'command-goal',executor:'debugSquad',personal:'debugDecisions',native:'debugDecisions',receipt:'audit',map:'map',record:'liveLLM'};
  const target=$(targets[key]);if(!target)return;
  if(key==='record')target.open=true;
  if(key==='receipt'){document.body.classList.remove('display-mode');$('mode').setAttribute('aria-pressed','true');$('mode').textContent='演示视图';target.open=true;const last=[...$('record').options].filter(o=>events.find(e=>String(e.index)===o.value&&e.time<=cursor&&e.faction===$('faction').value&&e.kind==='squad'&&['accepted','rejected'].includes(e.data.status))).at(-1);if(last){$('record').value=last.value;$('record').dispatchEvent(new Event('change'));}else put('raw','本方此时尚无可核对的小队回执。');}
  target.scrollIntoView({behavior:'instant',block:'center'});
 });
}
