import type { GameRegistry } from '../arena/registry.js';
import type { MatchState } from '../arena/sessions.js';
import { THEME } from './theme.js';

export function renderReplayPage(matchId: string, match: MatchState, registry: GameRegistry): string {
  const plugin = registry.get(match.gameId);
        const probe = plugin.create();
        const qLabels: Record<string, string> = {};
        for (const [key, q] of Object.entries(probe.questions(probe.initialState()))) {
          if (q.label) qLabels[key] = q.label;
        }
        return `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>回放 · ${plugin.name} · QuickPlay 竞技场</title>
<style>${THEME}
main{max-width:1120px;margin:0 auto;padding:26px 24px 60px}
#wrap{display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap}
#stage{background:var(--panel);padding:12px;border-radius:14px;border:1px solid var(--linesoft)}
#board{display:block;border-radius:8px;max-width:100%}
#transport{display:flex;align-items:center;gap:8px;margin-top:12px}
#transport button{font-family:var(--mono);font-size:13px;padding:7px 12px;border:1px solid var(--line);border-radius:99px;background:var(--panel2);color:var(--text);cursor:pointer;min-width:42px;transition:border-color .15s var(--ease),color .15s var(--ease)}
#transport button:hover{border-color:var(--accent);color:var(--accent)}
#slider{flex:1;accent-color:var(--accent)}
#step{font-family:var(--mono);font-size:11px;color:var(--dim);min-width:100px;text-align:right}
#panel{flex:1;min-width:300px;max-width:440px}
#panel .card{padding:16px 18px;margin-bottom:14px}
#panel .card h3{margin:0 0 10px;font-family:var(--mono);font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--dim);font-weight:600}
#summary{font-size:14px;line-height:1.7}
</style>
<header class="topbar"><a class="back" href="/">← 首页</a><h1>${plugin.name} · 回放</h1><span class="sub" id="who"></span></header>
<main><div id="wrap">
<div id="stage"><canvas id="board" width="480" height="480"></canvas>
<div id="transport">
<button id="first" title="第一步">⏮</button><button id="prev" title="上一步">◀</button>
<button id="play" title="播放/暂停">▶</button>
<button id="next" title="下一步">▶|</button><button id="last" title="最后一步">⏭</button>
<input id="slider" type="range" min="0" max="0" value="0"><span id="step"></span>
</div></div>
<div id="panel"><div class="card" id="summary"></div><div class="card"><div id="live"></div></div></div>
</div></main>
<script src="/client/${plugin.id}.js"></script>
<script type="module">
const OUTCOME_LABELS = { won: '胜利', lost: '失败', draw: '平局', finished: '已结束', void: '无效对局', 'invalid-limit': '无效决策超限', 'tick-limit': '超时', 'turn-limit': '回合数用尽', loop: '陷入死循环', aborted: '已手动停止', error: '出错' };
const Q_LABELS = ${JSON.stringify(qLabels)};
const OPT_LABELS = ${JSON.stringify(plugin.optionLabels ?? {})};
const PLAYER_LABELS = { human: '玩家', ai: 'AI', jev: 'Jev', openrouter: 'Jev', deepseek: 'DeepSeek' };
function qLabel(k){ return Q_LABELS[k] ?? k; }
function optLabel(k){ return OPT_LABELS[k] ? OPT_LABELS[k] + '（' + k + '）' : k; }
function bars(probs){
  const allEntries = Object.entries(probs);
  const entries = allEntries.length > 8 ? allEntries.sort((a,b)=>b[1]-a[1]).slice(0,6) : allEntries;
  const top = entries.length ? entries.reduce((a,b)=>b[1]>a[1]?b:a)[0] : null;
  return (allEntries.length > 8 ? '<div class="meta">显示概率最高的 6 项</div>' : '') + entries.map(([k,p])=>'<div class="bar'+(k===top?' top':'')+'"><i style="width:'+Math.max(Math.round(p*100),2)+'%"><span>'+optLabel(k)+'</span><span>'+(p*100).toFixed(0)+'%</span></i></div>').join('');
}
function renderAnswers(a){ return Object.entries(a).map(([k,v])=>{
  if(v.type==='choice'||v.type==='score') return '<h3>'+qLabel(k)+'</h3>'+bars(v.probabilities)+'<div class="meta">置信度 '+(v.confidence==null?'-':v.confidence.toFixed(2))+(v.type==='score'?' · 得分 '+v.score.toFixed(2):'')+'</div>';
  return '<h3>'+qLabel(k)+'</h3><div class="meta">为真概率 '+(v.noul*100).toFixed(0)+'%</div>'; }).join(''); }
const data = await (await fetch('/api/match/${matchId}/history')).json();
const records = data.history ?? [];
const board = document.getElementById('board');
const slider = document.getElementById('slider');
const stepEl = document.getElementById('step');
const live = document.getElementById('live');
slider.max = Math.max(0, records.length - 1);
const who = data.kind === 'human' ? '玩家' : (PLAYER_LABELS[data.backendName] ?? data.backendName ?? 'AI')
  + (data.rivalBackendName ? ' vs ' + (PLAYER_LABELS[data.rivalBackendName] ?? data.rivalBackendName) : '');
const dur = data.finishedAt ? ' · 用时 ' + Math.round((data.finishedAt - data.startedAt) / 1000) + 's' : '';
document.getElementById('who').textContent = who + ' · ' + (OUTCOME_LABELS[data.outcome] ?? '进行中');
const st = data.stats ?? {};
document.getElementById('summary').innerHTML = '<b>' + who + '</b> · ' + (OUTCOME_LABELS[data.outcome] ?? '进行中') + dur
  + '<div class="meta">' + (st.steps ?? 0) + ' 步' + (st.avgMs != null ? ' · 平均决策 ' + st.avgMs + 'ms' : '') + (st.totalTokens != null ? ' · tokens ' + st.totalTokens : '') + '</div>';
let idx = 0, playing = false, timer = null;
function show(i){
  idx = Math.max(0, Math.min(records.length - 1, i));
  const r = records[idx];
  if (!r) { live.innerHTML = '<span class="meta">没有记录</span>'; return; }
  for (const l of r.observation?.landings || []) OPT_LABELS[l.id] = '落点 (' + Math.round(l.x) + ', ' + l.y + ')';
  // 最后一步：记录存的是决策前画面，终局时用动作生效后的最终帧
  const obs = (idx === records.length - 1 && data.finalObservation) ? data.finalObservation : (r.resultObservation ?? r.observation);
  try { window.gameClient.draw(board, obs); } catch (e) { /* 保留上一帧 */ }
  live.innerHTML = renderAnswers(r.answers ?? {}) + '<div class="meta">' + (r.feedback || '') + (r.ms ? ' ' + r.ms + 'ms' : '') + '</div>';
  slider.value = idx;
  stepEl.textContent = (r.turn != null ? '回合 ' + r.turn : '帧 ' + (r.frame ?? idx)) + ' / ' + (records.length - 1);
}
function stop(){ playing = false; document.getElementById('play').textContent = '▶'; if (timer) { clearInterval(timer); timer = null; } }
document.getElementById('play').onclick = () => {
  if (playing) return stop();
  playing = true; document.getElementById('play').textContent = '⏸';
  timer = setInterval(() => { if (idx >= records.length - 1) return stop(); show(idx + 1); }, 700);
};
document.getElementById('first').onclick = () => show(0);
document.getElementById('prev').onclick = () => show(idx - 1);
document.getElementById('next').onclick = () => show(idx + 1);
document.getElementById('last').onclick = () => show(records.length - 1);
slider.oninput = () => show(Number(slider.value));
show(0);
</script>`;
}
