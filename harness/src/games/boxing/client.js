// KAPLAY owns the scene, render loop, articulated fighters and transient effects.
// Combat remains server-authoritative; observation frames drive every attack pose.
(function () {
  const W = 800, H = 450, FLOOR = 355;
  const colors = [[62, 196, 239], [249, 106, 92]];
  const phases = { idle: '准备', advance: '前进', retreat: '后退', guard: '格挡', startup: '起手', active: '判定', recovery: '收招 · 可反击', stun: '硬直', jump: '跳跃', dash: '冲刺', special: '烈焰冲拳' };
  let k, canvas, latest, loading = false, previousFrame = -1, eventFrame = -1;
  let fighters = [], hpBars = [], hpLabels = [], timer, distance, banner;
  let freezeUntil = 0;
  let powerBars = [], powerLabels = [];
  function rect(parent, x, y, w, h, color, z = 0) {
    return parent.add([k.rect(w, h, { radius: Math.min(12, w / 3, h / 3) }), k.pos(x, y), k.color(...color), k.z(z)]);
  }
  function circle(parent, x, y, r, color, z = 0) {
    return parent.add([k.circle(r), k.pos(x, y), k.color(...color), k.z(z)]);
  }
  function text(value, x, y, size, color = [232, 240, 250]) {
    return k.add([k.text(value, { size, font: 'sans-serif' }), k.pos(x, y), k.anchor('center'), k.color(...color), k.z(30)]);
  }
  function makeFighter(i) {
    const root = k.add([k.pos(i ? 610 : 190, FLOOR), k.scale(i ? -1 : 1, 1), k.rotate(0), k.z(5)]);
    const shadow = circle(k, root.pos.x, FLOOR + 4, 35, [5, 10, 20], 1); shadow.use(k.scale(1, 0.22));
    const dark = i ? [115, 46, 60] : [29, 83, 115];
    const legs = [rect(root, -25, -61, 17, 61, dark), rect(root, 12, -61, 17, 61, dark)];
    rect(legs[0], -4, 50, 26, 11, [221, 230, 239], 2); rect(legs[1], -2, 50, 26, 11, [221, 230, 239], 2);
    const body = rect(root, -23, -132, 46, 78, colors[i], 2); body.use(k.scale(1));
    rect(body, 5, 12, 7, 43, i ? [255, 154, 130] : [139, 225, 251], 1);
    rect(root, -24, -73, 48, 19, dark, 3);
    rect(root, -19, -73, 38, 5, [226, 230, 219], 4);
    const head = circle(root, 2, -157, 23, [239, 193, 153], 3);
    rect(head, -22, -19, 43, 9, dark, 1);
    circle(head, -21, 0, 5, [219, 163, 123], 1);
    circle(head, 10, -2, 2.5, [20, 27, 37], 2);
    rect(head, 5, -10, 12, 3, dark, 2);
    rect(head, 6, 10, 10, 2, [154, 94, 77], 2);
    const arms = [0, 1].map(j => {
      const arm = root.add([k.rect(42, 16, { radius: 8 }), k.pos(j ? 9 : -8, -118), k.rotate(-20), k.color(...colors[i]), k.z(j ? 6 : 1)]);
      const glove = circle(root, 42, -130, 16, j ? colors[i] : dark, j ? 7 : 2);
      circle(glove, -4, -5, 5, [249, 231, 213], 1).use(k.opacity(.28));
      rect(glove, -16, 5, 12, 5, [242, 231, 216], 1);
      return { arm, glove };
    });
    const label = text('准备', root.pos.x, FLOOR + 31, 15);
    return { root, shadow, legs, body, head, arms, label, target: root.pos.x, data: null, received: 0 };
  }
  function build() {
    k.destroyAll(); fighters = []; hpBars = []; hpLabels = []; powerBars = []; powerLabels = [];
    freezeUntil = 0; eventFrame = -1; k.setCamPos(k.vec2(W / 2, H / 2));
    rect(k, 0, 0, W, H, [12, 18, 32], -20);
    for (let i = 0; i < 10; i++) {
      const x = i * 87;
      rect(k, x, 85 + (i % 3) * 20, 55, 220, [19, 31, 48], -18);
      for (let j = 0; j < 4; j++) rect(k, x + 10, 115 + j * 34, 26, 3, [34, 59, 78], -17);
    }
    for (const x of [165, 635]) {
      const glow = circle(k, x, 195, 120, [77, 136, 165], -16); glow.use(k.scale(.75, 1.2)); glow.use(k.opacity(.06));
      rect(k, x - 34, 78, 68, 6, [155, 201, 213], -15);
    }
    for (let i = 0; i < 24; i++) {
      const x = 14 + i * 34, y = 268 + (i % 3) * 10;
      circle(k, x, y, 9, [34, 46, 65], -9);
      rect(k, x - 12, y + 8, 24, 32, [28, 39, 57], -9);
    }
    text('S T R E E T   C L A S H', 400, 111, 21, [111, 152, 168]);
    rect(k, 0, FLOOR, W, H - FLOOR, [26, 38, 55], -5);
    rect(k, 140, FLOOR + 49, 520, 2, [42, 60, 79], -4);
    for (let i = 0; i < 9; i++) rect(k, i * 100 - 20, FLOOR + 12, 62, 3, [66, 83, 101], -4);
    for (const x of [23, W - 33]) rect(k, x, 217, 10, 147, [50, 70, 92], -3);
    rect(k, 0, FLOOR, W, 3, [74, 119, 142], -2);
    [0, 1].forEach(i => {
      const x = i ? 450 : 28;
      rect(k, x, 23, 322, 22, [41, 49, 64], 20);
      hpBars.push(rect(k, x + 2, 25, 318, 18, colors[i], 21));
      hpLabels.push(text(i ? 'RIVAL' : 'PLAYER', x + 160, 64, 15));
      powerBars.push(rect(k, x, 393, 0, 9, [255, 197, 71], 21));
      powerLabels.push(text('POWER 0 / 100', x + 160, 378, 13, [255, 213, 126]));
      fighters.push(makeFighter(i));
    });
    timer = text('45', 400, 38, 32, [255, 220, 111]);
    distance = text('前进试探 · 后退诱空 · 抓收招反击', 400, 425, 14, [157, 185, 207]);
    banner = text('', 400, 164, 44, [255, 219, 108]);
    // Untagged onUpdate is scene-owned in KAPLAY: rebuild it after every destroyAll.
    k.onUpdate(() => fighters.forEach(updatePose));
  }
  function effect(e) {
    const side = e.from === 'self' ? 1 : 0;
    const v = fighters[e.type === 'miss' ? 1 - side : side];
    const x = v.target + (side ? -18 : 18), y = FLOOR - 132 - (v.data?.y || 0);
    const labels = { hit: '命中', counter: '反击 +2', guardbreak: '破防', block: '格挡', miss: '打空' };
    if (!labels[e.type]) return;
    const color = e.type === 'block' ? [104, 217, 255] : e.type === 'miss' ? [163, 176, 195] : [255, 220, 103];
    const callout = text(e.combo > 1 && e.type !== 'block' ? e.combo + ' HIT! ' + labels[e.type] : labels[e.type], Math.max(90, Math.min(710, x)), y - 88, 24, color);
    callout.use(k.opacity(1)); callout.use('combat-fx');
    const y0 = callout.pos.y;
    k.tween(0, 1, 0.6, t => { callout.pos.y = y0 - t * 28; callout.opacity = 1 - t; }).then(() => k.destroy(callout));
    if (e.type === 'miss') return;
    freezeUntil = k.time() + (e.kind === 'heavy' ? 0.045 : 0.025);
    k.shake(e.type === 'block' ? 1 : e.kind === 'special' ? 7 : e.kind === 'heavy' ? 4 : 2);
    for (let j = 0; j < 12; j++) {
      const angle = j * Math.PI / 6;
      const p = k.add([k.rect(j % 2 ? 15 : 8, 3), k.pos(x, y), k.rotate(angle * 180 / Math.PI), k.color(...color), k.opacity(1), k.z(15), 'combat-fx']);
      k.tween(0, 1, 0.24, t => { p.pos = k.vec2(x + Math.cos(angle) * 68 * t, y + Math.sin(angle) * 52 * t); p.opacity = 1 - t; }).then(() => k.destroy(p));
    }
  }
  function updatePose(v, i) {
    const f = v.data; if (!f || k.time() < freezeUntil) return;
    v.root.pos.x += (v.target - v.root.pos.x) * (1 - Math.exp(-k.dt() * 28));
    v.shadow.pos.x = v.root.pos.x; v.label.pos.x = v.root.pos.x; v.label.pos.y = Math.max(90, FLOOR - (f.y || 0) - 200);
    const moving = f.action === 'advance' || f.action === 'retreat';
    const stride = moving ? Math.sin(k.time() * 19) * 9 : 0;
    v.legs[0].pos.x = -25 + stride; v.legs[1].pos.x = 12 - stride;
    v.root.pos.y = FLOOR - (f.y || 0) - (moving ? Math.abs(stride) * 0.28 : Math.sin(k.time() * 3) * 1.2);
    if (f.hp <= 0) { v.root.angle += ((i ? 80 : -80) - v.root.angle) * Math.min(1, k.dt() * 7); v.label.text = 'K.O.'; return; }
    const tilt = f.phase === 'stun' ? -11 : f.phase === 'startup' ? -5 : f.phase === 'active' ? 9 : f.action === 'advance' ? 4 : 0;
    v.root.angle += ((i ? -tilt : tilt) - v.root.angle) * (1 - Math.exp(-k.dt() * 24));
    v.shadow.scale = k.vec2(Math.max(.35, 1 - (f.y || 0) / 300), .22);
    v.head.pos.y = -157 + (f.action === 'guard' ? 6 : 0);
    v.body.scale = k.vec2(1, f.action === 'guard' ? .93 : 1);
    let reach = 0;
    if (f.attackKind && f.phase !== 'stun') {
      const age = f.attackAge + Math.min(0.95, (k.time() - v.received) / 0.05);
      reach = age < f.startup ? -0.15 : age < f.startup + f.active ? 1 : Math.max(0, 1 - (age - f.startup - f.active) / Math.min(5, f.recovery));
    }
    v.arms.forEach(({ arm, glove }, j) => {
      const striking = f.attackKind === 'special' || (f.attackKind === 'heavy' ? j === 0 : j === 1);
      const extension = striking ? reach : 0;
      const gx = f.action === 'guard' ? 25 + j * 8 : 34 + extension * (f.attackKind === 'special' ? 100 : f.attackKind === 'heavy' ? 57 : 46);
      const gy = f.action === 'guard' ? -151 + j * 18 : -126 - extension * 7 + j * 9;
      const dx = gx - arm.pos.x, dy = gy - arm.pos.y;
      arm.width = Math.hypot(dx, dy); arm.angle = Math.atan2(dy, dx) * 180 / Math.PI;
      glove.pos = k.vec2(gx, gy);
      glove.color = f.phase === 'active' && striking ? k.rgb(255, 237, 171) : k.rgb(...colors[i]);
    });
    v.body.color = f.phase === 'stun' ? k.rgb(255, 235, 218) : k.rgb(...colors[i]);
    v.label.text = (f.y > 0 ? '空中 · ' : '') + (f.attackKind === 'special' ? '烈焰冲拳 · ' : '') + (phases[f.phase] || phases[f.action] || '准备');
    v.label.color = f.phase === 'recovery' ? k.rgb(255, 183, 109) : k.rgb(164, 199, 219);
  }
  function apply(obs) {
    if (!obs) return;
    const frame = obs.match?.frame ?? 0;
    if (frame < previousFrame) build();
    previousFrame = frame;
    const data = [obs.fighters?.self, obs.fighters?.opponent];
    data.forEach((f, i) => {
      if (!f) return;
      const v = fighters[i]; v.data = f; v.received = k.time();
      v.target = f.x ?? 400 + (i ? 1 : -1) * (obs.distance ?? 420) / 2;
      hpBars[i].width = Math.max(0, f.hp / f.maxHp) * 318;
      if (i) hpBars[i].pos.x = 770 - hpBars[i].width;
      powerBars[i].width = (f.meter || 0) / 100 * 322;
      powerLabels[i].text = `POWER ${f.meter || 0} / 100${f.meter >= 50 ? ' · I 必杀就绪' : ''}`;
      hpLabels[i].text = `${i ? 'RIVAL' : 'PLAYER'}  ${Math.ceil(f.hp)} / ${f.maxHp}`;
    });
    for (const e of obs.recent || []) if (e.frame > eventFrame) effect(e);
    eventFrame = frame;
    timer.text = String(Math.ceil(obs.match?.secondsLeft ?? 45));
    distance.text = `距离 ${obs.distance ?? 420}  |  命中连招 J → K → I（50气） · U 破防 · W 避投`;
    banner.text = ''; // Result text is owned by the viewer, not duplicated in the scene.
    canvas.setAttribute('aria-label', '拳击：左侧生命 ' + (data[0]?.hp ?? 100) + '，右侧生命 ' + (data[1]?.hp ?? 100));
  }
  function init() {
    canvas.width = W; canvas.height = H;
    canvas.style.width = '100%'; canvas.style.maxWidth = '800px'; canvas.style.height = 'auto';
    k = window.kaplay({ canvas, width: W, height: H, background: [12, 18, 32], global: false, focus: false });
    canvas.style.width = '100%'; canvas.style.height = 'auto'; canvas.style.aspectRatio = '800 / 450';
    build(); apply(latest);
  }
  window.gameClient = {
    reset() { previousFrame = -1; if (k) build(); },
    draw(target, obs) {
      canvas = target; latest = obs;
      if (k) return apply(obs);
      if (window.kaplay) return init();
      if (loading) return;
      loading = true;
      const script = document.createElement('script'); script.src = '/vendor/kaplay.js';
      script.onload = init;
      script.onerror = () => { loading = false; canvas.setAttribute('aria-label', 'KAPLAY 加载失败，请刷新重试'); };
      document.head.appendChild(script);
    },
  };
})();
