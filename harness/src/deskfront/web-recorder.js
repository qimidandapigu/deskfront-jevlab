// Records only this game's canvas. No microphone, screen capture, game commands or AI calls.
const base=new URL(import.meta.url).origin;
const jobId=location.pathname.split('/')[2],launch=window.__deskfrontLaunch;
let recorder,identity,firstWall=0,lastFrame,starting=false,failed=false,queue=Promise.resolve(),queued=0,seq=0,finishing=false;
const badge=document.createElement('div');badge.id='replay-recording-status';badge.setAttribute('role','status');
badge.style.cssText='position:fixed;bottom:7px;right:10px;z-index:6;font:11px system-ui;color:#dae6d4;background:#101a12c9;padding:3px 7px;border-radius:3px;pointer-events:none';
document.body.append(badge);
const note=text=>{badge.textContent=text;};
async function request(path,options){const r=await fetch(base+path,{...options,signal:AbortSignal.timeout(10000)});if(!r.ok){const e=Error('replay_http_'+r.status);e.status=r.status;throw e;}return r.json();}
async function close(complete,reason){if(finishing||!recorder||recorder.state==='inactive')return;finishing=true;recorder._complete=complete;recorder._reason=reason;recorder.stop();}
async function begin(frame){
 starting=true;
 let stream;
 try{
  if(!window.MediaRecorder||!HTMLCanvasElement.prototype.captureStream)throw Error('recording_unsupported');
  const mime=['video/webm;codecs=vp8','video/webm'].find(x=>MediaRecorder.isTypeSupported(x));if(!mime)throw Error('recording_unsupported');
  stream=document.getElementById('canvas').captureStream(15);
  recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:2500000});
  for(let attempt=0;attempt<16;attempt++){
   try{identity=await request('/api/recordings/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jobId,instanceId:launch.instanceId,boot:window.__deskfrontBoot,gameTime:Number(lastFrame?.time??frame.time)})});break;}
   catch(e){if(e.status!==409||attempt===15)throw e;note('正在连接回放录制…');await new Promise(r=>setTimeout(r,2000));}
  }
  firstWall=performance.now();
  recorder.ondataavailable=e=>{
   if(!e.data.size)return;queued+=e.data.size;
   if(queued>32*1024*1024){failed=true;note('回放保存中断');void close(false,'upload-backlog');return;}
   const n=seq++,game=Number(lastFrame?.time??frame.time),video=(performance.now()-firstWall)/1000,blob=e.data;
   queue=queue.then(async()=>{let error;for(let attempt=0;attempt<3;attempt++){try{await request(`/api/recordings/${identity.id}/chunk?seq=${n}&game=${game}&video=${video}`,{method:'POST',headers:{Authorization:'Bearer '+identity.token,'Content-Type':'video/webm'},body:blob});queued-=blob.size;return;}catch(e){error=e;await new Promise(r=>setTimeout(r,500*(attempt+1)));}}throw error;}).catch(()=>{failed=true;note('回放保存中断，已上传部分会保留');void close(false,'upload-failed');throw Error('upload_failed');});
   // Observe rejection immediately while retaining failure for finalization.
   queue.catch(()=>{});
  };
  recorder.onstop=async()=>{stream.getTracks().forEach(x=>x.stop());try{await queue;await request(`/api/recordings/${identity.id}/finish`,{method:'POST',headers:{Authorization:'Bearer '+identity.token,'Content-Type':'application/json'},body:JSON.stringify({complete:!failed&&recorder._complete===true,reason:recorder._reason})});note(failed?'部分回放已保留':'回放已保存 · 开局页查看');}catch{note('回放保存中断，已上传部分会保留');}};
  recorder.onerror=()=>{failed=true;note('回放录制中断');void close(false,'recorder-error');};
  recorder.start(1000);note('● 回放录制中 · 无声');
 }catch{stream?.getTracks().forEach(x=>x.stop());failed=true;note('本局未能录制回放');}
}
window.__deskfrontReplay={observe(frame){lastFrame=frame;if(!starting&&!failed&&frame.linked===true&&Number.isFinite(Number(frame.time)))void begin(frame);}};
// Never start, stop or replay game actions; this polls metadata only.
setInterval(async()=>{if(!recorder||finishing)return;try{const r=await fetch('/api/deskfront/web'),{job}=await r.json();if(job?.id===jobId&&['finished','stopped','failed'].includes(job.status))void close(job.status==='finished','game-'+job.status);}catch{}},2500);
addEventListener('pagehide',()=>{void close(false,'page-left');});
setInterval(()=>{if(identity&&recorder?.state==='recording')void request(`/api/recordings/${identity.id}/heartbeat`,{method:'POST',headers:{Authorization:'Bearer '+identity.token,'Content-Type':'application/json'},body:'{}'}).catch(()=>{});},8000);
