/** Read-only, public battle-lab projection. No requests, commands or tactical inference. */
import { recordedOverviewMap, nativeOverviewMap } from './overview-map.js';
const number = (v: any) => typeof v === 'number' && Number.isFinite(v) ? v : null;
const text = (v: any, limit = 1200) => typeof v === 'string' ? v.slice(0, limit) : '';
const obj = (v: any): any => v && typeof v === 'object' && !Array.isArray(v) ? v : {};
const list = (v: any): any[] => Array.isArray(v) ? v : [];
function pick(v: any, keys: string[]) { return Object.fromEntries(keys.filter(k => v?.[k] !== undefined).map(k => [k, v[k]])); }
function choices(response: any) {
  return Object.entries(obj(response?.answers)).slice(0, 18).map(([key, value]) => {
    const row = obj(value);
    return { question: key, choice: row.choice ?? null, probabilities: obj(row.probabilities) };
  });
}
export interface OverviewEvent { index: number; time: number; kind: string; faction: string; title: string; data: any; }
export function projectOverview(records: any[]) {
  const events: OverviewEvent[] = [];
  const vehicleMenus = new Map<string, any[]>(), vehicleQueued = new Map<string, any>();
  const vehicleKey = (r:any,id:any) => [r.run_id??'',r.faction??'',r.unit_id??'',id??''].join('|');
  let clock = 0;
  const emit = (kind: string, row: any, title: string, data: any) => events.push({
    index: events.length, time: clock, kind, faction: text(row.faction, 20), title, data,
  });
  for (const envelope of records) {
    const r = obj(envelope.record ?? envelope);
    const nativeTime = number(r.game_time);
    if (nativeTime !== null) clock = Math.max(clock, nativeTime);
    if (r.type==='battle-map-snapshot'&&r.schema==='deskfront-battle-map/v1'&&r.run_id&&r.run_id===r.snapshot?.run_id) {
      const map=nativeOverviewMap(r.snapshot);
      if(map)for(const faction of ['green','red']){
        emit('map',{faction},'原生剩余路线与战场采样',{...map,...(r.provenance==='native-verification'?{provenance:'native-verification'}:{})});
        const members=list(map.units).filter(u=>u.faction===faction&&typeof u.hp==='number'&&u.hp>0);
        const health=members.filter(u=>typeof u.max_hp==='number'&&u.max_hp>0).map(u=>Math.max(0,Math.min(100,100*u.hp/u.max_hp)));
        emit('observation',{faction},'原生单位观测',{alive:members.length,mean_health_percent:health.length?Math.round(health.reduce((a,b)=>a+b,0)/health.length*10)/10:null,scope:'native_faction_units'});
      }
    }
    if (r.type === 'human-model-request' && Array.isArray(r.context?.members)) {
      const map = recordedOverviewMap(r.context, text(r.faction,20));
      if(map) emit('map', r, '战场地图与执行观测采样', map);
      const members = list(r.context.members).filter(u => typeof u.hp === 'number' && u.hp > 0);
      const percentages = members.filter(u => number(u.max_hp) !== null && u.max_hp > 0).map(u => Math.max(0, Math.min(100, 100*u.hp/u.max_hp)));
      emit('observation', r, '小队成员观测', { alive: members.length,
        mean_health_percent: percentages.length ? Math.round(percentages.reduce((a,b)=>a+b,0)/percentages.length*10)/10 : null,
        scope:'recorded_squad_members_not_all_faction_assets',
      });
    }
    if (r.type === 'world-macro') {
      const value = obj(r.answers?.regulation?.value);
      emit('director', r, '导演安排后续体验', {
        requestId: text(r.requestId, 120), model: text(r.resolvedModel, 120),
        ...pick(value, ['reason', 'current_analysis', 'next_goal', 'force_intent', 'experience_flow', 'phase']),
        resources: Object.fromEntries(Object.entries(obj(r.context?.teams)).map(([faction, team]) =>
          [faction, pick(team, ['alive', 'weapons', 'mean_health_percent', 'observed_dead'])])),
        observedTick: number(r.context?.tick),
        source: 'recorded_model_report_not_proof_of_application',
      });
    }
    if (r.type === 'world-receipt' && r.status === 'completed') {
      emit('deployment', r, '引擎确认建成', {
        operationId: text(r.operation_id, 120), level: number(r.generation_scope?.target_world_revision),
        sourceReportId: r.experience_basis?.report_id ?? r.macro_call ?? null,
        intent: r.force_intent ?? null, selectedExperience: pick(r.selected_experience, ['selected_goal','expected','application']),
        manifest: Object.fromEntries(['enemies','reinforcements','equipment'].map(key => [key,
          list(r.force_manifest?.[key]).map(u => pick(u, ['id','kind','weapon','faction','crew_ids']))])),
        accepted: r.receipt?.accepted === true,
      });
    }
    if (r.type === 'human-commander-plan' || r.type === 'human-autonomous-plan') {
      emit('command', r, r.type === 'human-commander-plan' ? '总指挥提出目标' : 'JEV自主选择目标', {
        ...pick(r.plan, ['objective','risk','stage','region_id','position','radius','source','request_id','assessment_basis','tactical_brief','equipment_goal']),
        sourceType: r.type,
        squadId: text(r.squad_id, 120),
      });
    }
    if (r.type === 'human-support-submitted' || r.type === 'human-engine-receipt' && r.command?.action === 'support_order' && !r.command?.personal) {
      const c=obj(r.command);
      emit('support',r,'JEV装备支援指令',{
        assetId:text(c.asset_id,120),mode:text(c.mode,80),targetId:text(c.target_id,120),
        orderId:text(c.order_id,120),status:r.type==='human-support-submitted'?'submitted':r.receipt?.accepted===true?'accepted':r.receipt?.accepted===false?'rejected':'unknown',
      });
    }
    if (r.type === 'vehicle-personal-request') vehicleMenus.set(vehicleKey(r,r.action_id),list(r.context?.native_menu?.options));
    if (r.type === 'vehicle-personal-decision') {
      const option=vehicleMenus.get(vehicleKey(r,r.command?.action_id))?.find(o=>o.id===r.choice);
      const d={unitId:text(r.unit_id,120),unitKind:'tank',choice:text(option?.intent??r.choice,120),choiceId:text(r.choice,120),
        actionId:text(r.command?.action_id,120),status:r.http_status===202?'queued':'queue_rejected'};
      emit('soldier',r,'坦克选择局部动作',d);
      if(r.queue_result?.id)vehicleQueued.set(vehicleKey(r,r.queue_result.id),d);
    }
    if (r.type === 'vehicle-personal-receipt') {
      const selected=r.receipt?.id?vehicleQueued.get(vehicleKey(r,r.receipt.id)):null;
      if(selected)emit('soldier',r,'坦克局部动作原生回执',{...selected,linkedDecision:true,
        status:r.receipt.accepted===true?'accepted':r.receipt.accepted===false?'rejected':'unknown'});
      else emit('vehicle_receipt',r,'坦克独立回执（缺少关联身份）',{
        unitId:text(r.unit_id,120),receipt:pick(r.receipt,['id','accepted','status','message']),scope:'not_linked_to_a_decision'});
    }
    if (r.type === 'human-order-submitted' || r.type === 'human-engine-receipt') {
      const c = obj(r.command);
      if (c.action !== 'squad_order') continue;
      emit('squad', r, r.type === 'human-engine-receipt' ? '小队指令获得引擎回执' : 'JEV提交小队分工', {
        squadId: text(r.squad_id, 120), orderId: text(c.order_id, 120), intent: text(c.intent, 80),
        assignments: Object.fromEntries(Object.entries(obj(c.assignments)).map(([id, a]) =>
          [id, pick(a, ['role','region_id','region_path','source','keep_assignment','position','route_positions'])])),
        cooperation: list(c.cooperation_plan?.support_relations).map(x => pick(x, ['supporter_ids','assisted_member_ids','threat_ids'])),
        status: r.type === 'human-order-submitted' ? 'submitted' : r.receipt?.accepted === true ? 'accepted' : 'rejected',
      });
    }
    if (r.type === 'soldier-decision') emit('soldier', r, '士兵选择局部行动', {
      unitId: text(r.unit_id, 120), choice: text(r.choice, 200), behavior: text(r.local_behavior?.mode, 200),
      requestId: text(r.provider_request_id, 120), selected: choices(r.response), status: 'selected',
    });
    if (r.type === 'soldier-action-receipt') emit('soldier', r, '士兵行动获得引擎回执', {
      unitId: text(r.unit_id, 120), choice: text(r.intent, 200),
      status: r.result?.accepted === true ? 'accepted' : 'rejected',
    });
  }
  return { events, lastGameTime: clock, recordingNote:events.some(e=>e.kind==='map'&&e.data.provenance==='native-verification')?'原生验证回放：验证场景，非旧对局；未调用模型。':null, boundary: '模型安排、提交、原生接受与建成分别展示；接受不等于完成战术目标。日志顺序按最近记录的游戏时钟采样对齐。' };
}

