/** Display-only projections. Native execution and recorded model observations stay distinct. */
const array = (v: any): any[] => Array.isArray(v) ? v : [];
const object = (v: any): any => v && typeof v === 'object' && !Array.isArray(v) ? v : {};
const point = (v: any): [number,number] | null => Array.isArray(v) && v.length >= 2 && v.every(Number.isFinite)
  ? [v[0], v.length === 3 ? v[2] : v[1]] : null;
function fields(v: any, keys: string[]) { return Object.fromEntries(keys.filter(k => v?.[k] !== undefined).map(k => [k,v[k]])); }
function expand(v: any, facts: any[], depth = 0): any {
  if (depth > 14) return null;
  if (Array.isArray(v)) return v.slice(0,2000).map(x => expand(x,facts,depth+1));
  if (!v || typeof v !== 'object') return v;
  if (Object.keys(v).length===1 && Number.isInteger(v.ref)) return expand(facts[v.ref],facts,depth+1);
  return Object.fromEntries(Object.entries(v).filter(([k])=>k!=='shared_facts').map(([k,x])=>[k,expand(x,facts,depth+1)]));
}
function unit(u: any, faction: string, convert: (v:any)=>number[]|null) {
  return { ...fields(u,['id','kind','weapon','hp','max_hp','ammo','reload_remaining','suppression','state','order_mode','lm_intent','lm_reason','tactical_role','cover_id','target_id','visible','last_seen']),
    faction: u.faction || faction, position: convert(u.position) };
}
export function recordedOverviewMap(raw: any, faction: string) {
  const c=expand(raw,array(raw?.shared_facts)),t=object(c?.tactical_map);
  if(t.format!=='deskfront-coordinates/v1'||typeof t.diagram!=='string')return null;
  const rows=t.diagram.split('\n').filter((s:string)=>s.includes('|')).map((s:string)=>s.split('|')[1]?.trim().split(/\s+/)||[]);
  const origin=point(t.origin),cols=rows[0]?.length;
  if(!origin||!rows.length||!cols)return null;
  // Legacy diagrams lack the native origin binding. Never guess a world transform.
  const native=t.legacy_frame===false&&Number.isFinite(t.distance_to_cells)&&t.distance_to_cells>0;
  const scale=native?t.distance_to_cells:1,convert=(v:any)=>point(v)?.map(x=>x/scale)??null;
  const table=t.local_hard_covers;
  const covers=Array.isArray(table)?table:array(table?.rows).map(row=>Object.fromEntries(array(table.columns).map((key,i)=>[key,row[i]])));
  const members=array(c.members),contacts=array(c.contacts),known=new Set(members.map(u=>u.id));
  const evidence=object(c.execution_evidence?.members);
  return { source:'recorded_model_observation',time:Number.isFinite(c.time)?c.time:null,stage:c.generated_stage?.index??null,
    coordinateFrame:native?'native-world':'request-grid',bounds:[origin[0]/scale,origin[1]/scale,(origin[0]+cols)/scale,(origin[1]+rows.length)/scale],
    navigationRevision:t.navigation_revision??null,
    covers:covers.slice(0,1500).flatMap(u=>convert(u.position)&&convert(u.size)?[{...fields(u,['id','yaw','height']),position:convert(u.position),size:convert(u.size)}]:[]),
    units:[...members.map(u=>unit(u,faction,convert)),...contacts.filter(u=>!known.has(u.id)).map(u=>unit(u,'contact',convert))].filter(u=>u.position),
    objective:native?point(c.generated_stage?.target):null,
    execution:Object.fromEntries(members.map(u=>[u.id,{...fields(evidence[u.id],['range_status','seconds_since_last_shot','seconds_without_measured_progress','stationary_seconds','fire_block_reason']),
      routeProgress:object(evidence[u.id]?.route_progress),coverExecution:fields(evidence[u.id]?.cover_execution,['phase','reason']),
      assignment:fields(c.engine_squad?.assignments?.[u.id],['role','state','region_id'])}])),
    actualRoutes:[],diagram:t.diagram.slice(0,20000),
  };
}
export function nativeOverviewMap(w: any) {
  if(!Array.isArray(w?.bounds)||w.bounds.length!==4||!w.bounds.every(Number.isFinite))return null;
  const mission=object(w.world_growth?.mission);
  const capture=object(w.remaining_routes),revision=w.navigation_revision??w.navigation?.revision??null;
  const independent=capture.schema==='deskfront-remaining-routes/v1'&&capture.run_id===w.run_id&&capture.navigation_revision===revision;
  const routeRows=Object.hasOwn(w,'remaining_routes')?(independent?array(capture.units):[]):w.debug_visualize?.enabled===true?array(w.debug_visualize.units):[];
  return {source:'native_snapshot',time:Number.isFinite(w.time)?w.time:null,runId:w.run_id??null,stage:mission.index??(Number.isInteger(w.map_index)?w.map_index+1:null),
    coordinateFrame:'native-world',bounds:w.bounds,navigationRevision:revision,
    covers:array(w.covers).filter(u=>u.alive!==false&&point(u.position)).slice(0,1500).map(u=>({...fields(u,['id','height','yaw']),position:point(u.position),size:point(u.ray_size)??point(u.size)})),
    units:array(w.units).slice(0,300).map(u=>unit(u,'unknown',point)).filter(u=>u.position),
    objective:point(mission.target)??point(w.objective?.position),execution:{},
    actualRoutes:routeRows.filter(u=>u.valid!==false&&(u.navigation_revision==null||u.navigation_revision===revision)).map(u=>({unitId:u.unit_id,
      waypoints:array(u.waypoints).map(point).filter(Boolean),next:point(u.next),
      ...fields(u,['state','order','target_id','cover_id','suppression']),command:fields(u.command,['source','action','command_id','reason'])})),
  };
}
