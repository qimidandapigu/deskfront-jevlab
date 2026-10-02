import { matchStats, type BackendSource, type MatchState } from '../arena/sessions.js';
import type { GameRegistry } from '../arena/registry.js';
import type { ModelsConfig } from '../config.js';
import { THEME, OUTCOME_LABELS, PLAYER_LABELS } from './theme.js';
import type { HomeTemplateContext } from './template-types.js';

export function renderHomePage(context: HomeTemplateContext): string {
  const { registry, catalog, matches, config, backends, url } = context;
  const sessions = { catalog: () => catalog };
  const options = { config, backends };
        const modeLabel = (m: string) => m === 'turn' ? '回合制' : '实时';
        const cards = `<a class="card game-card" href="/ants" style="--game-accent:#c2e299"><div class="cover"><span>♧</span><small>六蚁协作 · 三关机关</small></div><div class="card-body"><div class="title">蚂蚁搬家<span class="badge">新游戏</span></div><div class="desc">转身过窄门、退出 U 形挡板、T 形大搬家。自己指挥六蚁，或观看 Jev / DeepSeek 独立协作。</div><div class="card-foot"><span>每关 3 分钟</span><b>进入实验室 ↗</b></div></div></a>` + registry.list().map(g =>
          `<a class="card game-card" href="/game/${g.id}" style="--game-accent:${g.experience?.accent ?? '#2ee6a8'}"><div class="cover" aria-hidden="true"><span>${g.experience?.symbol ?? '▶'}</span><small>${g.experience?.genre ?? modeLabel(g.mode)}</small></div><div class="card-body"><div class="title">${g.name}<span class="badge">${modeLabel(g.mode)}</span></div>` +
          `<div class="desc">${g.experience?.goal ?? g.description ?? ''}</div><div class="card-foot"><span>${g.experience?.duration ?? ''}</span><b>进入游戏 ↗</b></div></div></a>`).join('') + sessions.catalog().filter(g => g.mode === 'external').map(g =>
          `<a class="card game-card" href="${g.page}"><div class="cover"><span>▶</span><small>${g.capabilities.human ? '生成实验' : '协议演示'}</small></div><div class="card-body"><div class="title">${g.name}</div><div class="desc">${g.description}</div><div class="card-foot"><b>进入游戏 ↗</b></div></div></a>`).join('');
        const mask = (k: string) => k ? k.slice(0, 8) + '…（已配置，留空则不修改）' : '';
        const cfg = options.config?.get();
        // 最近对局：本次服务进程内的对局（新→旧，最多 8 条）
        const recent = [...matches.entries()]
          .sort((a, b) => b[1].startedAt - a[1].startedAt)
          .slice(0, 8);
        const recentPanel = recent.length ? `
<h2 class="sec-h">最近对局<span class="kicker">RECENT MATCHES</span></h2>
<div class="recent">${recent.map(([id, m]) => {
          const game = registry.list().find(g => g.id === m.gameId);
          const who = m.kind === 'human' ? '玩家' : (PLAYER_LABELS[m.backendName ?? ''] ?? m.backendName ?? 'AI');
          const vs = m.rivalBackendName ? ' vs ' + (PLAYER_LABELS[m.rivalBackendName] ?? m.rivalBackendName) : '';
          const outcome = m.status === 'done' ? (OUTCOME_LABELS[m.outcome ?? ''] ?? m.outcome ?? '?') : '进行中';
          const good = m.outcome === 'won' || m.outcome === 'finished';
          const stats = matchStats(m);
          const time = new Date(m.startedAt).toTimeString().slice(0, 8);
          return `<a class="recent-row" href="${m.runtime ? `/runtime/${m.gameId}?session=${id}` : `/replay/${id}`}">
<span class="recent-game">${game?.name ?? m.gameId}</span>
<span class="recent-who">${who}${vs}</span>
<span class="recent-outcome ${m.status === 'done' ? (good ? 'good' : 'bad') : ''}">${outcome}</span>
<span class="recent-meta">${stats.steps} 步${stats.totalTokens != null ? ' · ' + stats.totalTokens + ' tokens' : ''} · ${time}</span>
</a>`;
        }).join('')}</div>` : '';
        const modelCard = (id: string, title: string, subtitle: string, keyUrl: string, configured: boolean, providers: [string, string][], curProvider: string, keyMask: string, modelValue: string, modelHint: string) => `
<div class="cfg-card" id="card-${id}">
<div class="cfg-head"><span class="cfg-title">${title}</span><span class="cfg-badge ${configured ? 'ok' : 'na'}">${configured ? '已配置' : '未配置'}</span></div>
<p class="cfg-summary">${configured ? '使用已配置版本，选择这个 AI 即可开始。' : '配置后可开启 AI 对局；也可以先自己玩。'}</p>
<details class="cfg-advanced" id="${id}-advanced"><summary>${configured ? '高级设置' : '配置 AI'}</summary>
<div class="cfg-sub">${subtitle} · <a href="${keyUrl}" target="_blank" rel="noopener">获取 API Key ↗</a></div>
<div class="cfg-row"><label>接入方式</label><select id="${id}-provider">${providers.map(([v, l]) => `<option value="${v}"${v === curProvider ? ' selected' : ''}>${l}</option>`).join('')}</select></div>
<div class="cfg-row"><label>API Key</label><input id="${id}-key" type="password" placeholder="${keyMask || '粘贴 key 到这里'}"><button type="button" class="cfg-eye" data-for="${id}-key">显示</button></div>
<div class="cfg-row"><label>模型</label><select id="${id}-model" data-current="${modelValue}" data-hint="${modelHint}"><option value="${modelValue}" selected>${modelValue || '默认（' + modelHint + '）'}</option></select></div>
<div class="cfg-row" id="${id}-model-custom-row" hidden><label>自定义</label><input id="${id}-model-custom" placeholder="${modelHint}"></div>
<div class="cfg-row"><button type="button" class="cfg-test" data-model="${id}">测试连接</button><span class="cfg-test-status" id="${id}-test"></span></div>
</details>
</div>`;
        const configPanel = cfg ? `
<h2 class="sec-h">AI 设置<span class="kicker">AI SETTINGS</span></h2>
<p class="cfg-summary">选 Jev 或 DeepSeek 即可，无需挑选模型版本。沿用已配置版本，不自动切换新版本或预览版。</p>
<div class="cfg-grid">
${modelCard('jev', 'Jev', 'TypeSafe 结构化决策模型', 'https://console.typesafe.ai/keys', Boolean(cfg.jev.apiKey), [['typesafe', 'TypeSafe 官方直连'], ['openrouter', 'OpenRouter 中转']], cfg.jev.provider, mask(cfg.jev.apiKey), cfg.jev.model ?? '', cfg.jev.provider === 'typesafe' ? 'jev-latest' : 'typesafe/jev-1.13')}
${modelCard('deepseek', 'DeepSeek', '聊天模型 · logprobs 决策路线', 'https://console.volcengine.com/ark', Boolean(cfg.deepseek.apiKey), [['ark', '火山方舟'], ['openrouter', 'OpenRouter 中转']], cfg.deepseek.provider, mask(cfg.deepseek.apiKey), cfg.deepseek.model ?? '', 'deepseek-v4-1-flash-260910')}
${modelCard('analyst', 'Deskfront 指挥 / 体验分析', '无尽推进的独立规划模型；修改普通 DeepSeek 不会自动修改此项', 'https://console.volcengine.com/ark', Boolean(cfg.analyst?.apiKey), [['ark', '火山方舟'], ['openrouter', 'OpenRouter 中转']], cfg.analyst?.provider ?? 'ark', mask(cfg.analyst?.apiKey ?? ''), cfg.analyst?.model ?? '', 'deepseek-v4-1-flash-260910')}
</div>
<div class="cfg-footer">默认 AI：
<select id="default-model">
<option value="jev"${cfg.defaultModel === 'jev' ? ' selected' : ''}>Jev</option>
<option value="deepseek"${cfg.defaultModel === 'deepseek' ? ' selected' : ''}>DeepSeek</option>
</select>
<button id="cfg-save">保存配置</button><span id="cfg-status"></span></div>
<script>
// 模型下拉：从服务商 /models 拉真实列表；当前值不在列表里也会保留；「自定义…」兜底手动输入
function modelOf(id) {
  const v = document.getElementById(id + '-model').value;
  if (v === '__custom') return document.getElementById(id + '-model-custom').value || undefined;
  return v || undefined;
}
async function loadModelList(id) {
  const sel = document.getElementById(id + '-model');
  const provider = document.getElementById(id + '-provider').value;
  const apiKey = document.getElementById(id + '-key').value;
  const keep = sel.value === '__custom' ? sel.dataset.current : sel.value;
  sel.disabled = true;
  try {
    const r = await (await fetch('/api/models/list?target=' + id + '&provider=' + encodeURIComponent(provider) + (apiKey ? '&apiKey=' + encodeURIComponent(apiKey) : ''))).json();
    sel.innerHTML = '';
    if (r.ok && r.models && r.models.length) {
      for (const m of new Set(r.models)) {
        if (!keep && m === sel.dataset.hint) continue;
        sel.add(new Option(m, m));
      }
    }
    if (keep && ![...sel.options].some(o => o.value === keep)) sel.add(new Option(keep + '（当前）', keep), 0);
    if (!keep) sel.add(new Option('默认（' + sel.dataset.hint + '）', ''), 0);
    sel.value = keep;
    sel.add(new Option('自定义…', '__custom'));
    if (!r.ok) sel.title = '列表拉取失败：' + (r.error || '未知错误') + '，可选自定义手动输入';
    else sel.title = '';
  } catch (e) {
    sel.title = '列表拉取失败：' + e + '，可选自定义手动输入';
  }
  sel.disabled = false;
  document.getElementById(id + '-model-custom-row').hidden = sel.value !== '__custom';
}
for (const id of ['jev', 'deepseek', 'analyst']) {
  const sel = document.getElementById(id + '-model');
  sel.onchange = () => { document.getElementById(id + '-model-custom-row').hidden = sel.value !== '__custom'; };
  document.getElementById(id + '-provider').addEventListener('change', () => loadModelList(id));
  document.getElementById(id + '-advanced').addEventListener('toggle', function () {
    if (this.open && !this.dataset.loaded) {
      this.dataset.loaded = 'true';
      loadModelList(id);
    }
  });
}
for (const btn of document.querySelectorAll('.cfg-eye')) {
  btn.onclick = () => {
    const input = document.getElementById(btn.dataset.for);
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    btn.textContent = show ? '隐藏' : '显示';
  };
}
for (const btn of document.querySelectorAll('.cfg-test')) {
  btn.onclick = async () => {
    const id = btn.dataset.model;
    const el = document.getElementById(id + '-test');
    el.textContent = '测试中…'; el.className = 'cfg-test-status';
    btn.disabled = true;
    try {
      const r = await (await fetch('/api/config/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        target: id,
        provider: document.getElementById(id + '-provider').value,
        apiKey: document.getElementById(id + '-key').value,
        model: modelOf(id),
      }) })).json();
      el.textContent = r.ok ? ('连接正常 · ' + r.ms + 'ms') : ('失败：' + r.error);
      el.classList.add(r.ok ? 'pass' : 'fail');
    } catch (e) { el.textContent = '失败：' + e; el.classList.add('fail'); }
    btn.disabled = false;
  };
}
document.getElementById('cfg-save').onclick = async () => {
  const status = document.getElementById('cfg-status');
  const body = {
    defaultModel: document.getElementById('default-model').value,
    jev: { provider: document.getElementById('jev-provider').value,
      apiKey: document.getElementById('jev-key').value,
      model: modelOf('jev') },
    deepseek: { provider: document.getElementById('deepseek-provider').value,
      apiKey: document.getElementById('deepseek-key').value,
      model: modelOf('deepseek') },
    analyst: { provider: document.getElementById('analyst-provider').value,
      apiKey: document.getElementById('analyst-key').value,
      model: modelOf('analyst') },
  };
  const r = await (await fetch('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();
  status.textContent = r.ok ? '已保存，下一局生效' : ('保存失败：' + (r.error ?? '未知错误'));
};
</script>` : '';
        return `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>QuickPlay 竞技场</title>
<style>${THEME}
main{max-width:1120px;margin:0 auto;padding:44px 24px 72px}
.hero{margin-bottom:30px}
.hero h1{font-size:clamp(32px,5vw,54px);margin:18px 0 12px;letter-spacing:-.04em}
.hero .sub{color:var(--muted);font-size:14px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px}
a.card{display:block;padding:18px 20px;text-decoration:none;color:inherit;transition:border-color .18s var(--ease),transform .18s var(--ease),box-shadow .18s var(--ease)}
a.card:hover{border-color:rgba(46,230,168,.5);transform:translateY(-2px);box-shadow:0 10px 30px rgba(0,0,0,.4),0 0 0 1px rgba(46,230,168,.1)}
.title{font-size:16px;font-weight:600;display:flex;align-items:center;justify-content:space-between;gap:10px}
.badge{font-family:var(--mono);font-size:10px;letter-spacing:.14em;color:var(--accent);background:var(--accent-soft);border:1px solid rgba(46,230,168,.3);border-radius:99px;padding:3px 10px;flex-shrink:0}
.desc{font-size:13px;color:var(--muted);line-height:1.7;margin-top:10px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.sec-h{display:flex;align-items:center;gap:12px;font-size:18px;font-weight:600;margin:40px 0 14px}
.sec-h .kicker{flex-shrink:0}
.cfg-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}
.cfg-card{background:var(--panel);border:1px solid var(--linesoft);border-radius:14px;padding:18px 20px}
.cfg-head{display:flex;align-items:center;justify-content:space-between}
.cfg-title{font-size:15px;font-weight:600}
.cfg-badge{font-family:var(--mono);font-size:10px;letter-spacing:.1em;border-radius:99px;padding:3px 10px;border:1px solid}
.cfg-badge.ok{color:var(--good);border-color:rgba(52,211,153,.4);background:rgba(52,211,153,.08)}
.cfg-badge.na{color:var(--warn);border-color:rgba(240,178,74,.4);background:rgba(240,178,74,.08)}
.cfg-sub{font-size:12px;color:var(--dim);margin:6px 0 12px}
.cfg-summary{font-size:13px;color:var(--muted);line-height:1.7;margin:10px 0 16px}
.cfg-advanced summary{cursor:pointer;color:var(--accent);font-size:13px;padding:6px 0}
.cfg-advanced[open] summary{margin-bottom:12px}
.cfg-row[hidden]{display:none}
.cfg-sub a{color:var(--accent);text-decoration:none}
.cfg-row{display:flex;align-items:center;gap:10px;margin:10px 0;font-size:13px}
.cfg-row label{width:58px;color:var(--muted);flex-shrink:0;font-family:var(--mono);font-size:11px;letter-spacing:.06em}
.cfg-row input,.cfg-row select{flex:1;padding:7px 10px;border:1px solid var(--line);border-radius:8px;font-size:13px;min-width:0;background:var(--bg);color:var(--text)}
.cfg-row input:focus,.cfg-row select:focus{border-color:var(--accent);outline:none}
.cfg-row button{padding:7px 14px;border:1px solid var(--line);border-radius:99px;background:var(--panel2);cursor:pointer;font-size:12px;flex-shrink:0;transition:border-color .15s var(--ease)}
.cfg-row button:hover{border-color:var(--accent);color:var(--accent)}
.cfg-eye{width:56px}
.cfg-test-status{font-size:12px;color:var(--dim);font-family:var(--mono)}
.cfg-test-status.pass{color:var(--good)}
.cfg-test-status.fail{color:var(--bad)}
.cfg-footer{margin-top:18px;font-size:13px;display:flex;align-items:center;gap:12px;color:var(--muted)}
.cfg-footer select{padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--text)}
#cfg-save{padding:8px 24px;border-radius:99px;border:1px solid var(--accent);background:var(--accent);color:var(--accent-ink);font-weight:700;cursor:pointer;font-size:13px;transition:filter .15s var(--ease)}
#cfg-save:hover{filter:brightness(1.08)}
#cfg-status{color:var(--accent);font-size:12px;font-family:var(--mono)}
.recent{display:flex;flex-direction:column;gap:8px}
.recent-row{display:flex;align-items:center;gap:14px;background:var(--panel);border:1px solid var(--linesoft);border-radius:10px;padding:11px 16px;text-decoration:none;color:inherit;font-size:13px;transition:border-color .15s var(--ease)}
.recent-row:hover{border-color:rgba(46,230,168,.5)}
.recent-game{font-weight:600;min-width:64px}
.recent-who{color:var(--accent);min-width:72px;font-family:var(--mono);font-size:12px}
.recent-outcome{font-weight:600;min-width:90px}
.recent-outcome.good{color:var(--good)}
.recent-outcome.bad{color:var(--bad)}
.recent-meta{color:var(--dim);margin-left:auto;font-family:var(--mono);font-size:11px}
a.game-card{padding:0;overflow:hidden}
.cover{height:150px;position:relative;overflow:hidden;background:radial-gradient(ellipse at 70% 120%,var(--game-accent),transparent 70%),linear-gradient(135deg,#182234,#10151f);border-bottom:1px solid var(--line)}
.cover:before,.cover:after{content:'';position:absolute;border:1px solid var(--game-accent);width:180px;height:180px;transform:rotate(35deg);right:35px;top:-55px;opacity:.24}
.cover:after{right:90px;top:15px;width:110px;height:110px}
.cover>span{position:absolute;right:65px;top:10px;font:900 100px var(--mono);color:var(--game-accent);text-shadow:0 8px 40px #0b0e14}
.cover small{position:absolute;left:24px;bottom:22px;color:var(--text);letter-spacing:.14em;font-size:13px}
.card-body{padding:22px 24px}.card-body .title{font-size:22px}.card-body .desc{min-height:44px;line-height:1.8}
.card-foot{display:flex;justify-content:space-between;align-items:center;margin-top:20px;font-size:12px;color:var(--muted)}.card-foot b{color:var(--game-accent)}
.hero-actions{display:flex;gap:12px;align-items:center;margin-top:24px;flex-wrap:wrap}.hero-actions a{text-decoration:none}.hero-actions span{font-size:12px;color:var(--muted)}
.settings{margin-top:36px;padding:18px 22px}.settings summary{cursor:pointer;color:var(--muted)}.settings .sec-h{margin-top:24px}
@media(max-width:640px){main{padding:28px 16px}.grid{grid-template-columns:1fr}.cover{height:125px}.cfg-grid{grid-template-columns:1fr}.cfg-footer,.recent-row{flex-wrap:wrap}.recent-meta{width:100%;margin:0}}
</style>
<main>
<div class="hero"><div class="kicker"><span class="dot"></span>QUICKPLAY / 小游戏实验室</div>
<h1>认真玩一小局。</h1><div class="sub">解一道谜，抓一次反击，或者跳过下一道缺口。也可以切换 AI，看看它会怎么做。</div>
<div class="hero-actions"><a class="btn primary" href="/game/sokoban">从推箱子入门 →</a><span>真人游玩无需 API Key · 四种玩法 · 当前为原型版本</span></div></div>
<div class="grid">${cards}</div>${recentPanel}${configPanel ? '<details id="ai-settings" class="card settings"' + (url.searchParams.has('settings') ? ' open' : '') + '><summary>AI 实验设置 · 仅 AI 观战和模型对战需要</summary>' + configPanel + '</details>' : ''}</main>`;
}
