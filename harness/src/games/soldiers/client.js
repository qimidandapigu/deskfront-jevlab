// 玩具兵打枪渲染：Kaplay 版。俯视桌面枪战——木纹桌面、堆叠沙袋掩体；
// 小兵是俯视玩具兵（头盔/身体/持枪，枪口即朝向），玩家绿色带白星徽、敌人红色；
// 开火枪口闪光+抛弹壳，曳光弹双层发光，命中溅粒子，死亡翻倒淡出；
// 单位按 id 持久化、单一逐帧插值平滑移动；底部 HUD 用 k.text。
(function () {
  let k = null;
  let canvasEl = null;
  let loading = false;
  const pending = [];

  let W = 960, H = 640;
  let TILE = 12;           // 由观测 width/height 按画布自适应，40x20 格 → 480x440 战场区
  let OX = 0, OY = 0;      // 战场偏移（垂直居中，避免大片空桌面）
  let layoutKey = null;
  let lastTick = null;   // tick 回退说明开了新一局，强制重建静态层以清掉终局横幅等残留
  const units = new Map(); // id → { group, parts, hpBg, hpFg, cx, cy, dead, pulsing, color, dark }
  let tracerObjs = [];     // 每次观测重建的短寿命弹道对象
  let lastTracerSigs = new Set();
  let hudLine1 = null, hudLine2 = null, hudBg = null;
  let waitingText = null;
  let targetRing = null, controlRing = null, controlledId = null, unitLabel = null;
  let healthFill, ammoPips = [], missionLabel, clockLabel;

  function withKaplay(cb) {
    if (window.kaplay) return cb();
    pending.push(cb);
    if (loading) return;
    loading = true;
    const s = document.createElement('script');
    s.src = '/vendor/kaplay.js';
    s.onload = () => pending.splice(0).forEach(fn => fn());
    s.onerror = () => { pending.length = 0; };
    document.head.appendChild(s);
  }

  function ensureCtx() {
    if (k) return;
    canvasEl.width = W; canvasEl.height = H;
    k = window.kaplay({ canvas: canvasEl, width: W, height: H, background: [11, 14, 20], global: false, focus: false, pixelDensity: Math.min(window.devicePixelRatio || 1, 2) });
    canvasEl.style.width = '100%'; canvasEl.style.height = 'auto';
  }

  function updateUnits() {
      const selected = units.get(controlledId);
      if (controlRing && selected && !selected.dead) controlRing.pos = k.vec2(selected.cx,selected.cy);
      const blend = 1 - Math.exp(-k.dt() * 32);
      for (const unit of units.values()) {
        if (unit.dead) continue;
        // One persistent update owns position. Never stack tweens on every network packet.
        const dx = unit.tx - unit.cx, dy = unit.ty - unit.cy;
        setUnitPos(unit, unit.cx + dx * blend, unit.cy + dy * blend);
        const angle = ((unit.ta - unit.group.angle + 540) % 360) - 180;
        unit.group.angle += angle * blend;
        const swing = Math.hypot(dx, dy) > 0.3 ? Math.sin(k.time() * 24) * 3 : 0;
        unit.parts.legL.pos.y = -10 + swing; unit.parts.legR.pos.y = 3 - swing;
        if (unit.flashUntil > k.time()) unit.parts.helmet.color = k.rgb(255, 236, 177);
        else unit.parts.helmet.color = k.rgb(...unit.dark);
        const aim = unit.aim;
        unit.warning.opacity = aim?.aimTicks > 0 ? 0.65 + Math.sin(k.time() * 28) * 0.25 : 0;
        if (aim?.aimTicks > 0) {
          const x = cx(aim.aimX), y = cy(aim.aimY);
          unit.warning.pos = k.vec2(unit.cx, unit.cy);
          unit.warning.width = Math.hypot(x - unit.cx, y - unit.cy);
          unit.warning.angle = Math.atan2(y - unit.cy, x - unit.cx) * 180 / Math.PI;
          unit.mark.pos = k.vec2(x, y); unit.mark.opacity = 0.6;
        } else unit.mark.opacity = 0;
      }
  }

  const cx = gx => OX + gx * TILE + TILE / 2;
  const cy = gy => OY + gy * TILE + TILE / 2;

  function buildStatic(obs) {
    k.destroyAll();
    units.clear();
    targetRing = k.add([k.circle(20, { fill: false }), k.pos(0, 0), k.outline(2, k.rgb(255, 220, 100)), k.opacity(0), k.z(8)]);
    controlRing = k.add([k.circle(24, { fill: false }), k.pos(0,0), k.outline(3,k.rgb(225,255,240)), k.opacity(0), k.z(8)]);
    tracerObjs = [];
    lastTracerSigs = new Set();
    hudLine1 = hudLine2 = hudBg = null;
    waitingText = null;
    if (obs.width && obs.height) {
      TILE = Math.min(W / obs.width, (H - 144) / obs.height);
      OX = Math.floor((W - obs.width * TILE) / 2);
      OY = 64 + Math.floor((H - 144 - obs.height * TILE) / 2);
    }
    // Ground markings are paint, not obstacles. All cover below comes from collision data.
    const box = (x,y,w,h,c,z=0) => k.add([k.rect(w,h),k.pos(x,y),k.color(...c),k.z(z)]);
    box(0,0,W,H,[24,32,35],-3);
    box(OX,OY,obs.width*TILE,obs.height*TILE,[173,156,116],-2);
    for(let i=0;i<180;i++) {
      const x=OX+((i*157+i*i*43)%W), y=OY+((i*83+i*i*17)%(obs.height*TILE));
      k.add([k.circle(1+i%3),k.pos(x,y),k.color(117,108,81),k.opacity(.2),k.z(-1)]);
    }
    for(let i=0;i<30;i++) {
      const x=(i*173+41)%W,y=OY+(i*97+53)%(obs.height*TILE);
      k.add([k.circle(12+i%5*8),k.pos(x,y),k.scale(1.8,.45),k.color(194,176,131),k.opacity(.18),k.z(-1)]);
    }
    box(0,OY+175,W,108,[153,142,112],-1);
    box(410,OY,140,obs.height*TILE,[162,149,115],-1);
    for(let x=15;x<W;x+=74)box(x,OY+226,34,3,[203,184,139],0);
    for(let i=0;i<10;i++) {
      box(32+i*8,OY+20,3,44,[149,134,99],0);
      box(W-112+i*8,OY+obs.height*TILE-64,3,44,[149,134,99],0);
    }
    const stencil=(value,x,y,size)=>k.add([k.text(value,{size,font:'monospace'}),k.pos(x,y),k.color(108,103,78),k.opacity(.65),k.z(0)]);
    stencil('NORTH / 01',24,OY+85,17);
    stencil('INSERTION / A',370,OY+obs.height*TILE-45,22);
    box(0,0,W,60,[19,29,33],12);
    k.add([k.text('沙丘突围',{size:24,font:'monospace'}),k.pos(24,15),k.color(235,225,191),k.z(13)]);
    missionLabel=k.add([k.text('',{size:17,font:'sans-serif'}),k.pos(380,22),k.color(216,221,203),k.z(13)]);
    clockLabel=k.add([k.text('',{size:23,font:'monospace'}),k.pos(W-112,18),k.color(238,190,97),k.z(13)]);
    k.onUpdate(updateUnits);
    // 沙袋：两个错开堆叠的袋子（圆角椭圆 + 缝线），一眼是掩体
    for (const s of obs.sandbags || []) {
      const bx = OX + s.x * TILE, by = OY + s.y * TILE;
      k.add([k.rect(TILE, TILE, { radius: 3 }), k.pos(bx + 3, by + 4), k.color(84, 75, 51), k.opacity(.35), k.z(1)]);
      k.add([k.rect(TILE - 2, TILE * 0.62, { radius: 3 }), k.pos(bx + 1, by + TILE * 0.38), k.color(150, 124, 76), k.outline(1, k.rgb(96, 78, 46)), k.z(1)]);
      k.add([k.rect(TILE - 6, TILE * 0.55, { radius: 3 }), k.pos(bx + 4, by + 1), k.color(166, 140, 90), k.outline(1, k.rgb(96, 78, 46)), k.z(2)]);
      k.add([k.rect(TILE - 10, 1), k.pos(bx + 6, by + 4), k.color(206, 181, 120), k.z(2)]);
    }
  }

  function setUnitPos(u, px, py) {
    u.cx = px; u.cy = py;
    u.group.pos = k.vec2(px, py);
    u.hpBg.pos = k.vec2(px - 13, py - 22);
    u.hpFg.pos = k.vec2(px - 12, py - 21);
  }

  // 俯视玩具兵：影子/双腿/椭圆身体/持枪（+x 方向）/头盔；玩家加白星徽
  function makeUnit(u, color, dark, isPlayer) {
    const group = k.add([k.pos(0, 0), k.rotate((u.facing || 0) * 180 / Math.PI), k.scale(1.5), k.opacity(1), k.z(3)]);
    const parts = {};
    parts.shadow = group.add([k.circle(11), k.pos(1, 3), k.color(0, 0, 0), k.opacity(0.22), k.scale(1, 0.75), k.z(0)]);
    parts.legL = group.add([k.rect(6, 7, { radius: 2 }), k.pos(-8, -10), k.color(...dark), k.z(1)]);
    parts.legR = group.add([k.rect(6, 7, { radius: 2 }), k.pos(-8, 3), k.color(...dark), k.z(1)]);
    parts.gun = group.add([
      k.rect(17, 4, { radius: 1 }), k.pos(3, -2), k.color(52, 48, 44), k.z(3),
    ]);
    parts.muzzle = group.add([k.rect(4, 5), k.pos(19, -2.5), k.color(32, 30, 28), k.z(3)]);
    parts.arm = group.add([k.circle(4), k.pos(5, -5), k.color(...color), k.outline(1, k.rgb(...dark)), k.z(2)]);
    parts.body = group.add([
      k.circle(11), k.pos(0, 0), k.color(...color), k.outline(2, k.rgb(...dark)), k.z(2),
    ]);
    parts.helmet = group.add([
      k.circle(7.5), k.pos(0, 0), k.color(...dark), k.z(4),
    ]);
    group.add([k.rect(4, 12, { radius: 2 }), k.pos(-2, -6), k.color(...color), k.opacity(.5), k.z(5)]);
    group.add([k.rect(7, 15, { radius: 2 }), k.pos(-14, -7.5), k.color(...dark), k.outline(1, k.rgb(35, 50, 32)), k.z(2)]);
    group.add([k.circle(2.6), k.pos(-2, -2), k.color(255, 255, 255), k.opacity(0.25), k.z(5)]); // 头盔高光
    if (isPlayer) {
      group.add([k.circle(16, { fill: false }), k.pos(0, 0), k.outline(1.5, k.rgb(183, 239, 178)), k.opacity(.65), k.z(-1)]);
      group.add([k.circle(2.2), k.pos(0, 0), k.color(245, 245, 235), k.z(5)]);                    // 星徽
    }
    const hpBg = k.add([k.rect(26, 5, { radius: 2 }), k.pos(0, 0), k.color(32, 26, 20), k.opacity(0.9), k.z(10)]);
    const hpFg = k.add([k.rect(24, 3, { radius: 1 }), k.pos(0, 0), k.color(126, 200, 80), k.z(11)]);
    const warning = k.add([k.rect(1, 2), k.pos(0, 0), k.rotate(0), k.color(255, 85, 74), k.opacity(0), k.z(4)]);
    const mark = k.add([k.circle(14), k.pos(0, 0), k.color(255, 85, 74), k.opacity(0), k.outline(2, k.rgb(255, 210, 120)), k.z(4)]);
    const unit = { isPlayer, group, parts, hpBg, hpFg, warning, mark, cx: 0, cy: 0, tx: cx(u.x), ty: cy(u.y), ta: (u.facing || 0) * 180 / Math.PI, aim: u, dead: false, pulsing: false, color, dark };
    setUnitPos(unit, cx(u.x), cy(u.y));
    setUnitHp(unit, u);
    return unit;
  }

  function setUnitHp(unit, u) {
    const ratio = Math.max(0, u.hp / u.maxHp);
    if (unit.lastHp != null && u.hp < unit.lastHp) { unit.flashUntil = k.time() + .13; if (unit.isPlayer) k.shake(2); }
    unit.lastHp = u.hp;
    unit.hpFg.width = 24 * ratio;
    unit.hpFg.color = ratio > 0.3 ? k.rgb(52, 211, 153) : k.rgb(242, 109, 95);
  }

  function moveUnit(unit, u) {
    const tx = cx(u.x), ty = cy(u.y);
    if (Math.hypot(tx - unit.cx, ty - unit.cy) > 6 * TILE) setUnitPos(unit, tx, ty); // 重置类瞬移
    unit.tx = tx; unit.ty = ty;
    unit.ta = (u.facing || 0) * 180 / Math.PI;
    unit.aim = u;
    setUnitHp(unit, u);
  }

  function killUnit(unit) {
    unit.dead = true;
    const tag=k.add([k.text(unit.isPlayer ? '行动失败' : '目标清除', {size:18,font:'sans-serif'}),k.pos(unit.cx,unit.cy-38),k.anchor('center'),k.color(255,229,151),k.opacity(1),k.lifespan(1,{fade:.7}),k.z(16)]);
    k.destroy(unit.hpBg); k.destroy(unit.hpFg); k.destroy(unit.warning); k.destroy(unit.mark);
    const g = unit.group;
    const a0 = g.angle;
    k.tween(0, 1, 0.5, f => {   // 翻倒：侧躺 90° + 淡出
      g.angle = a0 + 90 * f;
      g.opacity = 1 - f;
    }, k.easings.easeInQuad);
    k.wait(0.55, () => k.destroy(g));
  }

  // 暴露警告：玩家小兵轻微红闪脉冲
  function pulseExposed(unit) {
    if (unit.pulsing) return;
    unit.pulsing = true;
    const base = k.rgb(...unit.color), warn = k.rgb(255, 80, 70);
    k.tween(0, 1, 0.6, t => {
      if (t >= 1 || unit.dead) { unit.parts.body.color = base; unit.pulsing = false; return; }
      const m = (Math.sin(t * Math.PI * 4) + 1) / 2 * 0.7;
      unit.parts.body.color = k.rgb(
        base.r + (warn.r - base.r) * m,
        base.g + (warn.g - base.g) * m,
        base.b + (warn.b - base.b) * m,
      );
    });
  }

  // 曳光弹：双层（粗透明光晕 + 细亮芯）；新弹道附加枪口闪光与抛弹壳；命中点爆粒子
  function renderTracers(obs) {
    tracerObjs.forEach(o => k.destroy(o));
    tracerObjs = [];
    const sigs = new Set();
    for (const t of obs.tracers || []) {
      const sig = t.id || `${t.x1},${t.y1},${t.x2},${t.y2},${t.hit}`;
      sigs.add(sig);
      const alpha = Math.max(0.15, t.ttl / 6);
      const x1 = cx(t.x1), y1 = cy(t.y1), x2 = cx(t.x2), y2 = cy(t.y2);
      const len = Math.hypot(x2 - x1, y2 - y1);
      const deg = Math.atan2(y2 - y1, x2 - x1) * 180 / Math.PI;
      const core = t.hit ? [255, 120, 50] : [245, 240, 220];
      tracerObjs.push(k.add([
        k.rect(len, t.hit ? 5 : 4), k.pos(x1, y1), k.anchor('left'), k.rotate(deg),
        k.color(...core), k.opacity(alpha * 0.3), k.lifespan(0.16, { fade: 0.12 }), k.z(2),
      ]));
      tracerObjs.push(k.add([
        k.rect(len, 2), k.pos(x1, y1), k.anchor('left'), k.rotate(deg),
        k.color(...core), k.opacity(alpha), k.lifespan(0.16, { fade: 0.12 }), k.z(2),
      ]));
      if (t.hit) {
        tracerObjs.push(k.add([
          k.circle(5), k.pos(x2, y2), k.color(255, 60, 30), k.opacity(alpha), k.lifespan(0.16, { fade: 0.12 }), k.z(2),
        ]));
      }
      if (!lastTracerSigs.has(sig)) {
        // 开火反馈：枪口黄色闪光，约 100ms；同时向侧后抛出一枚弹壳
        k.add([k.circle(5), k.pos(x1, y1), k.color(255, 220, 80), k.opacity(1), k.lifespan(0.1, { fade: 0.1 }), k.z(6)]);
        const ca = deg * Math.PI / 180, sx = x1 - Math.sin(ca) * 6, sy = y1 + Math.cos(ca) * 6;
        const shell = k.add([k.rect(3, 2), k.pos(sx, sy), k.color(220, 180, 70), k.opacity(1), k.lifespan(0.35, { fade: 0.2 }), k.z(6)]);
        k.tween(0, 1, 0.3, f => { shell.pos = k.vec2(sx - Math.sin(ca) * 8 * f, sy + Math.cos(ca) * 8 * f + 10 * f * f); });
        if (t.hit) {
          for (let i = 0; i < 5; i++) {
            const a = Math.random() * Math.PI * 2;
            const d = 8 + Math.random() * 10;
            const p = k.add([
              k.circle(2 + Math.random() * 1.5), k.pos(x2, y2),
              k.color(...(Math.random() < 0.5 ? [255, 120, 40] : [255, 60, 30])),
              k.opacity(1), k.lifespan(0.4, { fade: 0.35 }), k.z(6),
            ]);
            k.tween(0, 1, 0.35, f => { p.pos = k.vec2(x2 + Math.cos(a) * d * f, y2 + Math.sin(a) * d * f); });
          }
        }
      }
    }
    lastTracerSigs = sigs;
  }

  function renderHud(obs) {
    if (!hudBg) {
      hudBg = k.add([k.rect(W,88),k.pos(0,H-88),k.color(19,29,33),k.z(10)]);
      unitLabel = k.add([k.text('先锋  /  VANGUARD',{size:13,font:'sans-serif'}),k.pos(24,H-72),k.color(151,175,160),k.z(11)]);
      k.add([k.rect(210,8),k.pos(24,H-27),k.color(49,64,62),k.z(11)]);
      healthFill=k.add([k.rect(210,8),k.pos(24,H-27),k.color(111,214,169),k.z(12)]);
      hudLine1=k.add([k.text('',{size:19,font:'sans-serif'}),k.pos(24,H-53),k.color(237,239,222),k.z(11)]);
      hudLine2=k.add([k.text('',{size:16,font:'sans-serif'}),k.pos(295,H-38),k.color(204,212,198),k.z(11)]);
      ammoPips=[];
      for(let i=0;i<6;i++)ammoPips.push(k.add([k.rect(12,25,{radius:3}),k.pos(298+i*20,H-73),k.color(238,196,104),k.z(11)]));
    }
    const p = obs.player;
    const labels = { shoot: '开火', advance: '推进', hold: '据守', peek: '探头', flank: '侧移', flankLeft: '向左侧移', flankRight: '向右侧移', retreat: '后撤' };
    hudLine1.text = `${p?.hp ?? 0} / 100`;
    healthFill.width = 210 * Math.max(0,p?.hp ?? 0)/100;
    healthFill.color = (p?.hp ?? 0)>30 ? k.rgb(111,214,169) : k.rgb(245,108,87);
    ammoPips.forEach((pip,i)=>{pip.opacity=i<(p?.ammo??0)?1:.16;});
    missionLabel.text = `2 v 2   绿方 ${obs.alliesAlive ?? 1} / ${obs.allies?.length ?? 1}   ·   红方 ${obs.enemiesAlive} / ${obs.enemies.length}`;
    const mate = (obs.allies || []).find(u => u.id !== p?.id);
    unitLabel.text = `${p?.id === "ally-1" ? "队员 2" : "队员 1"}${obs.human ? " · Q 切人" : " · AI"}   ${mate ? "队友 " + mate.hp + " HP" : ""}`;
    const seconds=Math.max(0,180-Math.floor(obs.tick/20));
    clockLabel.text=String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0');
    const fireLabels = { ready: '可开火', range: '超出射程，靠近目标', blocked: '沙袋挡住射线，绕到侧面', cooldown: '射击间隔', empty: '弹匣空，按 R 换弹', reloading: '换弹中，寻找掩护', defeated: '已倒下', clear: '目标已清除' };

    hudLine2.text = `${Math.max(0, 180 - Math.floor(obs.tick / 20))}s  ·  ${obs.enemies.some(e => e.aimTicks > 0) ? '红线锁定！离开标记点' : p?.reloadTicks ? '换弹中，躲回沙袋后' : obs.exposed ? '射角已打开 · 按住空格射击，保持移动' : '黄色圈是当前目标 · WASD 移动，空格射击'}`;
    hudLine2.text = obs.enemies.some(e=>e.aimTicks>0) ? '危险：离开红色锁定点！' : fireLabels[obs.fireStatus] || '';
    if (obs.order) {
      const movement = { hold: '停留', advance: '接近', retreat: '后撤', left: '左侧移', right: '右侧移', reposition: '绕障找射角' };
      const weapon = { shoot: '开火', cease: '停火', reload: '换弹' };
      hudLine2.text = `${Math.max(0, 180 - Math.floor(obs.tick / 20))}s · ${movement[obs.order.movement]} + ${weapon[obs.order.weapon]} → 敌兵 ${Number(obs.order.target.slice(-1)) + 1} · ${obs.order.remainingMs > 0 ? (obs.order.remainingMs / 1000).toFixed(1) + 's' : '无输入 · 游戏继续'}`;
      if (obs.order.recovery) hudLine2.text = `${obs.order.recovery} · ${movement[obs.order.movement]}`;
      if (obs.order.remainingMs <= 0) hudLine2.text = `${Math.max(0, 180 - Math.floor(obs.tick / 20))}s · 无输入 · 游戏继续运行`;
    }
  }


  function render(obs) {
    if (lastTick != null && typeof obs.tick === 'number' && obs.tick < lastTick) layoutKey = null;
    if (obs.tick === lastTick && layoutKey) return;
    if (typeof obs.tick === 'number') lastTick = obs.tick;
    const key = `${obs.width}x${obs.height}|${(obs.sandbags || []).map(s => s.x + ',' + s.y).join(';')}`;
    if (layoutKey !== key) { buildStatic(obs); layoutKey = key; }

    // 小兵：按 id 持久化，绿方玩家 + 红方敌兵
    const seen = new Set();
    const list = [];
    for (const ally of obs.allies || (obs.player ? [obs.player] : [])) list.push({ u: ally, color: [52, 211, 153], dark: [22, 110, 80], isPlayer: true });
    for (const e of obs.enemies || []) list.push({ u: e, color: [242, 109, 95], dark: [140, 45, 38], isPlayer: false });
    for (const { u, color, dark, isPlayer } of list) {
      let unit = units.get(u.id);
      if (!u.alive) {
        if (unit && !unit.dead) killUnit(unit);
        continue;
      }
      if (!unit || unit.dead) { unit = makeUnit(u, color, dark, isPlayer); units.set(u.id, unit); }
      else moveUnit(unit, u);
      if (isPlayer && obs.exposed) pulseExposed(unit);
      seen.add(u.id);
    }
    for (const [id, unit] of units) {
      if (!seen.has(id) && !unit.dead) { killUnit(unit); }
    }

    const target = units.get(obs.targetId);
    targetRing.opacity = target && !target.dead ? .9 : 0;
    if (target && !target.dead) targetRing.pos = k.vec2(target.cx, target.cy);
    controlledId = obs.controlledId;
    controlRing.opacity = obs.human && units.get(controlledId) && !units.get(controlledId).dead ? 1 : 0;
    renderTracers(obs);
    renderHud(obs);
    canvasEl.setAttribute('aria-label', `玩具兵 2v2：当前控制 ${obs.controlledId}，生命 ${obs.player?.hp ?? 0}，队友存活 ${obs.alliesAlive}，剩余敌兵 ${obs.enemiesAlive}，Q 切换队员`);
  }

  window.gameClient = {
    reset() { layoutKey = null; lastTick = null; },
    draw(canvas, observation) {
      canvasEl = canvas;
      withKaplay(() => {
        ensureCtx();
        if (!observation) {
          if (!waitingText) {
            waitingText = k.add([k.text('等待开局…', { size: 16 }), k.pos(W / 2, H / 2), k.anchor('center'), k.color(255, 255, 255), k.z(30)]);
          }
          return;
        }
        render(observation);
      });
    },
  };
})();
