import { test } from 'node:test';
import assert from 'node:assert/strict';
import { newBout, stepBout, fighterObservation, boxingBotAction, BOXING } from '../src/games/boxing/engine.js';

function run(bout: ReturnType<typeof newBout>, inputs: [string, string], ticks: number) {
  for (let i = 0; i < ticks; i++) stepBout(bout, inputs);
}

test('jab 在射程内命中扣血', () => {
  const bout = newBout();
  bout.fighters[0].x = 300; bout.fighters[1].x = 400; // 距离 100 < jab range 114
  run(bout, ['jab', 'idle'], BOXING.commandTicks);
  assert.ok(bout.fighters[1].hp < bout.fighters[1].maxHp, `hp=${bout.fighters[1].hp}`);
});

test('guard 挡住 jab 不掉血但吃 stun', () => {
  const bout = newBout();
  bout.fighters[0].x = 300; bout.fighters[1].x = 400;
  run(bout, ['jab', 'guard'], BOXING.commandTicks);
  assert.equal(bout.fighters[1].hp, bout.fighters[1].maxHp);
  assert.ok(bout.events.some(e => e['type'] === 'block'));
});

test('KO 后终局且 winner 正确', () => {
  const bout = newBout();
  bout.fighters[1].hp = 1;
  bout.fighters[0].x = 300; bout.fighters[1].x = 400;
  run(bout, ['jab', 'idle'], BOXING.commandTicks);
  assert.equal(bout.status, 'done');
  assert.equal(bout.winner, 0);
});

test('时间到按血量百分比判胜', () => {
  const bout = newBout();
  bout.fighters[0].hp = 30; bout.fighters[1].hp = 10;
  bout.frame = BOXING.limitMs / BOXING.tickMs - 1;
  stepBout(bout, ['idle', 'idle']);
  assert.equal(bout.status, 'done');
  assert.equal(bout.winner, 0);
  assert.equal(bout.reason, 'time');
});

test('observation 含距离与双方状态；bot 返回合法动作', () => {
  const bout = newBout();
  const obs = fighterObservation(bout, 0) as { distance: number; self: { hp: number }; opponent: { hp: number } };
  assert.equal(obs.distance, 420);
  assert.equal(obs.self.hp, BOXING.hp);
  assert.ok(['idle','advance','retreat','jab','heavy','guard','throw','dash','jump','special'].includes(boxingBotAction(bout, 1)));
});

test('非法输入按 idle 处理不抛错', () => {
  const bout = newBout();
  stepBout(bout, ['fly', 'idle']);
  assert.equal(bout.fighters[0].action, 'idle');
});

test('range is evaluated after both sides move: mirrored retreat escapes jab', () => {
  for (const side of [0, 1] as const) {
    const bout = newBout();
    bout.fighters[0].x = 300; bout.fighters[1].x = 414;
    bout.fighters[side].attack = { kind: 'jab', age: 1, tried: false };
    stepBout(bout, side === 0 ? ['idle', 'retreat'] : ['retreat', 'idle']);
    assert.equal(bout.fighters[1 - side]!.hp, BOXING.hp);
    assert.ok(bout.events.some(e => e.type === 'miss'));
  }
});

test('jab interrupts heavy startup; throw beats guard; whiff recovery is punishable', () => {
  const b = newBout(); b.fighters[0].x = 300; b.fighters[1].x = 400;
  run(b, ['jab', 'heavy'], 2);
  assert.equal(b.fighters[0].hp, BOXING.hp);
  assert.equal(b.fighters[1].attack, null);
  const t = newBout(); t.fighters[0].x = 300; t.fighters[1].x = 400;
  run(t, ['throw', 'guard'], 6);
  assert.equal(t.fighters[1].hp, 92);
  assert.ok(t.events.some(e => e.type === 'guardbreak'));
  const p = newBout(); p.fighters[0].x = 300; p.fighters[1].x = 410;
  p.fighters[1].attack = { kind: 'heavy', age: 9, tried: true };
  run(p, ['jab', 'idle'], 2);
  assert.equal(p.fighters[1].hp, 95);
  assert.ok(p.events.some(e => e.type === 'counter'));
});


test('jump evades grounded throws and lands; dash closes space with cooldown', () => {
 const b=newBout();b.fighters[0].x=300;b.fighters[1].x=400;
 run(b,['jump','throw'],6);assert.equal(b.fighters[0].hp,100);assert.ok(b.fighters[0].y>0);
 run(b,['idle','idle'],15);assert.equal(b.fighters[0].y,0);
 const d=newBout();stepBout(d,['dash','idle']);assert.equal(d.fighters[0].x,255);
 stepBout(d,['dash','idle']);assert.equal(d.fighters[0].x,255);
});
test('meter pays for special; confirmed jab heavy special form a true combo', () => {
 const b=newBout();b.fighters[0].x=300;b.fighters[1].x=400;
 stepBout(b,['special','idle']);assert.equal(b.fighters[0].attack,null);
 b.fighters[0].meter=50;
 run(b,['jab','idle'],2);run(b,['heavy','idle'],7);run(b,['special','idle'],3);
 assert.equal(b.fighters[0].combo,3);assert.equal(b.fighters[1].hp,69);
 assert.equal(b.fighters[0].meter,36);
});
test('whiffed or blocked jab cannot cancel into heavy', () => {
 for(const blocked of [false,true]){
 const b=newBout();if(blocked){b.fighters[0].x=300;b.fighters[1].x=400;}
 run(b,['jab',blocked?'guard':'idle'],2);stepBout(b,['heavy','idle']);
 assert.equal(b.fighters[0].attack?.kind,'jab');assert.equal(b.fighters[0].combo,0);
 }
});
