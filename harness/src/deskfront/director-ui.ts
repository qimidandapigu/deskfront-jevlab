/** Read-only view of the existing analyst, generator and native construction receipts. */
export const directorPanel = `<section id="director-board" class="panel director-board" aria-labelledby="director-title">
<style>
.director-board{margin:18px 0;padding:22px!important}.director-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}.director-head h2{margin-bottom:4px}.director-flow{display:grid;grid-template-columns:1fr 1fr;gap:24px 32px;margin-top:18px}.director-flow article{min-width:0;border-top:1px solid #cfdbd3;padding-top:12px}.director-flow h3{font-size:15px;margin:0 0 8px;color:#126958}.director-flow p{white-space:pre-wrap;overflow-wrap:anywhere;max-width:72ch}.director-board small{display:block;color:#4b645a}.director-board .director-error{color:#96382e}.director-history{margin-top:20px;border-top:1px solid #cfdbd3;padding-top:12px}.director-history ol{padding-left:22px;max-height:260px;overflow:auto}.director-history li{padding:6px 0}.director-board summary{cursor:pointer}.director-board :focus-visible{outline:2px solid #126958;outline-offset:3px}.director-board::selection{background:#c4e8d7}.director-board [hidden]{display:none}.director-board a{color:#126958;text-underline-offset:3px}@media(max-width:680px){.director-flow{grid-template-columns:1fr;gap:16px}.director-board{padding:16px!important}}
</style>
<div class="director-head"><h2 id="director-title">关卡导演 · 从这一局，决定下一关</h2><span id="director-status" class="tag" role="status">等待会话</span></div>
<p id="director-scope" class="muted">读取真实分析与生成记录，接入后自动更新。</p>
<p><a id="director-console-link" href="/runtime/deskfront/director">打开关卡导演台 →</a></p>
<p id="director-error" class="director-error" hidden></p>
<div class="director-flow">
<article><h3>观察到的表现</h3><p id="director-observation">尚未收到战场样本</p><small id="director-sample-time"></small></article>
<article><h3>导演如何理解</h3><p id="director-analysis">等待首次体验分析</p><small id="director-assessment"></small><details><summary>展开完整体验报告</summary><p id="director-full-analysis"></p></details></article>
<article><h3>下一关想带来的体验</h3><p id="director-goal">尚未提出下一关目标</p><details><summary>展开战术问题与布局要求</summary><p id="director-goal-details"></p><small id="director-avoid"></small></details></article>
<article><h3>正在生成与实际落地</h3><p id="director-build">尚未提交关卡</p><small id="director-build-evidence"></small></article>
</div>
<details class="director-history" open><summary>关卡生成记录</summary><ol id="director-history"><li>尚无记录</li></ol></details>
</section>`;

