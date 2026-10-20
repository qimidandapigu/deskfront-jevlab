/** Local video storage, independent of the live game/AI process. */
import { createServer, type IncomingMessage } from 'node:http';
import { createReadStream } from 'node:fs';
import { readFile, writeFile, appendFile, mkdir, readdir, stat, rename } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID, createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { projectOverview } from '../output/web-game-20261020/sdk/src/deskfront/overview-view.js';

const uuid=/^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i;
const sessionId=/^deskfront-[a-zA-Z0-9-]+$/;
const localOrigin=/^http:\/\/(127\.0\.0\.1|localhost):\d{1,5}$/;
const archiveReason=(s:any)=>({'first-defeat':'本局战败结束','capture-frozen':'录到部分画面，曾出现停滞','recording-error':'录制异常结束，可能不完整','recording-stopped-externally':'录制被中止，片段保留','max-duration':'达到录制时长上限','completed':'对局结束'}[s.reason as string]??'历史录制，完整性未核验');
const json=async(path:string)=>JSON.parse(await readFile(path,'utf8'));
const digest=(data:Buffer|string)=>createHash('sha256').update(data).digest('hex');
const dirs=async(path:string)=>(await readdir(path,{withFileTypes:true}).catch(()=>[])).filter(x=>x.isDirectory()&&!x.isSymbolicLink()).map(x=>x.name);
async function body(req:IncomingMessage,max=16384){const chunks:Buffer[]=[];let size=0;for await(const chunk of req){size+=chunk.length;if(size>max)throw Error('body_too_large');chunks.push(chunk);}return Buffer.concat(chunks);}
export function byteRange(range:string|undefined,size:number){
 if(!range)return{start:0,end:size-1,partial:false};
 const m=/^bytes=(\d*)-(\d*)$/.exec(range);if(!m||!m[1]&&!m[2])return null;
 const start=m[1]?Number(m[1]):Math.max(0,size-Number(m[2]));
 const end=m[1]&&m[2]?Math.min(Number(m[2]),size-1):size-1;
 return Number.isSafeInteger(start)&&Number.isSafeInteger(end)&&start>=0&&start<size&&end>=start?{start,end,partial:true}:null;
}
function run(file:string,args:string[]){return new Promise<void>((ok,no)=>{const p=spawn(file,args,{windowsHide:true,stdio:'ignore'});const deadline=setTimeout(()=>p.kill(),60000);p.once('error',e=>{clearTimeout(deadline);no(e);});p.once('exit',code=>{clearTimeout(deadline);code===0?ok():no(Error('video_finalize_failed'));});});}
export function createReplayService(root:string,options:{work?:string;ffmpeg?:string}={}){
 const web=resolve(root,'output/web-game-20261020'),work=options.work??resolve(web,'replays');
 const active=new Map<string,{token:string;meta:any;busy:boolean;ending:boolean;lastHash:string}>();
 let listing:any[]=[];
 async function save(meta:any){const path=resolve(work,meta.id);await mkdir(path,{recursive:true});await writeFile(resolve(path,'meta.tmp'),JSON.stringify(meta,null,2));await rename(resolve(path,'meta.tmp'),resolve(path,'meta.json'));}
 async function job(id:string){if(!uuid.test(id))throw Error('invalid_job');return json(resolve(web,'sessions',id,'job.json'));}
 async function finish(id:string,complete:boolean,reason:string){
  const a=active.get(id);if(!a||a.ending)return;a.ending=true;
  try{while(a.busy)await new Promise(r=>setTimeout(r,25));a.meta.state='processing';await save(a.meta);
   if(!a.meta.bytes)throw Error('empty_video');
   await run(options.ffmpeg??'ffmpeg',['-nostdin','-v','error','-y','-i',resolve(work,id,'capture.webm'),'-map','0:v:0','-c','copy',resolve(work,id,'video.webm')]);
   a.meta.state=complete?'ready':'partial';a.meta.reason=reason;a.meta.file='video.webm';
  }catch(e){a.meta.state='failed';a.meta.reason=String((e as Error).message);}
  a.meta.endedAt=Date.now();await save(a.meta);active.delete(id);
 }
 async function scan(){
  const rows:any[]=[];
  for(const id of await dirs(work)){if(!uuid.test(id))continue;try{const m=await json(resolve(work,id,'meta.json'));if(m.id!==id||!uuid.test(m.jobId))continue;const j=await job(m.jobId).catch(()=>null);const path=m.file==='video.webm'?resolve(work,id,m.file):null;const playable=path&&((await stat(path).catch(()=>null))?.size??0)>0;
   rows.push({id:'web-'+id,title:'网页对局',createdAt:m.startedAt,session:j?.session??m.session??null,status:m.state,hasVideo:!!playable,file:playable?path:null,kind:'web',jobId:m.jobId,startGameTime:m.startGameTime,samples:m.samples??[],note:m.state==='partial'?'连接中断，已保留录到的片段':m.startGameTime>3?'从游戏 '+Math.floor(m.startGameTime)+' 秒开始的片段':'从录制开始播放',sound:false});
  }catch{}}
  for(const id of await dirs(resolve(web,'sessions'))){if(!uuid.test(id)||rows.some(x=>x.jobId===id))continue;try{const j=await job(id);rows.push({id:'job-'+id,title:'网页对局',createdAt:j.createdAt,session:j.session??null,status:'no-video',hasVideo:false,kind:'web',note:'这局没有录视频，仅有战斗记录'});}catch{}}
  for(const folder of await dirs(resolve(root,'output/obs-recordings'))){try{
   const base=resolve(root,'output/obs-recordings',folder),s=await json(resolve(base,'status.json'));if(!sessionId.test(s.session?.matchId??''))continue;
   const path=typeof s.recording?.outputPath==='string'&&/\.mp4$/i.test(s.recording.outputPath)?s.recording.outputPath:null;
   if(!path||!((await stat(path).catch(()=>null))?.size))continue;
   const samples=(await readFile(resolve(base,'capture-health.jsonl'),'utf8').catch(()=>'')).split('\n').flatMap(line=>{try{const v=JSON.parse(line),video=(Date.parse(v.at)-Date.parse(s.recording.startedAt))/1000;return video>=0&&Number.isFinite(v.nativeGameTime)?[{video,game:v.nativeGameTime}]:[];}catch{return[];}});
   rows.push({id:'obs-'+digest(folder).slice(0,24),title:'历史录像 · EXE',createdAt:Date.parse(s.recording.startedAt??s.startedAt),session:s.session.matchId,status:'archive',hasVideo:true,file:path,kind:'obs',note:archiveReason(s),sound:null,samples,log:s.build?.publicHarness?resolve(s.build.publicHarness,'logs',s.session.matchId+'.jsonl'):null});
  }catch{}}
  listing=rows.sort((a,b)=>b.createdAt-a.createdAt);return listing;
 }
 async function chapters(row:any){
  if(row.kind!=='obs'||!sessionId.test(row.session??'')||!row.samples?.length)return[];
  const paths=row.log?[row.log]:[resolve(web,'sdk/logs',row.session+'.jsonl')];
  let records:any[]=[];for(const path of paths){try{if((await stat(path)).size>200_000_000)continue;records=(await readFile(path,'utf8')).split('\n').flatMap(x=>{try{return[JSON.parse(x)];}catch{return[];}});break;}catch{}}
  const samples=row.samples.filter((v:any)=>Number.isFinite(v.game)&&Number.isFinite(v.video)).sort((a:any,b:any)=>a.game-b.game);
  const out:any[]=[];for(const e of projectOverview(records).events){if(e.kind!=='deployment'||e.data.accepted===false)continue;const before=[...samples].reverse().find((s:any)=>s.game<=e.time),after=samples.find((s:any)=>s.game>=e.time);if(!before||!after)continue;const t=after.game===before.game?before.video:before.video+(e.time-before.game)/(after.game-before.game)*(after.video-before.video);const level=e.data.level;if(Number.isFinite(t)&&t>=0&&!out.some(x=>x.level===level))out.push({level,time:t});}return out;
 }
 const server=createServer(async(req,res)=>{
  const origin=req.headers.origin;
  const host=req.headers.host??'';
  const send=(code:number,value:any)=>{res.writeHead(code,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(value));};
  if(!/^(127\.0\.0\.1|localhost):\d+$/.test(host)||origin&&!localOrigin.test(origin)){send(403,{error:'local_origin_required'});return;}
  res.setHeader('Cross-Origin-Resource-Policy','cross-origin');
  if(origin){res.setHeader('Access-Control-Allow-Origin',origin);res.setHeader('Vary','Origin');}
  res.setHeader('Access-Control-Allow-Headers','Content-Type,Authorization');res.setHeader('Access-Control-Allow-Methods','GET,HEAD,POST,OPTIONS');
  if(req.method==='OPTIONS'){res.writeHead(204);res.end();return;}
  try{
   const url=new URL(req.url??'/',`http://${host}`),path=url.pathname;
   if(req.method==='GET'&&path==='/health'){send(200,{service:'deskfront-replays',version:3,pid:process.pid,active:active.size});return;}
   const asset=/^\/(recorder|replays)\.js$/.exec(path);
   if(asset&&req.method==='GET'){res.writeHead(200,{'Content-Type':'text/javascript; charset=utf-8','Cache-Control':'no-store'});res.end(await readFile(resolve(root,'src/deskfront/web-'+asset[1]+'.js')));return;}
   if(path==='/api/replays'&&req.method==='GET'){const rows=await scan();send(200,{rows:rows.map(({file,samples,log,...r})=>r)});return;}
   const media=/^\/api\/replays\/((?:web-[\da-f-]+)|(?:obs-[\da-f]{24}))\/(media|detail)$/.exec(path);
   if(media&&['GET','HEAD'].includes(req.method??'')){
    let row=listing.find(x=>x.id===media[1]);if(!row){await scan();row=listing.find(x=>x.id===media[1]);}if(!row){send(404,{error:'replay_not_found'});return;}
    if(media[2]==='detail'){send(200,{chapters:await chapters(row)});return;}
    const info=row.file?await stat(row.file).catch(()=>null):null;if(!info?.isFile()||!info.size){send(404,{error:'video_unavailable'});return;}
    const range=byteRange(req.headers.range,info.size);if(!range){res.writeHead(416,{'Content-Range':'bytes */'+info.size});res.end();return;}
    res.writeHead(range.partial?206:200,{'Content-Type':row.kind==='obs'?'video/mp4':'video/webm','Accept-Ranges':'bytes','Content-Length':range.end-range.start+1,...(range.partial?{'Content-Range':`bytes ${range.start}-${range.end}/${info.size}`}:{})});
    if(req.method==='HEAD')res.end();else{const stream=createReadStream(row.file,{start:range.start,end:range.end});stream.on('error',()=>res.destroy());res.on('close',()=>stream.destroy());stream.pipe(res);}return;
   }
   if(req.method!=='POST'||!origin){send(405,{error:'method_not_allowed'});return;}
   if(path==='/api/recordings/start'){
    const b=JSON.parse((await body(req)).toString()),j=await job(b.jobId);
    if(!['running','starting'].includes(j.status)||j.instanceId!==b.instanceId||!uuid.test(b.boot??'')||!Number.isFinite(b.gameTime)||b.gameTime<0){send(409,{error:'game_identity_mismatch'});return;}
    const existing=[...active.values()].find(x=>x.meta.jobId===b.jobId);if(existing){send(409,{error:'recording_already_active'});return;}
    if(active.size>=4){send(429,{error:'too_many_recordings'});return;}
    const id=randomUUID(),token=randomUUID(),meta={id,jobId:b.jobId,instanceId:b.instanceId,boot:b.boot,session:j.session??null,state:'recording',startedAt:Date.now(),updatedAt:Date.now(),startGameTime:b.gameTime,bytes:0,next:0,samples:[{game:b.gameTime,video:0}]};
    active.set(id,{token,meta,busy:false,ending:false,lastHash:''});await save(meta);send(201,{id,token});return;
   }
   const upload=/^\/api\/recordings\/([\da-f-]+)\/(chunk|finish|heartbeat)$/.exec(path);
   if(!upload||!uuid.test(upload[1]!)){send(404,{error:'not_found'});return;}
   const a=active.get(upload[1]!);if(!a||req.headers.authorization!=='Bearer '+a.token){send(403,{error:'recording_token_required'});return;}
   if(a.ending||a.busy){send(409,{error:'recording_busy'});return;}
   a.busy=true;
   try{
    if(upload[2]==='heartbeat'){await body(req);a.meta.updatedAt=Date.now();send(200,{state:a.meta.state});return;}
    if(upload[2]==='chunk'){
     const seq=Number(url.searchParams.get('seq')),data=await body(req,16*1024*1024),hash=digest(data);
     if(seq===a.meta.next-1&&hash===a.lastHash){send(200,{next:a.meta.next});return;}
     if(!Number.isSafeInteger(seq)||seq!==a.meta.next||!data.length){send(409,{error:'chunk_sequence_mismatch',next:a.meta.next});return;}
     if(a.meta.bytes+data.length>4*1024**3){send(413,{error:'recording_size_limit'});return;}
     await appendFile(resolve(work,upload[1]!,'capture.webm'),data);a.meta.bytes+=data.length;a.meta.next++;a.lastHash=hash;a.meta.updatedAt=Date.now();
     const game=Number(url.searchParams.get('game')),video=Number(url.searchParams.get('video'));
     if(Number.isFinite(game)&&Number.isFinite(video)&&game>=0&&video>=0)a.meta.samples.push({game,video});
     await save(a.meta);send(200,{next:a.meta.next});return;
    }
    const b=JSON.parse((await body(req)).toString());a.busy=false;await finish(upload[1]!,b.complete===true,b.complete?'game-ended':b.reason==='page-left'?'page-left':'recording-stopped');send(200,{state:a.meta.state});
   }finally{a.busy=false;}
  }catch(e){if(!res.headersSent)send(400,{error:(e as Error).message});else res.destroy();}
 });
 const watchdog=setInterval(()=>{for(const[id,a]of active)if(!a.busy&&!a.ending&&Date.now()-a.meta.updatedAt>120000)void finish(id,false,'connection-lost');},5000);watchdog.unref();server.on('close',()=>clearInterval(watchdog));
 return{server,scan,finish,work};
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const root=resolve(dirname(fileURLToPath(import.meta.url)),'..'),service=createReplayService(root);
 await mkdir(service.work,{recursive:true});
 // Recover uploaded bytes after a sidecar restart; never label an interrupted stream complete.
 for(const id of await dirs(service.work)){if(!uuid.test(id))continue;const path=resolve(service.work,id);try{const m=await json(resolve(path,'meta.json'));if(['recording','processing'].includes(m.state)){try{await run('ffmpeg',['-nostdin','-v','error','-y','-i',resolve(path,'capture.webm'),'-map','0:v:0','-c','copy',resolve(path,'video.webm')]);m.state='partial';m.file='video.webm';m.reason='service-restarted';}catch{m.state='failed';m.reason='service-restarted';}await writeFile(resolve(path,'meta.json'),JSON.stringify(m,null,2));}}catch{}}
 service.server.listen(Number(process.argv[2]??50206),'127.0.0.1',()=>console.log('Deskfront replay service http://127.0.0.1:'+((service.server.address() as any).port)));
}
