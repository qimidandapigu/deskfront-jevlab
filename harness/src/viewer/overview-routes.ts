import type { IncomingMessage, ServerResponse } from 'node:http';
import { createReadStream, existsSync } from 'node:fs';
import { readFile, readdir, stat } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createInterface } from 'node:readline';
import { projectOverview, liveOverview } from '../deskfront/overview-view.js';
import { readOverviewPreview } from '../deskfront/overview-obs.js';
import { projectPlanningCalls, planningCallSummary, planningCallAt } from '../deskfront/planning-calls.js';
type Dependencies = {logDir:string;live:()=>{id:string;status:string;gameId:string}[];state:(id:string)=>any;recordingsDir?:string};
type Send = (status:number,body:string|Buffer,type?:string,headers?:Record<string,string>)=>void;
const valid=/^deskfront-[a-zA-Z0-9-]+$/;
function recordingsDirectory(){let folder=dirname(fileURLToPath(import.meta.url));for(let i=0;i<9;i++,folder=dirname(folder))if(existsSync(resolve(folder,'versions/current.json')))return resolve(folder,'output/obs-recordings');return resolve(process.cwd(),'output/obs-recordings');}
// Workspace previews opt into the registered frontend. Portable SDKs keep
// their own bundled frontend unless explicitly configured by their launcher.
async function overviewFrontend(){
 const registry=process.env.DESKFRONT_OVERVIEW_REGISTRY;
 if(!registry)return{root:resolve(dirname(fileURLToPath(import.meta.url)),'../deskfront'),version:'bundled'};
 const current=JSON.parse(await readFile(registry,'utf8'));
 const sdk=current.active?.find((entry:any)=>entry.id==='split-full')?.publicHarness;
 if(typeof sdk!=='string'||!sdk.trim())throw Error('frontend_registry_invalid');
 const root=resolve(dirname(registry),'..',sdk,'src/deskfront');
 if(!existsSync(resolve(root,'overview.html')))throw Error('frontend_missing');
 return{root,version:encodeURIComponent(sdk)};
}
export function createOverviewRoutes(deps:Dependencies){
 const recordingsDir=deps.recordingsDir??recordingsDirectory();
 let recordingCache:{at:number;rows:any[]}={at:0,rows:[]};
 const cache=new Map<string,{mtime:number;at:number;value:ReturnType<typeof projectOverview>;calls:any[]}>();
 const previews=new Map<string,{at:number;data:Buffer}>();
 async function recordings(){
  if(Date.now()-recordingCache.at<10000)return recordingCache.rows;
  const folders=(await readdir(recordingsDir).catch(()=>[] as string[])).filter(x=>/^\d{4}-\d{2}-\d{2}(?:T|[-_]|$)/.test(x)).sort().reverse().slice(0,100);
  const rows=(await Promise.all(folders.map(async folder=>{try{
   const path=resolve(recordingsDir,folder),status=JSON.parse(await readFile(resolve(path,'status.json'),'utf8')),id=status.session?.matchId;
   if(!valid.test(id))return null;
   const video=typeof status.recording?.outputPath==='string'&&/\.mp4$/i.test(status.recording.outputPath)?status.recording.outputPath:null;
   const health=(await readFile(resolve(path,'capture-health.jsonl'),'utf8').catch(()=>'')).trim().split('\n'),startedAt=Date.parse(status.recording?.startedAt);
   const sync=health.flatMap(line=>{try{const r=JSON.parse(line),time=(Date.parse(r.at)-startedAt)/1000;return Number.isFinite(time)&&typeof r.nativeGameTime==='number'?[{video:time,game:r.nativeGameTime}]:[];}catch{return[];}});
   return{id,path,video,sync,modified:Date.parse(status.updatedAt??status.startedAt)||0,
    sourceLog:typeof status.build?.publicHarness==='string'?resolve(status.build.publicHarness,'logs',id+'.jsonl'):null,
    mirror:status.status==='recording'&&status.capture?.windowPolicy?.ownerVerified===true?status.capture?.source:null};
  }catch{return null;}}))).filter(Boolean);recordingCache={at:Date.now(),rows};return rows;
 }
 async function sessionList(){const media=await recordings(),active=deps.live().filter(x=>x.gameId==='deskfront');
  const names=(await readdir(deps.logDir).catch(()=>[] as string[])).filter(x=>x.endsWith('.jsonl')&&valid.test(x.slice(0,-6)));
  const files=await Promise.all(names.map(async name=>({id:name.slice(0,-6),modified:(await stat(resolve(deps.logDir,name)).catch(()=>null))?.mtimeMs??0})));
  return[...new Set([...active.map(x=>x.id),...files.map(x=>x.id),...media.map(x=>x.id)])].map(id=>({id,
   mode:active.find(x=>x.id===id)?.status==='running'?'live':'recording',hasVideo:!!media.find(x=>x.id===id)?.video,
   modified:media.find(x=>x.id===id)?.modified??files.find(x=>x.id===id)?.modified??Date.now()}))
   .sort((a,b)=>Number(b.mode==='live')-Number(a.mode==='live')||b.modified-a.modified).slice(0,40);
 }
 return async function handle(req:IncomingMessage,res:ServerResponse,url:URL,send:Send):Promise<boolean>{
  const asset=/^\/battle-lab\/(style\.css|LICENSE\.txt|overview-map\.js|planning\.js|combat-chain\.js|tactical-orders\.js|generation\.css|generation\.js|generation-model\.js|generation-scene\.js|generation-game\.js|generation-motion\.js|lab\.css|lab\.js|lab-model\.js|lab-map\.js)$/.exec(url.pathname);
  const lab=url.pathname==='/runtime/deskfront/lab'||['/','/runtime/deskfront'].includes(url.pathname)&&url.searchParams.get('view')==='lab';
  const generation=url.pathname==='/runtime/deskfront/generation'||['/','/runtime/deskfront'].includes(url.pathname)&&url.searchParams.get('view')==='generation';
  const page=lab||generation||url.pathname==='/runtime/deskfront/overview'||['/','/runtime/deskfront'].includes(url.pathname)&&url.searchParams.get('view')==='overview';
  if(asset||page){
   if(req.method!=='GET'){send(405,'Method not allowed','text/plain');return true;}
   try{
    const frontend=await overviewFrontend(),file=asset?'battle-lab/'+asset[1]:lab?'lab.html':generation?'generation.html':'overview.html';
    const type=!asset?'text/html; charset=utf-8':asset[1]!.endsWith('.css')?'text/css; charset=utf-8':asset[1]!.endsWith('.js')?'text/javascript; charset=utf-8':'text/plain; charset=utf-8';
    send(200,await readFile(resolve(frontend.root,file)),type,{'Cache-Control':'no-store','X-Deskfront-Frontend':frontend.version});
   }catch{send(503,'Current frontend unavailable','text/plain',{'Cache-Control':'no-store'});}
   return true;
  }
  if(!url.pathname.startsWith('/api/deskfront/overview/'))return false;
  const json=(code:number,value:any)=>send(code,JSON.stringify(value),'application/json',{'Cache-Control':'no-store'});
  if(!['GET','HEAD'].includes(req.method??'')){json(405,{error:'read_only'});return true;}
  const key=url.pathname.slice('/api/deskfront/overview/'.length);
  try{
   if(key==='sessions'){json(200,{sessions:await sessionList()});return true;}
   const[id,action,extra,tail]=key.split('/');
   if(!valid.test(id??'')||tail||extra&&(action!=='calls'||!/^c\d+$/.test(extra))||action&&!['media','preview','calls'].includes(action)){json(400,{error:'invalid_session'});return true;}
   const media=(await recordings()).find(x=>x.id===id),active=deps.live().find(x=>x.id===id&&x.gameId==='deskfront');
   if(action==='media'){
    const info=media?.video?await stat(media.video).catch(()=>null):null;
    if(!info?.isFile()||!info.size){json(404,{error:'recording_unavailable'});return true;}
    const range=req.headers.range;let start=0,end=info.size-1;
    if(range){const m=/^bytes=(\d*)-(\d*)$/.exec(range);if(!m||!m[1]&&!m[2]){send(416,'','video/mp4',{'Content-Range':'bytes */'+info.size});return true;}
     start=m[1]?Number(m[1]):Math.max(0,info.size-Number(m[2]));end=m[1]&&m[2]?Math.min(Number(m[2]),info.size-1):info.size-1;
     if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start<0||start>=info.size||end<start){send(416,'','video/mp4',{'Content-Range':'bytes */'+info.size});return true;}}
    res.writeHead(range?206:200,{'Content-Type':'video/mp4','Accept-Ranges':'bytes','Content-Length':String(end-start+1),...(range?{'Content-Range':`bytes ${start}-${end}/${info.size}`}:{})});
    if(req.method==='HEAD')res.end();else createReadStream(media.video,{start,end}).on('error',()=>res.destroy()).pipe(res);return true;
   }
   if(action==='preview'){
    if(active?.status!=='running'||!media?.mirror){json(404,{error:'bound_capture_unavailable'});return true;}
    let saved=previews.get(id!);if(!saved||Date.now()-saved.at>1500){saved={at:Date.now(),data:await readOverviewPreview(media.mirror)};previews.set(id!,saved);}
    send(200,saved.data,'image/png',{'Cache-Control':'no-store'});return true;
   }
   let path=resolve(deps.logDir,id+'.jsonl'),info=await stat(path).catch(()=>null);
   if(!info&&media?.sourceLog){path=media.sourceLog;info=await stat(path).catch(()=>null);}
   if(!info&&!active){json(404,{error:'session_not_found'});return true;}
   if(info&&info.size>200000000){json(413,{error:'recording_too_large'});return true;}
   let saved=cache.get(id!);
   if(!saved||info&&info.mtimeMs!==saved.mtime&&Date.now()-saved.at>5000){
    const records:any[]=[];if(info){const lines=createInterface({input:createReadStream(path,{encoding:'utf8'}),crlfDelay:Infinity});for await(const line of lines){try{records.push(JSON.parse(line));}catch{}}}
    saved={at:Date.now(),mtime:info?.mtimeMs??0,value:projectOverview(records),calls:projectPlanningCalls(records)};cache.set(id!,saved);if(cache.size>5)cache.delete(cache.keys().next().value!);
   }
   if(action==='calls'){
    const at=Number(url.searchParams.get('at')??saved.value.lastGameTime);
    if(!extra||!Number.isFinite(at)||at<0){json(400,{error:'invalid_call'});return true;}
    const call=planningCallAt(saved.calls.find(c=>c.id===extra),at);
    json(call?200:404,call??{error:'call_unavailable_at_this_time'});return true;
   }
   const after=Number(url.searchParams.get('after')??-1),live=active?liveOverview(deps.state(id!)):null;
   json(200,{id,mode:active?.status==='running'?'live':'recording',live,
    events:saved.value.events.filter(e=>e.index>(Number.isFinite(after)?after:-1)),calls:saved.calls.map(planningCallSummary),lastGameTime:saved.value.lastGameTime,boundary:saved.value.boundary,recordingNote:saved.value.recordingNote,
    media:media?.video?{url:'/api/deskfront/overview/'+id+'/media',sync:media.sync}:null,previewAvailable:active?.status==='running'&&!!media?.mirror});return true;
  }catch{json(503,{error:'overview_temporarily_unavailable'});return true;}
 };
}
