/** Local, bounded new-game controller. Browser input never selects commands or paths. */
import { readFile, writeFile, mkdir, open, stat, unlink } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { resolve, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
import type { IncomingMessage, ServerResponse } from 'node:http';

type Counts={smg:number;rocket:number;rifle:number};
type Job={id:string;requestId:string;counts:Counts;status:string;createdAt:number;updatedAt:number;session?:string;origin?:string;report?:string;launcherPid?:number;launchedGamePid?:number;connection?:string;error?:string;outcome?:unknown};
type Send=(status:number,body:string|Buffer,type?:string,headers?:Record<string,string>)=>void;
const jsonFile=async(path:string)=>JSON.parse((await readFile(path,'utf8')).replace(/^\uFEFF/,''));
export function validateBeginnerCounts(value:unknown):Counts {
 if(!value||typeof value!=='object'||Array.isArray(value))throw Error('请选择 1–3 个开局名额。');
 const v=value as Record<string,unknown>;
 if(Object.keys(v).some(k=>!['smg','rocket','rifle'].includes(k)))throw Error('开局只支持冲锋枪、火箭筒和步枪。');
 for(const k of ['smg','rocket','rifle'])if(!Number.isInteger(v[k])||Number(v[k])<0||Number(v[k])>3)throw Error('兵种数量须为 0–3 的整数。');
 const counts=v as Counts,total=counts.smg+counts.rocket+counts.rifle;
 if(total<1||total>3)throw Error('开局合计须为 1–3 个名额。');return{smg:counts.smg,rocket:counts.rocket,rifle:counts.rifle};
}
export function createBeginnerRoutes(workspace:string) {
 const root=resolve(workspace,'output/beginner-sessions'),pointer=resolve(root,'current.json'),lock=resolve(root,'launch.lock');
 let busy=false;
 const folder=(j:Job)=>resolve(root,j.id);
 const save=async(j:Job)=>{j.updatedAt=Date.now();const file=resolve(folder(j),'job.json'),temp=file+'.'+randomUUID()+'.tmp';await writeFile(temp,JSON.stringify(j,null,2));await (await import('node:fs/promises')).rename(temp,file);};
 const current=async():Promise<Job|null>=>{try{const p=await jsonFile(pointer);if(!/^[\da-f-]{36}$/.test(p.id))return null;return await jsonFile(resolve(root,p.id,'job.json'));}catch{return null;}};
 const archives=new Map<string,{overview:Function;director:Function}>();
 async function archived(j:Job,req:IncomingMessage,res:ServerResponse,url:URL,send:Send){
  let handlers=archives.get(j.id);
  if(!handlers){
   const receipt=await jsonFile(resolve(folder(j),'launch.json')),sdk=String(receipt.publicHarness),report=await jsonFile(String(receipt.report));
   if(report.matchId!==j.session||!sdk.startsWith(resolve(workspace,'output/module-exports')))throw Error('archive_identity_mismatch');
   const [overview,director]=await Promise.all([import(pathToFileURL(resolve(sdk,'src/viewer/overview-routes.ts')).href),import(pathToFileURL(resolve(sdk,'src/viewer/director-routes.ts')).href)]);
   const deps={logDir:resolve(sdk,'logs'),live:()=>[],state:()=>null};handlers={overview:overview.createOverviewRoutes(deps),director:director.createDirectorRoutes(deps)};archives.set(j.id,handlers);
  }
  const wrapped:Send=(code,body,type,headers)=>{if(code===200&&type?.includes('application/json')){
   const value=JSON.parse(String(body));if(url.pathname==='/api/deskfront/overview/'+j.session)Object.assign(value,{mode:'live',media:null,previewAvailable:true,liveFrameUrl:'/api/deskfront/overview/'+j.session+'/stream',frameSource:'native-viewport',beginner:{status:j.status,maxStages:10,counts:j.counts}});
   send(code,JSON.stringify(value),type,headers);
  }else send(code,body,type,headers);};
  if(url.pathname.startsWith('/api/deskfront/director/'))return handlers.director(req,url,wrapped);
  return handlers.overview(req,res,url,wrapped);
 }
 const publicJob=(j:Job|null)=>j?{id:j.id,status:j.status,counts:j.counts,maxStages:10,session:j.session,error:j.error,outcome:j.outcome,createdAt:j.createdAt,
  url:j.session?'/?view=lab&tab=combat&session='+encodeURIComponent(j.session):null}:null;
 async function refresh(j:Job){
  if(j.status==='starting'){
   try{const receipt=await jsonFile(resolve(folder(j),'launch.json'));j.report=receipt.report;j.launcherPid=receipt.launcherPid;
    const report=await jsonFile(j.report!);const origin=new URL(report.url);if(origin.hostname!=='127.0.0.1'||origin.protocol!=='http:'||!/^deskfront-[\w-]+$/.test(report.matchId))throw Error('invalid_launch_receipt');
    j.session=report.matchId;j.origin=origin.origin;j.connection=report.connection;j.launchedGamePid=report.launchedGamePid;j.status='running';await save(j);
   }catch{if(Date.now()-j.createdAt>180000){j.status='failed';j.error='启动未完成。请重试；运行记录已保存。';await save(j);} }
  }
  if(j.status==='running'&&j.origin&&j.session){
   try{const r=await fetch(j.origin+'/api/match/'+j.session+'/state?compact=1',{signal:AbortSignal.timeout(6000)});if(!r.ok)throw Error('state');const state:any=await r.json();
    if(state.status==='done'){j.status=state.error?'failed':'finished';j.error=state.error?'本局运行已停止，详情见看板记录。':undefined;j.outcome=state.outcome;await save(j);}
   }catch{const c=await jsonFile(j.connection??'').catch(()=>null);if(c?.status==='closed'){j.status='finished';await save(j);} }
  }
  return j;
 }
 async function stop(j:Job){
  // The stop helper verifies the launch receipt, executable and unique settings
  // path before ending only this launch's process tree. No global process kill.
  if(j.origin&&j.session)await fetch(j.origin+'/api/match/'+j.session+'/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(5000)}).catch(()=>null);
  await new Promise<void>((done,reject)=>{const p=spawn('powershell.exe',['-NoProfile','-ExecutionPolicy','Bypass','-File',resolve(workspace,'tools/stop-deskfront-beginner.ps1'),'-JobFile',resolve(folder(j),'job.json')],{cwd:workspace,windowsHide:true,stdio:'ignore'});p.once('error',reject);p.once('exit',code=>code===0?done():reject(Error('本局窗口未能关闭，请先关闭游戏窗口。')));});
  j.status='stopped';await save(j);
 }
 async function launch(counts:Counts,requestId:string){
  await mkdir(root,{recursive:true});let handle;
  try{handle=await open(lock,'wx');await handle.writeFile(String(process.pid));}
  catch{const pid=Number(await readFile(lock,'utf8').catch(()=>0)),age=Date.now()-(await stat(lock)).mtimeMs;let alive=age<30000;try{if(pid){process.kill(pid,0);alive=true;}}catch{}if(!alive){await unlink(lock).catch(()=>{});handle=await open(lock,'wx');await handle.writeFile(String(process.pid));}else throw Error('已有启动正在处理，请稍候。');}
  try{
   const old=await current();if(old?.requestId===requestId)return old;
   if(old&&['starting','running'].includes((await refresh(old)).status))throw Error('当前已有一局在运行，请进入看板或先结束本局。');
   if(old?.status==='failed'||old?.status==='finished')await stop(old);
   const j:Job={id:randomUUID(),requestId,counts,status:'starting',createdAt:Date.now(),updatedAt:Date.now()};await mkdir(folder(j),{recursive:true});
   // Preserve player preferences without overwriting their saved configuration.
   const saved=resolve(process.env.APPDATA??'','Godot/app_userdata/Deskfront · 桌面前线/deskfront-board-settings.cfg');
   let settings=await readFile(saved,'utf8').catch(()=>'');settings=settings.replace(/^\s*\[beginner\][^\r\n]*\r?\n[\s\S]*?(?=^\s*\[|$(?![\s\S]))/gm,'');
   const frame=resolve(folder(j),'live.jpg').replaceAll('\\','/');settings+='\n\n[beginner]\nschema=2\nenabled=true\nsmg='+counts.smg+'\nrocket='+counts.rocket+'\nrifle='+counts.rifle+'\nmax_stages=10\nframe_file="'+frame+'"\n';
   const board=resolve(folder(j),'board-settings.cfg');await writeFile(board,settings);await save(j);await writeFile(pointer,JSON.stringify({id:j.id}));
   const out=await open(resolve(folder(j),'launcher-stdout.log'),'a'),err=await open(resolve(folder(j),'launcher-stderr.log'),'a');
   const p=spawn('powershell.exe',['-NoProfile','-ExecutionPolicy','Bypass','-File',resolve(workspace,'tools/start-deskfront-current.ps1'),'-BoardSettings',board,'-Seconds','3600','-Requests','10000','-ReceiptPath',resolve(folder(j),'launch.json')],{cwd:workspace,windowsHide:true,stdio:['ignore',out.fd,err.fd]});
   p.once('error',()=>{void (async()=>{j.status='failed';j.error='启动程序失败，请重试。';await save(j);})();});
   p.once('exit',code=>{if(code&&j.status==='starting')void (async()=>{j.status='failed';j.error='启动检查未通过，未进入游戏。运行记录已保存。';await save(j);})();});
   await out.close();await err.close();return j;
  }finally{await handle?.close();await unlink(lock).catch(()=>{});}
 }
 const monitor=setInterval(async()=>{if(busy)return;busy=true;try{const j=await current();if(j)await refresh(j);}finally{busy=false;}},1500);monitor.unref();
 return async(req:IncomingMessage,res:ServerResponse,url:URL,send:Send):Promise<boolean>=>{
  const json=(code:number,value:unknown)=>send(code,JSON.stringify(value),'application/json; charset=utf-8',{'Cache-Control':'no-store'});
  if(url.pathname==='/'&&url.searchParams.get('view')==='beginner'){
   const reg=await jsonFile(resolve(workspace,'versions/current.json')),sdk=reg.active.find((e:any)=>e.id==='split-full').publicHarness;
   send(200,await readFile(resolve(workspace,sdk,'src/deskfront/beginner.html')),'text/html; charset=utf-8',{'Cache-Control':'no-store'});return true;
  }
  if(url.pathname.startsWith('/api/deskfront/beginner')){
   const remote=req.socket.remoteAddress;if(!['127.0.0.1','::1','::ffff:127.0.0.1'].includes(remote??'')||!['127.0.0.1','localhost','[::1]'].includes((req.headers.host??'').replace(/:\d+$/,''))){json(403,{error:'仅限本机使用'});return true;}
   if(req.method==='GET'&&url.pathname==='/api/deskfront/beginner'){json(200,{job:publicJob(await current())});return true;}
   if(req.method==='POST'){
    if(req.headers.origin&&req.headers.origin!=='http://'+req.headers.host){json(403,{error:'请求来源不匹配'});return true;}
    if(!req.headers['content-type']?.startsWith('application/json')){json(415,{error:'需要 JSON 请求'});return true;}
    try{let body='';for await(const chunk of req){body+=chunk;if(body.length>2048)throw Error('请求过大');}const input=JSON.parse(body);
     if(url.pathname==='/api/deskfront/beginner/start'){
      const counts=validateBeginnerCounts(input.counts);if(typeof input.requestId!=='string'||!/^[\w-]{8,80}$/.test(input.requestId))throw Error('启动编号无效');const j=await launch(counts,input.requestId);json(202,{job:publicJob(j)});return true;
     }
     if(url.pathname==='/api/deskfront/beginner/stop'){const j=await current();if(!j||j.id!==input.id)throw Error('本局已改变，请刷新');await refresh(j);if(j.status==='starting')throw Error('游戏正在启动，请在进入看板后结束本局。');await stop(j);json(200,{job:publicJob(j)});return true;}
    }catch(e){json(400,{error:e instanceof Error?e.message:'请求失败'});return true;}
   }
   json(404,{error:'接口不存在'});return true;
  }
  if(req.method!=='GET')return false;
  const m=/^\/api\/deskfront\/(overview|director)\/(deskfront-[\w-]+)(\/calls\/[\w-]+|\/preview|\/stream)?$/.exec(url.pathname);
  if(!m)return false;const j=await current();if(!j||j.session!==m[2]||!j.origin)return false;
  if(m[3]==='/stream'){
   // Frame delivery is independent of log/model polling. Drop old frames under
   // backpressure instead of building a playback queue behind the real game.
   res.writeHead(200,{'Content-Type':'multipart/x-mixed-replace; boundary=deskfront-frame','Cache-Control':'no-store, no-cache, must-revalidate','X-Content-Type-Options':'nosniff'});
   let reading=false,closed=false,stamp=0;
   const tick=async()=>{if(closed||reading||res.writableNeedDrain)return;reading=true;try{
    const file=resolve(folder(j),'live.jpg'),info=await stat(file);if(info.mtimeMs===stamp)return;
    const bytes=await readFile(file);if(closed||bytes[0]!==255||bytes[1]!==216||bytes.at(-1)!==217)return;
    stamp=info.mtimeMs;res.write('--deskfront-frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+bytes.length+'\r\nX-Frame-Time: '+Math.round(stamp)+'\r\n\r\n');res.write(bytes);res.write('\r\n');
   }catch{/* Wait for a valid first/next frame, never substitute other media. */}finally{reading=false;}};
   const frames=setInterval(()=>void tick(),50);frames.unref();res.once('close',()=>{closed=true;clearInterval(frames);});void tick();return true;
  }
  if(m[3]==='/preview'){
   try{const file=resolve(folder(j),'live.jpg'),info=await stat(file),bytes=await readFile(file);if(bytes[0]!==255||bytes[1]!==216||bytes.at(-1)!==217)throw Error('frame');
    send(200,bytes,'image/jpeg',{'Cache-Control':'no-store','X-Frame-Age-Ms':String(Date.now()-info.mtimeMs)});
   }catch{json(503,{error:'等待游戏首帧'});}return true;
  }
  try{const r=await fetch(j.origin+url.pathname+url.search,{signal:AbortSignal.timeout(12000)});let v:any=await r.json();
   if(m[1]==='overview'&&!m[3]&&r.ok){v={...v,mode:'live',media:null,previewAvailable:true,liveFrameUrl:'/api/deskfront/overview/'+j.session+'/stream',beginner:{status:j.status,maxStages:10,counts:j.counts},frameSource:'native-viewport'};}
   json(r.status,v);
  }catch{if(['finished','stopped','failed'].includes(j.status)){try{await archived(j,req,res,url,send);return true;}catch{}}json(503,{error:'实时连接暂不可用，请检查游戏窗口。'});}return true;
 };
}