export const directorScript = `
let directorFingerprint='';
function renderDirector(s){
  document.getElementById('director-console-link').href='/runtime/deskfront/director'+(s?.id?'?session='+encodeURIComponent(s.id):'');
  const g=s?.payload?.game||{},w=s?.latest?.observation||{},d=g.worldDirector;
  const fingerprint=JSON.stringify([s?.id,s?.status,d,w.world_growth?.mission?.status]);
  if(fingerprint===directorFingerprint)return;directorFingerprint=fingerprint;
  const put=(name,value)=>document.getElementById('director-'+name).textContent=value;
  const excerpt=value=>value.length>180?value.slice(0,180)+'…':value;
  const statuses={idle:'等待观察',observing:'观察战局',jev_planning:'JEV 正在规划关卡',jev_building:'JEV 正在搭建布局',prepared:'方案已备好，等待提交',submitted:'已提交，等待引擎确认',completed:'关卡已落地',awaiting_preparation:'等待生成',commit_retry:'提交重试中',confirmation_unknown:'落地结果待确认'};
  const receiptNames={completed:'引擎已确认建成',building:'引擎搭建中',queued_not_completed:'已入队，尚未建成',confirmation_unknown:'确认缺失，不能认定建成',rejected:'引擎拒绝',superseded_unconfirmed:'旧方案已失效，未确认建成'};
  const stopped=s?.status==='done';
  put('status',stopped?'会话已结束':!d?'导演未接入':d.generation_blocked?'生成已暂停 · 重复失败':d.analysis_busy?'正在分析体验':statuses[d.status]||d.status||'等待观察');
  put('scope',!d?(g.levelSource==='game-local'?'当前使用游戏内置关卡，没有接入 AI 关卡导演。':'等待 AI 关卡导演连接。'):('观察对象：'+(g.greenController==='harness'?'AI 绿队的对局表现，不是人类玩家能力画像':'当前对局；仅依据实际操作样本判断')+' · '+(stopped?'以下为本局最后记录':'战斗中持续采样，分析定期更新；清场后生成下一关')));
  const error=document.getElementById('director-error');error.textContent=[d?.analysis_error?'体验分析失败：'+d.analysis_error+'；当前保留上次报告。':'',d?.error?(d.recovery?.message||'生成未完成：'+d.error)+'。'+(d.recovery?.next_action||''):''].filter(Boolean).join(' ');error.hidden=!error.textContent;
  const sample=d?.latest_observation,e=d?.experience,goal=e?.next_goal||{},history=Array.isArray(d?.history)?d.history:[],last=history[history.length-1],prep=d?.prepared;
  const mission=sample?.encounter||{},green=sample?.teams?.green;
  const lines=[];
  if(green){lines.push('绿队存活 '+green.alive+' 人'+(typeof green.hp_fraction==='number'?'，总血量比例 '+Math.round(green.hp_fraction*100)+'%':''));}
  if(typeof mission.enemies_remaining==='number')lines.push('本关剩余守军 '+mission.enemies_remaining+' 人');
  if(typeof mission.seconds_without_progress==='number')lines.push('距上次任务进展 '+Math.round(mission.seconds_without_progress)+' 秒');
  put('observation',lines.join('；')||'尚未收到可展示的战场样本');
  put('sample-time',sample?'采样于游戏 '+Number(sample.time).toFixed(1)+' 秒 · 保留最近 '+d.observations+' 个样本':'');
  put('analysis',excerpt(e?.current_analysis||'等待首次体验分析；不预先推断玩家偏好'));
  put('assessment',e?'报告基于游戏 '+Number(e.observed_at).toFixed(1)+' 秒的观察 · 上方为原文节选':'');
  put('full-analysis',e?[e.current_analysis,e.assessment,e.reason].filter(Boolean).join('\\n\\n'):'尚无报告');
  put('goal',goal.experience||'尚未提出下一关目标');
  put('goal-details',goal.experience?['想形成的战术问题：'+goal.tactical_problem,'布局调整：'+goal.layout_change].join('\\n'):'尚无布局要求');
  put('avoid',goal.avoid?'希望避免：'+goal.avoid:'');
  const row=prep||last;
  const kinds={rescue:'营救',assault:'突击',tank:'坦克',mortar:'迫击炮',infantry:'步兵'};
  const brief=typeof row?.layout_brief==='string'?row.layout_brief:row?.layout_brief?.scene_intent;
  put('build',row?[row.reason||'关卡方案', '任务：'+(kinds[row.mission_kind]||row.mission_kind||'待定')+' · 支援：'+(kinds[row.support_type]||row.support_type||'待定'),brief||''].filter(Boolean).join('\\n'):'尚未提交关卡；战斗结束、达到生成条件后才会搭建');
  put('build-evidence',row?(prep?'方案待提交，不代表已建成':receiptNames[row.status]||row.status)+' · '+(row.operation_id?'操作 '+row.operation_id.slice(0,8):'等待操作回执')+(row.macro_call?' · 使用体验报告 '+String(row.macro_call).slice(0,8):' · 无先前体验报告'):'');
  const list=document.getElementById('director-history');list.replaceChildren();
  if(!history.length){const li=document.createElement('li');li.textContent='尚无提交记录';list.append(li);}
  for(const row of history.slice().reverse()){
    const li=document.createElement('li'),title=document.createElement('strong'),p=document.createElement('p'),small=document.createElement('small');
    title.textContent='第 '+(typeof row.growth_revision==='number'?row.growth_revision+1:'?')+' 关 · '+(receiptNames[row.status]||row.status);
    p.textContent=row.reason||(typeof row.layout_brief==='string'?row.layout_brief:row.layout_brief?.scene_intent)||row.option||'等待方案说明';
    small.textContent=(row.macro_call?'依据体验报告 '+String(row.macro_call).slice(0,8):'开局或无体验报告')+' · '+(row.receipt?.message||row.construction?.evidence||'等待引擎回执');
    li.append(title,p,small);list.append(li);
  }
}
`;
