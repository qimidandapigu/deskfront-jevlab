import {sampleAssembly} from './generation-motion.js';
/* Read-only projection. Never turn an intention or a future report into a receipt. */
export const steps = [
  ['observe','观察','上下文'],['plan','规划 · DeepSeek','体验意图'],
  ['forces','计算 · 算法','兵力清单'],['generate','搭建 · JEV','空间方案'],['validate','校验','检查'],['apply','应用','建成回执']
];
export function generationChoices(stage,step=3) {
  if(step===3){
    const order=['scene_shape','tactical_approach','mission_kind','support_type','force_package','defender_mix'];
    return (stage?.planning?.decisions||[]).filter(d=>Array.isArray(d.options)&&d.options.length&&d.options.some(o=>o.id===d.choice))
      .sort((a,b)=>order.indexOf(a.key)-order.indexOf(b.key))
      .map(d=>({key:d.key,label:d.label,selected:d.choice,options:d.options,source:d.optionsSource,actor:'JEV',fixed:d.selection==='fixed'}));
  }
  if(step===1 && stage?.reportId && stage?.analysis && stage?.forceIntent){
    const names={very_easy:'很容易',easy:'容易',normal:'普通',hard:'难',very_hard:'困难'},id=stage.forceIntent.difficulty;
    return [{key:'adopted_difficulty',label:'难度（采用设置）',selected:id,options:[{id,label:names[id]||id}],source:'adopted_only',actor:'本关',fixed:false}];
  }
  return [];
}
export function matchingAssemblyMedia(media,stage) {
  return !!stage && media?.operationId===stage.id && /^[a-f0-9]{12}$/.test(media.coversDigest||'')
    && stage.reconstruction==='level-'+stage.id+'-'+media.coversDigest
    && media.video==='assembly-'+stage.id+'.mp4' && Number.isFinite(media.duration) && media.duration===30;
}
export function generationSummary(stage) {
  if (!stage) return {title:'等待生成记录',description:'选择一局，查看它实际采用的方案。',challenge:'未记录',kinds:'未记录',support:'未记录',source:'等待记录',states:['missing','missing','missing','missing','missing','missing']};
  const intent=stage.forceIntent, bound=!!stage.reportId && !!stage.analysis;
  const difficulty={very_easy:'充分缓冲',easy:'适度缓冲',normal:'常规挑战',hard:'提高挑战',very_hard:'高压挑战'};
  const names={rifle:'步枪',smg:'冲锋枪',rocket:'火箭筒',tank:'坦克',mortar:'迫击炮'};
  const pool=intent?.enemy_kinds;
  const kinds=Array.isArray(pool)&&pool.length&&pool.every(k=>Object.hasOwn(names,k)) ? '允许：'+pool.map(k=>names[k]).join(' · ') : '未记录';
  const challenge=difficulty[intent?.difficulty] || '未记录';
  const support=intent ? (intent.reinforce ? '补足能力' : '保持现有编成') : '未记录';
  const failed=['rejected','failed','error','generation_blocked'].includes(stage.status);
  const complete=stage.status==='completed';
  const checks=stage.replay?.frames?.filter(f=>f.kind==='check') || [];
  const lastCheck=checks.at(-1),hasCheck=!!lastCheck && /检查通过/.test(lastCheck.text||'');
  const hasFailure=!!lastCheck && /失败|拒绝|未通过/.test(lastCheck.text||'');
  return {title:bound ? (challenge!=='未记录'?challenge+' · '+(intent?.reinforce?'补足能力':'保持编成'):'已关联体验安排') : stage.reportId?'体验安排未记录':'JEV 自主策划',
    description:bound?'本次已关联体验安排，实际效果仍待观察。':stage.reportId?'来源报告未保存，不补写体验判断。':'本次未采用 DeepSeek 报告，由 JEV 根据当时事实策划。',
    challenge,kinds,support,source:bound?'已关联 DeepSeek':stage.reportId?'报告缺失':'JEV 自主策划',
    states:[stage.observation?'done':'missing',bound?'done':stage.reportId?'missing':'skipped',
      stage.forceSummary?'done':'missing',stage.buildSteps?.length?'done':stage.plannerId?'active':'missing',complete?'done':hasFailure||failed?'error':hasCheck?'done':'missing',complete?'done':failed?'error':'pending'],
    status:complete?'引擎已建成':failed?'生成未完成':({prepared:'方案已准备',queued_not_completed:'已提交，等待完成',building:'引擎搭建中'})[stage.status]||'等待完成回执'};
}
export function flowCaptions(stage,summary) {
  return [stage?.observation?'观测已关联':'观测未记录',
    summary.states[1]==='skipped'?'未采用 · JEV 自主':summary.states[1]==='done'?'意图已关联':'报告未记录',
    stage?.forceSummary?'编成已记录':'清单未记录',stage?.buildSteps?.length?'方案已返回':stage?.plannerId?'策划已返回':'等待方案',
    summary.states[4]==='done'?'检查通过':summary.states[4]==='error'?'检查未通过':'检查未记录',
    summary.states[5]==='done'?'已建成':summary.states[5]==='error'?'未建成':'等待回执'];
}
export function sceneAt(stage,time=30) {return sampleAssembly(stage,time);}
export function availablePhases(stage) {
  const a=stage?.assembly;
  return [{at:0,label:'初稿',available:!!a?.draft},{at:14.2,label:'修改',available:!!a?.revision},
    {at:18.4,label:'布局',available:!!a?.final},{at:21,label:'通路',available:!!a?.routes?.main?.length},
    {at:24.5,label:'部署',available:!!a?.units?.length}];
}
