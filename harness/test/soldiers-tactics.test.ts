import test from 'node:test';
import assert from 'node:assert/strict';
import { createSoldiersGame } from '../src/games/soldiers/adapter.js';
import { getOrder, tacticalAwareness } from '../src/games/soldiers/engine.js';
import { createRealtimeMatch, type RealtimeRecord } from '../src/arena/realtime.js';
import type { Answer, Question, SystemOne } from '../src/systemone/types.js';
const a = (choice: string): Answer => ({type:'choice',choice,probabilities:{[choice]:1},confidence:1});
function plan(q: Record<string,Question>, move='advance', duration='long') {
  return Object.fromEntries(Object.entries(q).map(([k,v]) => [k,a(k.endsWith('movement') ? move : k.endsWith('duration') ? duration : k.endsWith('weapon') ? 'shoot' : v.type==='choice' ? Object.keys(v.criteria)[0]! : '')]));
}
function combat() {
  const g=createSoldiersGame(), s=g.initialState();
  s.game.sandbags=[];s.game.allies[1]!.hp=0;s.game.enemies[1]!.hp=0;
  Object.assign(s.game.player,{x:20,y:15});Object.assign(s.game.enemies[0]!,{x:20,y:9});
  s.game.enemyCommands=['shoot','hold'];return {g,s};
}
test('combat removes already-completed approach; observations expose lock and usable dodge directions',()=>{
  const {g,s}=combat(); const q=g.questions(s).movement!;
  assert.ok(q.type==='choice');assert.ok(!('reposition' in q.criteria));assert.ok('left' in q.criteria);
  g.step(s);const awareness=tacticalAwareness(s.game,s.game.player);
  assert.equal(awareness.threats[0]!.stillOnLock,true);
  assert.equal(awareness.targets[0]!.directions.left!.escapesLocks,true);
  const shots=plan(g.questions(s),'left','normal');g.act(s,shots);
  for(let i=0;i<10;i++)g.step(s);
  assert.equal(s.game.player.hp,100);assert.notEqual(s.game.player.x,20);
});
test('delayed approaches revalidate live routes, expired dodges and dead targets are rejected',()=>{
  const {g,s}=combat(), hook=g.decision!;
  assert.equal(hook.validateResponse!(s,plan(g.questions(s),'advance'),2500),null);
  assert.equal(hook.validateResponse!(s,plan(g.questions(s),'left','normal'),2500),null);
  assert.equal(hook.validateResponse!(s,plan(g.questions(s),'left','short'),2500),'evasion-expired');
  assert.equal(hook.validateResponse!(s,plan(g.questions(s),'advance'),5100),'observation-expired');
  const old=plan(g.questions(s));s.game.enemies[0]!.hp=0;
  assert.equal(hook.validateResponse!(s,old,500),'target-or-action-changed');
});
test('prefetch requests next action while current action still moves; unresolved input remains bounded',async()=>{
  const g=createSoldiersGame();let calls=0;let pending:((v:Record<string,Answer>)=>void)|undefined;
  const model:SystemOne={ask:async (_o,q)=>{calls++;if(calls===1)return plan(q);return new Promise(r=>pending=r);}};
  const m=createRealtimeMatch(g,model);m.state.game.sandbags=[];m.state.game.enemyCommands=['hold','hold'];
  await m.tick();const expiry=getOrder(m.state.game,m.state.game.player)!.expiresAt;
  for(let i=0;i<18;i++)await m.tick(false);
  assert.equal(calls,2);assert.ok(m.state.game.tick<expiry);
  const before=m.state.game.player.y;await m.tick(false);assert.notEqual(m.state.game.player.y,before);
  for(let i=0;i<30;i++)await m.tick(false);
  const stopped={x:m.state.game.player.x,y:m.state.game.player.y};await m.tick(false);
  assert.deepEqual({x:m.state.game.player.x,y:m.state.game.player.y},stopped);
  assert.ok(pending);m.stop();
});
test('runner applies a still-valid slow approach but respects an explicit maximum age override',async()=>{
  for(const override of [undefined,1000]) {
    const g=createSoldiersGame();let resolve!:(a:Record<string,Answer>)=>void;let qs!:Record<string,Question>;
    const backend:SystemOne={ask:async(_o,q)=>{qs=q;return new Promise(r=>resolve=r);}};
    const records:RealtimeRecord[]=[];const m=createRealtimeMatch(g,backend,{...(override?{maxDecisionAgeMs:override}:{}),onUpdate:r=>records.push(r)});
    m.state.game.enemyCommands=['hold','hold'];await m.tick(false);
    for(let i=0;i<45;i++)await m.tick(false);
    resolve(plan(qs));await new Promise(r=>setImmediate(r));
    assert.equal(records[0]!.execution!.status,override?'discarded':'applied');m.stop();
  }
});

test('all living bodies block movement equally; dead units do not block',()=>{
  const {g,s}=combat();const f=s.game;
  Object.assign(f.player,{x:20,y:12});Object.assign(f.enemies[0]!,{x:20,y:10});f.enemyCommands=['hold','hold'];
  for(let i=0;i<10;i++){g.act(s,{control:a('north')});g.step(s);}
  assert.ok(Math.hypot(f.player.x-f.enemies[0]!.x,f.player.y-f.enemies[0]!.y)>=1.2);
  const y=f.player.y;g.act(s,{control:a('east')});g.step(s);assert.ok(f.player.x>20);assert.equal(f.player.y,y);
  f.enemies[0]!.hp=0;f.enemies[1]!.hp=100;f.player.x=20;f.player.y=11.5;
  g.act(s,{control:a('north')});g.step(s);assert.equal(f.player.y,11);
});
test('overlapping legacy units can retreat and strafe; tactical preview matches physics',()=>{
  for(const move of ['retreat','left','right']) {
    const {g,s}=combat();const f=s.game;f.enemyCommands=['hold','hold'];
    Object.assign(f.enemies[0]!,{x:f.player.x,y:f.player.y});
    const preview=tacticalAwareness(f,f.player).targets[0]!.directions[move]!;
    assert.ok(preview.travel>0);assert.equal(preview.blocked,false);
    g.act(s,plan(g.questions(s),move,'normal'));for(let i=0;i<8;i++)g.step(s);
    assert.ok(Math.hypot(f.player.x-f.enemies[0]!.x,f.player.y-f.enemies[0]!.y)>=1.2);
  }
});
test('close combat asks for disengagement rather than another advance',()=>{
  const {g,s}=combat();s.game.enemies[0]!.y=s.game.player.y-2;
  const q=g.questions(s).movement!;assert.ok(q.type==='choice');assert.ok(!('advance' in q.criteria));assert.ok('retreat' in q.criteria);
});
