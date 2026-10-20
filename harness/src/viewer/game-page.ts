import type { GameRegistry } from '../arena/registry.js';
import type { BackendSource } from '../arena/sessions.js';
import type { RealtimeGame } from '../arena/plugin.js';
import { THEME } from './theme.js';

export function renderGamePage(pluginId: string, registry: GameRegistry, backends?: BackendSource): string {
        const plugin = registry.get(pluginId);
        const variants = JSON.stringify(plugin.variants ?? []);
        const backendNames = JSON.stringify(backends?.names ?? []);
        const defaultBackend = JSON.stringify(backends?.defaultName ?? backends?.names?.[0] ?? '');
        const description = plugin.experience
          ? `<b>你的目标</b><p>${plugin.experience.goal}</p><b>上手诀窍</b><p>${plugin.experience.tip}</p>`
          : plugin.description ?? '';
        // 回合制默认可自己玩（questions/humanQuestions 出按钮）；实时游戏需插件提供键位方案
        const allowHuman = plugin.mode === 'turn' || !!plugin.humanControls;
        // 题目标签由各问题 label 聚合，选项标签由 plugin.optionLabels 提供：新游戏零前端改动
        const probe = plugin.create();
        const qLabels: Record<string, string> = {};
        for (const [key, q] of Object.entries(probe.questions(probe.initialState()))) {
          if (q.label) qLabels[key] = q.label;
        }
        // 模型对模型：对手位独立问题集的标签也注入（如玩具兵的 enemy0/1/2）
        const rivalProbe = (probe as RealtimeGame<unknown>).rival;
        if (rivalProbe?.questions) {
          for (const [key, q] of Object.entries(rivalProbe.questions(probe.initialState()))) {
            if (q.label) qLabels[key] = q.label;
          }
        }
        const questionLabels = JSON.stringify(qLabels);
        const optionLabels = JSON.stringify(plugin.optionLabels ?? {});
        const humanControls = JSON.stringify(plugin.humanControls ?? null);
        // 实时游戏实现了 rival 钩子即可左右各选模型（模型对模型）
        const rivalAi = plugin.mode !== 'turn' && typeof (probe as RealtimeGame<unknown>).rival === 'object';
        const sideLabels = JSON.stringify(plugin.sideLabels ?? { self: '左', rival: '右' });
        return `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${plugin.name} · QuickPlay 竞技场</title>
<style>${THEME}
main{max-width:1120px;margin:0 auto;padding:26px 24px 60px}
#controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:18px}
select{font-size:13px;padding:8px 16px;border:1px solid var(--line);border-radius:99px;background:var(--panel2);color:var(--text);cursor:pointer;transition:border-color .15s var(--ease)}
select:hover{border-color:var(--accent)}
#status{font-family:var(--mono);font-size:12px;color:var(--muted);letter-spacing:.04em;display:inline-flex;align-items:center;gap:8px}
#wrap{display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap}
#stage{position:relative;background:var(--panel);padding:12px;border-radius:14px;border:1px solid var(--linesoft)}
#board{display:block;border-radius:8px;max-width:100%}
#overlay{position:absolute;inset:12px;display:none;align-items:center;justify-content:center;font-family:var(--mono);font-size:56px;font-weight:700;color:#fff;text-shadow:0 2px 18px rgba(0,0,0,.7);background:rgba(6,10,16,.5);border-radius:8px;pointer-events:none}
#overlay.error-state{flex-direction:column;gap:20px;pointer-events:auto;font-size:26px;overflow:auto}
#overlay.error-state p{max-width:460px;margin:0;font-size:16px;font-weight:400;line-height:1.8;color:var(--text);text-shadow:none}
#overlay.error-state a{font-size:16px;text-shadow:none;color:var(--accent)}
#overlay.count-pop{background:transparent;text-shadow:0 4px 28px rgba(46,230,168,.5);animation:countPop .95s var(--ease)}
@keyframes countPop{0%{transform:scale(2.4);opacity:0}20%{transform:scale(1);opacity:1}70%{transform:scale(.95);opacity:1}100%{transform:scale(.7);opacity:0}}
#panel{flex:1;min-width:300px;max-width:440px}
#panel .card{padding:16px 18px;margin-bottom:14px}
#panel .card h3{margin:0 0 10px;font-family:var(--mono);font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--dim);font-weight:600}
#howto{font-size:13px;line-height:1.8;color:var(--muted)}
#howto b{color:var(--text)}
#howto p{margin:6px 0 16px}#howto p:last-child{margin-bottom:0}
#stage{flex:1 1 480px;min-width:0;max-width:100%;overflow:hidden}
#board{height:auto!important;margin:auto;touch-action:none}
#panel{flex:1 1 280px;min-width:0}
#overlay{font-family:var(--sans);font-size:clamp(24px,4vw,42px);text-align:center;padding:20px}
#mode-help{font-size:13px;color:var(--muted);margin:0 0 18px;line-height:1.7}
#controls label{font-size:12px;color:var(--muted);display:flex;gap:8px;align-items:center}
#pad{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}#pad button{padding:12px 16px;touch-action:none;user-select:none;border-radius:10px;min-width:64px}
#pad button:active{background:var(--accent);color:var(--accent-ink)}
@media(max-width:640px){body{padding-bottom:110px}#pad{position:fixed;bottom:0;left:0;right:0;margin:0;padding:12px;z-index:20;background:rgba(11,14,20,.96);border-top:1px solid var(--line)}#pad button{flex:1;min-width:72px;padding:12px 8px}}
#feedback{color:var(--warn);font-size:14px;line-height:1.6;min-height:24px}
#next{margin:0 0 16px}#progress-note{color:var(--accent);font-size:12px;margin:10px 0}
@media(max-width:640px){main{padding:18px 12px}.topbar{padding:12px}.topbar .sub{display:none}#stage{padding:6px}#overlay{inset:6px}#panel{max-width:none}#controls{gap:8px}select{max-width:210px}#wrap{gap:14px}}
.mv{display:block;width:100%;text-align:left;margin:8px 0;padding:12px 16px;border:1px solid var(--line);border-radius:10px;background:var(--panel2);cursor:pointer;font-size:14px;color:var(--text);transition:border-color .15s var(--ease),background .15s var(--ease)}
.mv:hover{border-color:var(--accent);background:rgba(46,230,168,.06)}
.warehouse{max-width:1200px!important;--accent:#e9bd78;--accent-ink:#2e251c}
.warehouse-heading{margin:2px 0 28px}.warehouse-heading>span{font-size:10px;letter-spacing:.23em;color:#bc9b72}.warehouse-heading h2{font-size:34px;letter-spacing:.06em;color:#f4e8d4;margin:8px 0}.warehouse-heading p{color:#b8ab98;margin:0;font-size:14px}
.warehouse #stage{flex:1 1 580px;background:linear-gradient(145deg,#39382f,#222821);border:1px solid #575447;border-radius:24px;padding:18px;box-shadow:0 24px 65px #0005,inset 0 1px #ffffff12}
.warehouse #board{width:100%;border-radius:14px}.warehouse #panel{flex:1 1 260px;max-width:300px}.warehouse #panel .card{background:#1c2422;border-color:#35413a;border-radius:16px;padding:22px}.warehouse #howto{color:#b9c2b3;font-size:14px;line-height:1.9}.warehouse #howto b{color:#efe4cb}
.warehouse #stage{flex:0 1 auto;width:min(640px,calc((100dvh - 290px)*.909 + 36px));min-width:300px}.warehouse-heading{margin-bottom:18px}.warehouse-heading h2{font-size:30px}.warehouse #wrap{gap:26px}
.warehouse{padding-top:18px}.warehouse-heading{display:grid;grid-template-columns:auto 1fr;align-items:end;gap:6px 20px;margin-bottom:14px}.warehouse-heading>span{grid-column:1/-1}.warehouse-heading h2{margin:0}.warehouse-heading p{margin:0 0 4px}.warehouse #controls{margin-bottom:12px}.warehouse #mode-help{margin-bottom:8px}.warehouse #progress-note{margin:6px 0}
.warehouse #controls{padding:12px;background:#19221f;border:1px solid #323d35;border-radius:16px}.warehouse select{background:#273029;border-color:#445041}.warehouse summary{cursor:pointer;color:#dfc79f;font-size:13px;padding:3px 0}.warehouse details[open] summary{margin-bottom:20px}.warehouse .mv{background:#27322b;border-color:#3b4a3e}.warehouse #mode-help{color:#b1b9a8}.warehouse #overlay{inset:18px;border-radius:14px;background:#17241bd9}.warehouse #live:empty{display:none}
@media(max-width:640px){.warehouse-heading{margin-bottom:18px}.warehouse-heading h2{font-size:28px}.warehouse #stage{padding:8px;border-radius:16px}.warehouse #panel{max-width:none}.warehouse #overlay{inset:8px}}
@media(max-width:640px){.warehouse #stage{width:100%;min-width:0}.warehouse #wrap{gap:14px}}


.arcade #wrap{gap:22px}.arcade #stage{flex:1 1 700px;border-radius:20px;padding:14px;background:linear-gradient(145deg,#26333f,#141d29);box-shadow:0 18px 55px #0004}.arcade #board{width:100%;border-radius:12px}.arcade #panel{flex:1 1 240px;max-width:280px}.arcade #howto{font-size:14px;line-height:1.9}.arcade #panel .card{border-radius:16px;background:#141e29}.arcade #controls{padding:12px 16px;background:#141e29;border:1px solid #2a3946;border-radius:14px}.arcade #mode-help{color:#b4c6cc}#live-card summary,.rival-analysis summary{cursor:pointer;font-size:13px;color:#a9c8d8;padding:4px 0}#live-card details[open]>summary,.rival-analysis[open]>summary{margin-bottom:18px}.rival-analysis{margin-top:14px}.arcade #overlay{inset:14px;border-radius:12px;background:#0a131ccc}
@media(max-width:850px){.arcade #stage{flex-basis:100%}.arcade #panel{max-width:none}.arcade #controls{padding:10px}.arcade #stage{padding:6px}.arcade #overlay{inset:6px}}

.battlefield{max-width:1240px;margin:auto;padding:22px 28px;background:radial-gradient(ellipse at top,#26333166,transparent 65%)}
.battlefield #wrap{display:block}.battlefield #stage{padding:0;background:#172327;border:1px solid #516157;border-radius:12px;overflow:hidden;box-shadow:0 24px 80px #0007}.battlefield #stage{max-width:min(1040px,calc(150dvh - 270px));margin:auto}.battlefield #board{display:block;width:100%;max-height:none;object-fit:contain;border-radius:0}
.battlefield #controls{background:transparent;border:0;border-radius:0;padding:0;margin-bottom:14px}.battlefield #start{background:#e9bc68;color:#1d2928;border-color:#e9bc68;border-radius:6px;padding:12px 28px}.battlefield #mode-help{font-size:12px;color:#acb9ad;margin-bottom:12px}.battlefield #panel{max-width:none;display:flex;gap:12px;align-items:start;margin-top:14px}.battlefield #howto{flex:1;background:transparent;border:0;padding:8px 0;font-size:12px}.battlefield #howto p{display:inline;margin-right:20px}.battlefield #howto b{color:#dfc48e}.battlefield #live-card{flex:1;background:#162226;padding:14px}.battlefield #pad{flex:1}.battlefield #overlay{inset:0;border-radius:0;background:#0c171bd9}.battlefield .mv{background:#263734;border-color:#475a50;border-radius:6px}
@media(max-width:700px){.battlefield{padding:12px}.battlefield #panel{display:block}.battlefield #stage{max-width:100%}.battlefield #board{max-height:none}.battlefield #howto{margin-bottom:10px}.battlefield #controls{gap:6px}.battlefield #controls select{max-width:135px}}
</style>
<header class="topbar"><a class="back" href="/">← 首页</a><h1>${plugin.name}</h1><span class="sub">LIVE MATCH</span>${plugin.id === 'soldiers' ? '<a href="/game/soldiers-endless">无尽生成实验 ↗</a>' : ''}</header>
<main class="${plugin.id === 'sokoban' ? 'warehouse' : plugin.id === 'soldiers' ? 'arcade battlefield' : 'arcade'}">
${plugin.id === 'sokoban' ? '<div class="warehouse-heading"><span>THE LITTLE WAREHOUSE</span><h2>小小仓库</h2><p>挪动一步，让一切各就各位。</p></div>' : ''}
<div id="controls">
<label>出场 <select id="backend" aria-label="出场方式" hidden></select></label><span id="vs" hidden style="font-family:var(--mono);font-size:12px;color:var(--dim);letter-spacing:.1em">VS</span><select id="rival" aria-label="对手" hidden></select>
<select id="variant" aria-label="关卡" hidden></select>
<button id="start" class="btn primary">开始游戏</button><button id="stop" class="btn danger" hidden>结束本局</button><span id="status" role="status">准备就绪</span></div>
<p id="mode-help"></p><div id="progress-note"></div>
<div id="wrap">
<div id="stage"><canvas id="board" tabindex="0" aria-label="${plugin.name}游戏画面" width="480" height="480"></canvas><div id="overlay"></div></div>
<div id="panel"><button id="next" class="btn primary" hidden>下一关 →</button>${description ? '<div class="card" id="howto">' + description + '</div>' : ''}<div id="pad" hidden aria-label="游戏操作"></div><div id="feedback" role="status"></div><div class="card" id="live-card"><div id="live"><span class="meta">先看看场景，准备好后开始游戏。</span></div></div></div>
</div>
</main>
<script src="/client/${plugin.id}.js"></script>
<script type="module">
const variants = ${variants};
const backendNames = ${backendNames};
const defaultBackend = ${defaultBackend};
const RIVAL_AI = ${rivalAi};
const SIDE_LABELS = ${sideLabels};
const MODE = '${plugin.mode}';
const POLL_MS = MODE === 'realtime' ? (['boxing', 'soldiers', 'jump'].includes('${plugin.id}') ? 40 : 150) : 100;
const variantSel = document.getElementById('variant');
const backendSel = document.getElementById('backend');
const rivalSel = document.getElementById('rival');
const vsEl = document.getElementById('vs');
const startBtn = document.getElementById('start');
const stopBtn = document.getElementById('stop');
const statusEl = document.getElementById('status');
const live = document.getElementById('live');
const board = document.getElementById('board');
function setAnalysisMode(ai) {
  const card = document.getElementById('live-card');
  let details = card.querySelector('details');
  if (ai && !details) { details = document.createElement('details'); const title = document.createElement('summary'); title.textContent = 'AI 决策分析'; details.append(title, live); card.append(details); }
  else if (!ai && details) { card.append(live); details.remove(); }
}
const overlay = document.getElementById('overlay');
const pad = document.getElementById('pad');
const feedbackEl = document.getElementById('feedback');
const nextBtn = document.getElementById('next');
function showOverlay(text, cls){ overlay.classList.remove('count-pop', 'error-state'); overlay.textContent = text; overlay.style.color = cls === 'good' ? '#7bd88a' : cls === 'bad' ? '#ff8a7a' : '#fff'; overlay.style.display = 'flex'; }
function hideOverlay(){ overlay.classList.remove('error-state'); overlay.style.display = 'none'; }
let lastCount = -1;
function countOverlay(n){
  overlay.style.color = '#fff';
  overlay.style.display = 'flex';
  if (n !== lastCount) {   // 每个数字变化时重新触发弹出动画
    lastCount = n;
    overlay.textContent = n > 0 ? String(n) : 'GO!';
    overlay.classList.remove('count-pop');
    void overlay.offsetWidth;
    overlay.classList.add('count-pop');
  }
}
if (variants.length) {
  variantSel.hidden = false;
  variantSel.innerHTML = variants.map((v, i) => '<option value="' + v.id + '"' + (i === 0 ? ' selected' : '') + '>' + v.name + '</option>').join('');
}
const PLAYER_LABELS = { human: '玩家', ai: 'AI', jev: 'Jev', openrouter: 'Jev', deepseek: 'DeepSeek', bot: '内置 Bot' };
PLAYER_LABELS.human = '自己玩'; PLAYER_LABELS.mock = '离线规则演示'; PLAYER_LABELS.ai = 'AI 观战';
const playerOpts = backendNames.length ? backendNames.slice() : ['ai'];
if (${allowHuman}) playerOpts.push('human');
if (playerOpts.length) {
  backendSel.hidden = false;
  backendSel.innerHTML = playerOpts.map(n => '<option value="' + n + '"' + (n === defaultBackend || (n === 'ai' && !playerOpts.includes(defaultBackend)) ? ' selected' : '') + '>' + (PLAYER_LABELS[n] ?? n) + '</option>').join('');
  if (playerOpts.includes('human')) backendSel.value = 'human';
}
// 支持对手位 AI 的实时游戏：右侧下拉框 = 内置 Bot + 各模型，选模型即模型对模型
if (RIVAL_AI && backendNames.length && !backendSel.hidden) {
  const rivalOpts = ['bot', ...backendNames];
  rivalSel.hidden = false; vsEl.hidden = false;
  rivalSel.innerHTML = rivalOpts.map(n => '<option value="' + n + '"' + (n === 'bot' ? ' selected' : '') + '>' + (PLAYER_LABELS[n] ?? n) + '</option>').join('');
  const syncRival = () => { rivalSel.disabled = false; };   // 左侧选玩家时右侧仍可挑模型：玩家 vs AI
  backendSel.addEventListener('change', syncRival);
  syncRival();
}
const Q_LABELS = ${questionLabels};
const OPT_LABELS = ${optionLabels};
const HUMAN_CONTROLS = ${humanControls};
const OUTCOME_LABELS = { won: '胜利', lost: '失败', draw: '平局', finished: '已结束', void: '无效对局', 'invalid-limit': '无效决策超限', 'tick-limit': '超时', 'turn-limit': '回合数用尽', loop: '陷入死循环', aborted: '已手动停止', error: '出错' };
function qLabel(k){ return Q_LABELS[k] ?? k; }
function optLabel(k){ return OPT_LABELS[k] ? OPT_LABELS[k] + '（' + k + '）' : k; }
function bars(probs){
  const allEntries = Object.entries(probs);
  const entries = allEntries.length > 8 ? allEntries.sort((a,b)=>b[1]-a[1]).slice(0,6) : allEntries;
  const top = entries.length ? entries.reduce((a,b)=>b[1]>a[1]?b:a)[0] : null;
  return (allEntries.length > 8 ? '<div class="meta">显示概率最高的 6 项</div>' : '') + entries.map(([k,p])=>'<div class="bar'+(k===top?' top':'')+'"><i style="width:'+Math.max(Math.round(p*100),2)+'%"><span>'+optLabel(k)+'</span><span>'+(p*100).toFixed(0)+'%</span></i></div>').join('');
}
function gauge(score, probs){ const max = Math.max(...Object.keys(probs).map(Number), 1); const pct = Math.max(0, Math.min(100, score / max * 100)); return '<div class="gauge"><i style="width:'+pct+'%"></i></div><div class="meta" style="margin-top:4px">危险度 '+score.toFixed(2)+' / '+max+'</div>'; }
function renderAnswers(a){ return Object.entries(a).map(([k,v])=>{
  if(v.type==='score'&&k==='danger') return '<h3>'+qLabel(k)+'</h3>'+gauge(v.score,v.probabilities);
  if(v.type==='choice'||v.type==='score') return '<h3>'+qLabel(k)+'</h3>'+bars(v.probabilities)+'<div class="meta">置信度 '+(v.confidence==null?'-':v.confidence.toFixed(2))+(v.type==='score'?' · 得分 '+v.score.toFixed(2):'')+'</div>';
  return '<h3>'+qLabel(k)+'</h3><div class="meta">为真概率 '+(v.noul*100).toFixed(0)+'%</div>'; }).join(''); }
function renderBadges(r){
  const b = [];
  if (r.error) {
    const message = document.createElement('pre');
    message.className = 'err';
    message.textContent = '模型请求失败（第 ' + (r.failureCount || 1) + ' 次）：' + r.error;
    b.push(message.outerHTML);
  }
  if (r.execution) {
    const e = r.execution;
    const esc = value => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    const label = {applied:'已执行',rejected:'拒绝',discarded:'旧回复已丢弃',skipped:'未执行',error:'决策失败'}[e.status] ?? e.status;
    b.push('<span class="tag">' + esc(label) + '</span>');
    if (e.reason) b.push('<span class="tag warn">' + esc(e.reason) + '</span>');
    if (e.action && typeof e.action.command === 'string') b.push('<span class="tag cyan">执行：' + esc(optLabel(e.action.command)) + '</span>');
    if (e.action) b.push('<details><summary>实际执行</summary><pre>' + esc(JSON.stringify(e.action.command, null, 2)) + '</pre></details>');
    const effect = e.feedback ?? r.observation?.decisionFeedback;
    if (effect) b.push('<span class="tag">成效 ' + esc({progressed:'有进展',regressed:'进展减少',unchanged:'暂无目标进展',unknown:'尚未评估'}[effect.status] ?? effect.status) + ' · 连续原地无收益 ' + effect.repeats + '</span>');
  }
  if (r.hesitation) b.push('<span class="tag">低置信度（照常执行）</span>');
  if (r.capped) b.push('<span class="tag cyan">降级 ' + optLabel(r.capped.from) + '→' + optLabel(r.capped.to) + '</span>');
  if (r.blocked) b.push('<span class="tag warn">风险标记（未拦截） ' + optLabel(r.blocked.choice) + '</span>');
  if (r.abstained) b.push('<span class="tag">弃权已转为可用动作</span>');
  if (r.usage) { const u = r.usage; b.push('<span class="tag">tokens ' + (u.totalTokens ?? ((u.promptTokens ?? 0) + (u.completionTokens ?? 0))) + '</span>'); }
  return b.length ? '<div class="tags">' + b.join('') + '</div>' : '';
}
function setIdle(text){ startBtn.disabled = false; startBtn.textContent = '再来一局'; variantSel.disabled = false; backendSel.disabled = false; rivalSel.disabled = false; stopBtn.hidden = true; statusEl.textContent = text; }
function fail(msg){
  const raw = String(msg || '服务未返回具体原因');
  const missingKey = /需要配置.*API_KEY|未配置.*(?:key|密钥)|缺.*API.?key/i.test(raw);
  const auth = /401|403|unauthorized|invalid.*(?:key|token)/i.test(raw);
  const timeout = /timeout|timed out|超时/i.test(raw);
  const title = missingKey ? '请先配置 AI' : auth ? 'AI 验证失败' : timeout ? 'AI 响应超时' : '暂时无法开始游戏';
  const provider = /OPENROUTER/i.test(raw) ? 'OpenRouter' : /TYPESAFE/i.test(raw) ? 'TypeSafe' : '当前接入方式';
  const hint = missingKey ? provider + ' 尚未配置 API Key。请在 AI 设置中确认接入方式、填写 Key 并保存，再回来重试。'
    : auth ? '请在 AI 设置中检查 API Key 是否有效，以及是否有访问所选模型的权限。'
    : timeout ? '模型服务暂时没有及时响应，请稍后点击“再来一局”。'
    : '请检查本地服务和模型连接，然后点击“再来一局”重试。';
  showOverlay(title, 'bad');
  overlay.classList.add('error-state');
  const message = document.createElement('p'); message.textContent = hint; overlay.append(message);
  const settings = document.createElement('a'); settings.href = '/?settings=1#ai-settings'; settings.textContent = '打开 AI 设置'; overlay.append(settings);
  const details = document.createElement('details');
  const summary = document.createElement('summary'); summary.textContent = '错误详情';
  const pre = document.createElement('pre'); pre.className = 'err'; pre.textContent = raw;
  details.append(summary, pre); live.replaceChildren(details);
  const analysis = document.querySelector('#live-card > details'); if (analysis) analysis.open = true;
  polling = false; pad.hidden = true; setIdle(title);
}
function doneFooter(s, id){
  pad.hidden = true;
  if (s.outcome === 'won' && s.kind === 'human' && variants.length) {
    try { const cleared = JSON.parse(localStorage.getItem('quickplay:${plugin.id}:cleared') || '[]'); if (!cleared.includes(variantSel.value)) cleared.push(variantSel.value); localStorage.setItem('quickplay:${plugin.id}:cleared', JSON.stringify(cleared)); } catch {}
    nextBtn.hidden = variantSel.selectedIndex >= variants.length - 1;
    updateProgress();
  }
  const st = s.stats ?? {};
  return '<div class="meta">' + (MODE === 'turn' ? '操作 ' + (st.steps ?? '?') + ' 次' : '本局已结束')
    + (st.avgMs != null ? ' · 平均决策 ' + st.avgMs + 'ms' : '')
    + (st.totalTokens != null ? ' · tokens ' + st.totalTokens : '')
    + ' · <a href="/replay/' + id + '">查看本局回放 ↗</a></div>';
}
let polling = false;
let lastObsJson = null;
let lastPanelHtml = null;
let lastLiveFrame = -1, lastLiveAt = 0;   // 实时局帧冻结检测：停表思考时提示而不是像卡死
async function poll(id){
  let s;
  try { s = await (await fetch('/api/match/'+id+'/state')).json(); }
  catch (e) {   // 服务器进程挂了/网络断：明确提示而不是定格成"死机"
    showOverlay('连接中断', 'bad');
    live.innerHTML += '<div class="result bad">连接服务器失败，对局中断</div>';
    setIdle('连接中断'); polling = false; return;
  }
  if (s.error) {   // 服务器重启后对局丢失：同样明确提示
    showOverlay('对局已失效', 'bad');
    live.innerHTML += '<div class="result bad">对局已失效（服务器可能已重启），请再来一局</div>';
    setIdle('对局已失效'); polling = false; return;
  }
  if (s.latest) {
    // AI 实时局优先画逐帧直播观测（决策帧间隔数秒，直接看会"瞬移"）；面板仍用最新决策记录
    const drawObs = s.liveObservation ?? s.latest.resultObservation ?? s.latest.observation;
    const obsJson = JSON.stringify(drawObs);
    if (obsJson !== lastObsJson) {   // 观测没变就不重绘，消除整帧重画的闪烁
      lastObsJson = obsJson;
      try { window.gameClient.draw(board, drawObs); } catch (e) { live.innerHTML = '<pre style="color:red">draw error: ' + (e && e.stack || e) + '</pre>'; return; }
    }
    for (const l of s.latest.observation?.landings || []) OPT_LABELS[l.id] = '落点 (' + Math.round(l.x) + ', ' + l.y + ')';
    let html;
    if (s.latestRival) {   // 模型对模型：面板分左右两栏，各自显示决策分布
      const L = PLAYER_LABELS[s.backendName] ?? s.backendName ?? SIDE_LABELS.self;
      const R = PLAYER_LABELS[s.rivalBackendName] ?? s.rivalBackendName ?? SIDE_LABELS.rival;
      html = '<h3 style="color:var(--accent)">' + SIDE_LABELS.self + ' · ' + L + '</h3>'
        + renderAnswers(s.latest.answers) + renderBadges(s.latest) + '<div class="meta">' + (s.latest.feedback || '') + ' ' + s.latest.ms + 'ms</div>'
        + '<h3 style="color:var(--cyan);margin-top:16px">' + SIDE_LABELS.rival + ' · ' + R + '</h3>'
        + renderAnswers(s.latestRival.answers) + renderBadges(s.latestRival) + '<div class="meta">' + s.latestRival.ms + 'ms</div>';
    } else {
      html = renderAnswers(s.latest.answers) + renderBadges(s.latest) + '<div class="meta">'+(s.latest.feedback||'')+' '+s.latest.ms+'ms</div>';
    }
    if (html !== lastPanelHtml) { lastPanelHtml = html; live.innerHTML = html; }
  }
  const remainMs = startsAt - Date.now();
  if (s.latest && (s.latest.turn === 0 || s.latest.frame === 0) && remainMs > 0) { const n = Math.ceil(remainMs / 1000); statusEl.textContent = n + ' 秒后开局'; countOverlay(n); }
  else if (s.latest && lastCount >= 0 && remainMs > -800 && (s.latest.turn === 0 || s.latest.frame === 0)) { countOverlay(0); statusEl.textContent = 'GO!'; }
  else if (s.latest) {
    lastCount = -1; hideOverlay();
    if (MODE === 'realtime' && s.liveFrame != null) {
      if (s.liveFrame !== lastLiveFrame) { lastLiveFrame = s.liveFrame; lastLiveAt = Date.now(); }
      // 停表思考期间帧号冻结：超过 0.6s 没新帧说明在等模型，不是卡死
      statusEl.textContent = s.latest.error ? '模型请求失败，正在重试…' : Date.now() - lastLiveAt > 600 ? '画面更新延迟（第 ' + s.liveFrame + ' 帧）' : '第 ' + s.liveFrame + ' 帧';
    } else {
      statusEl.textContent = s.latest.turn === 0 ? '等待 AI 第一步…' : s.latest.turn != null ? '回合 ' + s.latest.turn + ' / 60' : '第 ' + s.latest.frame + ' 帧';
    }
  }
  if (s.status === 'done') {
    if (s.finalObservation !== undefined && s.finalObservation !== null) {
      try { window.gameClient.draw(board, s.finalObservation); } catch (e) { /* 保留决策前画面 */ }
    }
    const duel = !!s.rivalBackendName;
    const label = duel && s.outcome === 'won' ? SIDE_LABELS.self + '方胜利'
      : duel && s.outcome === 'lost' ? SIDE_LABELS.rival + '方胜利'
      : (OUTCOME_LABELS[s.outcome] ?? s.outcome);
    const good = !duel && (s.outcome === 'won' || s.outcome === 'finished');
    // 最后一步走位动画播完再弹结果覆盖层，别让"胜利"盖住最后一推
    const lastPath = s.finalObservation && Array.isArray(s.finalObservation.lastPath) ? s.finalObservation.lastPath : null;
    const animMs = lastPath && lastPath.length ? lastPath.length * 130 + 400 : 0;
    const finishedMatch = id;
    const finishDisplay = () => {
      if (currentMatch !== finishedMatch) return;
      showOverlay(label, duel ? '' : good ? 'good' : 'bad');
      live.innerHTML += '<div class="result' + (duel ? '' : good ? ' good' : ' bad') + '">结果：' + label + '</div>' + (s.error ? '<pre class="err">' + s.error + '</pre>' : '') + doneFooter(s, id);
      setIdle('已结束');
    };
    if (window.gameClient.whenIdle) window.gameClient.whenIdle().then(finishDisplay);
    else setTimeout(finishDisplay, animMs);
    polling = false;
    return;
  }
  setTimeout(() => poll(id), POLL_MS);
}
let human = null;
let lastRivalHtml = null;
async function rtPoll(){
  if (!human || !human.rt) return;
  let s;
  try { s = await (await fetch('/api/match/'+human.matchId+'/state?compact=1')).json(); }
  catch (e) {
    showOverlay('连接中断', 'bad');
    live.innerHTML += '<div class="result bad">连接服务器失败，对局中断</div>';
    setIdle('连接中断'); human = null; return;
  }
  if (s.error) {
    showOverlay('对局已失效', 'bad');
    live.innerHTML += '<div class="result bad">对局已失效（服务器可能已重启），请再来一局</div>';
    setIdle('对局已失效'); human = null; return;
  }
  const remainMs = startsAt - Date.now();
  if (s.latest && s.latest.frame === 0 && remainMs > 0) { const n = Math.ceil(remainMs / 1000); statusEl.textContent = n + ' 秒后开局'; countOverlay(n); }
  else if (s.latest && lastCount >= 0 && remainMs > -800 && s.latest.frame === 0) { countOverlay(0); statusEl.textContent = 'GO!'; }
  else { lastCount = -1; hideOverlay(); if (s.latest) statusEl.textContent = '游戏进行中'; }
  if (s.latest) { try { window.gameClient.draw(board, s.latest.observation); } catch (e) { /* 保留上一帧 */ } }
  if (s.latestRival) {   // 玩家 vs AI：右侧面板实时显示对手模型的决策分布
    const R = PLAYER_LABELS[s.rivalBackendName] ?? s.rivalBackendName ?? SIDE_LABELS.rival;
    const html = (s.latestCompanion ? '<h3>队友 · ' + R + '</h3>' + renderAnswers(s.latestCompanion.answers) + renderBadges(s.latestCompanion) : '') + '<h3 style="color:var(--cyan);margin-top:12px">' + SIDE_LABELS.rival + ' · ' + R + '</h3>'
      + renderAnswers(s.latestRival.answers) + renderBadges(s.latestRival) + '<div class="meta">' + s.latestRival.ms + 'ms</div>';
    if (html !== lastRivalHtml) { lastRivalHtml = html; const rp = document.getElementById('rivalPanel'); if (rp) rp.innerHTML = html; }
  }
  if (s.status === 'done') {
    if (s.finalObservation) { try { window.gameClient.draw(board, s.finalObservation); } catch (e) {} }
    const duel = !!s.rivalBackendName;
    const label = duel && s.outcome === 'won' ? '你赢了！'
      : duel && s.outcome === 'lost' ? SIDE_LABELS.rival + '方（' + (PLAYER_LABELS[s.rivalBackendName] ?? s.rivalBackendName) + '）胜利'
      : (OUTCOME_LABELS[s.outcome] ?? s.outcome);
    const good = duel ? s.outcome === 'won' : (s.outcome === 'won' || s.outcome === 'finished');
    showOverlay(label, good ? 'good' : 'bad');
    live.innerHTML += '<div class="result ' + (good ? 'good' : 'bad') + '">结果：' + label + '</div>' + doneFooter(s, human.matchId);
    setIdle('已结束');
    human = null;
    return;
  }
  setTimeout(rtPoll, '${plugin.id}' === 'jump' ? 16 : ['boxing', 'soldiers'].includes('${plugin.id}') ? 40 : 100);
}
let rtTimer = null;
function rtCompute(){
  let input = HUMAN_CONTROLS.idle || 'idle';
  for (const a of HUMAN_CONTROLS.priority) { if (human.keys.has(a)) { input = a; break; } }
  const combos = HUMAN_CONTROLS.combos || {};
  for (const c in combos) {
    if (c.split('+').every(function(p){ return human.keys.has(p); })) { input = combos[c]; break; }
  }
  return input;
}
function rtSend(){
  if (!human || !human.rt) return;
  const input = rtCompute();
  if (input !== human.sent) {
    human.sent = input;
    fetch('/api/match/'+human.matchId+'/input', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ input }) }).catch(() => { feedbackEl.textContent = '操作发送失败，请结束本局后重试。'; });
  }
}
function rtKey(e, down){
  if (!HUMAN_CONTROLS || !human) return;
  const raw = e.key && e.key.length === 1 ? e.key.toLowerCase() : e.key;
  const action = HUMAN_CONTROLS.keys[raw];
  if (!action) return;
  e.preventDefault();
  if ((HUMAN_CONTROLS.events || []).includes(action)) {
    if (down && !e.repeat && !human.pressed.has(raw)) {
      human.pressed.clear(); human.keys.clear(); human.pressed.add(raw);
      if (rtTimer) { clearTimeout(rtTimer); rtTimer = null; }
      human.sent = HUMAN_CONTROLS.idle || 'idle';
      fetch('/api/match/'+human.matchId+'/input', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({input:action}) });
    } else if (!down) human.pressed.delete(raw);
    return;
  }
  if (rtTimer) { clearTimeout(rtTimer); rtTimer = null; }
  if (down) {
    human.pressed.add(raw);
    human.keys = new Set([...human.pressed].map(k => HUMAN_CONTROLS.keys[k]));
    human.downAt = performance.now();
    rtSend();
  } else {
    human.pressed.delete(raw);
    human.keys = new Set([...human.pressed].map(k => HUMAN_CONTROLS.keys[k]));
    // 点按保底：出招类输入至少保留 150ms，确保服务器至少消费一个 tick（快按不会被松开事件立刻冲掉）
    const oneShot = HUMAN_CONTROLS.oneShot || [];
    const held = performance.now() - (human.downAt || 0);
    if (held < 150 && oneShot.indexOf(human.sent) >= 0) {
      rtTimer = setTimeout(function(){ rtTimer = null; rtSend(); }, 150 - held);
      return;
    }
    rtSend();
  }
}
function renderChoices(c){
  live.innerHTML = '<h3>你的回合</h3>' + c.options.map(o => '<button class="mv" data-k="' + o.id + '">' + o.label + (o.id === 'undo' ? ' · Z' : '') + '</button>').join('');
  live.querySelectorAll('.mv').forEach(b => { b.onclick = () => play(b.dataset.k); });
}
let actionBusy = false;
async function play(choice){
  if (!human || actionBusy) return;
  actionBusy = true;
  try {
    const r = await (await fetch('/api/match/'+human.matchId+'/action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: human.question, choice }) })).json();
    if (r.error) { feedbackEl.textContent = r.error; return; }
    showHuman(r);
  } catch { feedbackEl.textContent = '操作未送达，请重试。'; }
  finally { await window.gameClient.whenIdle?.(); actionBusy = false; }
}
function showHuman(s){
  feedbackEl.textContent = s.latest?.feedback || '';
  if (s.latest) { try { window.gameClient.draw(board, s.latest.observation); } catch (e) { live.innerHTML = '<pre style="color:red">draw error: ' + (e && e.stack || e) + '</pre>'; return; } }
  if (s.status === 'done') {
    const label = OUTCOME_LABELS[s.outcome] ?? s.outcome;
    const finishedMatch = human.matchId;
    Promise.resolve(window.gameClient.whenIdle?.()).then(() => { if (currentMatch === finishedMatch) showOverlay(label, s.outcome === 'won' ? 'good' : 'bad'); });
    live.innerHTML = '<div class="result ' + (s.outcome === 'won' ? 'good' : 'bad') + '">结果：' + label + '</div>' + doneFooter(s, human.matchId);
    setIdle('已结束');
    human = null;
    return;
  }
  human.question = s.choices.question;
  human.keys = s.choices.keys;
  statusEl.textContent = '回合 ' + (s.latest && s.latest.turn || 1) + ' · 轮到你';
  renderChoices(s.choices);
}
document.addEventListener('keydown', e => {
  if (!human) return;
  if (e.target.closest('input,select,textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
  if (human.rt) { rtKey(e, true); return; }
  const map = { ArrowUp: 'U', ArrowDown: 'D', ArrowLeft: 'L', ArrowRight: 'R', w: 'U', s: 'D', a: 'L', d: 'R', z: 'undo' };
  const k = map[e.key.length === 1 ? e.key.toLowerCase() : e.key];
  if (k && human.keys.includes(k)) { e.preventDefault(); play(k); }
});
document.addEventListener('keyup', e => {
  if (human && human.rt) rtKey(e, false);
});
function releaseInputs(){
  if (rtTimer) { clearTimeout(rtTimer); rtTimer = null; }
  if (human?.rt) { human.keys.clear(); human.pressed.clear(); rtSend(); }
}
window.addEventListener('blur', releaseInputs);
document.addEventListener('visibilitychange', () => { if (document.hidden) releaseInputs(); });
let currentMatch = null;
let startsAt = 0;
stopBtn.onclick = async () => {
  if (!currentMatch) return;
  stopBtn.disabled = true;
  releaseInputs();
  try {
    await fetch('/api/match/'+currentMatch+'/stop', { method: 'POST' });
    statusEl.textContent = '正在停止…';
    if (human && !human.rt) showHuman(await (await fetch('/api/match/'+currentMatch+'/state')).json());
  } catch { stopBtn.disabled = false; feedbackEl.textContent = '结束请求未送达，请重试。'; }
};
startBtn.onclick = async () => {
  try {
  setAnalysisMode(backendSel.value !== 'human');
  startBtn.disabled = true; variantSel.disabled = true; backendSel.disabled = true; rivalSel.disabled = true;
  stopBtn.hidden = false; stopBtn.disabled = false;
  startBtn.textContent = '进行中…';
  hideOverlay();
  nextBtn.hidden = true; feedbackEl.textContent = ''; pad.hidden = true;
  lastCount = -1;
  live.innerHTML = ''; statusEl.textContent = '加载中，请稍候…';
  lastObsJson = null; lastPanelHtml = null;
  currentMatch = null;
  window.gameClient.reset?.();
  human = null;
  const player = backendSel.hidden ? 'ai' : backendSel.value;
  const rival = variants.find(v => v.id === variantSel.value)?.rival !== false && RIVAL_AI && !rivalSel.hidden && rivalSel.value !== 'bot' ? rivalSel.value : null;
  const body = JSON.stringify({
    ...(variants.length ? { variant: variantSel.value } : {}),
    ...(player === 'human' ? { mode: 'human', ...(rival ? { rival } : {}) } : { mode: 'ai', ...(backendNames.length ? { backend: player } : {}), ...(rival ? { rival } : {}) }),
  });
  const r = await (await fetch('/api/match/${plugin.id}', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body })).json();
  if (r.error) { fail(r.error); return; }
  currentMatch = r.matchId;
  startsAt = r.startsAt ?? 0;
  if (r.kind === 'human') {
    if (MODE === 'realtime') {
      human = { matchId: r.matchId, rt: true, keys: new Set(), pressed: new Set(), sent: null };
      live.innerHTML = '<h3>自己玩</h3><div>' + (HUMAN_CONTROLS ? HUMAN_CONTROLS.help : '') + '</div>' + (rival ? '<details class="rival-analysis"><summary>对手 AI 分析</summary><div id="rivalPanel"></div></details>' : '');
      lastRivalHtml = null;
      buildPad(); board.focus();
      rtPoll();
      return;
    }
    const s = await (await fetch('/api/match/'+r.matchId+'/state')).json();
    human = { matchId: r.matchId, question: null, keys: [] };
    showHuman(s);
    board.focus();
    return;
  }
  if (!polling) { polling = true; poll(r.matchId); }
  } catch { fail('无法开始游戏，请检查本地服务后重试。'); }
};
function buildPad(){
  pad.replaceChildren();
  if (!HUMAN_CONTROLS) return;
  const seen = new Set();
  for (const [key, action] of Object.entries(HUMAN_CONTROLS.keys)) {
    if (seen.has(action)) continue;
    seen.add(action);
    const b = document.createElement('button'); b.className = 'btn';
    b.textContent = OPT_LABELS[action] || ({ flankLeft:'向左侧移', flankRight:'向右侧移' })[action] || action;
    b.addEventListener('pointerdown', e => { e.preventDefault(); b.setPointerCapture(e.pointerId); rtKey({ key, preventDefault(){} }, true); });
    b.addEventListener('keydown', e => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); if (human?.rt) rtKey({ key, preventDefault(){} }, true); } });
    b.addEventListener('keyup', e => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); if (human?.rt) rtKey({ key, preventDefault(){} }, false); } });
    for (const event of ['pointerup','pointercancel','lostpointercapture']) b.addEventListener(event, () => { if (human?.rt) rtKey({ key, preventDefault(){} }, false); });
    pad.append(b);
  }
  pad.hidden = false;
}
function updateProgress(){
  if (!variants.length) return;
  try { const cleared = JSON.parse(localStorage.getItem('quickplay:${plugin.id}:cleared') || '[]'); document.getElementById('progress-note').textContent = '本机通关进度 ' + variants.filter(v => cleared.includes(v.id)).length + ' / ' + variants.length; } catch {}
}
let previewVersion = 0;
async function previewBoard(){
  const version = ++previewVersion;
  try {
    const r = await (await fetch('/api/preview/${plugin.id}?variant=' + encodeURIComponent(variantSel.value))).json();
    if (version === previewVersion && !startBtn.disabled) { window.gameClient.reset?.(); window.gameClient.draw(board, r.observation); }
  } catch { feedbackEl.textContent = '场景预览加载失败，可以重试或直接开始。'; }
}
function modeHelp(){ document.getElementById('mode-help').textContent = backendSel.value === 'human' ? '自己玩 · ' + (HUMAN_CONTROLS?.help || '方向键 / WASD 移动 · Z 撤销 · 也可点右侧按钮') : backendSel.value === 'mock' ? '离线规则演示 · 使用固定规则选择动作，不调用真实模型。' : ('${plugin.id}' === 'jump' ? 'AI 辅助路线 · 模型选落脚点，本地寻路与控制器完成跳跃；落稳后等待下一次选择。会产生 API 用量。' : 'AI 观战 · 模型负责操作，右侧显示决策过程，会产生 API 用量。' + (MODE === 'realtime' ? ' 游戏持续运行；无指令时保持无输入状态。' : '')); }
backendSel.addEventListener('change', modeHelp);
variantSel.addEventListener('change', () => { rivalSel.hidden = !RIVAL_AI || variants.find(v => v.id === variantSel.value)?.rival === false; vsEl.hidden = rivalSel.hidden; hideOverlay(); nextBtn.hidden = true; previewBoard(); });
nextBtn.onclick = () => { variantSel.selectedIndex++; startBtn.onclick(); };
updateProgress(); modeHelp(); previewBoard();
if (location.hash.includes('auto')) startBtn.onclick();
</script>`;
}
