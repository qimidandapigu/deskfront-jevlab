import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { createBoxingGame } from '../src/games/boxing/adapter.js';
import { createJumpGame } from '../src/games/jump/adapter.js';
import { createSoldiersGame } from '../src/games/soldiers/adapter.js';

// Component-aware stub: missing scale stays undefined, and destroyAll removes scene callbacks.
function scene(file: string) {
  let objects:any[] = [], updates:Array<()=>void> = [];
  const v=(x:number,y=x):any=>({x,y,lerp(p:any,t:number){return v(x+(p.x-x)*t,y+(p.y-y)*t);},eq(p:any){return x===p.x&&y===p.y;},clone(){return v(x,y);},dist(p:any){return Math.hypot(x-p.x,y-p.y);}});
  let camera=v(240,240);
  function add(parts:any[]) {const o=Object.assign({add,use(c:any){Object.assign(this,c);},onUpdate(f:()=>void){updates.push(f);}},...parts);objects.push(o);return o;}
  const k:any=new Proxy({add,vec2:v,pos:(x:any,y:number)=>({pos:typeof x==='number'?v(x,y):x}),scale:(x:number,y=x)=>({scale:v(x,y)}),rotate:(angle:number)=>({angle}),text:(text:string)=>({text}),color:(r:number,g:number,b:number)=>({color:{r,g,b}}),rgb:(r:number,g:number,b:number)=>({r,g,b}),
    rect:(width:number,height:number)=>({width,height}),tween:()=>Promise.resolve(),time:()=>0,dt:()=>1/60,onUpdate:(f:()=>void)=>updates.push(f),destroyAll:()=>{objects=[];updates=[];},getCamPos:()=>camera,setCamPos:(p:any)=>{camera=p;},easings:{},
  },{get:(target:any,name)=>target[name]??(()=>({}))});
  const window:any={kaplay:()=>k};
  vm.runInNewContext(readFileSync(file,'utf8'),{window,console,document:{}});
  const canvas={width:480,height:480,style:{},setAttribute(){}};
  return {client:window.gameClient,canvas,objects:()=>objects,frame:()=>[...updates].forEach(f=>f())};
}

test('jump presentation: initial render and movement frames have a valid actor scale',()=>{
  const h=scene('src/games/jump/client.js'),g=createJumpGame(),s=g.initialState();
  h.client.draw(h.canvas,g.observe(s));
  assert.doesNotThrow(h.frame);
  const actor=h.objects().find(o=>o.facing===1&&o.target);
  assert.ok(actor);assert.equal(actor.scale.x,1);
  const x=actor.pos.x;
  const moving=g.act(s,{control:{type:'choice',choice:'right',probabilities:{right:1},confidence:1}});
  h.client.draw(h.canvas,g.observe(g.step(moving))); h.frame();
  assert.ok(actor.pos.x>x,'presentation follows the new physics position');
});

test('boxing presentation: reset and frame rollback preserve the fighter update loop',()=>{
  const h=scene('src/games/boxing/client.js'),g=createBoxingGame();
  const initial=g.observe(g.initialState()) as any;
  h.client.draw(h.canvas,initial);
  for (const reset of [true,false]) {
    if(reset) h.client.reset(); else h.client.draw(h.canvas,initial);
    const obs=structuredClone(initial);obs.match.frame=10;obs.fighters.self.x=260;obs.fighters.self.action='advance';
    h.client.draw(h.canvas,obs);
    const fighter=h.objects().find(o=>o.pos?.y===355&&o.scale?.x===1);
    assert.ok(fighter);const x=fighter.pos.x;h.frame();
    assert.ok(fighter.pos.x>x,'rebuilt fighter still interpolates towards its target');
  }
});



test('soldiers presentation: first build and restart retain movement and aim updates',()=>{
  const h=scene('src/games/soldiers/client.js'),g=createSoldiersGame();
  const initial=g.observe(g.initialState()) as any;
  for(let round=0;round<2;round++) {
    h.client.reset(); h.client.draw(h.canvas,initial); h.frame();
    const groups=h.objects().filter(o=>o.scale?.x>1 && typeof o.angle==='number');
    const player=groups.sort((a,b)=>b.pos.y-a.pos.y)[0];
    assert.ok(player);const x=player.pos.x;
    const moved=structuredClone(initial);moved.tick=1;moved.player.x+=1;moved.allies.find((u:any)=>u.id===moved.player.id).x=moved.player.x;
    moved.enemies[0].aimTicks=5;moved.enemies[0].aimX=moved.player.x;moved.enemies[0].aimY=moved.player.y;
    h.client.draw(h.canvas,moved);h.frame();
    assert.ok(player.pos.x>x,'units must interpolate after destroyAll');
    assert.ok(h.objects().some(o=>o.height===2&&o.width>10&&o.opacity>0),'aim warning follows the latest telegraph');
  }
});
