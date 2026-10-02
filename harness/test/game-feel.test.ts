import { test } from 'node:test';
import assert from 'node:assert/strict';
import { actor, progress, starterLevel, step } from '../src/games/jump/engine.js';
import { createBoxingGame } from '../src/games/boxing/adapter.js';
import { newFirefight, soldierObservation } from '../src/games/soldiers/engine.js';

test('jump grace permits late edge jump but expires and never grants double jump', () => {
 const l=starterLevel(), p=progress(), a=actor({x:559,y:400});
 step(a,{move:1,jump:false},l,p);
 assert.equal(a.grounded,false);
 step(a,{move:1,jump:true},l,p); assert.ok(a.vy<0);
 step(a,{move:0,jump:false},l,p);
 step(a,{move:0,jump:true},l,p); assert.ok(a.vy>-5);
 const b=actor({x:559,y:400});
 for(let i=0;i<9;i++) step(b,{move:1,jump:false},l,progress());
 step(b,{move:0,jump:true},l,progress()); assert.ok(b.vy>0);
});
test('jump buffers landing input, consumes once, and held input does not bounce', () => {
 const l=starterLevel(),p=progress(),a={...actor({x:64,y:398}),grounded:false,vy:3};
 step(a,{move:0,jump:true},l,p); assert.ok(a.vy<0); assert.equal(a.grounded,false);
 for(let i=0;i<100;i++)step(a,{move:0,jump:true},l,p);
 assert.equal(a.grounded,true);assert.equal(a.y,400);
});
test('boxing practice opponents stand still, guard, or repeat heavy without rival AI', () => {
 for(const mode of ['practice-idle','practice-guard','practice-heavy']){
 const g=createBoxingGame(mode),s=g.initialState(); assert.equal(g.rival,undefined);
 const x=s.bout.fighters[1]!.x;g.step(s);assert.equal(s.bout.fighters[1]!.x,x);
 if(mode==='practice-heavy')assert.equal(s.bout.fighters[1]!.attack?.kind,'heavy');
 }
 assert.ok(createBoxingGame().rival);
});
test('soldier firing feedback distinguishes distance, cover, reload and readiness', () => {
 const f=newFirefight();f.sandbags=[];f.player.x=5;f.player.y=5;
 f.enemies.forEach((e,i)=>{e.hp=i?0:40;e.x=10;e.y=5;});
 const status=()=> (soldierObservation(f) as {fireStatus:string}).fireStatus;
 assert.equal(status(),'ready'); f.player.cool=2;assert.equal(status(),'cooldown');
 f.player.cool=0;f.player.reload=3;assert.equal(status(),'reloading');
 f.player.reload=0;f.player.ammo=0;assert.equal(status(),'empty');
 f.player.ammo=6;f.enemies[0]!.x=30;assert.equal(status(),'range');
 f.enemies[0]!.x=10;f.sandbags=[{x:7,y:5}];assert.equal(status(),'blocked');
});
