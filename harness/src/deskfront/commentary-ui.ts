export const commentaryPanel = `<section class="panel" style="margin-top:18px" aria-label="战况解说">
<div class="row"><h2>赛事解说 · 解说小明</h2><div><button id="commentary-toggle">关闭解说</button>
<label>音量 <input id="commentary-volume" aria-label="解说音量" type="range" min="0" max="1" step="0.05" value="1" style="width:100px"></label></div></div>
<p id="commentary-caption" aria-live="polite" style="font-size:16px;min-height:2em">声音与字幕会直接出现在游戏窗口，陪你看完整场战斗。</p>
<p id="commentary-state" class="muted">新局默认开启解说 · 可随时关闭 · 平稳时留白 · 文字与语音独立计费，每局各最多600次。</p>
<div class="row"><button id="danmaku-toggle">开启 AI 生成弹幕</button><label>密度 <select id="danmaku-density"><option value="low">低</option><option value="normal">普通</option></select></label><span id="danmaku-state" class="muted">真实模型生成 · 虚拟观众短评 · 独立预算30次 · 不朗读</span></div><details><summary>最近解说</summary><div id="commentary-history"></div></details></section>`;

export const commentaryScript = `
let commentaryEnabled=true,commentarySession=null,commentaryActive=false,commentaryBusy=false,commentaryEpoch=0;
const commentaryLabels={'off':'解说已关闭','ended':'本局已结束','paused':'游戏暂停，解说已暂停','watching':'正在看比赛，等待值得讲的变化','preparing':'正在准备解说','starting':'正在送入游戏','playing':'正在播放 · 游戏内同步字幕','budget':'本局解说额度已用完','spectator-only':'当前仅支持全场观战解说','waiting-native':'等待游戏字幕层就绪；旧对局请重新开局','native-delivery-failed':'游戏未确认播放，请重新开启解说','service-error':'解说暂不可用'};
async function commentaryApi(session,action,body){const r=await fetch('/api/deskfront/commentary/'+session+'/'+action,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw Error('解说服务暂不可用');return r.json()}
function commentaryRender(s){
 $('commentary-toggle').textContent=s.enabled?'关闭解说':'开启解说';
 $('commentary-state').textContent=(commentaryLabels[s.status]||s.status)+' · 文字 '+s.requests+'/'+s.limit+' · 语音 '+s.speechRequests+'/'+s.limit+(s.entry?.source==='facts-fallback'?' · 事实播报':'')+(s.entry?.warning?' · '+s.entry.warning:'');
 const visible=s.enabled&&s.status!=='paused'&&s.playback?.phase==='playing'&&s.playback?.subtitle_visible;
 if(visible)$('commentary-caption').textContent=s.playback.text;
 const overlay=$('commentary-map-caption');if(overlay){overlay.hidden=!visible;overlay.textContent=visible?s.playback.text:''}
 $('commentary-history').replaceChildren();for(const entry of [...(s.history||[])].reverse()){const p=document.createElement('p');p.textContent=Number(entry.observedAt).toFixed(1)+'秒 · '+entry.text;$('commentary-history').append(p)}
}
$('commentary-toggle').onclick=async()=>{commentaryEpoch++;commentaryEnabled=!commentaryEnabled;const wanted=commentaryEnabled;$('commentary-toggle').textContent=wanted?'关闭解说':'开启解说';if(!id){$('commentary-state').textContent=wanted?'开局后自动开启连续解说':'解说已关闭';return}try{const s=await commentaryApi(id,wanted?'start':'stop',{volume:Number($('commentary-volume').value)});commentaryActive=wanted;commentaryRender(s)}catch{$('commentary-state').textContent='解说暂不可用，请重试'}};
$('commentary-volume').onchange=()=>{if(id)commentaryApi(id,'volume',{volume:Number($('commentary-volume').value)}).catch(()=>{})};
async function commentaryTick(){
 try{
  if(commentarySession!==id){if(commentarySession&&commentaryActive)await commentaryApi(commentarySession,'stop',{}).catch(()=>{});commentarySession=id;commentaryActive=false;commentaryEpoch++;$('commentary-history').replaceChildren()}
  if(!id||commentaryBusy)return;
  if(latestId===id&&latest?.status==='done'){commentaryEnabled=false;commentaryActive=false;$('commentary-toggle').textContent='开启解说';$('commentary-state').textContent='本局已结束';const overlay=$('commentary-map-caption');if(overlay)overlay.hidden=true;return}
  commentaryBusy=true;const requestedId=id,epoch=commentaryEpoch;
  const s=commentaryEnabled&&!commentaryActive?await commentaryApi(id,'start',{volume:Number($('commentary-volume').value)}):await commentaryApi(id,'state');
  if(requestedId!==id||epoch!==commentaryEpoch)return;
  commentaryEnabled=s.enabled;commentaryActive=s.enabled;commentaryRender(s);
 }catch{$('commentary-state').textContent='解说暂不可用，稍后重试'}
 finally{commentaryBusy=false;setTimeout(commentaryTick,500)}
}
commentaryTick();
let danmakuWanted=true,danmakuSession=null;
async function danmakuApi(action,session=id){const r=await fetch('/api/deskfront/danmaku/'+session+'/'+action,action==='state'?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({density:$('danmaku-density').value})});if(!r.ok)throw Error('弹幕服务暂不可用');return r.json()}
function showDanmaku(s){if(['payment-required','auth-error'].includes(s.status))danmakuWanted=false;$('danmaku-toggle').textContent=s.enabled?'关闭 AI 生成弹幕':'开启 AI 生成弹幕';$('danmaku-state').textContent='AI 生成弹幕 · '+s.requests+'/'+s.limit+' 次 · '+({'off':'已关闭','watching':'等待新战况','showing':'正在放送','generating':'生成中','paused':'暂停','budget':'额度用完','waiting-native':'等待新版本游戏窗口','retry-later':'稍后重试','payment-required':'模型接口额度不足，已停止请求','auth-error':'模型凭证不可用，已停止请求'}[s.status]||s.status)}
$('danmaku-toggle').onclick=async()=>{danmakuWanted=!danmakuWanted;if(!id){$('danmaku-state').textContent=danmakuWanted?'新局开启后启用弹幕':'已关闭';return}try{showDanmaku(await danmakuApi(danmakuWanted?'start':'stop'));danmakuSession=id}catch(e){$('danmaku-state').textContent=e.message}};
$('danmaku-density').onchange=async()=>{try{if(id&&danmakuWanted)showDanmaku(await danmakuApi('start'))}catch(e){$('danmaku-state').textContent=e.message}};
async function pollDanmaku(){try{if(danmakuSession!==id){if(danmakuSession)await danmakuApi('stop',danmakuSession).catch(()=>{});danmakuSession=id}if(id){const state=await danmakuApi('state');showDanmaku(danmakuWanted&&latest?.status==='running'&&!state.enabled&&!['payment-required','auth-error'].includes(state.status)?await danmakuApi('start'):state)}}catch{}finally{setTimeout(pollDanmaku,2000)}}pollDanmaku();
`;
