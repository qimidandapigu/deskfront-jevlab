import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { createSessionService } from '../src/arena/sessions.js';
import { createDefaultRegistry } from '../src/games/index.js';
import { createDefaultRuntimeRegistry } from '../src/games/runtimes.js';
import { createMockSystemOne } from '../src/systemone/mock.js';
import { execFileSync } from 'node:child_process';

test('encounter combat context and exit guards',()=>{
  execFileSync(process.env.PYTHON_BIN??'python',['-X','utf8','test/deskfront_world_combat_checks.py'],{stdio:'pipe'});
});

test('infinite encounter accepts green Harness orders while red remains native', {
  skip:process.env.DESKFRONT_WORLD_TEST!=='1',timeout:60000,
},async()=>{
  const dir='output/world-harness-'+Date.now();mkdirSync(dir,{recursive:true});
  console.log(dir);
  const currentCards=new Set(JSON.parse(execFileSync(process.env.PYTHON_BIN??'python',
    ['-c','import json,sys;sys.path.insert(0,"src/deskfront");from world.region_graph import SELECTABLE_MODULES;print(json.dumps(SELECTABLE_MODULES))'],
    {encoding:'utf8'})) as string[]);
  const service=createSessionService({registry:createDefaultRegistry(),runtimes:createDefaultRuntimeRegistry(),backend:createMockSystemOne(),
    backends:{names:['mock'],defaultName:'mock',create:()=>createMockSystemOne()},logDir:dir});
  try{
    const id=service.start('deskfront',{backend:'mock',variant:'infinite-headless',runtime:{durationMs:45000,maxRequests:100}}).matchId;
    let verified=false;
    for(let i=0;i<170;i++){
      await new Promise(r=>setTimeout(r,250));
      const s=service.state(id);assert.notEqual(s.outcome,'error',s.error);
      const w=s.latest?.observation as {control?:Record<string,string>;units?:{faction:string}[];world_growth?:{
        revision:number;completed?:{design?:{design_card?:{signature?:string};build_operations?:{op?:string;module?:string}[]}}[]
      }}|undefined;
      const rows=service.history(id).history as {record?:{type?:string;unit_id?:string;receipt?:{accepted?:boolean};command?:{faction?:string;assignments?:Record<string,{region_id?:string;region_path?:string[]}>}}}[];
      if(w?.world_growth?.revision){
        assert.equal(w.control?.green,'lm');assert.equal(w.control?.red,'game_ai');
        if(w.world_growth.revision===1){
          assert.ok((w.units?.filter(u=>u.faction==='green').length??0)>=4);
          assert.ok((w.units?.filter(u=>u.faction==='red').length??0)>=3);
          const design=w.world_growth.completed?.[0]?.design;
          assert.equal(design?.design_card?.signature,'region_graph');
          const placements=design?.build_operations?.filter(o=>o.op==='place_region')??[];
          assert.equal(placements.length,9);
          assert.ok(placements.every(o=>o.module==='fortress_base'||currentCards.has(o.module??'')),
            'Native infinite world must build current selectable cards only');
        }
        const receipts=rows.filter(r=>r.record?.type==='human-engine-receipt'&&r.record.receipt?.accepted);
        assert.ok(receipts.every(r=>r.record?.command?.faction==='green'));
        if(receipts.length>=2 && receipts.some(r=>Object.values(r.record?.command?.assignments??{}).every(a=>a.region_id&&a.region_path?.length))){verified=true;break;}
      }
      if(s.status==='done')break;
    }
    writeFileSync(dir+'/report.json',JSON.stringify({verified,state:service.state(id),history:service.history(id)},null,2));
    assert.ok(verified,'Requires accepted green Harness commands with per-member region routes; see report');
    service.stop(id);await service.wait(id);
  }finally{await service.close();}
});