export function liveOverview(state: any) {
  const w = obj(state?.latest?.observation ?? state?.finalObservation);
  const g=obj(state?.payload?.game);
  return { status: state?.status ?? 'unknown', gameTime: number(w.time), runId: text(w.run_id, 120),
    tick:number(w.tick),requestLimit:number(state?.config?.runtime?.maxRequests),
    controllers:{green:text(g.greenController,40),red:text(g.redController,40)},
    modelStatus: ['green','red'].map(team=>{const v=obj(team==='green'?g.lm:g.redLm);return{team,pending:v.pending===true||v.squad?.pending===true,error:text(v.squad?.error,300)};}),
    map: nativeOverviewMap(w),
    paused: w.paused === true,
    units: list(w.units).map(u => ({ id: text(u.id, 120), faction: text(u.faction, 20),
      weapon: text(u.weapon, 40), kind: text(u.kind, 40), alive: typeof u.hp === 'number' ? u.hp > 0 : null,
      healthPercent: number(u.max_hp) && number(u.hp) !== null ? Math.max(0, Math.min(100, 100*u.hp/u.max_hp)) : null,
    })),
    mission: pick(w.world_growth?.mission, ['mission_kind','status','enemies_remaining']),
    requests: number(state?.payload?.requests),
  };
}
