import test from 'node:test';
import assert from 'node:assert/strict';
import {createAssistedJumpGame} from '../src/games/jump/assisted.js';
import {JUMP_LEVELS} from '../src/games/jump/levels.js';
for(const level of JUMP_LEVELS) test(`assisted ${level.id}: slow decisions finish with no midair requests`,()=>{
 const game=createAssistedJumpGame(level.level);let s=game.initialState(),calls=0;
 while(!game.isTerminal(s)) {
  assert.equal(s.actor.grounded,true);
  const q=game.questions(s).control!;assert.equal(q.type,'choice');if(q.type!=='choice')throw Error();
  const ids=Object.keys(q.criteria);assert.notEqual(ids[0],'wait');
  const id=ids[calls%ids.length]!;
  const before={x:s.actor.x,y:s.actor.y};
  for(let i=0;i<90;i++)s=game.step(s); // 1.5s API latency, physics remains running.
  assert.equal(s.actor.x,before.x);assert.equal(s.actor.y,before.y);
  s=game.act(s,{control:{type:'choice',choice:id,probabilities:{[id]:1},confidence:1}});calls++;
  while(!game.isTerminal(s)&&game.decisionReady?.(s)===false)s=game.step(s);
  assert.ok(calls<45,'no repeated planning loop');
 }
 assert.equal(s.progress.won,true);assert.equal(s.deaths,0);
});
test('stale landing is rejected and manual keys keep direct control',()=>{
 const g=createAssistedJumpGame(JUMP_LEVELS[1]!.level);let s=g.initialState();
 const q=g.questions(s).control!;if(q.type!=='choice')throw Error();const id=Object.keys(q.criteria)[0]!;
 s=g.act(s,{control:{type:'choice',choice:'right',probabilities:{right:1},confidence:1}});
 for(let i=0;i<10;i++)s=g.step(s);
 const x=s.actor.x;s=g.act(s,{control:{type:'choice',choice:id,probabilities:{[id]:1},confidence:1}});
 assert.equal(s.routeQueue,undefined);assert.match(s.routeStatus!,/重新规划/);s=g.step(s);assert.equal(s.actor.x,x);
});
