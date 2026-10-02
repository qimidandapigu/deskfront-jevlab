import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { createSessionService } from '../src/arena/sessions.js';
import { createDefaultRegistry } from '../src/games/index.js';
import { createDefaultRuntimeRegistry } from '../src/games/runtimes.js';
import { createMockSystemOne } from '../src/systemone/mock.js';

test('Deskfront squad coordination: support, arrival, handoff and ownership contracts', () => {
  execFileSync(process.env.PYTHON_BIN ?? 'python', ['test/deskfront_tactics_checks.py'], {env:{...process.env,PYTHONUTF8:'1'},stdio:'pipe'});
});

test('coordinated variant connects the unchanged game through Harness and receives real receipts', {
  skip:process.env.DESKFRONT_LIVE_TEST!=='1',timeout:100000,
}, async()=>{
  const configuredRoot = process.env.DESKFRONT_ROOT;
  const root = configuredRoot
    ? resolve(configuredRoot)
    : [resolve('..'), resolve('../deskfront-jevlab')]
      .find(candidate => existsSync(resolve(candidate, 'project.godot')))
    ?? resolve('../deskfront-jevlab');
  const before=execFileSync('git',['status','--porcelain'],{cwd:root});
  const service=createSessionService({registry:createDefaultRegistry(),runtimes:createDefaultRuntimeRegistry(),backend:createMockSystemOne(),
    backends:{names:['mock'],defaultName:'mock',create:()=>createMockSystemOne()},logDir:'output/deskfront-tactics-test'});
  try{
    const id=service.start('deskfront',{backend:'mock',variant:'duel-tactics-headless',runtime:{durationMs:90000,maxRequests:100}}).matchId;
    let verified=false;
    for(let i=0;i<340;i++){
      await new Promise(r=>setTimeout(r,250));
      const s=service.state(id);assert.notEqual(s.outcome,'error',s.error);
      const p=s.payload as {game?:{lm?:{squad?:{plan?:{source?:string};events?:{text:string}[]}}}};
      const rows=service.history(id).history as {record?:{type?:string;receipt?:{accepted?:boolean}}}[];
      if(p?.game?.lm?.squad?.plan?.source==='local_rules'&&rows.some(r=>r.record?.type==='squad-receipt'&&r.record.receipt?.accepted)){
        verified=true;break;
      }
      if(s.status==='done')break;
    }
    assert.ok(verified,'requires real Godot acceptance with explicit local-rule plan');
    service.stop(id);await service.wait(id);
  }finally{await service.close();assert.deepEqual(execFileSync('git',['status','--porcelain'],{cwd:root}),before);}
});
