import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { createSokobanGame } from '../src/games/sokoban/adapter.js';
import { reachablePushes } from '../src/games/sokoban/pushes.js';

const rows = ['########', '#      #', '# .    #', '# $    #', '# @    #', '#      #', '#      #', '########'];
const answer = (choice: string) => ({ action: { type: 'choice' as const, choice, probabilities: {[choice]:1}, confidence:1 } });
const observe = (game: ReturnType<typeof createSokobanGame>, state: ReturnType<typeof game.initialState>) => game.observe(state, {turn:1,recent:[],feedback:null});

async function harness() {
  let objects: any[] = [], updates: (()=>void)[] = [], dt = 0;
  const vec = (x: number, y: number): any => ({x,y,lerp(p: any,t: number){ return vec(x+(p.x-x)*t,y+(p.y-y)*t); }});
  const k: any = {
    vec2: vec, dt:()=>dt, loadSprite:()=>Promise.resolve(),
    sprite:(name:string)=>({sprite:name}), anchor:()=>({}), scale:()=>({}), z:()=>({}), color:()=>({}), rect:()=>({}),
    pos:(p:any,y?:number)=>({pos:typeof p==='number'?vec(p,y!):p}), text:(text:string)=>({text}),
    add:(parts:any[])=>{const o=Object.assign({use(c:any){Object.assign(this,c);}},...parts);objects.push(o);return o;},
    destroyAll:()=>{objects=[];updates=[];}, onUpdate:(fn:()=>void)=>updates.push(fn),
  };
  const attrs: Record<string,string> = {};
  const canvas={setAttribute:(key:string,value:string)=>{attrs[key]=value;}};
  const window:any={kaplay:()=>k,matchMedia:()=>({matches:false}),devicePixelRatio:1};
  vm.runInNewContext(readFileSync('src/games/sokoban/client.js','utf8'),{window,console,document:{getElementById:()=>null}});
  const client=window.gameClient;
  const game=createSokobanGame(rows);
  client.draw(canvas,observe(game,game.initialState()));
  await new Promise(resolve=>setImmediate(resolve));
  return {client,canvas,attrs,game,objects:()=>objects,frame:(seconds:number)=>{dt=seconds;[...updates].forEach(f=>f());}};
}

test('sokoban presentation: moves immediately after reset and finishes before idle resolves',async()=>{
  const h=await harness();
  h.client.reset(); h.client.draw(h.canvas,observe(h.game,h.game.initialState()));
  const result=h.game.act(h.game.initialState(),answer('U'));
  h.client.draw(h.canvas,observe(h.game,result.state));
  let idle=false; h.client.whenIdle().then(()=>{idle=true;});
  await Promise.resolve(); assert.equal(idle,false);
  h.frame(.06); assert.equal(idle,false);
  h.frame(.06); await Promise.resolve();
  assert.equal(idle,true); assert.match(h.attrs['aria-label']!,/1\/1.*第 1 步/);
  assert.equal(h.objects().filter(o=>o.sprite==='filled').length,1);
});

test('sokoban presentation: long route is continuous, duplicate snapshots do not replay it',async()=>{
  const h=await harness();
  const option=reachablePushes(h.game.initialState()).find(o=>o.walkSteps>=4)!;
  assert.ok(option);
  const result=h.game.act(h.game.initialState(),answer(option.id));
  const obs=observe(h.game,result.state);
  h.client.draw(h.canvas,obs); h.client.draw(h.canvas,obs);
  const actor=h.objects().find(o=>o.sprite==='worker');
  const start={...actor.pos}; h.frame(.055);
  assert.ok(actor.pos.x!==start.x || actor.pos.y!==start.y);
  let idle=false; h.client.whenIdle().then(()=>{idle=true;});
  h.frame(option.actions.length*.11); await Promise.resolve();
  assert.equal(idle,true);
  const end={x:actor.pos.x,y:actor.pos.y}; h.frame(1);
  assert.deepEqual({x:actor.pos.x,y:actor.pos.y},end);
});

test('sokoban presentation: queued undo and next move preserve the final authoritative board',async()=>{
  const h=await harness();
  let s=h.game.initialState();
  for(const action of ['R','undo','L']) {s=h.game.act(s,answer(action)).state;h.client.draw(h.canvas,observe(h.game,s));}
  let idle=false;h.client.whenIdle().then(()=>{idle=true;});
  h.frame(.2);h.frame(.2);h.frame(.2);await Promise.resolve();
  assert.equal(idle,true);assert.match(h.attrs['aria-label']!,/第 3 步/);
});
