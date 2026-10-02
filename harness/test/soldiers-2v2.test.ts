import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createSoldiersGame } from '../src/games/soldiers/adapter.js';
import { newFirefight, stepFirefight, SOLDIERS, getOrder } from '../src/games/soldiers/engine.js';
import { createRealtimeMatch } from '../src/arena/realtime.js';
import { startViewer } from '../src/viewer/server.js';
import { createDefaultRegistry } from '../src/games/index.js';
import type { Answer, Question, SystemOne } from '../src/systemone/types.js';

const answer = (choice: string): Answer => ({ type: 'choice', choice, probabilities: { [choice]: 1 }, confidence: 1 });
function plan(qs: Record<string, Question>) {
  return Object.fromEntries(Object.entries(qs).map(([key,q]) => [key, answer(key.endsWith('movement') ? 'advance' : key.endsWith('weapon') ? 'cease' : key.endsWith('duration') ? 'short' : q.type === 'choice' ? Object.keys(q.criteria)[0]! : '')]));
}
test('exactly two equal units per team, rotation-symmetric spawns and cover', () => {
  const f = newFirefight();
  assert.equal(f.allies.length,2); assert.equal(f.enemies.length,2);
  f.allies.forEach((u,i) => {
    const e = f.enemies[i]!;
    assert.equal(e.x,SOLDIERS.width-1-u.x); assert.equal(e.y,SOLDIERS.height-1-u.y);
    for (const key of ['hp','maxHp','ammo','reload','cool','aim'] as const) assert.equal(u[key],e[key]);
  });
  for (const b of f.sandbags) assert.ok(f.sandbags.some(t=>t.x===39-b.x && t.y===19-b.y));
});
test('both models control two units and may target either opposing living unit', () => {
  const game=createSoldiersGame(), s=game.initialState();
  for (const side of [game,game.rival!]) {
    const qs=side.questions!(s); assert.equal(Object.keys(qs).length,8);
    for (const [key,q] of Object.entries(qs)) if (key.endsWith('target') && q.type==='choice') assert.equal(Object.keys(q.criteria).length,2);
    side.act(s,plan(qs));
  }
  assert.ok([...s.game.allies,...s.game.enemies].every(u=>getOrder(s.game,u)));
});
test('Q transfers control, clears movement and excludes human from AI questions; death transfers to survivor', () => {
  const game=createSoldiersGame(), s=game.initialState(), f=s.game;
  game.humanCompanion!.start(s,true); f.sandbags=[];
  game.act(s,plan(game.questions(s)));
  game.act(s,{control:answer('east')}); game.step(s);
  game.act(s,{control:answer('switch')});
  assert.equal(f.controlledId,'ally-1'); assert.equal(f.command,'hold'); assert.equal(f.controlEpoch,1);
  assert.equal(getOrder(f,f.allies[1]!),null);
  assert.deepEqual(Object.keys(game.questions(s)),['movement','weapon','target','duration']);
  const pos=f.allies.map(u=>[u.x,u.y]); game.step(s);
  assert.deepEqual(f.allies.map(u=>[u.x,u.y]),pos);
  f.allies[1]!.hp=0; game.step(s);
  assert.equal(f.controlledId,'player'); assert.equal(f.status,'running');
  f.player.hp=0; game.step(s); assert.equal(f.winner,'enemy');
});
test('simultaneous lethal shots draw, rather than rewarding the first team iterated', () => {
  const f=newFirefight(); f.sandbags=[]; f.allies[1]!.hp=0; f.enemies[1]!.hp=0;
  Object.assign(f.player,{x:20,y:15,hp:10}); Object.assign(f.enemies[0]!,{x:20,y:10,hp:10});
  f.command='shoot'; f.enemyCommands=['shoot','hold'];
  for(let i=0;i<=SOLDIERS.aimTicks;i++) stepFirefight(f);
  assert.equal(f.player.hp,0); assert.equal(f.enemies[0]!.hp,0); assert.equal(f.status,'done'); assert.equal(f.winner,null);
});
test('switch rejects an in-flight companion decision without freezing physics', async () => {
  let resolve!: (a:Record<string,Answer>)=>void, requested!: Record<string,Question>;
  const model:SystemOne={ask:async (_o,q)=>{requested=q; return new Promise(r=>{resolve=r;});}};
  const game=createSoldiersGame(), match=createRealtimeMatch(game,model);
  match.startHumanCompanion(true);
  await match.tick(false);
  const result=plan(requested);
  match.applyExternal({control:answer('switch')},'self',true);
  for(let i=0;i<4;i++) await match.tick(false);
  assert.equal(match.summary.ticks,5);
  resolve(result); await new Promise(r=>setImmediate(r));
  assert.equal(match.state.game.allyOrders['ally-1'],null);
  assert.equal(match.state.game.controlledId,'ally-1'); match.stop();
});
test('viewer uses selected rival model for teammate; Q is consumed once and slow inference keeps publishing frames', async () => {
  const seen: string[]=[];
  const model:SystemOne={ask:async (obs)=>{seen.push((obs as {team:string}).team); return new Promise(()=>{});}};
  const dir=mkdtempSync(join(tmpdir(),'soldiers-2v2-'));
  const server=await startViewer({backend:model,backends:{names:['selected'],create(name){assert.equal(name,'selected');return model;}},registry:createDefaultRegistry(),port:0,startDelayMs:0,logDir:dir});
  const base=`http://127.0.0.1:${server.port}`;
  try {
    const start=await (await fetch(base+'/api/match/soldiers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:'human',rival:'selected'})})).json() as {matchId:string};
    assert.ok(start.matchId);
    const state=async()=>await (await fetch(base+`/api/match/${start.matchId}/state`)).json() as {latest:{frame:number;observation:{controlledId:string;allies:unknown[];enemies:unknown[]}}};
    await new Promise(r=>setTimeout(r,350)); const before=await state();
    assert.ok(seen.includes('green') && seen.includes('red'));
    assert.equal(before.latest.observation.allies.length,2); assert.equal(before.latest.observation.enemies.length,2);
    await fetch(base+`/api/match/${start.matchId}/input`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({input:'switch'})});
    await new Promise(r=>setTimeout(r,200)); const after=await state();
    assert.equal(after.latest.observation.controlledId,'ally-1'); assert.ok(after.latest.frame>before.latest.frame);
    await new Promise(r=>setTimeout(r,150)); assert.equal((await state()).latest.observation.controlledId,'ally-1');
  } finally { await server.close(); rmSync(dir,{recursive:true,force:true}); }
});
