/* Mirror the live world_growth_preview.gd module semantics, not the offline
 * assembly movie: selected desk and its furnished template enter together.
 * Later recorded batches edit existing props. Timings are presentation only. */
const cache=new WeakMap();
export const ease=value=>{const t=Math.max(0,Math.min(1,value));return t*t*(3-2*t);};
const equal=(a,b)=>a.length===b.length&&a.every((v,i)=>v===b[i]);
export function assemblyMotion(stage){
 const assembly=stage?.assembly;if(!assembly)return null;
 if(cache.has(assembly))return cache.get(assembly);
 const geometry=assembly.final||assembly.revision||assembly.draft;if(!geometry)return null;
 const floors=geometry.floors||[],tiles=[];
 const draftCells=stage.buildSteps?.find(b=>b.stage==='layout_draft')?.cells||[];
 const floor=floors.length===1?floors[0]:null;
 if(floor&&Array.isArray(stage.cells)&&stage.cells.length){
  const seen=new Set();for(const cell of stage.cells){const m=/^c([0-2])r([0-2])$/.exec(cell.id||'');if(!m||seen.has(cell.id))continue;seen.add(cell.id);
   const col=Number(m[1]),row=Number(m[2]),dx=(floor[2]-floor[0])/3,dz=(floor[3]-floor[1])/3;
   const initial=draftCells.find(c=>c.id===cell.id);
   tiles.push({id:cell.id,col,row,template:initial?.template||'',rotation:initial?.rotation??null,rect:[floor[0]+col*dx,floor[1]+row*dz,floor[0]+(col+1)*dx,floor[1]+(row+1)*dz],start:.2+(col*3+row)*.65});
  }
 }else floors.forEach((rect,i)=>tiles.push({id:'floor-'+i,rect:[...rect],start:.2+i*.25}));
 const bounds=floors.length?[Math.min(...floors.map(p=>p[0])),Math.min(...floors.map(p=>p[1])),Math.max(...floors.map(p=>p[2])),Math.max(...floors.map(p=>p[3]))]:null;
 const cellIndex=row=>bounds?Math.max(0,Math.min(2,Math.floor((row[0]-bounds[0])/(bounds[2]-bounds[0])*3)))*3+Math.max(0,Math.min(2,Math.floor((row[1]-bounds[1])/(bounds[3]-bounds[1])*3))):0;
 const tileFor=row=>tiles.find(t=>t.col*3+t.row===cellIndex(row))||tiles[0];
 const pieces=[],updates=[],frames=[{at:0,geometry:assembly.draft}],birth=(row,start,bundle=false)=>{const item={initial:[...row],row:[...row],start,end:Infinity,moves:[],bundle,tile:tileFor(row)};pieces.push(item);return item;};
 let active=[];
 if(assembly.draft)active=assembly.draft.covers.map(row=>birth(row,tileFor(row)?.start??.2,true));
 const transition=(geometry,at)=>{if(!geometry)return;const remaining=[...active],next=[],pending=[],changes={at,moved:0,replaced:0,added:0,removed:0,unchanged:0};
  for(const row of geometry.covers){const i=remaining.findIndex(p=>equal(p.row,row));if(i>=0){next.push(remaining.splice(i,1)[0]);changes.unchanged++;}else pending.push(row);}
  for(const row of pending){let chosen=-1,distance=Infinity;remaining.forEach((p,i)=>{if(cellIndex(p.row)!==cellIndex(row)||p.row[4]!==row[4])return;const d=Math.hypot(p.row[0]-row[0],p.row[1]-row[1]);if(d<distance){distance=d;chosen=i;}});
   const previous=chosen>=0?remaining.splice(chosen,1)[0]:null;
   if(previous&&equal(previous.row.slice(2),row.slice(2))){previous.moves.push({at,from:[...previous.row],to:[...row]});previous.row=[...row];next.push(previous);changes.moved++;}
   else {const item=birth(row,at);if(previous){previous.end=at;item.replacement={from:[...previous.row],rotation:previous.row[2]===row[3]&&previous.row[3]===row[2]?Math.PI/2:0};changes.replaced++;}else changes.added++;next.push(item);}
  }
  remaining.forEach(p=>{p.end=at;changes.removed++;});active=next;updates.push(changes);frames.push({at,geometry});
 };
 const batches=(stage.buildSteps||[]).filter(b=>b.stage!=='layout_draft'&&b.geometry?.source==='builder_compiled_spec'&&b.geometry.assembly_usable!==false&&Array.isArray(b.geometry.covers));
 if(batches.length)batches.forEach((b,i)=>transition(b.geometry,14.2+i*3.2/Math.max(1,batches.length-1)));
 else transition(assembly.revision,14.2);
 transition(assembly.final,18.4);
 const units=(assembly.units||[]).map((u,i,all)=>({...u,start:24.5+i*Math.min(.62,3.6/Math.max(1,all.length-1))}));
 const result={tiles,pieces,units,geometry,bounds,updates,frames};cache.set(assembly,result);return result;
}
export function sampleAssembly(stage,time=30){
 const a=stage?.assembly,plan=assemblyMotion(stage);if(!plan)return null;
 const geometry=plan.frames.filter(f=>f.at<=time).at(-1)?.geometry;
 const chosen=plan.tiles.filter(t=>time>t.start).length;
 const update=plan.updates.filter(u=>u.at<=time).at(-1),hasEdits=update&&(update.added+update.removed+update.moved+update.replaced)>0;
 const phase=time<6.5?'选用桌面模块 · '+chosen+'/'+plan.tiles.length:time<14.2?'模块组合完成':time<18.4?(hasEdits?'调整已有布局':'复核已有布局'):time<21?'完成布局':time<24.5?'展开通路':time<29.5?'兵力落位':'完成布局';
 const props=[];
 for(const p of plan.pieces){const enter=ease((time-p.start)/.85),leave=ease((time-p.end)/.7);if(enter<=0||leave>=1)continue;
  let row=[...p.initial],rotation=0;if(p.replacement){const f=ease((time-p.start)/.9);row[0]=p.replacement.from[0]+(p.initial[0]-p.replacement.from[0])*f;row[1]=p.replacement.from[1]+(p.initial[1]-p.replacement.from[1])*f;rotation=p.replacement.rotation*(1-f);}
  for(const move of p.moves){if(time<move.at)continue;const f=ease((time-move.at)/.9);row=[...move.to];row[0]=move.from[0]+(move.to[0]-move.from[0])*f;row[1]=move.from[1]+(move.to[1]-move.from[1])*f;}
  const groupProgress=ease((time-(p.tile?.start??p.start))/.85);
  props.push({row,lift:(p.bundle?-.10*(1-groupProgress):0)-.06*leave,scale:(p.bundle?1:enter)*(1-leave),module:p.tile?.id||'',rotation});
 }
 const routes=time>=21&&a.final?(a.final.routes||a.routes):null;
 return {geometry:geometry||{...plan.geometry,covers:[]},phase,props,tiles:plan.tiles.map(t=>{const progress=ease((time-t.start)/.85);return {...t,progress,lift:-.10*(1-progress)};}),
  bounds:plan.bounds,routes,routeProgress:Math.max(0,Math.min(1,(time-21)/3.5)),units:a.final?plan.units.filter(u=>time>=u.start):[],
  note:geometry?'':(time<14.2?'初稿':time<18.4?'修改稿':'完成布局')+'几何未记录；仅展示已记录桌面结构。',
  geometryMissing:!geometry};
}
