import test from 'node:test';
import assert from 'node:assert/strict';
import {createSessionService} from '../src/arena/sessions.js';
import {createDefaultRegistry} from '../src/games/index.js';
import {createRuntimeRegistry} from '../src/arena/runtime.js';
import {createExternalGameRuntime} from '../src/external/runtime.js';
import {GAME_PROTOCOL} from '../src/external/protocol.js';
import {createMockSystemOne} from '../src/systemone/mock.js';

for(const scenario of ['normal','unknown','deskfront'])test(scenario==='deskfront'?'Deskfront ends cleanly on the shared request budget':scenario==='unknown'?'unknown roles never reach a backend':'commander and executor route independently with one shared budget',async()=>{
  const unknown=scenario==='unknown';
  const gameId=scenario==='deskfront'?'deskfront':'role-test';
  const created:string[]=[];
  const script=`const io=require('node:readline').createInterface({input:process.stdin});let n=0;
    const emit=x=>console.log(JSON.stringify(x));
    const request=()=>emit({type:'request',id:String(++n),state:{},questions:{x:{type:'choice',instructions:'choose',criteria:{go:'go'}}},...(n===1?{role:${JSON.stringify(unknown?'untrusted':'commander')}}:{})});
    io.on('line',l=>{const m=JSON.parse(l);if(m.type==='start'){emit({type:'ready',protocol:${JSON.stringify(GAME_PROTOCOL)}});request()}
    if(m.type==='response'){if(n<3)request();else{emit({type:'state',observation:{error:m.error}});emit({type:'end',outcome:'done'})}}if(m.type==='stop')process.exit(0)});`;
  const runtimes=createRuntimeRegistry([createExternalGameRuntime({protocol:GAME_PROTOCOL,id:gameId,name:'roles',description:'test',decisionRoles:{commander:'deepseek'},command:[process.execPath,'-e',script],capabilities:{human:false,ai:true,seed:false}})]);
  const service=createSessionService({registry:createDefaultRegistry(),runtimes,backend:createMockSystemOne(),backends:{names:['jev','deepseek'],defaultName:'jev',create:name=>{created.push(name);return createMockSystemOne()}},logDir:'output/role-tests'});
  try{
    const id=service.start(gameId,{backend:'jev',runtime:{maxRequests:2}}).matchId;
    const s=await service.wait(id);
    if(unknown){assert.equal(s.outcome,'error');assert.match(s.error!,/Unknown decision role/);assert.deepEqual(created,['jev']);}
    else if(scenario==='deskfront'){assert.equal(s.outcome,'request-budget');assert.equal(s.error,undefined);assert.deepEqual(created,['jev','deepseek']);}
    else{assert.equal(s.outcome,'done');assert.deepEqual(created,['jev','deepseek']);assert.deepEqual(s.latest?.observation,{error:'request-budget'});
      assert.deepEqual((service.history(id).history as {type:string;role?:string}[]).filter(r=>r.type==='decision').map(r=>r.role),['commander','executor']);}
  }finally{await service.close()}
});

test('failed external decision records elapsed time without request content', async () => {
  const script = `const io=require('node:readline').createInterface({input:process.stdin});
    const emit=x=>console.log(JSON.stringify(x));
    io.on('line',l=>{const m=JSON.parse(l);if(m.type==='start'){emit({type:'ready',protocol:${JSON.stringify(GAME_PROTOCOL)}});
      emit({type:'request',id:'fail-one',state:{secret:'private-state'},questions:{x:{type:'choice',instructions:'private-prompt',criteria:{go:'go'}}}})}
      if(m.type==='response'){emit({type:'end',outcome:'done'})}if(m.type==='stop')process.exit(0)});`;
  const backend = { async ask() { throw new Error('upstream-failed'); } };
  const runtimes = createRuntimeRegistry([createExternalGameRuntime({ protocol: GAME_PROTOCOL, id: 'role-error-test', name: 'roles',
    description: 'test', command: [process.execPath, '-e', script], capabilities: { human: false, ai: true, seed: false } })]);
  const service = createSessionService({ registry: createDefaultRegistry(), runtimes, backend, logDir: 'output/role-tests' });
  try {
    const id = service.start('role-error-test').matchId;
    const result = await service.wait(id);
    assert.equal(result.outcome, 'done');
    const errors = (service.history(id).history as { type: string; elapsedMs?: number; error?: string }[]).filter(record => record.type === 'decision-error');
    assert.equal(errors.length, 1);
    assert.equal(errors[0]!.error, 'upstream-failed');
    assert.ok(typeof errors[0]!.elapsedMs === 'number' && errors[0]!.elapsedMs >= 0);
    assert.ok(!JSON.stringify(errors[0]).includes('private-state'));
    assert.ok(!JSON.stringify(errors[0]).includes('private-prompt'));
  } finally { await service.close(); }
});
