const base=new URL(import.meta.url).origin,$=id=>document.getElementById(id);
let rows=[],limit=8,selected=null,lastList='';
const time=value=>new Date(value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
function draw(){
 const visible=rows.filter(x=>(!$('replay-only').checked||x.hasVideo)&&!(x.status==='failed'&&x.jobId&&rows.some(y=>y.jobId===x.jobId&&y.id!==x.id&&(y.hasVideo||y.status==='recording')))),list=$('replay-list');list.replaceChildren();
 for(const row of visible.slice(0,limit)){
  const item=document.createElement('li'),copy=document.createElement('div'),title=document.createElement('strong'),note=document.createElement('small'),actions=document.createElement('div');
  const parts=row.jobId?rows.filter(x=>x.jobId===row.jobId&&x.status!=='failed'):[];
  title.textContent=time(row.createdAt)+' · '+row.title+(parts.length>1?' · 第 '+parts.filter(x=>x.createdAt<=row.createdAt).length+' 段':'');
  const states={recording:'正在录制，结束后可播放',processing:'录像正在保存',failed:'录像未保存成功',partial:'片段回放 · 从游戏 '+Math.floor(row.startGameTime??0)+' 秒起'};
  note.textContent=states[row.status]??row.note;copy.append(title,note);actions.className='replay-actions';
  if(row.hasVideo){const play=document.createElement('button');play.textContent='从头回放';play.onclick=()=>open(row);actions.append(play);}
  if(row.session){const link=document.createElement('a');link.textContent='战斗记录 ↗';link.href='/?view=lab&tab=combat&session='+encodeURIComponent(row.session)+'&at=0';link.target='_blank';link.rel='noopener';actions.append(link);}
  item.append(copy,actions);list.append(item);
 }
 $('replay-more').hidden=visible.length<=limit;$('replay-empty').hidden=visible.length>0;$('replay-message').textContent=`${rows.filter(x=>x.hasVideo).length} 段可回放录像`;
}
async function refresh(){try{const r=await fetch(base+'/api/replays',{cache:'no-store',signal:AbortSignal.timeout(10000)});if(!r.ok)throw Error();const v=await r.json(),key=JSON.stringify(v.rows);if(key!==lastList){lastList=key;rows=v.rows;draw();}}catch{$('replay-message').textContent='回放服务暂不可用，请稍后刷新';}}
async function open(row){
 selected=row.id;const video=$('replay-video');video.pause();video.src=base+'/api/replays/'+encodeURIComponent(row.id)+'/media';video.playbackRate=Number($('replay-speed').value);video.load();
 $('replay-player').hidden=false;$('replay-title').textContent=time(row.createdAt)+' · '+row.title;
 $('replay-note').textContent=(row.sound===false?'游戏画面回放 · 无声音和人物浮层。':'历史录像。')+' '+row.note;
 const chapters=$('replay-chapters');chapters.replaceChildren(new Option('从头播放','0'));chapters.disabled=true;
 $('replay-player').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
 video.play().catch(()=>{if(selected===row.id)$('replay-note').textContent+=' 点击播放开始观看。';});
 // Existing Web segments can contain a restarted Godot run under one job/session.
 // Do not map those videos to another run's deployment clock.
 if(row.kind==='obs')try{const r=await fetch(base+'/api/replays/'+row.id+'/detail'),v=await r.json();if(selected!==row.id)return;for(const c of v.chapters??[])chapters.add(new Option('第 '+c.level+' 关',String(c.time)));chapters.disabled=chapters.options.length<2;}catch{}
}
$('replay-only').onchange=()=>{limit=8;draw();};$('replay-more').onclick=()=>{limit+=12;draw();};$('replay-refresh').onclick=refresh;
$('replay-restart').onclick=()=>{const v=$('replay-video');v.currentTime=0;v.play().catch(()=>{});};
$('replay-speed').onchange=()=>{$('replay-video').playbackRate=Number($('replay-speed').value);};
$('replay-chapters').onchange=()=>{const v=$('replay-video');v.currentTime=Number($('replay-chapters').value);v.play().catch(()=>{});};
$('replay-close').onclick=()=>{$('replay-video').pause();$('replay-video').removeAttribute('src');$('replay-video').load();$('replay-player').hidden=true;selected=null;};
$('replay-fullscreen').onclick=()=>{$('replay-video').requestFullscreen().catch(()=>{$('replay-note').textContent+=' 当前浏览器不支持全屏。';});};
$('replay-video').onerror=()=>{$('replay-note').textContent='这段录像暂时无法播放，文件可能缺失或尚未保存完成。';};
refresh();setInterval(refresh,10000);
