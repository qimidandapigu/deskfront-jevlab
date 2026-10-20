import {generationSummary,flowCaptions,sceneAt,availablePhases,steps,generationChoices} from './generation-model.js';
import {drawGeneration,ViewportControls} from './generation-scene.js';
import {GenerationGame} from './generation-game.js';
const $=id=>document.getElementById(id),put=(id,value)=>$(id).textContent=value??'',el=(tag,text)=>Object.assign(document.createElement(tag),{textContent:text??''});
const params=new URLSearchParams(location.search),api='/api/deskfront/director/';
let session=params.get('session')||'',selected=params.get('stage')||'',data=null,follow=!selected,serial=0,abort=null,timer=null;
const embedded=params.get('embed')==='1';let surfaceActive=!document.hidden;if(embedded){document.documentElement.classList.add('embedded');$('session').closest('label').hidden=true;document.querySelector('.generation-toolbar').append($('connection'));}
// Playback seconds are separate from the established choreography coordinates.
const duration=15,toMotionTime=t=>t*2,firstTime=s=>(availablePhases(s).find(p=>p.available)?.at??17)/2;
let playTime=duration,playing=false,lastFrame=0,selectedStep=3,sceneKey='',layers={cover:true,route:true,units:true};
// Video drives stage selection; this path never seeks the video back.
function followVideo({session:id,operation,gameTime}){
 if(id!==session||!data)return;
 if(gameTime===null){put('notice','这一段没有保存时钟对齐，左侧保留所选记录。');return;}
 const stage=data.stages?.find(s=>s.id===operation),next=stage?.id||'';
 put('notice',stage?'':operation?'这一时刻对应的关卡生成记录未保存。':'录像尚未到首关建成；左侧暂无对应方案。');
 if(selected===next)return;
 selected=next;follow=false;playing=false;$('chapter').value=selected;render({locateGame:false});
}
const game=new GenerationGame(followVideo);
let modelView;
let choiceKey='',inspectedChoice='';
const icons={forces:'<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M8 6h8M8 11h2m4 0h2M8 15h2m4 0h2M8 19h2m4 0h2"/>',observe:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',plan:'<circle cx="12" cy="18" r="2"/><circle cx="5" cy="5" r="2"/><circle cx="19" cy="5" r="2"/><path d="M12 16V11L6 7m6 4 6-4"/>',generate:'<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="10" y="10" width="4" height="4"/><path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4"/>',validate:'<path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6Z"/><path d="m8 12 3 3 5-6"/>',apply:'<path d="M3 12h18m-7-7 7 7-7 7"/>'};
const current=()=>data?.stages?.find(s=>s.id===selected)||null;
function links(){const q='?session='+encodeURIComponent(session);$('battle-tab').href='/?view=lab&tab=combat&session='+encodeURIComponent(session);$('brand-battle').href=$('battle-tab').href;$('generation-tab').href='/?view=lab&tab=generation&session='+encodeURIComponent(session);$('original-records').href='/runtime/deskfront/director'+q+'&view=records';history.replaceState(null,'','?view=generation&session='+encodeURIComponent(session)+(embedded?'&embed=1':'')+(selected?'&stage='+encodeURIComponent(selected):''));if(embedded)parent.postMessage({type:'deskfront-generation-session',session},location.origin);}
function fact(name,value){const dl=$('facts');dl.append(el('dt',name),el('dd',value||'未记录'));}
function renderDetails(s){$('facts').replaceChildren();if(!s){put('raw','');return;}
 fact('身份',s.id+' · 第'+s.index+'关');fact('策略来源',s.reportId?('DeepSeek 报告 '+s.reportId+(s.analysis?'':'（正文未保存）')):'JEV 自主策划／未采用导演报告');
 fact('实际采用的体验安排',s.analysis?.goal?.experience);fact('当时的分析',s.analysis?.text);fact('关卡策划',s.planning?.intent||s.intent);
 fact('兵力意图',s.forceIntent?JSON.stringify(s.forceIntent):null);fact(s.forcesConfirmed?'确认部署':'计划编成',s.forceSummary);
 fact('实际选择',s.planning?.decisions?.map(x=>x.label+'：'+x.choiceLabel+(x.selection==='fixed'?'（给定条件）':x.selection==='choice'?'（模型选择）':'（菜单未记录）')).join('；'));
 fact('绑定调用',[s.plannerId&&'JEV策划 '+s.plannerId,...(s.builderIds||[]).map(x=>'JEV搭建 '+x)].filter(Boolean).join('；'));
 fact('回执',s.status+' · '+(s.message||'无附加说明'));fact('几何来源',s.assembly?.note||'尚无可用完成几何');
 fact('通路与部署',[s.assembly?.notes?.routes,s.assembly?.deployment?.note].filter(Boolean).join(' '));
 put('raw',JSON.stringify(s,null,2));
}
function flowDetail(index,s){const summary=generationSummary(s),messages=[
 s?.observation?'使用本次生成绑定的观测；不混用之后的战况。':'该关没有保存可绑定的观测；不从最新战况补写。',
 summary.states[1]==='done'?'DeepSeek 的已完成体验安排与本次生成关联。':summary.states[1]==='skipped'?'本次没有采用 DeepSeek 报告，JEV 自主策划；生成不等待慢脑。':'没有找到对应报告正文，不推断它的内容。',
 s?.forceSummary?('兵力推荐算法按已选难度、补员许可、兵种范围及当时队伍状态计算人数。'+(s.forcesConfirmed?'确认部署：':'计划清单：')+s.forceSummary+'。不决定路线和站位。'):'没有保存本关人数清单，不推测计算结果。',
 s?.builderIds?.length?'JEV 返回策划和空间批次；采用算法人数清单，设计布局、路线与部署。':'没有保存空间搭建批次。',
 s?.status==='completed'?'完成回执确认构建已通过；这不代表体验效果已经验证。':'仅按已保存的检查或失败记录显示，不把模型返回当作通过。',
 s?.status==='completed'?'引擎已确认建成；预演只使用该操作的布局与部署位置。':'尚无本次引擎完成回执，不能显示已建成。'];
 put('step-description',messages[index]);
}
function renderFlow(s,summary){const captions=flowCaptions(s,summary);$('flow').replaceChildren();steps.forEach(([key,label],i)=>{
 const b=el('button');b.type='button';b.className='flow-step';b.dataset.state=summary.states[i];b.dataset.step=key;b.setAttribute('aria-pressed',String(i===selectedStep));b.setAttribute('aria-label',label+'，'+captions[i]);
 const symbol=el('span');symbol.className='flow-icon';symbol.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true">'+icons[key]+'</svg>';const heading=el('b',label.split(' · ')[0]);if(label.includes(' · ')){const separator=el('span',' · '),role=el('span',label.split(' · ')[1]);separator.className='flow-separator';role.className='flow-role';heading.append(separator,role);}b.append(symbol,heading,el('small',captions[i]));b.onclick=()=>{selectedStep=i;renderFlow(current(),generationSummary(current()));renderChoices();};$('flow').append(b);
 });flowDetail(selectedStep,s);
}
function draw(){const s=current(),scene=sceneAt(s,toMotionTime(playTime));
 drawGeneration($('model'),scene,{abstract:true,animate:true,time:toMotionTime(playTime),view:modelView?.view});
 put('scene-phase',scene?.note||scene?.phase||'');
 $('seek').value=String(playTime);put('position',playTime.toFixed(1)+' / '+duration+' 秒');put('play',playing?'暂停':'播放');
}
const choiceIcons={north_hook:'M8 34V21q0-7 7-7h12V5m-5 5 5-5 5 5',south_hook:'M8 5v10q0 7 7 7h12v12m-5-5 5 5 5-5',split_lanes:'M20 35V24M20 24 8 14V5m0 0L4 9m4-4 4 4M20 24l12-10V5m0 0-4 4m4-4 4 4',central_breach:'M20 35V5m-6 6 6-6 6 6',offset_pockets:'M7 35V26l26-12V5m-6 6 6-6 5 6',defended_corner:'M7 34V18h25V5m-6 6 6-6 5 6'};
function renderChoices(){
 const s=current(),groups=generationChoices(s,selectedStep),old=$('choice-kind').value;
 $('choice-kind').replaceChildren();for(const group of groups){const option=el('option',group.label);option.value=group.key;$('choice-kind').append(option);}
 if(groups.some(g=>g.key===old))$('choice-kind').value=old;
 const group=groups.find(g=>g.key===$('choice-kind').value)||groups[0];$('choice-kind').hidden=groups.length<2;$('choice-cards').replaceChildren();
 put('choices-title',selectedStep===1?'采用设置':'可选方案');
 if(!group){put('choice-note',selectedStep===2?'算法计算人数，不是模型候选选择。'+(s?.forceSummary?((s.forcesConfirmed?'确认部署：':'计划清单：')+s.forceSummary):'本关清单未记录。'):selectedStep===3?'本次未保存完整候选菜单，不补画其他选项。':selectedStep===1?'本关未保存可核对的 DeepSeek 候选菜单。':'该环节没有模型选择菜单。');put('choice-inspection','');return;}
 const key=(s?.id||'')+'|'+group.key;if(choiceKey!==key){choiceKey=key;inspectedChoice=group.selected;}
 for(const option of group.options){const button=el('button');button.type='button';button.className='choice-card';button.dataset.option=option.id;button.dataset.selected=String(option.id===group.selected);button.setAttribute('aria-pressed',String(option.id===inspectedChoice));
 const glyph=el('span');glyph.className='choice-glyph';glyph.innerHTML='<svg viewBox="0 0 40 40" aria-hidden="true"><path d="'+(choiceIcons[option.id]||'M8 30V10h24v20ZM14 20h12m-6-6v12')+'"/></svg>';
 button.append(glyph,el('span',option.label));if(option.id===group.selected){const tick=el('small',group.source==='adopted_only'?'已采用':group.fixed?'给定':'已选');tick.className='choice-selected';button.append(tick);}
 button.onclick=()=>{inspectedChoice=option.id;renderChoices();};$('choice-cards').append(button);
 }
 const chosen=group.options.find(o=>o.id===group.selected),inspected=group.options.find(o=>o.id===inspectedChoice);
 put('choice-note',group.source==='adopted_only'?'只保存了最终采用设置；完整候选菜单未记录。':group.fixed?'本次只有一个给定条件，不能视为自主比较。':group.options.length+' 项已记录候选 · '+(group.source==='recorded_choice_trace'?'来自当次选择记录':'来自旧版返回的选项键'));
 put('choice-inspection',group.actor+' · '+group.label+'；'+(inspectedChoice===group.selected?'本次采用：'+chosen.label:'查看：'+inspected?.label+'；本次采用：'+chosen.label)+'。只读查看。');
}
$('choice-kind').onchange=()=>renderChoices();
function render({locateGame=true}={}){const s=current(),summary=generationSummary(s);put('strategy-title',summary.title);put('strategy-description',summary.description);put('strategy-source',summary.source);
 for(const key of ['challenge','kinds','support'])put(key,summary[key]);put('build-status',summary.status||'等待回执');
 put('input-summary',s?.observation?[Number.isFinite(s.observation.greenAlive)?'当时存活 '+s.observation.greenAlive+' 人':'',Number.isFinite(s.observation.health)?'生命保留 '+Math.round(s.observation.health*100)+'%':''].filter(Boolean).join(' · ')||'数值未记录':'没有关联观测');
 put('next-observation',s?.analysis?.goal?.tactical_problem||'体验效果未验证');put('map-state',s?'第'+s.index+'关 · 已保存方案':'等待记录');put('geometry-note',s?.assembly?'2.5D 模块预演 · 桌面自带物件；时间为展示编排。':'尚无完成几何，不用示意地图替代。');
 renderFlow(s,summary);renderDetails(s);const enabled=!!s?.assembly;for(const id of ['play','seek','replay'])$(id).disabled=!enabled;

 const key=session+'|'+selected+'|'+!!s?.assembly;if(sceneKey!==key){modelView.reset();const auto=!!s?.assembly&&!document.hidden&&surfaceActive;sceneKey=key;playing=auto;playTime=auto?firstTime(s):duration;lastFrame=performance.now();}
 modelView.setEnabled(enabled);renderChoices();game.bind(session,selected,s,{locate:locateGame});draw();links();
}
function clearSession(){data=null;selected='';sceneKey='';playing=false;playTime=duration;$('chapter').replaceChildren(el('option','读取关卡…'));render();}
async function load(){clearTimeout(timer);abort?.abort();const request=new AbortController();abort=request;const mine=++serial,scope=session;$('refresh').disabled=true;
 try{const r=await fetch(api+encodeURIComponent(session),{signal:request.signal,cache:'no-store'});if(!r.ok)throw Error(r.status===404?'未找到这局生成记录，请切换对局。':'生成记录读取失败，请刷新重试。');const value=await r.json();if(mine!==serial||session!==scope)return;data=value;put('notice',value.error?'生成记录包含错误：'+value.error:'');
 put('connection',value.mode==='live'?'实时生成 · 每2.5秒同步':'历史记录 · 只读回放');
 const stages=Array.isArray(value.stages)?value.stages:[];$('chapter').replaceChildren();for(const s of stages){const o=el('option','第'+s.index+'关 · '+(({completed:'已建成',building:'搭建中',queued_not_completed:'等待回执',rejected:'未通过'})[s.status]||s.status||'状态未记录'));o.value=s.id;$('chapter').append(o);}
 if(!stages.length){const o=el('option','暂无生成记录');o.value='';$('chapter').append(o);}
 if(follow||!stages.some(s=>s.id===selected))selected=stages.at(-1)?.id||'';$('chapter').value=selected;render();
 }catch(e){if(e.name!=='AbortError'&&mine===serial){put('notice',e.message);put('connection','连接中断 · 当前画面为已保存记录');playing=false;}}
 finally{if(mine===serial){$('refresh').disabled=false;if(data?.mode==='live'&&!document.hidden&&surfaceActive)timer=setTimeout(load,2500);}}
}
async function changeSession(id){abort?.abort();serial++;session=id;follow=true;clearSession();links();if(session)await load();}
async function init(){render();try{const r=await fetch(api+'sessions',{cache:'no-store'});if(!r.ok)throw Error('对局列表读取失败，请刷新页面。');const rows=(await r.json()).sessions||[];if(session&&!rows.some(r=>r.id===session))rows.unshift({id:session,mode:'recording'});$('session').replaceChildren();for(const row of rows){const o=el('option',(row.mode==='live'?'实时 · ':'记录 · ')+row.id.slice(-8));o.value=row.id;$('session').append(o);}if(!rows.length){put('connection','暂无对局');put('notice','先运行一局，再查看生成记录。');return;}session=session||rows[0].id;$('session').value=session;links();await load();}catch(e){put('notice',e.message);put('connection','读取失败');}}
$('session').onchange=()=>changeSession($('session').value);$('chapter').onchange=()=>{selected=$('chapter').value;follow=false;playing=false;render();};$('refresh').onclick=load;$('latest').onclick=()=>{follow=true;selected=data?.stages?.at(-1)?.id||'';$('chapter').value=selected;render();};
$('open-details').onclick=()=>{const d=$('generation-details');d.open=!d.open;$('open-details').setAttribute('aria-expanded',String(d.open));if(d.open)d.scrollIntoView({block:'nearest',behavior:'instant'});};$('generation-details').addEventListener('toggle',()=>{$('open-details').setAttribute('aria-expanded',String($('generation-details').open));});
function start(){if(!current()?.assembly)return;if(playTime>=duration)playTime=firstTime(current());playing=true;lastFrame=performance.now();draw();}
$('play').onclick=()=>{if(playing){playing=false;draw();}else start();};$('replay').onclick=()=>{playTime=firstTime(current());start();};$('seek').oninput=()=>{playing=false;playTime=Number($('seek').value);draw();};
document.addEventListener('visibilitychange',()=>{if(document.hidden){playing=false;clearTimeout(timer);}else{draw();if(data?.mode==='live'&&surfaceActive)load();}});
new ResizeObserver(()=>draw()).observe($('assembly-player'));new ResizeObserver(()=>draw()).observe($('model'));
function frame(now){if(playing&&!document.hidden&&surfaceActive){playTime=Math.min(duration,playTime+Math.min(.1,(now-lastFrame)/1000)*Number($('speed').value));if(playTime>=duration)playing=false;draw();}lastFrame=now;requestAnimationFrame(frame);}requestAnimationFrame(frame);modelView=new ViewportControls({viewport:$('model-viewport'),prefix:'model-view-',fullscreen:$('assembly-player'),onChange:()=>draw()});init();

window.addEventListener('message',event=>{if(!embedded||event.origin!==location.origin||event.source!==parent||event.data?.type!=='deskfront-surface-visibility')return;surfaceActive=event.data.active===true;game.setVisible(surfaceActive);if(!surfaceActive){playing=false;clearTimeout(timer);}else if(data?.mode==='live')load();draw();});
