/** Browser Godot + the existing complete public Harness and private AI generator. */
import {readFile,writeFile,mkdir,open} from 'node:fs/promises';
import {spawn,type ChildProcess} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {resolve,dirname} from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {validateBeginnerCounts} from './deskfront-beginner.js';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..'),work=resolve(root,'output/web-game-20261020');
const load=async(p:string)=>JSON.parse((await readFile(p,'utf8')).replace(/^\uFEFF/,''));
const pin=await load(resolve(work,'pin.json')),sdk=resolve(work,'sdk'),release=resolve(root,'output/web-releases/deskfront-20261020');
const urlOf=(path:string)=>pathToFileURL(resolve(sdk,path)).href;
const [{startViewer},{createGameRegistry},{createRuntimeRegistry},{createAttachedDeskfrontRuntime}]=await Promise.all([
  import(urlOf('src/viewer/server.ts')),import(urlOf('src/arena/registry.ts')),import(urlOf('src/arena/runtime.ts')),import(urlOf('src/deskfront/attached_runtime.ts'))]);
const registry=await load(resolve(root,'versions/current.json'));registry.active.find((e:any)=>e.id==='split-full').publicHarness=sdk;
const registryPath=resolve(work,'frontend-registry.json');await writeFile(registryPath,JSON.stringify(registry));process.env.DESKFRONT_OVERVIEW_REGISTRY=registryPath;
type Job={id:string;instanceId:string;requestId:string;counts:any;status:string;url:string;host:string;session?:string;origin?:string;error?:string;hostProcess?:ChildProcess;harness?:ChildProcess;attaching?:boolean;presentation?:boolean;report?:string;createdAt:number;stopped?:boolean;privateGenerator?:string};
let job:Job|null=null,publicOrigin='';const jobs=new Map<string,Job>();
const folder=(j:Job)=>resolve(work,'sessions',j.id);
const view=(j:Job|null)=>j?{id:j.id,counts:j.counts,status:j.status,url:j.url,session:j.session,error:j.error,createdAt:j.createdAt,mode:'godot-web',maxStages:10}:null;
const save=async(j:Job)=>{const {hostProcess,harness,attaching,...data}=j;await writeFile(resolve(folder(j),'job.json'),JSON.stringify(data,null,2));};
const sleep=(ms:number)=>new Promise(r=>setTimeout(r,ms));
const jsonHeaders={'Cache-Control':'no-store','Cross-Origin-Opener-Policy':'same-origin','Cross-Origin-Embedder-Policy':'require-corp'};
function client(req:any){return ['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress)&&(!req.headers.origin||req.headers.origin===publicOrigin);}
async function start(input:any){
 const counts=validateBeginnerCounts(input.counts);
 if(typeof input.requestId!=='string'||!/^[\w-]{8,80}$/.test(input.requestId))throw Error('启动编号无效');
 if(job?.requestId===input.requestId)return job;
 if(job&&!['finished','stopped','failed'].includes(job.status))throw Error('已有一局在运行，请先结束本局。');
 if(job&&!job.stopped)await stop(job);
 const id=randomUUID(),instanceId=randomUUID();
 const j:Job={id,instanceId,requestId:input.requestId,counts,status:'starting',url:'/web/run/'+id,host:'',createdAt:Date.now()};
 await mkdir(folder(j),{recursive:true});
 const saved=resolve(process.env.APPDATA??'','Godot/app_userdata/Deskfront · 桌面前线/deskfront-board-settings.cfg');
 let settings=await readFile(saved,'utf8').catch(()=>'');settings=settings.replace(/^\s*\[beginner\][^\r\n]*\r?\n[\s\S]*?(?=^\s*\[|$(?![\s\S]))/gm,'');
 settings+='\n[beginner]\nschema=2\nenabled=true\nsmg='+counts.smg+'\nrocket='+counts.rocket+'\nrifle='+counts.rifle+'\nmax_stages=10\nframe_file=""\n';
 await writeFile(resolve(folder(j),'web-config.json'),JSON.stringify({instanceId,settings}));
 const out=await open(resolve(folder(j),'host.log'),'a');
 j.hostProcess=spawn(process.env.PYTHON_BIN??'python',[resolve(root,'tools/deskfront-web-host.py'),'--job',folder(j),'--code',resolve(work,'host-code')],{cwd:root,windowsHide:true,stdio:['ignore',out.fd,out.fd]});await out.close();
 jobs.set(id,j);job=j;await save(j);
 for(let i=0;i<60;i++){const c=await load(resolve(folder(j),'connection.json')).catch(()=>null);if(c?.status==='running'){j.host=c.url;await save(j);return j;}if(j.hostProcess.exitCode!==null)throw Error('Web 通信服务启动失败');await sleep(100);}
 throw Error('Web 通信服务启动超时');
}
async function attach(j:Job){
 if(j.attaching||j.session||j.stopped)return;j.attaching=true;
 try{
  const health=await(await fetch(j.host+'/web/health')).json() as any;if(!health.live){j.attaching=false;return;}
  j.status='connecting';const out=await open(resolve(folder(j),'harness.log'),'a');
  j.report=resolve(folder(j),'session.json');
  // Resolve the provider for a new game, not from the old Web-build pin.
  // Existing sessions retain their already loaded provider and frozen plans.
  const current=await load(resolve(root,'versions/current.json'));
  const provider=current.active.find((entry:any)=>entry.id==='split-full')?.privateGenerator;
  if(typeof provider!=='string'||!provider)throw Error('当前私有关卡生成器未登记');
  await readFile(resolve(root,provider));j.privateGenerator=provider;await save(j);
  j.harness=spawn(process.execPath,['--import','tsx','tools/deskfront-attach.ts','--connection',resolve(folder(j),'connection.json'),
   '--backend','jev','--levels','ai','--level-generator',resolve(root,provider),'--config',resolve(root,'config.local.json'),
   '--env-file',resolve(root,'.env'),'--seconds','3600','--requests','10000','--port','0','--spectator','false','--annie','false',
   '--demo-rules','false','--report',j.report],{cwd:sdk,windowsHide:true,stdio:['ignore',out.fd,out.fd]});await out.close();
  for(let i=0;i<180;i++){if(j.stopped)return;const receipt=await load(j.report).catch(()=>null);if(receipt?.matchId){j.session=receipt.matchId;j.origin=new URL(receipt.url).origin;j.status='running';
    await writeFile(resolve(folder(j),'presentation.json'),JSON.stringify({directorUrl:publicOrigin+'/api/deskfront/director/'+j.session,directorPage:publicOrigin+'/?view=generation&session='+j.session,runtimeStatusUrl:publicOrigin+'/api/deskfront/runtime-status/'+j.session}));
    await save(j);return;}if(j.harness.exitCode!==null)throw Error('Harness 启动失败，请查看运行记录。');await sleep(200);}
  throw Error('Harness 启动超时');
 }catch(e){j.status='failed';j.error=String(e);await save(j);}finally{j.attaching=false;}
}
async function stop(j:Job){
 if(j.origin&&j.session)await fetch(j.origin+'/api/match/'+j.session+'/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).catch(()=>null);
 j.stopped=true;j.harness?.kill();j.hostProcess?.kill();j.status='stopped';j.error=undefined;const connection=await load(resolve(folder(j),'connection.json'));connection.status='closed';await writeFile(resolve(folder(j),'connection.json'),JSON.stringify(connection));await save(j);
}
async function proxy(req:any,res:any,url:URL,send:any,target:string,transform?:Function){
 const headers:Record<string,string>={};if(req.headers['content-type'])headers['Content-Type']=req.headers['content-type'];
 let body:Buffer|undefined;if(req.method!=='GET'&&req.method!=='HEAD'){const chunks:Buffer[]=[];let size=0;for await(const c of req){size+=c.length;if(size>8*1024*1024)throw Error('请求过大');chunks.push(c);}body=Buffer.concat(chunks);}
 const response=await fetch(target+url.pathname+url.search,{method:req.method,headers,body:body?new Uint8Array(body).buffer:undefined,signal:AbortSignal.timeout(15000)});
 const type=response.headers.get('content-type')??'application/octet-stream';let bytes:Buffer=Buffer.from(await response.arrayBuffer());
 if(transform&&response.ok&&type.includes('application/json'))bytes=Buffer.from(JSON.stringify(transform(JSON.parse(bytes.toString()))));
 send(response.status,bytes,type,jsonHeaders);
}
const server=await startViewer({registry:createGameRegistry(),runtimes:createRuntimeRegistry([createAttachedDeskfrontRuntime()]),
 logDir:resolve(sdk,'logs'),host:'127.0.0.1',port:Number(process.argv[2]??0),localRoutes:async(req:any,res:any,url:URL,send:any)=>{
  res.setHeader('Cross-Origin-Opener-Policy','same-origin');res.setHeader('Cross-Origin-Embedder-Policy','require-corp');
  const json=(code:number,data:any)=>send(code,JSON.stringify(data),'application/json; charset=utf-8',jsonHeaders);
  if(url.pathname==='/'&&url.searchParams.get('view')==='beginner'){
   let html=await readFile(resolve(sdk,'src/deskfront/beginner.html'),'utf8');html=html.replaceAll('/api/deskfront/beginner','/api/deskfront/web').replaceAll('使用当前正式 EXE','使用当前 Godot Web 版本').replaceAll('游戏窗口','浏览器游戏');send(200,html.replaceAll('http://127.0.0.1:50206',process.env.DESKFRONT_REPLAY_ORIGIN??'http://127.0.0.1:50206'),'text/html; charset=utf-8',jsonHeaders);return true;
  }
  if(url.pathname==='/web/surface.js'){send(200,await readFile(resolve(root,'tools/deskfront-web-surface.js')),'text/javascript',jsonHeaders);return true;}
  if(url.pathname.startsWith('/api/deskfront/web')){
   if(!client(req)){json(403,{error:'仅允许本机同源访问'});return true;}
   if(req.method==='GET'){if(job?.host&&!job.session&&!job.attaching&&!['failed','stopped'].includes(job.status))void attach(job);json(200,{job:view(job)});return true;}
   try{if(!req.headers['content-type']?.startsWith('application/json'))throw Error('需要 JSON 请求');let text='';for await(const c of req){text+=c;if(text.length>2048)throw Error('请求过大');}const input=JSON.parse(text);
    if(url.pathname.endsWith('/start'))json(202,{job:view(await start(input))});else if(url.pathname.endsWith('/stop')&&job&&job.id===input.id){await stop(job);json(200,{job:view(job)});}else json(400,{error:'本局身份不匹配'});
   }catch(e){json(400,{error:e instanceof Error?e.message:String(e)});}return true;
  }
  const run=/^\/web\/run\/([\da-f-]{36})$/.exec(url.pathname);
  if(run){const j=jobs.get(run[1]!);if(!j){json(404,{error:'对局不存在'});return true;}let html=await readFile(resolve(root,'src/deskfront/web-run.html'),'utf8');html=html.replaceAll('__JOB_ID__',j.id).replaceAll('__INSTANCE_ID__',j.instanceId);send(200,html.replaceAll('http://127.0.0.1:50206',process.env.DESKFRONT_REPLAY_ORIGIN??'http://127.0.0.1:50206'),'text/html; charset=utf-8',jsonHeaders);return true;}
  const play=/^\/play\/([\da-f-]{36})\/(.+)$/.exec(url.pathname);
  if(play){const j=jobs.get(play[1]!);if(!j){json(404,{error:'对局不存在'});return true;}
   const name=decodeURIComponent(play[2]!);if(name==='index.html'){let html=await readFile(resolve(root,'src/deskfront/web-player.html'),'utf8');html=html.replace('__CONFIG__',JSON.stringify(await load(resolve(folder(j),'web-config.json'))).replaceAll('<','\\u003c'));send(200,html.replaceAll('http://127.0.0.1:50206',process.env.DESKFRONT_REPLAY_ORIGIN??'http://127.0.0.1:50206'),'text/html; charset=utf-8',jsonHeaders);return true;}
   if(!/^game\.(js|wasm|pck|audio\.worklet\.js|audio\.position\.worklet\.js|worker\.js)$/.test(name)){json(404,{error:'资源不存在'});return true;}
   try{const type=name.endsWith('.wasm')?'application/wasm':name.endsWith('.js')?'text/javascript':'application/octet-stream';send(200,await readFile(resolve(release,name)),type,{...jsonHeaders,'Cross-Origin-Resource-Policy':'same-origin'});}catch{json(404,{error:'资源不存在'});}return true;
  }
  // The engine's own origin is this viewer. Model credentials stay in the host.
  if(url.pathname==='/api/sync'&&job?.host){if(!client(req)){json(403,{error:'origin_denied'});return true;}await proxy(req,res,url,send,job.host);return true;}
  if(url.pathname==='/web/presentation.json'){json(200,job?await load(resolve(folder(job),'presentation.json')).catch(()=>({})):{});return true;}
  if(url.pathname==='/web/health'){json(200,{job:view(job),engine:job?.host?await fetch(job.host+'/web/health').then(r=>r.json()).catch(()=>null):null});return true;}
  if(job?.origin&&url.pathname.startsWith('/api/deskfront/')){
   await proxy(req,res,url,send,job.origin,(value:any)=>{
    if(url.pathname==='/api/deskfront/overview/'+job!.session)return {...value,mode:'live',media:null,previewAvailable:true,
     liveFrameUrl:'/play/'+job!.id+'/index.html?instance_id='+job!.instanceId,frameSource:'godot-web',beginner:{status:job!.status,maxStages:10,counts:job!.counts}};
    return value;});return true;
  }
  return false;
 }});
publicOrigin='http://127.0.0.1:'+server.port;
await writeFile(resolve(work,'server.json'),JSON.stringify({pid:process.pid,url:publicOrigin+'/?view=beginner',origin:publicOrigin,sdk,pin,mode:'godot-web'},null,2));
console.log(publicOrigin+'/?view=beginner');
const monitor=setInterval(async()=>{const j=job;if(!j?.origin||!j.session||j.stopped)return;try{
 const response=await fetch(j.origin+'/api/match/'+j.session+'/state?compact=1');const s:any=await response.json();
 if(s.status==='done'){j.status=s.error?'failed':'finished';j.error=s.error;await save(j);}
 if(!j.presentation&&s.status!=='done'&&s.payload?.game?.engineLive){j.presentation=true;for(const part of ['commentary','danmaku'])await fetch(j.origin+'/api/deskfront/'+part+'/'+j.session+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(part==='danmaku'?{density:'low'}:{})});}
}catch{/* Poll again; transient metadata failure must not terminate gameplay. */}},2000);monitor.unref();
