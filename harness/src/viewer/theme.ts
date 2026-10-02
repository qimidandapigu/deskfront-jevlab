export const OUTCOME_LABELS: Record<string, string> = {
  won: '胜利', lost: '失败', draw: '平局', finished: '已结束', void: '无效对局',
  'invalid-limit': '无效决策超限', 'tick-limit': '超时', 'turn-limit': '回合数用尽',
  loop: '陷入死循环', aborted: '已手动停止', error: '出错',
};

export const PLAYER_LABELS: Record<string, string> = { human: '玩家', ai: 'AI', jev: 'Jev', openrouter: 'Jev', deepseek: 'DeepSeek', mock: '离线规则演示' };

export const THEME = `
:root{
  --bg:#0b0e14;--panel:#10151f;--panel2:#171e2c;--line:#232c3f;--linesoft:#1a2231;
  --text:#e9edf4;--muted:#a5b1c3;--dim:#8794a8;
  --accent:#2ee6a8;--accent-ink:#06231a;--accent-soft:rgba(46,230,168,.12);
  --cyan:#43c6e8;--warn:#f0b24a;--bad:#f26d5f;--good:#34d399;
  --mono:ui-monospace,"SF Mono","Cascadia Mono","JetBrains Mono",Consolas,monospace;
  --sans:"PingFang SC","Microsoft YaHei",system-ui,-apple-system,sans-serif;
  --ease:cubic-bezier(.32,.72,0,1);
}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{color-scheme:dark}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);-webkit-font-smoothing:antialiased;
  background-image:radial-gradient(1000px 480px at 75% -8%,rgba(46,230,168,.07),transparent 60%),radial-gradient(800px 560px at -8% 12%,rgba(67,198,232,.05),transparent 55%);
  background-attachment:fixed}
::selection{background:rgba(46,230,168,.28)}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-thumb{background:#2a3449;border-radius:4px}
::-webkit-scrollbar-track{background:transparent}
a{color:var(--accent)}
button,select,input{font-family:inherit;color:var(--text)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}
.kicker{display:flex;align-items:center;gap:9px;font-family:var(--mono);font-size:10px;letter-spacing:.24em;text-transform:uppercase;color:var(--dim)}
.topbar{display:flex;align-items:center;gap:14px;padding:13px 24px;background:rgba(11,14,20,.82);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border-bottom:1px solid var(--linesoft);position:sticky;top:0;z-index:10}
.topbar .back{font-family:var(--mono);font-size:12px;letter-spacing:.06em;color:var(--muted);text-decoration:none;padding:6px 14px;border:1px solid var(--line);border-radius:99px;transition:border-color .15s var(--ease),color .15s var(--ease)}
.topbar .back:hover{border-color:var(--accent);color:var(--accent)}
.topbar h1{font-size:16px;margin:0;font-weight:600}
.topbar .sub{color:var(--dim);font-size:12px;font-family:var(--mono)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 8px var(--accent);flex-shrink:0}
.dot.pulse{animation:pulse 1.5s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.card{background:var(--panel);border:1px solid var(--linesoft);border-radius:14px}
.btn{font-size:14px;padding:8px 20px;border:1px solid var(--line);border-radius:99px;background:var(--panel2);color:var(--text);cursor:pointer;transition:border-color .15s var(--ease),background .15s var(--ease),transform .1s var(--ease)}
.btn:hover{border-color:var(--accent)}
.btn:active{transform:scale(.97)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);font-weight:700}
.btn.primary:hover{filter:brightness(1.08)}
.btn.primary:disabled{opacity:.5;cursor:default;filter:none}
.btn.danger{color:var(--bad);border-color:rgba(242,109,95,.45);background:transparent}
.btn.danger:hover{border-color:var(--bad);background:rgba(242,109,95,.1)}
.bar{background:var(--linesoft);margin:4px 0;border-radius:5px;overflow:hidden}
.bar>i{display:flex;justify-content:space-between;gap:10px;background:linear-gradient(90deg,rgba(46,230,168,.55),rgba(46,230,168,.8));color:var(--accent-ink);font-family:var(--mono);font-size:11px;padding:3px 9px;font-style:normal;min-width:fit-content;white-space:nowrap}
.bar.top>i{background:linear-gradient(90deg,var(--accent),#7df2c8);font-weight:700}
.gauge{height:8px;background:var(--linesoft);border-radius:4px;overflow:hidden;margin:6px 0}
.gauge>i{display:block;height:100%;background:linear-gradient(90deg,var(--warn),var(--bad))}
.tags{margin:8px 0}
.tag{display:inline-flex;align-items:center;font-family:var(--mono);font-size:11px;border:1px solid var(--line);color:var(--muted);border-radius:99px;padding:2px 10px;margin:2px 6px 2px 0}
.tag.warn{color:var(--warn);border-color:rgba(240,178,74,.45)}
.tag.bad{color:var(--bad);border-color:rgba(242,109,95,.45)}
.tag.cyan{color:var(--cyan);border-color:rgba(67,198,232,.45)}
.meta{color:var(--dim);font-size:11px;margin-top:10px;font-family:var(--mono);letter-spacing:.02em}
.meta a{color:var(--accent);text-decoration:none}
.result{font-size:22px;font-weight:700;margin:12px 0 0}
.result.good{color:var(--good)}.result.bad{color:var(--bad)}
pre.err{color:var(--bad);white-space:pre-wrap;font-size:12px;font-family:var(--mono)}
@media (prefers-reduced-motion:reduce){*{animation-duration:.01ms!important;transition-duration:.01ms!important}}
`;

