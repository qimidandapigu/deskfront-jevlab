// 闯关 viewer：Kaplay 渲染版。obs.static.level 携带地图，客户端缓存场景；
// 动态部分每帧更新（obs.actor / obs.progress / obs.execution）。
// 视觉语义按马里奥式平台跳跃惯例设计：金币=旋转金币、钥匙=钥匙形、开关=红色大按钮、
// 门=木板门、终点=旗杆旗面、危险=水面波浪。角色是戴红帽的小人，有眨眼和呼吸待机。
// 场景层次：三段天空色带 + 太阳 + 视差远山 + 漂移云朵；位移 tween 平滑过渡，
// 相机 lerp 跟随，摔死（瞬移）时在原位放一蓬水花粒子。
(function () {
  const WIDTH = 800;
  const WATER_Y = 430;
  const GROUND_Y = 400; // engine 里 y >= 400 的平台视为地面，延伸到底部
  const BOTTOM = 480;

  let k = null;          // kaplay 上下文（global:false）
  let canvasEl = null;
  let staticKey = null;  // 已搭建静态层的关卡标识
  let cachedLevel = null; // static.level 只发一次，缓存供后续帧复用
  let lastSeq = null;    // turn/frame 回退说明开了新一局，强制重建以清掉通关横幅等残留
  let actorObj = null;
  let hud = null;
  let banner = null;
  let dyn = null;        // 每关的动态对象
  let camTarget = null;  // 相机目标，onUpdate 里 lerp 逼近，避免观测到达时瞬移
  let loading = false;
  const pending = [];

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
    k = window.kaplay({
      canvas: canvasEl, width: WIDTH, height: 480,
      background: [11, 17, 28], global: false, focus: false, crisp: false, pixelDensity: 1,
    });
    canvasEl.style.width = '100%'; canvasEl.style.height = 'auto';
  }

  function buildStatic(level) {
    k.destroyAll();
    dyn = { coins: new Map(), key: null, swBase: null, swBtn: null, door: null };
    actorObj = hud = banner = null;
    camTarget = null;
    k.setCamPos(k.vec2(WIDTH / 2, 240));

    const chapter = level.title.includes('月下') || level.title.includes('星灯');
    // Forest palette: jade twilight, with violet dusk in the final chapter.
    for (let i = 0; i < 24; i++) {
      k.add([k.rect(WIDTH, 21), k.pos(0, i * 20), k.color(chapter ? 27+i : 12+i, 25+i*2, chapter ? 55+i*2 : 38+i), k.fixed(), k.z(-20)]);
    }
    for (let i = 0; i < 36; i++) k.add([k.circle(i % 4 === 0 ? 1.6 : .8), k.pos(18 + i * 113 % 770, 70 + i * 37 % 190), k.color(211, 231, 247), k.opacity(.45), k.fixed(), k.z(-19)]);
    // 月亮 + 光晕（fixed）
    k.add([k.circle(44), k.pos(690, 113), k.color(190, 215, 240), k.opacity(0.14), k.fixed(), k.z(-19)]);
    k.add([k.circle(26), k.pos(690, 113), k.color(205, 224, 244), k.fixed(), k.z(-19)]);
    // 远山剪影（fixed + 视差：只走相机位移的 0.35 倍）
    const hills = [];
    const hillDefs = [
      { x: 60, r: 150, c: [22, 32, 48] },
      { x: 300, r: 195, c: [18, 28, 44] },
      { x: 540, r: 130, c: [26, 38, 54] },
    ];
    for (const d of hillDefs) {
      const h = k.add([k.circle(d.r), k.pos(d.x, GROUND_Y + 30), k.color(d.c[0], d.c[1], d.c[2]), k.opacity(0.6), k.fixed(), k.z(-15)]);
      h.baseX = d.x;
      hills.push(h);
    }
    // Layered trees: branching trunks and overlapping canopies, parallax follows the camera.
    for (let layer = 0; layer < 3; layer++) {
      for (let i = 0; i < 8; i++) {
        const x = i * 170 - 140 + layer * 65;
        const tree = k.add([k.pos(x, 0), k.fixed(), k.z(-14 + layer)]);
        tree.baseX = x;
        const tint = layer === 0 ? [35,66,70] : layer === 1 ? [22,52,55] : [13,37,41];
        const top = 95 + (i * 41 + layer * 57) % 155;
        tree.add([k.rect(20+layer*9, 480-top), k.pos(0,top), k.color(...tint)]);
        for (let b=0;b<4;b++) {
          tree.add([k.rect(9,65+b*8),k.pos(10,top+35+b*39),k.rotate(b%2 ? 38 : -42),k.color(...tint)]);
          tree.add([k.circle(45+b*8),k.scale(1.35,.6),k.pos((b%2 ? 1 : -1)*(23+b*8),top+b*26),k.color(...tint)]);
        }
        tree.onUpdate(()=>{tree.pos.x=tree.baseX-(k.getCamPos().x-WIDTH/2)*(.12+layer*.12);});
      }
    }
    // Hanging lanterns and fireflies give the forest depth without obscuring jump edges.
    for(let i=0;i<26;i++) {
      const x=30+i*97%level.width, y=130+i*67%245;
      const mote=k.add([k.circle(i%5===0 ? 3 : 1.5),k.pos(x,y),k.color(193,244,156),k.opacity(.6),k.z(-3)]);
      mote.onUpdate(()=>{mote.pos.y=y+Math.sin(k.time()*1.1+i)*9;mote.opacity=.25+Math.abs(Math.sin(k.time()+i))*.5;});
    }
    // 平台：圆角深色岩层 + 外探薄荷台面唇边 + 台面阴影 + 点缀（"可以站"的信号）
    for (const p of level.platforms) {
      const isGround = p.y >= GROUND_Y;
      const h = isGround ? BOTTOM - p.y : 26;
      k.add([k.rect(p.w, h, { radius: 4 }), k.pos(p.x, p.y), k.color(50, 65, 65), k.outline(2, k.rgb(13, 30, 35)), k.z(1)]);
      for(let row=0;row<Math.ceil(h/19);row++) for(let tx=0;tx<p.w;tx+=37) {
        const offset=row%2 ? 17 : 0;
        const bx=tx+offset;
        if(bx+4>=p.w) continue;
        k.add([k.rect(Math.min(33,p.w-bx-2),13,{radius:2}),k.pos(p.x+bx+1,p.y+12+row*19),k.color(57+row%2*8,75+row%2*6,72),k.z(1)]);
      }
      k.add([k.rect(p.w + 2, 9, { radius: 3 }), k.pos(p.x - 1, p.y - 1), k.color(117, 207, 159), k.z(2)]);   // 台面唇边
      k.add([k.rect(p.w, 3, { radius: 1 }), k.pos(p.x, p.y + 8), k.color(57, 131, 110), k.z(2)]);          // 台面阴影
      if(!isGround) for(let j=12;j<p.w-8;j+=31) {
        const len=15+(j*7)%30;
        k.add([k.rect(2,len),k.pos(p.x+j,p.y+17),k.color(63,126,100),k.z(0)]);
        for(let v=4;v<len;v+=9) k.add([k.circle(3),k.scale(1.5,.7),k.pos(p.x+j+(v%2?3:-3),p.y+17+v),k.color(74,154,111),k.z(0)]);
      }
      // Tiny glowing mushrooms and grass at the safe edges of each ledge.
      const mx=p.x+Math.min(p.w-16,32);
      k.add([k.rect(3,9),k.pos(mx,p.y-9),k.color(179,208,173),k.z(2)]);
      k.add([k.circle(7),k.scale(1,.48),k.pos(mx+1,p.y-10),k.color(118,217,188),k.z(2)]);
      const tufts = Math.max(2, Math.floor(p.w / 46));
      for (let i = 0; i < tufts; i++) {
        const span = Math.max(12, p.w - 16);
        const tx = p.x + 8 + ((i * 37 + p.x) % span);
        const th = 4 + ((i + Math.floor(p.y)) % 3) * 2;
        k.add([k.rect(3, th, { radius: 1 }), k.pos(tx, p.y - th + 1), k.color(36, 150, 110), k.z(2)]);
      }
    }
    // 终点：旗杆 + 顶端金球 + 飘动旗面 + 底座
    k.add([k.rect(20, 7, { radius: 2 }), k.pos(level.goal.x - 8, level.goal.y - 7), k.color(60, 68, 84), k.z(2)]);
    k.add([k.rect(4, 64), k.pos(level.goal.x, level.goal.y - 64), k.color(200, 206, 216), k.outline(1, k.rgb(120, 128, 142)), k.z(2)]);
    k.add([k.circle(5), k.pos(level.goal.x + 2, level.goal.y - 66), k.color(240, 178, 74), k.outline(1, k.rgb(160, 112, 36)), k.z(2)]);
    const flag = k.add([k.rect(30, 18), k.scale(1), k.pos(level.goal.x + 4, level.goal.y - 62), k.color(117, 207, 159), k.outline(1, k.rgb(24, 140, 100)), k.z(2)]);
    flag.onUpdate(() => { flag.scale = k.vec2(1 + Math.sin(k.time() * 5) * 0.12, 1); });
    // 水面：深蓝主色 + 顶部亮带 + 青色波浪线（"危险"信号），整体轻微起伏
    const water = k.add([k.rect(level.width, BOTTOM - WATER_Y), k.pos(0, WATER_Y), k.color(18, 48, 74), k.opacity(0.92), k.z(4)]);
    const waterTop = k.add([k.rect(level.width, 4), k.pos(0, WATER_Y), k.color(38, 90, 130), k.opacity(0.8), k.z(4)]);
    water.onUpdate(() => { water.pos.y = WATER_Y + Math.sin(k.time() * 2) * 2; });
    waterTop.onUpdate(() => { waterTop.pos.y = WATER_Y + Math.sin(k.time() * 2) * 2; });
    for (let i = 0; i * 46 < level.width; i++) {
      const wave = k.add([k.rect(22, 3, { radius: 1 }), k.pos(i * 46 + 8, WATER_Y + 3), k.color(67, 198, 232), k.opacity(0.85), k.z(5)]);
      const wx = i * 46 + 8, ph = i * 1.1;
      wave.onUpdate(() => {
        wave.pos.x = wx + Math.sin(k.time() * 1.6 + ph) * 7;
        wave.pos.y = WATER_Y + 3 + Math.sin(k.time() * 2) * 2;
      });
    }
    // 相机平滑跟随器 + 远山视差（不可见对象挂 onUpdate）
    const cam = k.add([k.pos(WIDTH / 2, 240), k.opacity(0)]);
    cam.onUpdate(() => {
      if (camTarget) {
        const cur = k.getCamPos();
        k.setCamPos(cur.lerp(camTarget, 1 - Math.exp(-8 * k.dt())));
      }
      const off = (k.getCamPos().x - WIDTH / 2) * 0.35;
      for (const h of hills) h.pos.x = h.baseX - off;
    });
  }

  function poof(x, y, color) {
    const [r, g, b] = color || [220, 220, 220];
    for (let i = 0; i < 8; i++) {
      const p = k.add([k.circle(4), k.pos(x, y), k.color(r, g, b), k.opacity(0.9), k.z(5)]);
      const a = (i / 8) * Math.PI * 2;
      const vx = Math.cos(a) * 60, vy = Math.sin(a) * 60 - 30;
      const x0 = x, y0 = y;
      k.tween(0, 1, 0.5, t => {
        p.pos = k.vec2(x0 + vx * t, y0 + vy * t + 120 * t * t);
        p.opacity = 0.9 * (1 - t);
      }).then(() => k.destroy(p));
    }
  }

  function confetti(x, y) {
    const palette = [[255, 90, 90], [255, 200, 40], [90, 200, 120], [90, 140, 255], [200, 120, 255]];
    for (let i = 0; i < 24; i++) {
      const c = palette[i % palette.length];
      const p = k.add([k.rect(6, 6), k.pos(x, y), k.color(c[0], c[1], c[2]), k.opacity(1), k.z(6)]);
      const a = Math.random() * Math.PI * 2, v = 80 + Math.random() * 120;
      const vx = Math.cos(a) * v, vy = Math.sin(a) * v - 120;
      const x0 = x, y0 = y, spin = (Math.random() - 0.5) * 720;
      k.tween(0, 1, 1.2, t => {
        p.pos = k.vec2(x0 + vx * t, y0 + vy * t + 260 * t * t);
        p.angle = spin * t;
        p.opacity = 1 - t;
      }).then(() => k.destroy(p));
    }
  }

  // 金币：竖立金色硬币，横向"翻面"旋转（保留最小宽度避免侧视消失）+ 高光条
  function makeCoin(x, y, i) {
    const g = k.add([k.pos(x, y), k.scale(1), k.z(2)]);
    g.add([k.circle(10), k.pos(0, 0), k.color(247, 202, 68), k.outline(2, k.rgb(180, 132, 26))]);
    g.add([k.rect(3, 12, { radius: 1 }), k.pos(-1.5, -6), k.color(255, 236, 160)]);
    g.onUpdate(() => {
      const s = Math.sin(k.time() * 3 + i);
      g.scale = k.vec2(Math.max(Math.abs(s), 0.3), 1);    // 绕竖轴旋转的错觉
      g.pos.y = y + Math.sin(k.time() * 2 + i * 0.9) * 2; // 轻微上下浮动
    });
    return g;
  }

  // 钥匙：圆环头 + 柄 + 两齿，金色——一眼可读为"钥匙"
  function makeKey(x, y) {
    const g = k.add([k.pos(x, y), k.z(2)]);
    g.add([k.circle(6, { fill: false }), k.pos(-6, 0), k.outline(3, k.rgb(255, 214, 64))]);
    g.add([k.rect(14, 4, { radius: 2 }), k.pos(-4, -2), k.color(255, 214, 64)]);
    g.add([k.rect(3, 6), k.pos(4, 0), k.color(255, 214, 64)]);
    g.add([k.rect(3, 6), k.pos(8, 0), k.color(255, 214, 64)]);
    const y0 = y;
    g.onUpdate(() => { g.pos.y = y0 + Math.sin(k.time() * 2.5) * 3; });
    return g;
  }

  // 开关：宽金属底座（带螺丝）+ 红色圆顶按钮（带高光）；踩下后圆顶压扁变绿
  function makeSwitch(x, y) {
    const base = k.add([k.rect(30, 7, { radius: 2 }), k.pos(x - 15, y - 4), k.color(58, 66, 84), k.outline(1, k.rgb(34, 40, 54)), k.z(2)]);
    base.add([k.circle(1.5), k.pos(4, 3.5), k.color(34, 40, 54)]);
    base.add([k.circle(1.5), k.pos(26, 3.5), k.color(34, 40, 54)]);
    const btn = k.add([k.circle(8.5), k.scale(1), k.pos(x, y - 6), k.color(242, 109, 95), k.outline(2, k.rgb(150, 50, 42)), k.z(3)]);
    btn.add([k.circle(3), k.pos(-2.5, -3), k.color(255, 190, 180), k.opacity(0.85)]); // 高光
    return { base, btn };
  }

  // 门：深色门框 + 石板门（横向板缝，高门像塔门）+ 靠下的圆把手；开门=门板下沉
  function makeDoor(x, y, h) {
    const g = k.add([k.pos(x, y), k.z(2)]);
    g.add([k.rect(22, h + 4), k.pos(-11, -2), k.color(30, 38, 54)]);                    // 门框
    const panel = g.add([k.rect(16, h), k.opacity(1), k.pos(-8, 0), k.color(62, 76, 102)]);           // 门板
    for (let sy = 10; sy < h - 6; sy += 26) {                                           // 横向板缝
      panel.add([k.rect(16, 2), k.pos(-8, sy), k.color(44, 56, 78)]);
    }
    panel.add([k.circle(2.5), k.pos(4, h - 30), k.color(240, 178, 74)]);                // 把手（人够得到的高度）
    return { group: g, panel, h };
  }

  // 角色：薄荷帽小人（腿/身体/头/帽/眼），子对象挂在脚底锚点上，移动/拉伸整体跟随
  function makeActor(x, y) {
    const a = k.add([k.pos(x, y), k.scale(1), k.anchor('bot'), k.z(3)]);
    a.facing = 1;
    a.legL = a.add([k.rect(8, 10, { radius: 2 }), k.pos(-11, -10), k.color(26, 34, 50), k.z(0)]);
    a.legR = a.add([k.rect(8, 10, { radius: 2 }), k.pos(3, -10), k.color(26, 34, 50), k.z(0)]);
    a.add([k.circle(13),k.scale(1,.28),k.pos(0,-1),k.color(5,19,24),k.opacity(.4),k.z(-1)]);
    a.add([k.rect(11,21,{radius:4}),k.pos(-17,-29),k.color(123,78,49),k.outline(2,k.rgb(49,36,30)),k.z(0)]);
    a.body = a.add([k.rect(25, 19, { radius: 6 }), k.pos(-12.5, -29), k.color(235,175,82), k.outline(2, k.rgb(114,76,44)), k.z(1)]);
    a.head = a.add([k.circle(10), k.pos(0, -38), k.color(255, 213, 170), k.outline(2, k.rgb(190, 140, 100)), k.z(2)]);
    a.hat = a.add([k.rect(25, 12, { radius: 6 }), k.pos(-12.5, -50), k.color(77,131,110), k.outline(2,k.rgb(31,68,64)), k.z(3)]);
    a.add([k.rect(25,5,{radius:2}),k.pos(-12.5,-29),k.color(223,104,75),k.z(4)]);
    const scarf=a.add([k.rect(16,5,{radius:2}),k.pos(-24,-27),k.color(223,104,75),k.z(0)]);
    scarf.onUpdate(()=>{scarf.angle=Math.sin(k.time()*8)*12;});
    a.hat.add([k.circle(4),k.pos(12,5),k.color(246,223,148),k.z(4)]);
    a.brim = a.add([k.rect(10, 4, { radius: 1 }), k.pos(7.5, -42), k.color(117, 207, 159), k.z(3)]);
    a.eyeWhites = [-5.6, 4.4].map(dx => a.head.add([k.circle(3.2), k.scale(1), k.pos(dx, -1.2), k.color(255, 255, 255), k.z(4)]));
    a.pupils = [-5.6, 4.4].map(dx => a.head.add([k.circle(1.6), k.pos(dx + 0.7, -1.2), k.color(40, 40, 50), k.z(5)]));
    let blinkAt = 2 + Math.random() * 3;
    a.onUpdate(() => {
      // 单一插值器：不要为每个网络帧叠加 tween，旧动画会反复拉回角色。
      if (a.target) a.pos = a.pos.lerp(a.target, 1 - Math.exp(-60 * k.dt()));
      a.scale = a.scale.lerp(k.vec2(1, 1), 1 - Math.exp(-16 * k.dt()));
      // 朝向：帽子檐和眼睛偏向移动方向
      const f = a.facing;
      a.brim.pos.x = f > 0 ? 7.5 : -17.5;
      a.pupils.forEach((p, i) => { p.pos.x = (i === 0 ? -5.6 : 4.4) + 0.7 + f * 1.4; });
      // 眨眼
      if (k.time() > blinkAt) {
        blinkAt = k.time() + 2 + Math.random() * 3;
        a.eyeWhites.forEach(e => {
          k.tween(1, 0.1, 0.08, t => { e.scale = k.vec2(1, t); })
            .then(() => k.tween(0.1, 1, 0.1, t => { e.scale = k.vec2(1, t); }));
        });
      }
      // 待机呼吸：头部轻微起伏；走路时两腿交替
      const moving = a.target && Math.abs(a.target.x - a.pos.x) > 1;
      a.head.pos.y = -38 + Math.sin(k.time() * 2.2) * (moving ? 0 : 1);
      const step = moving ? Math.sin(k.time() * 18) * 3 : 0;
      a.legL.pos.y = -10 + Math.max(0, step);
      a.legR.pos.y = -10 + Math.max(0, -step);
    });
    return a;
  }

  function updateDyn(obs, level) {
    const { progress: prog, actor: a } = obs;

    level.coins.forEach((c, i) => {
      const taken = prog.coins.includes(i);
      if (!taken && !dyn.coins.has(i)) {
        dyn.coins.set(i, makeCoin(c.x, c.y, i));
      } else if (taken && dyn.coins.has(i)) {
        poof(c.x, c.y, [255, 220, 90]);
        k.destroy(dyn.coins.get(i));
        dyn.coins.delete(i);
      }
    });

    if (!prog.key && !dyn.key) {
      dyn.key = makeKey(level.key.x, level.key.y);
    } else if (prog.key && dyn.key) { k.destroy(dyn.key); dyn.key = null; }

    if (!dyn.swBtn) {
      const sw = makeSwitch(level.switch.x, level.switch.y);
      dyn.swBase = sw.base; dyn.swBtn = sw.btn;
    }
    if (prog.switchOn && !dyn.swPressed) {
      dyn.swPressed = true;
      dyn.swBtn.pos.y += 5;                        // 圆顶压扁下陷
      dyn.swBtn.scale = k.vec2(1.15, 0.45);
      dyn.swBtn.color = k.rgb(52, 211, 153);       // 变绿
    } else if (!prog.switchOn && dyn.swPressed) {
      dyn.swPressed = false;
      dyn.swBtn.pos.y -= 5;
      dyn.swBtn.scale = k.vec2(1, 1);
      dyn.swBtn.color = k.rgb(242, 109, 95);
    }

    if (!dyn.door) {
      dyn.door = makeDoor(level.door.x, level.door.y, level.door.h);
    }
    if (prog.switchOn && !dyn.door.open) {
      dyn.door.open = true;                       // 开门：门板沉入门框
      const d = dyn.door;
      k.tween(0, 1, 0.4, t => { d.panel.pos.y = d.h * 0.94 * t; d.panel.opacity = 1 - 0.75 * t; }, k.easings.easeInQuad);
    } else if (!prog.switchOn && dyn.door && dyn.door.open) {
      dyn.door.open = false;
      const d = dyn.door;
      k.tween(0, 1, 0.4, t => { d.panel.pos.y = d.h * 0.94 * (1 - t); d.panel.opacity = 0.25 + 0.75 * t; });
    }

    // 角色：anchor bot，obs.actor.y 是脚底；起跳拉伸、落地压扁回弹
    if (!actorObj) {
      actorObj = makeActor(a.x, a.y);
      actorObj.target = k.vec2(a.x, a.y);
    }
    const to = k.vec2(a.x, a.y);
    if (!actorObj.target.eq(to)) {
      const from = actorObj.pos.clone();
      if (to.x !== from.x) actorObj.facing = to.x > from.x ? 1 : -1;
      if (from.dist(to) > 200) { // 摔死：在落点（旧位置）溅水花，角色回出生点
        poof(from.x, Math.min(from.y, WATER_Y), [200, 225, 245]);
        actorObj.pos = to;
      } else {
        if (actorObj.grounded === true && !a.grounded && a.vy < 0) actorObj.scale = k.vec2(0.8, 1.2);
        if (actorObj.grounded === false && a.grounded) actorObj.scale = k.vec2(1.25, 0.75);
      }
      actorObj.target = to;
    }
    actorObj.grounded = a.grounded;

    // 相机目标：横向跟随，实际移动由 buildStatic 里的 lerp 完成
    camTarget = k.vec2(level.width <= WIDTH ? level.width / 2 : Math.min(Math.max(a.x + actorObj.facing * 70, WIDTH / 2), level.width - WIDTH / 2), 240);

    // HUD
    const total = level.coins.length;
    const text = level.title + '    ·    金币 ' + prog.coins.length + ' / ' + total
      + '    ·    重试 ' + (obs.deaths ?? 0)
      + '\n' + (prog.key ? '✓ 钥匙' : '○ 寻找钥匙') + '    →    ' + (prog.switchOn ? '✓ 开关' : '○ 踩下开关') + '    →    ' + (prog.won ? '✓ 抵达终点' : '○ 到达旗帜');
    if (!hud) {
      k.add([k.rect(WIDTH, 64), k.pos(0, 0), k.color(13, 24, 39), k.opacity(.85), k.fixed(), k.z(9)]);
      hud = k.add([k.text(text, { size: 17, font: 'sans-serif', lineSpacing: 7 }), k.pos(18, 12), k.fixed(), k.color(224, 236, 229), k.z(10)]);
    } else if (hud.text !== text) hud.text = text;
    canvasEl.setAttribute('aria-label', '闯关：金币 ' + prog.coins.length + '/' + total + '，' + (prog.key ? '已获得钥匙' : '寻找钥匙'));

    if (prog.won && !banner) {
      banner = true; // The viewer owns the single result overlay.
      confetti(level.goal.x + 12, level.goal.y - 40);
    }
  }

  window.gameClient = {
    reset() { staticKey = null; lastSeq = null; },
    draw(canvas, observation) {
      canvasEl = canvas;
      if (!observation || !observation.actor) return;
      if (observation.static && observation.static.level) cachedLevel = observation.static.level;
      if (!cachedLevel) return; // 还没收到过 static.level（如回放从中间帧开始）
      withKaplay(() => {
        ensureCtx();
        const seq = observation.turn ?? observation.frame;
        if (lastSeq != null && typeof seq === 'number' && seq < lastSeq) staticKey = null;
        if (typeof seq === 'number') lastSeq = seq;
        const level = cachedLevel;
        const key = level.width + ':' + level.title;
        if (staticKey !== key) { buildStatic(level); staticKey = key; }
        updateDyn(observation, level);
      });
    },
  };
})();
