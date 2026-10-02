import { THEME } from './theme.js';
import type { BackendSource } from '../arena/sessions.js';
import type { ExternalCatalogEntry } from './template-types.js';

export function renderRuntimePage(entry: ExternalCatalogEntry, backends?: BackendSource): string {
  const options = { backends };
  return `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>${entry.name}</title><style>${THEME}main{max-width:1000px;margin:30px auto;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere}select,button{padding:8px;margin:5px}</style>
<main><a href="/">← 游戏大厅</a><h1>${entry.name}</h1><p>${entry.description}</p>
<select id="backend">${(options.backends?.names ?? []).map(name => `<option value="${name}"${name === options.backends?.defaultName ? ' selected' : ''}>${name}</option>`).join('')}</select>
<select id="variant" ${entry.variants.length ? '' : 'hidden'}>${entry.variants.map(v => `<option value="${v.id}">${v.name}</option>`).join('')}</select>
<select id="controller">${entry.capabilities.ai ? '<option value="ai">模型游玩</option>' : ''}${entry.capabilities.human ? '<option value="human">玩家游玩</option>' : ''}</select>
<div id="game-options"></div><label>最长运行秒数 <input id="duration" type="number" min="1" value="60"></label>
<label ${entry.capabilities.seed ? '' : 'hidden'}>种子 <input id="seed" type="number" min="0" max="4294967295" value="42"></label>
<button id="start">开始</button><button id="stop">结束本局</button><p id="status">准备就绪</p><pre id="world"></pre>
<details><summary>会话记录</summary><pre id="records"></pre></details></main>
<script>
let id=new URLSearchParams(location.search).get('session'),busy=false;
const statusEl=document.getElementById('status'),world=document.getElementById('world');
const optionSchema=${JSON.stringify(entry.options).replace(/</g, '\\u003c')},optionInputs={};
for(const [key,schema] of Object.entries(optionSchema)){const label=document.createElement('label');label.textContent=(schema.description||key)+' ';const input=document.createElement(schema.enum?'select':'input');if(schema.enum){schema.enum.forEach(value=>{const option=document.createElement('option');option.value=String(value);option.textContent=String(value);input.append(option);});}else input.type=schema.type==='boolean'?'checkbox':schema.type==='string'?'text':'number';if(schema.default!==undefined){input.value=String(schema.default);input.checked=schema.default===true;}if(schema.min!==undefined)input.min=String(schema.min);if(schema.max!==undefined)input.max=String(schema.max);label.append(input);document.getElementById('game-options').append(label);optionInputs[key]=input;}
async function api(path,body){const r=await fetch('/api/match/'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error);return data;}
document.getElementById('start').onclick=async()=>{if(busy)return;busy=true;try{if(id)await api(id+'/stop',{});const backend=document.getElementById('backend').value,variant=document.getElementById('variant').value,gameOptions={};for(const[key,input]of Object.entries(optionInputs)){const schema=optionSchema[key];if(schema.type!=='boolean'&&input.value==='')continue;gameOptions[key]=schema.enum?schema.enum.find(v=>String(v)===input.value):schema.type==='boolean'?input.checked:schema.type==='string'?input.value:Number(input.value);}const result=await api(${JSON.stringify(entry.id)},{mode:document.getElementById('controller').value,...(backend?{backend}:{}),...(variant?{variant}:{}),...(${entry.capabilities.seed}?{seed:Number(document.getElementById('seed').value)}:{}),gameOptions,runtime:{durationMs:Number(document.getElementById('duration').value)*1000}});id=result.matchId;history.replaceState(null,'','?session='+id);}catch(e){statusEl.textContent=e.message;}finally{busy=false;}};
document.getElementById('stop').onclick=async()=>{try{if(id)await api(id+'/stop',{});}catch(e){statusEl.textContent=e.message;}};
setInterval(async()=>{if(!id||busy)return;busy=true;try{const state=await api(id+'/state');statusEl.textContent=state.status==='done'?'已结束 · '+state.outcome:'进行中';world.textContent=JSON.stringify(state.latest?.observation??{},null,2);if(state.status==='done')document.getElementById('records').textContent=JSON.stringify(await api(id+'/history'),null,2);}catch(e){statusEl.textContent=e.message;}finally{busy=false;}},300);
</script></html>`;
}
