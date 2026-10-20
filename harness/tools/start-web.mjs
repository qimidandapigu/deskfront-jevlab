/** Portable entry for the prebuilt Web game. Never downloads game dependencies implicitly. */
import {readFile,copyFile,access} from 'node:fs/promises';
import {spawn,spawnSync} from 'node:child_process';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
process.chdir(root);
const check=process.argv.includes('--check'),smoke=process.argv.includes('--smoke'),pythonCandidates=[process.env.PYTHON_BIN,'python','python3'].filter(Boolean);
const [major,minor]=process.versions.node.split('.').map(Number);
if(major<22||major===22&&minor<19)throw Error('需要 Node.js 22.19 或更新版本，推荐24 LTS。');
let python;
for(const candidate of pythonCandidates){const r=spawnSync(candidate,['-c','import sys; print(sys.executable); print("%d.%d"%sys.version_info[:2])'],{encoding:'utf8',windowsHide:true});if(r.status===0&&r.stdout.trim().split(/\r?\n/).at(-1)==='3.13'){python=r.stdout.trim().split(/\r?\n/)[0];break;}}
if(!python&&process.platform==='win32'){const r=spawnSync('py',['-3.13','-c','import sys;print(sys.executable)'],{encoding:'utf8',windowsHide:true});if(r.status===0)python=r.stdout.trim();}
if(!python)throw Error('需要 Python 3.13（随包宿主和关卡运行组件采用 CPython 3.13 格式）。安装后重试，或设置 PYTHON_BIN。');
process.env.PYTHON_BIN=python;
for(const file of ['output/web-releases/deskfront-20261020/game.wasm','output/web-releases/deskfront-20261020/game.pck','output/web-releases/deskfront-20261020/game.js','output/web-game-20261020/host-code/release_runtime.pyc','output/web-game-20261020/level-runtime/provider.pyc','output/web-game-20261020/sdk/src/deskfront/attached_entry.py'])await access(resolve(root,file));
await access(resolve(root,'node_modules/tsx/package.json')).catch(()=>{throw Error('请先在 harness 目录执行 npm ci。');});
const importTest=spawnSync(python,['-c',`import sys;sys.path.insert(0,'output/web-game-20261020/host-code');import release_runtime;sys.path.insert(0,'output/web-game-20261020/sdk/src/deskfront');from level_provider import load_factory;f=load_factory('output/web-game-20261020/level-runtime/provider.pyc');assert callable(f)`],{encoding:'utf8',windowsHide:true});
if(importTest.status!==0)throw Error('运行组件检查失败：'+importTest.stderr);
const config=resolve(root,'config.local.json');
try{await access(config);}catch{await copyFile(resolve(root,'config.local.example.json'),config);console.log('已建立 config.local.json，请填写自己的模型密钥。');}
const value=JSON.parse(await readFile(config,'utf8')),keys=Boolean(value.jev?.apiKey&&value.deepseek?.apiKey&&value.analyst?.apiKey);
const ffmpeg=spawnSync('ffmpeg',['-version'],{windowsHide:true,stdio:'ignore'}).status===0;
console.log(JSON.stringify({gameFiles:true,python:'3.13',hostImport:true,levelRuntimeImport:true,keysConfigured:keys,ffmpegAvailable:ffmpeg,networkModelCalls:0}));
if(check)process.exit(0);
if(!keys&&!smoke)throw Error('请先填写 config.local.json 中 jev / deepseek / analyst 的 apiKey；DeepSeek 和 analyst 可使用同一密钥。不会启动付费模型请求。');
if(!ffmpeg)console.warn('未安装 FFmpeg：游戏可运行，回放封装暂不可用。安装 FFmpeg 后重新启动即可。');
const children=[];
function stop(){for(const child of children)if(child.exitCode===null)child.kill();}
// Register cleanup before spawning anything: a failed viewer must not orphan replay.
process.on('exit',stop);
process.on('SIGINT',()=>{stop();process.exit(0);});process.on('SIGTERM',()=>{stop();process.exit(0);});
function start(file,port){return new Promise((ok,no)=>{
 const child=spawn(process.execPath,['--import','tsx',file,String(port)],{cwd:root,env:process.env,windowsHide:true,stdio:['inherit','pipe','inherit']});children.push(child);let text='',ready=false;
 const timer=setTimeout(()=>{child.kill();no(Error(file+' 启动超过20秒，请检查端口及服务日志。'));},20000);
 child.stdout.on('data',chunk=>{const s=chunk.toString();process.stdout.write(s);text=(text+s).slice(-8192);const m=/http:\/\/127\.0\.0\.1:(\d+)/.exec(text);if(m&&!ready){ready=true;clearTimeout(timer);ok({child,port:Number(m[1])});}});
 child.once('error',e=>{clearTimeout(timer);no(e);});child.once('exit',code=>{clearTimeout(timer);if(!ready)no(Error(file+' 启动失败 '+code));});
});}
try{
 const replay=await start('tools/deskfront-replays.ts',Number(process.env.REPLAY_PORT??0));
 process.env.DESKFRONT_REPLAY_ORIGIN='http://127.0.0.1:'+replay.port;
 const viewer=await start('tools/deskfront-web.ts',Number(process.env.VIEWER_PORT??(smoke?0:50205)));
 const origin='http://127.0.0.1:'+viewer.port;
 console.log('打开 '+origin+'/?view=beginner');
 if(smoke){
  const page=await(await fetch(origin+'/?view=beginner',{signal:AbortSignal.timeout(5000)})).text();
  const health=await(await fetch(origin+'/web/health',{signal:AbortSignal.timeout(5000)})).json();
  if(!page.includes('replay-list')||!page.includes(process.env.DESKFRONT_REPLAY_ORIGIN+'/replays.js')||health.job!==null)throw Error('启动自检未通过');
  console.log(JSON.stringify({smoke:true,web:true,replay:true,credentialsRequired:false,modelCalls:0,pids:children.map(x=>x.pid),ports:[viewer.port,replay.port]}));
  stop();
 }else viewer.child.once('exit',code=>{stop();process.exit(code??1);});
}catch(e){stop();console.error(e.message);process.exitCode=1;}
