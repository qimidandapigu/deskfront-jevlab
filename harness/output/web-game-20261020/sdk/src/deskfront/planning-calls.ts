/** Correlate only explicit saved identities. A nearby receipt is never assumed to belong to a call. */
const keys=(v:any,names:string[])=>Object.fromEntries(names.filter(k=>v?.[k]!==undefined).map(k=>[k,v[k]]));
export function projectPlanningCalls(records:any[]){
 const calls:any[]=[],serial=new Map<string,any>(),decisions=new Map<string,any>(),providers=new Map<string,any>();let clock=0;
 const key=(r:any)=>[r.run_id??'',r.faction??'',r.role??'',r.request_serial??''].join('|');
 const add=(r:any,role:string,request:any)=>{const c:any={id:'c'+calls.length,role,faction:r.faction??'',unitId:r.unit_id??null,runId:r.run_id??null,
  requestedAt:clock,returnedAt:null,elapsedMs:null,providerId:null,model:null,error:null,errorAt:null,
  stage:r.context?.generated_stage?.index??null,wireResponse:null,
  request,response:null,receipts:[] as any[],detailAvailable:true};calls.push(c);return c;};
 for(const e of records){const r=e.record??e;if(typeof r.game_time==='number'&&Number.isFinite(r.game_time))clock=Math.max(clock,r.game_time);
  if(r.type==='human-model-request'){const c=add(r,r.role,keys(r,['context','questions']));serial.set(key(r),c);}
  else if(['human-coordinate-response','human-member-task-response'].includes(r.type)){const c=serial.get(key(r));if(c&&(r.type==='human-member-task-response'||!c.wireResponse))c.wireResponse=keys(r.response,['answers']);}
  else if(r.type==='human-model-response'){const c=serial.get(key(r));if(c){c.returnedAt=clock;c.response=keys(r.response,['answers','usage','usageComplete','requestedModel','resolvedModel','requestId']);c.providerId=r.response?.requestId??null;c.model=r.response?.resolvedModel??r.response?.requestedModel??null;c.elapsedMs=typeof r.elapsed_s==='number'?Math.round(r.elapsed_s*1000):null;if(c.providerId)providers.set(c.providerId,c);}}
  else if(['human-model-error','human-model-timeout'].includes(r.type)){const c=serial.get(key(r));if(c){c.errorAt=clock;c.error=String(r.error??r.reason??r.type).slice(0,500);}}
  else if(r.type==='soldier-model-request'){const c=add(r,'personal',keys(r,['context','questions','choices','action_options']));if(r.local_decision_id)decisions.set([r.run_id,r.faction,r.unit_id,r.local_decision_id].join('|'),c);}
  else if(r.type==='soldier-decision'){const c=decisions.get([r.run_id,r.faction,r.unit_id,r.local_decision_id].join('|'));if(c){c.returnedAt=clock;c.response=keys(r.response,['answers','usage','usageComplete','requestedModel','resolvedModel','requestId']);c.providerId=r.provider_request_id??r.response?.requestId??null;c.model=r.response?.resolvedModel??r.response?.requestedModel??null;if(c.providerId)providers.set(c.providerId,c);}}
  else if(r.type==='human-engine-receipt'){const c=providers.get(r.request_id);if(c&&c.runId===r.run_id&&c.faction===r.faction)c.receipts.push({at:clock,commandId:r.command_id??null,command:keys(r.command,['action','intent','order_id','unit_ids','assignments']),receipt:keys(r.receipt,['accepted','message','tick','id','status'])});}
  else if(['world-macro','world-planner','world-builder'].includes(r.type)){
   const role=r.type==='world-macro'?'director':r.type==='world-planner'?'planner':'builder',c=add(r,role,r.type==='world-macro'?{context:r.model_context??r.context}:null);
   c.returnedAt=clock;c.response=keys(r,['answers','plan','operations','requestId','resolvedModel','requestedModel','usage']);c.providerId=r.requestId??null;c.model=r.resolvedModel??r.requestedModel??null;c.elapsedMs=r.elapsed_ms??null;
   if(c.providerId)providers.set(c.providerId,c);
  }
 }
 // Individual soldier receipts in legacy logs have no decision identity. Keep them
 // in the normal event viewer; do not attach one to the nearest soldier call.
 let bytes=0;for(const c of [...calls].reverse()){const size=Buffer.byteLength(JSON.stringify(c));bytes+=size;if(size>2000000||bytes>32000000){c.request=null;c.response=null;c.wireResponse=null;c.receipts=[];c.detailAvailable=false;}}
 return calls;
}
export function planningCallSummary(c:any){return {...keys(c,['id','role','faction','unitId','stage','requestedAt','returnedAt','elapsedMs','providerId','model','error','errorAt','detailAvailable']),receiptTimes:c.receipts.map((r:any)=>r.at)};}
export function planningCallAt(c:any,at:number){
 if(!c||c.requestedAt>at)return null;
 const returned=c.returnedAt!==null&&c.returnedAt<=at,error=c.errorAt!==null&&c.errorAt<=at;
 return {...planningCallSummary(c),returnedAt:returned?c.returnedAt:null,elapsedMs:returned?c.elapsedMs:null,
  providerId:returned?c.providerId:null,model:returned?c.model:null,error:error?c.error:null,errorAt:error?c.errorAt:null,
  request:c.request,response:returned?c.response:null,wireResponse:returned?c.wireResponse:null,receipts:c.receipts.filter((r:any)=>r.at<=at),
  boundary:'只展示实际保存字段。缺失的system、参数或未明确关联的回执不补造；接受不等于完成。'};
}
