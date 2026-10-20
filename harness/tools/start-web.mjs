/** Portable entry for the prebuilt Web game. Never downloads game dependencies implicitly. */
import {readFile,writeFile,copyFile,access,mkdir} from 'node:fs/promises';
import {spawn,spawnSync} from 'node:child_process';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
process.chdir(root);
const check=process.argv.includes('--check'),pythonCandidates=[process.env.PYTHON_BIN,'python','python3'].filter(Boolean);
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
if(!keys)throw Error('请先填写 config.local.json 中 jev / deepseek / analyst 的 apiKey；DeepSeek 和 analyst 可使用同一密钥。不会启动付费模型请求。');
if(!ffmpeg)console.warn('未安装 FFmpeg：游戏可运行，回放封装暂不可用。安装 FFmpeg 后重新启动即可。');
const children=[];
function start(file,port){return new Promise((ok,no)=>{const child=spawn(process.execPath,['--import','tsx',file,String(port)],{cwd:root,env:process.env,windowsHide:true,stdio:['inherit','pipe','inherit']});children.push(child);let text='';child.stdout.on('data',chunk=>{const s=chunk.toString();process.stdout.write(s);text+=s;const m=/http:\/\/127\.0\.0\.1:(\d+)/.exec(text);if(m)ok({child,port:Number(m[1])});});child.once('error',no);child.once('exit',code=>{if(!text.includes('http://'))no(Error(file+' 启动失败 '+code));});});}
const replay=await start('tools/deskfront-replays.ts',Number(process.env.REPLAY_PORT??0));
process.env.DESKFRONT_REPLAY_ORIGIN='http://127.0.0.1:'+replay.port;
const viewer=await start('tools/deskfront-web.ts',Number(process.env.VIEWER_PORT??50205));
console.log('打开 http://127.0.0.1:'+viewer.port+'/?view=beginner');
function stop(){for(const child of children)if(child.exitCode===null)child.kill();}
process.on('SIGINT',()=>{stop();process.exit(0);});process.on('SIGTERM',()=>{stop();process.exit(0);});
viewer.child.once('exit',code=>{stop();process.exit(code??1);});
