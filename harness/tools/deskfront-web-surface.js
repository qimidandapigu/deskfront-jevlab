/* Match nativeOverviewMap's X/Z projection. The live Web message may contain
 * Vector3 navigation points and ray sizes alongside already projected Vector2
 * actor positions. Never interpret elevation as the map's second axis. */
const projectedTerrain=new WeakMap();
export function projectWebMap(map){
  if(!map)return null;
  const rows=value=>Array.isArray(value)?value:[];
  const point=value=>Array.isArray(value)&&value.length>=2&&value.every(Number.isFinite)
    ?[value[0],value.length===3?value[2]:value[1]]:null;
  const source=rows(map.covers);
  let covers=projectedTerrain.get(source);
  if(!covers){covers=source.flatMap(row=>{const position=point(row.position),size=point(row.size);return position&&size?[{...row,position,size}]:[];});projectedTerrain.set(source,covers);}
  return {...map,
    covers,
    units:rows(map.units).flatMap(row=>{const position=point(row.position);return position?[{...row,position}]:[];}),
    objective:point(map.objective),
    actualRoutes:rows(map.actualRoutes).map(row=>({...row,waypoints:rows(row.waypoints).map(point).filter(Boolean),next:point(row.next)}))
  };
}

export function terrainHydrator(){
  let terrain=null;
  return frame=>{
    const map=frame?.map;if(!map)return null;
    if(!map.terrainKey)return frame;
    const key=JSON.stringify([frame.boot,frame.runId,map.stage,map.navigationRevision,map.bounds,map.terrainKey]);
    if(Array.isArray(map.covers))terrain={key,covers:map.covers};
    if(terrain?.key!==key)return null;
    return {...frame,map:{...map,covers:terrain.covers}};
  };
}
/* The iframe occupies the untransformed slot. Only its clipped contents zoom. */
export function surfacePlacement(viewport,ancestors=[]){
  let box={x:viewport.x,y:viewport.y,width:viewport.width,height:viewport.height},clip={...box};
  const intersect=(a,b)=>{const x=Math.max(a.x,b.x),y=Math.max(a.y,b.y);return {x,y,width:Math.max(0,Math.min(a.x+a.width,b.x+b.width)-x),height:Math.max(0,Math.min(a.y+a.height,b.y+b.height)-y)};};
  for(const f of ancestors){
    const sx=f.width/f.viewportWidth,sy=f.height/f.viewportHeight;
    const map=r=>({x:f.x+r.x*sx,y:f.y+r.y*sy,width:r.width*sx,height:r.height*sy});
    box=map(box);clip=intersect(map(clip),f);
  }
  const insets=[Math.max(0,clip.y-box.y),Math.max(0,box.x+box.width-clip.x-clip.width),Math.max(0,box.y+box.height-clip.y-clip.height),Math.max(0,clip.x-box.x)];
  return {box,clip,clipPath:'inset('+insets.map(v=>v+'px').join(' ')+')'};
}
export function webSurface(owner){
  const top=window.top;
  if(!top.__deskfrontWebSurface){
    const doc=top.document,frame=doc.createElement('iframe'),layer=doc.createElement('div');
    frame.title='桌面前线 · Godot Web 实时游戏';frame.allow='autoplay; fullscreen';frame.allowFullscreen=true;
    // Keep the engine viewport stable while scrolling. Only the outer crop moves.
    layer.dataset.webSurface='';
    layer.style.cssText='position:fixed;left:0;top:0;z-index:20;overflow:hidden;visibility:hidden;contain:layout paint;';
    frame.style.cssText='position:absolute;left:0;top:0;border:0;background:#0b140e;';
    layer.append(frame);doc.body.append(layer);
    const host={frame,layer,url:'',owner:null,loaded:false},hydrate=terrainHydrator();
    top.addEventListener('message',event=>{
      if(event.source!==frame.contentWindow||event.origin!==top.location.origin||event.data?.type!=='deskfront-web-render')return;
      const value=event.data.frame,url=new URL(host.url||top.location.href);
      if(!value||value.jobId!==url.pathname.split('/')[2]||value.instanceId!==url.searchParams.get('instance_id'))return;
      if(!Number.isFinite(value.tick)||!Number.isFinite(value.time)||value.map?.runId!==value.runId||value.map?.time!==value.time)return;
      if(host.lastFrame?.boot===value.boot&&host.lastFrame.tick>value.tick)return;
      const hydrated=hydrate(value);if(!hydrated)return;
      const projected={...hydrated,map:projectWebMap(hydrated.map)};
      host.lastFrame=projected;
      const current=host.owner;if(current?.active)current.canvas.dispatchEvent(new current.canvas.ownerDocument.defaultView.CustomEvent('deskfront-web-frame',{detail:projected}));
    });
    frame.addEventListener('load',()=>{host.loaded=true;host.owner?.notify('ready');});
    let lastTransform='';
    const transform=(value)=>{
      if(value===lastTransform)return;
      // The player owns its clipping stage. Zoom never resizes Godot's window.
      frame.contentWindow?.postMessage({type:'deskfront-web-view',transform:value},top.location.origin);lastTransform=value;
    };
    frame.addEventListener('load',()=>{lastTransform='';});
    const style=(element,values)=>{
      for(const [key,value] of Object.entries(values))if(element.style[key]!==value)element.style[key]=value;
    };
    const position=()=>{
      const current=host.owner;
      if(!current?.active||!current.canvas.isConnected){style(layer,{visibility:'hidden'});return;}
      if(doc.fullscreenElement===layer||doc.fullscreenElement===frame){style(layer,{visibility:'visible',width:'100%',height:'100%',transform:'none'});style(frame,{width:'100%',height:'100%',transform:'none'});transform('none');return;}
      const viewport=current.viewport??current.canvas.parentElement;
      const r=viewport.getBoundingClientRect(),ancestors=[];
      let win=current.canvas.ownerDocument.defaultView;
      while(win!==top){
        const element=win.frameElement,outer=element.getBoundingClientRect();
        ancestors.push({x:outer.left+element.clientLeft,y:outer.top+element.clientTop,width:element.clientWidth,height:element.clientHeight,viewportWidth:win.innerWidth,viewportHeight:win.innerHeight});win=win.parent;
      }
      // Also crop to the top window. Offscreen slots must not cover other content.
      ancestors.push({x:0,y:0,width:top.innerWidth,height:top.innerHeight,viewportWidth:top.innerWidth,viewportHeight:top.innerHeight});
      const {box,clip}=surfacePlacement({x:r.left,y:r.top,width:r.width,height:r.height},ancestors);
      if(box.width<2||box.height<2){style(layer,{visibility:'hidden'});return;}
      // Width and height only change on a real slot resize, never because of scroll clipping.
      style(frame,{width:box.width+'px',height:box.height+'px',transform:`translate(${box.x-clip.x}px, ${box.y-clip.y}px)`});
      style(layer,{width:clip.width+'px',height:clip.height+'px',transform:`translate(${clip.x}px, ${clip.y}px)`,visibility:current.present===false||clip.width<1||clip.height<1?'hidden':'visible'});
      transform(current.canvas.style.transform||'none');
    };
    // Paint-aligned tracking avoids the old 60 ms timer jumping behind scroll.
    const tick=()=>{position();top.requestAnimationFrame(tick);};
    top.requestAnimationFrame(tick);
    host.position=position;top.__deskfrontWebSurface=host;
  }
  const host=top.__deskfrontWebSurface;
  return {
    connect(url){
      if(!url.startsWith('/play/'))throw Error('invalid_web_game_url');
      const absolute=new URL(url,location.origin).href;
      host.owner=owner;
      if(host.url!==absolute){host.loaded=false;host.lastFrame=null;host.url=absolute;host.frame.src=absolute;}
      owner.canvas.hidden=false;owner.canvas.style.opacity='0';owner.canvas.style.pointerEvents='none';
      owner.hasFrame=host.loaded;owner.notify(host.loaded?'ready':'connecting');host.position();
    },
    pause(){if(host.owner===owner){host.owner=null;host.layer.style.visibility='hidden';}}
  };
}
export function fullscreenWebGame(){
  const host=window.top.__deskfrontWebSurface;
  if(!host?.owner?.active)return false;
  void host.layer.requestFullscreen().catch(()=>{});return true;
}
