// KAPLAY presentation: one clock, queued actions, stable box matching, local SVG artwork.
(function () {
  const W = 640, H = 704, STEP = 0.11;
  let k, canvas, loading, ready = false, layout = '', state = null, key = null;
  let cell = 48, ox = 0, oy = 0, actor, crates = [], hud, queue = [], active = null;
  let pending = [], waiters = [], direction = { x: 0, y: 1 }, walkTime = 0;
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const svg = body => 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">${body}</svg>`);
  const assets = {
    floor: svg(`<rect width="128" height="128" fill="#b8ac8c"/><rect x="2" y="2" width="124" height="124" rx="7" fill="#dbcfb0"/><path d="M9 9H119M9 9V119" stroke="#efe6ce" stroke-width="3"/><path d="M16 108h24m43-83h19m-35 55h12" stroke="#b3a889" stroke-width="2" opacity=".5"/>`),
    wall: svg(`<rect width="128" height="128" fill="#797c60"/><rect x="3" y="13" width="122" height="112" rx="9" fill="#444f40"/><rect x="3" y="3" width="122" height="105" rx="9" fill="#717d5e"/><rect x="7" y="6" width="114" height="88" rx="7" fill="#89906d"/><path d="M11 14H116M11 14V82" fill="none" stroke="#a3aa85" stroke-width="4"/><path d="M7 53H121M64 7V53M34 54V94M99 54V94" stroke="#687554" stroke-width="3"/><path d="M13 100H115" stroke="#5b694c" stroke-width="3"/>`),
    goal: svg(`<circle cx="64" cy="64" r="42" fill="#ebba54" opacity=".2"/><rect x="29" y="29" width="70" height="70" rx="15" fill="none" stroke="#b78a36" stroke-width="4" stroke-dasharray="13 8"/><path d="M64 46v36M46 64h36" stroke="#ac7f30" stroke-width="5" stroke-linecap="round"/>`),
    box: crate(false), filled: crate(true),
    worker: svg(`<ellipse cx="64" cy="108" rx="30" ry="10" fill="#433e30" opacity=".25"/><rect x="43" y="86" width="16" height="22" rx="7" fill="#3c4745"/><rect x="70" y="86" width="16" height="22" rx="7" fill="#3c4745"/><rect x="30" y="58" width="20" height="31" rx="10" fill="#e1ac76"/><rect x="80" y="58" width="20" height="31" rx="10" fill="#e1ac76"/><rect x="39" y="53" width="51" height="43" rx="16" fill="#cc7750"/><path d="M47 57v22h35V57M47 78v17h35V78" fill="#668c94" stroke="#456c78" stroke-width="5"/><rect x="55" y="75" width="19" height="14" rx="4" fill="#8bafb1"/><rect x="39" y="25" width="51" height="41" rx="19" fill="#f2c591"/><path d="M42 30h44" stroke="#c59866" stroke-width="9"/><circle cx="54" cy="47" r="3" fill="#3f4542"/><circle cx="76" cy="47" r="3" fill="#3f4542"/><path d="M60 57q5 4 10 0" fill="none" stroke="#bd825e" stroke-width="2.5" stroke-linecap="round"/><path d="M32 32Q34 7 63 7Q92 7 96 33Z" fill="#e8b64f"/><path d="M60 9v18" stroke="#f7d57f" stroke-width="8" stroke-linecap="round"/><rect x="28" y="28" width="74" height="10" rx="5" fill="#d99937"/><path d="M38 18q5-7 13-7" fill="none" stroke="#ffe5a2" stroke-width="4" stroke-linecap="round"/>`),
  };
  function crate(goal) {
    const face = goal ? '#70a48b' : '#d8a662', rim = goal ? '#3f7560' : '#9b6738', light = goal ? '#a1ccb0' : '#f2cb8b';
    return svg(`<ellipse cx="66" cy="113" rx="48" ry="10" fill="#4e432d" opacity=".23"/><rect x="14" y="15" width="100" height="102" rx="9" fill="${rim}"/><rect x="14" y="10" width="100" height="96" rx="8" fill="${face}" stroke="${rim}" stroke-width="3"/><path d="M23 19h82M23 19v77" fill="none" stroke="${light}" stroke-width="5"/><path d="M28 44h72M28 68h72M28 90h72" stroke="${rim}" stroke-width="2" opacity=".5"/><path d="M25 25l77 70M102 25L25 95" stroke="${rim}" stroke-width="14"/><path d="M25 22l77 70M102 22L25 92" stroke="${light}" stroke-width="8"/><g fill="${rim}"><circle cx="25" cy="24" r="3"/><circle cx="102" cy="24" r="3"/><circle cx="25" cy="93" r="3"/><circle cx="102" cy="93" r="3"/></g>${goal ? '<circle cx="65" cy="58" r="20" fill="#f4edcd"/><path d="M54 58l8 8 15-17" fill="none" stroke="#417963" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>' : ''}`);
  }
  const same = (a,b) => a.x === b.x && a.y === b.y;
  const point = p => k.vec2(ox + (p.x + .5) * cell, oy + (p.y + .5) * cell);
  function sprite(name, p, z) { return k.add([k.sprite(name), k.anchor('center'), k.pos(point(p)), k.scale(cell / 128), k.z(z)]); }
  function settled() { if (!active && !queue.length && !pending.length) { waiters.splice(0).forEach(resolve => resolve()); } }
  function init() {
    if (loading) return loading;
    loading = (async () => {
      if (!window.kaplay) await new Promise((resolve, reject) => {
        const script = document.createElement('script'); script.src = '/vendor/kaplay.js'; script.onload = resolve; script.onerror = reject; document.head.append(script);
      });
      k = window.kaplay({ canvas, width: W, height: H, background: [38, 47, 40], global: false, focus: false, crisp: false, pixelDensity: Math.min(window.devicePixelRatio || 1, 2) });
      await Promise.all(Object.entries(assets).map(([name, data]) => k.loadSprite(name, data)));
      ready = true;
      const items = pending; pending = []; items.forEach(accept); settled();
    })().catch(error => {
      const feedback = document.getElementById('feedback');
      if (feedback) feedback.textContent = '场景加载失败，请刷新重试。';
      console.error('Sokoban scene:', error);
      pending = []; settled();
    });
    return loading;
  }
  function reset() {
    queue = []; active = null; pending = []; state = null; key = null; layout = '';
    if (k) k.destroyAll();
    actor = null; crates = []; settled();
  }
  function build(obs) {
    k.destroyAll(); queue = []; active = null;
    const rows = obs.board.rows, cols = Math.max(...rows.map(r => r.length));
    cell = Math.min(576 / cols, 576 / rows.length);
    ox = (W - cols * cell) / 2; oy = 80 + (576 - rows.length * cell) / 2;
    k.add([k.rect(cols * cell + 12, rows.length * cell + 12, { radius: 12 }), k.pos(ox - 6, oy - 3), k.color(24, 33, 28), k.z(-1)]);
    rows.forEach((row, y) => {
      for (let x = 0; x < cols; x++) {
        const ch = row[x] || '#'; sprite(ch === '#' ? 'wall' : 'floor', {x,y}, 0);
        if ('.*+'.includes(ch)) sprite('goal', {x,y}, 1);
      }
    });
    k.add([k.text('LITTLE WAREHOUSE', { size: 16, font: 'sans-serif' }), k.pos(32, 25), k.color(238, 224, 190)]);
    hud = k.add([k.text('', { size: 14, font: 'sans-serif' }), k.pos(W - 32, 27), k.anchor('topright'), k.color(196, 209, 177)]);
    k.add([k.text('MOVE  /  ARROWS     ·     UNDO  /  Z', { size: 12, font: 'sans-serif' }), k.pos(W / 2, H - 23), k.anchor('center'), k.color(162, 176, 151)]);
    actor = sprite('worker', obs.entities.player, 5);
    crates = obs.entities.boxes.map(p => ({ obj: sprite(p.onGoal ? 'filled' : 'box', p, 3), ...p }));
    state = obs; updateHud(obs);
    // KAPLAY's untagged onUpdate is an object too; destroyAll removes it on scene rebuild.
    k.onUpdate(update);
  }
  function updateHud(obs) {
    const filled = obs.entities.boxes.filter(b => b.onGoal).length;
    hud.text = `${filled} / ${obs.entities.boxes.length}    ·    ${obs.revision ?? obs.turn ?? 0} MOVES`;
    canvas.setAttribute('aria-label', `推箱子：${filled}/${obs.entities.boxes.length} 个木箱已归位，第 ${obs.revision ?? obs.turn ?? 0} 步`);
  }
  function accept(obs) {
    const map = obs.board.rows.map(r => r.replace(/[@+$*]/g, c => c === '@' || c === '$' ? ' ' : '.')).join('\n');
    const nextKey = JSON.stringify([obs.revision, obs.entities]);
    if (map !== layout || !state) { layout = map; key = nextKey; build(obs); settled(); return; }
    if (key === nextKey) return;
    key = nextKey;
    queue.push(obs);
  }
  function begin(obs) {
    // Reserve unchanged boxes first: a moving crate must never steal its neighbour's identity.
    const remaining = new Set(crates);
    const matched = obs.entities.boxes.map(p => {
      const old = crates.find(b => remaining.has(b) && same(b,p));
      if (old) remaining.delete(old);
      return { p, old };
    });
    matched.forEach(m => { if (!m.old) { m.old = remaining.values().next().value; remaining.delete(m.old); } });
    let prev = state.entities.player;
    const path = obs.lastPath || [];
    const valid = path.length && same(path[path.length - 1], obs.entities.player) && path.every(p => {
      const ok = Math.abs(prev.x-p.x) + Math.abs(prev.y-p.y) === 1; prev = p; return ok;
    });
    // Undo/replay seeking has no forward path: show the authoritative board without sliding through walls.
    if (!valid || reduced || matched.some(m => !m.old)) { const rest = queue; build(obs); queue = rest; return; }
    active = { obs, elapsed: 0, path: [state.entities.player, ...path], matched, duration: path.length * STEP };
  }
  function complete(a) {
    actor.pos = point(a.obs.entities.player);
    crates = a.matched.map(({p,old}) => {
      old.obj.pos = point(p); old.obj.use(k.sprite(p.onGoal ? 'filled' : 'box'));
      Object.assign(old, p); return old;
    });
    state = a.obs; updateHud(state); active = null;
  }
  function update() {
    if (!state) return;
    if (!active && queue.length) begin(queue.shift());
    if (!active) { settled(); return; }
    const a = active;
    a.elapsed = Math.min(a.duration, a.elapsed + k.dt());
    const progress = a.elapsed / STEP, i = Math.min(a.path.length - 2, Math.floor(progress));
    const f = Math.min(1, progress - i), from = a.path[i], to = a.path[i+1];
    direction = {x: to.x-from.x, y: to.y-from.y};
    actor.pos = point(from).lerp(point(to), f);
    walkTime += k.dt();
    actor.pos.y -= Math.sin(progress * Math.PI) ** 2 * cell * .025;
    actor.angle = direction.x * Math.sin(walkTime * 22) * 2;
    const push = Math.max(0, Math.min(1, progress - (a.path.length - 2)));
    a.matched.forEach(({p,old}) => { old.obj.pos = point(old).lerp(point(p), push); });
    if (a.elapsed >= a.duration) { actor.angle = 0; complete(a); settled(); }
  }
  window.gameClient = {
    reset,
    whenIdle() { return new Promise(resolve => { waiters.push(resolve); settled(); }); },
    draw(target, obs) {
      if (!obs?.board?.rows?.length || !obs.entities?.player) return;
      canvas = target;
      if (!ready) { pending.push(obs); init(); }
      else accept(obs);
    },
  };
})();
