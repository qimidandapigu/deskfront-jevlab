import {ViewportControls} from './generation-scene.js';
/* The right viewport is always same-session game media, never generated geometry. */
export function clockSamples(rows) {
  const samples=[];
  for(const r of Array.isArray(rows)?rows:[]){if(!Number.isFinite(r?.video)||!Number.isFinite(r?.game)||r.video<0||r.game<0)continue;
    const last=samples.at(-1);if(last&&(r.video<=last.video||r.game<last.game))continue;samples.push({video:r.video,game:r.game});}
  return samples;
}
export function mapClock(samples,value,from='game',to='video') {
  if(!Number.isFinite(value)||samples.length<2||value<samples[0][from]||value>samples.at(-1)[from])return null;
  const i=samples.findIndex(s=>s[from]>=value);if(i<0)return null;if(samples[i][from]===value||i===0)return samples[i][to];
  const a=samples[i-1],b=samples[i],span=b[from]-a[from];return span>0?a[to]+(b[to]-a[to])*(value-a[from])/span:b[to];
}
export function operationTime(events,operation) {
  return (events||[]).find(e=>e.kind==='deployment'&&e.data?.operationId===operation&&Number.isFinite(e.time))?.time??null;
}
// Resolve from receipts at or before this instant, including backward seeking.
export function deploymentAt(events,time) {
  if(!Number.isFinite(time))return null;
  return (events||[]).filter(e=>e.kind==='deployment'&&e.data?.accepted!==false&&typeof e.data?.operationId==='string'&&e.data.operationId&&Number.isFinite(e.time)&&e.time<=time)
    .reduce((last,e)=>!last||e.time>=last.time?e:last,null);
}
const fmt=value=>Number.isFinite(value)?Math.floor(value/60).toString().padStart(2,'0')+':'+Math.floor(value%60).toString().padStart(2,'0'):'—';
export class GenerationGame {
  constructor(onTimeline=()=>{}){
    this.onTimeline=onTimeline;this.surfaceActive=true;
    this.id='';this.operation='';this.stage=null;this.epoch=0;this.value=null;this.samples=[];this.timer=null;this.abort=null;this.mediaId='';this.seekKey='';this.previewSerial=0;
    this.$=id=>document.getElementById(id);this.video=this.$('game-video');this.image=this.$('game-preview');
    this.liveSurface=new LiveGameSurface(this.image,state=>{if(this.liveSurface.session!==this.id)return;if(this.liveSurface.hasFrame){this.controls?.setEnabled(true);this.image.hidden=true;this.$('game-empty').hidden=true;}if(state==='reconnecting'){this.$('game-status').textContent='画面重连中';this.note(this.liveSurface.hasFrame?'正在重连 · 保留同局上一帧。':'正在连接同局实时画面…');}else if(state==='ready'){this.$('game-status').textContent=['finished','stopped','failed'].includes(this.value?.beginner?.status)?'本局已结束':'同局实时画面';this.note('连续实时传帧 · 声音由游戏窗口播放。');}});
    this.$('game-play').onclick=()=>{if(this.video.paused)this.video.play().catch(()=>this.note('点击播放可继续观看。'));else this.video.pause();};
    this.$('game-sound').onclick=()=>{this.video.muted=!this.video.muted;this.update();};
    this.$('game-seek').oninput=()=>{this.video.pause();this.video.currentTime=Number(this.$('game-seek').value);this.update(true);};
    this.$('game-locate').onclick=()=>this.locate(true);
    this.controls=new ViewportControls({viewport:this.$('game-viewport'),prefix:'game-view-',fullscreen:this.$('game-player'),
      onChange:view=>{for(const media of [this.video,this.image,this.liveSurface.canvas])media.style.transform='translate('+view.x+'px,'+view.y+'px) scale('+view.scale+')';},
      contentSize:rect=>{const media=!this.liveSurface.canvas.hidden?this.liveSurface.canvas:this.video.hidden?this.image:this.video,w=media.videoWidth||media.naturalWidth||media.width,h=media.videoHeight||media.naturalHeight||media.height;
        if(!w||!h)return {width:rect.width,height:rect.height};const fit=Math.min(rect.width/w,rect.height/h);return {width:w*fit,height:h*fit};}});
    this.image.addEventListener('load',()=>this.controls.paint());
    this.video.addEventListener('loadedmetadata',()=>this.controls.paint());
    for(const key of ['loadedmetadata','timeupdate','seeked','play','pause','ended'])this.video.addEventListener(key,()=>{if(key==='loadedmetadata')this.locate(false);this.update(key==='timeupdate'||key==='seeked');});
    this.video.addEventListener('error',()=>{if(this.mediaId===this.id)this.empty('录像无法读取','这局录像暂不可用，右侧不会用几何示意替代。');});
    document.addEventListener('visibilitychange',()=>{if(document.hidden){clearTimeout(this.timer);this.video.pause();this.liveSurface.pause();}else if(this.surfaceActive&&this.value?.mode==='live')this.load();});
  }
  note(text){this.$('game-source').textContent=text;}
  empty(title,detail){this.controls.setEnabled(false);this.liveSurface.reset();this.video.pause();this.video.hidden=true;this.image.hidden=true;this.$('game-empty').hidden=false;this.$('game-empty-title').textContent=title;this.$('game-empty-copy').textContent=detail;this.$('game-status').textContent=title;for(const id of ['game-play','game-sound','game-seek','game-locate'])this.$(id).disabled=true;}
  bind(id,operation,stage,{locate=true}={}){
    this.stage=stage;
    if(this.id!==id){this.controls.reset();this.liveSurface.reset();this.id=id;this.operation=operation||'';this.epoch++;this.abort?.abort();clearTimeout(this.timer);this.previewSerial++;this.mediaId='';this.seekKey='';this.value=null;this.samples=[];this.video.pause();this.video.removeAttribute('src');this.video.load();this.image.removeAttribute('src');this.empty('读取同局游戏画面','只接入这一局的游戏录像或已绑定的实景。');this.note('');if(id)this.load();return;}
    if(this.operation!==operation){this.operation=operation||'';this.seekKey=locate?'':this.id+'|'+this.operation;if(locate)this.locate(true);}this.update();
  }
  setVisible(active){if(this.surfaceActive===active)return;this.surfaceActive=active;if(!active){clearTimeout(this.timer);this.abort?.abort();this.video.pause();this.liveSurface.pause();}else if(this.id&&(!this.value||this.value.mode==='live'))this.load();}
  async load(){
    if(!this.surfaceActive||document.hidden)return;
    clearTimeout(this.timer);this.abort?.abort();const request=new AbortController();this.abort=request;const epoch=this.epoch,id=this.id;
    try{const r=await fetch('/api/deskfront/overview/'+encodeURIComponent(id),{cache:'no-store',signal:request.signal});if(!r.ok)throw Error('同局游戏画面读取失败');const value=await r.json();if(epoch!==this.epoch||id!==this.id)return;if(value.id!==id)throw Error('游戏画面身份不匹配');this.value=value;this.samples=clockSamples(value.media?.sync);for(const key of ['game-play','game-sound','game-seek','game-locate'])this.$(key).hidden=!!value.beginner;
      if(value.mode==='live'){
        this.video.pause();this.video.hidden=true;
        if(value.liveFrameUrl){this.$('game-status').textContent=['running','starting'].includes(value.beginner?.status)?'同局实时画面':'本局已结束';this.liveSurface.connect(value.liveFrameUrl,id);this.controls.setEnabled(this.liveSurface.hasFrame);this.image.hidden=true;this.$('game-empty').hidden=this.liveSurface.hasFrame;if(!this.liveSurface.hasFrame){this.$('game-empty-title').textContent='正在连接游戏画面';this.$('game-empty-copy').textContent='等待本局首帧，不显示其他对局画面。';}this.note(['running','starting'].includes(value.beginner?.status)?'连续实时传帧 · 声音由游戏窗口播放。':'本局已结束 · 保留最后游戏画面。');}
        else if(value.previewAvailable){this.$('game-status').textContent=value.beginner?.status==='finished'?'本局已结束':'同局实时画面';this.note(value.frameSource==='native-viewport'?'游戏实时画面 · 声音由游戏窗口播放。':'本局绑定的 OBS 实景，完整画面仍在游戏窗口。');await this.refreshPreview(epoch);}
        else {this.empty('游戏在独立窗口运行','当前未绑定网页实景源。游戏画面接入后在这里显示。');this.note('同局实时状态 · 不以搭建预演或历史录像替代实景。');}
        if(value.beginner){this.$('game-clock').textContent='游戏时间';this.$('game-time').textContent=fmt(value.live?.gameTime);}
      }else if(value.media?.url===('/api/deskfront/overview/'+id+'/media')){
        this.liveSurface.reset();this.$('game-status').textContent='同局游戏录像';this.image.hidden=true;this.$('game-empty').hidden=true;this.video.hidden=false;this.controls.setEnabled(true);
        if(this.mediaId!==id){this.mediaId=id;this.video.src=value.media.url;this.video.load();}
        this.locate(false);this.update();
      }else {this.empty('没有关联的游戏录像','本局记录可以继续查看；右侧不使用其他关卡或拼装动画补画。');this.note('当前为历史记录；没有同局游戏画面。');}
    }catch(error){if(error.name!=='AbortError'&&epoch===this.epoch){if(this.liveSurface.url){this.$('game-status').textContent='状态同步重试';this.note(this.liveSurface.hasFrame?'状态暂未同步，保留同局画面并自动重试。':'正在连接同局实时画面…');}else{this.empty('游戏画面暂不可用',error.message+'，请刷新重试。');this.note('没有用几何预演替代游戏。');}}}
    finally{if(this.abort===request&&epoch===this.epoch&&this.value?.mode==='live'&&!document.hidden&&this.surfaceActive)this.timer=setTimeout(()=>this.load(),2500);}
  }
  async refreshPreview(epoch){
    const serial=++this.previewSerial,id=this.id;const img=new Image();img.src='/api/deskfront/overview/'+encodeURIComponent(id)+'/preview?t='+Date.now();
    try{await img.decode();if(epoch!==this.epoch||serial!==this.previewSerial||id!==this.id)return;this.image.src=img.src;this.image.hidden=false;this.$('game-empty').hidden=true;this.controls.setEnabled(true);}catch{if(epoch===this.epoch){if(this.image.naturalWidth&&!this.image.hidden)this.note('实景采样重试中 · 保留上一帧。');else this.empty('实景采样暂不可用','游戏仍在独立窗口运行；下一次同步会重试。');}}
  }
  locate(autoplay){
    if(this.value?.mode==='live'||!this.operation||this.mediaId!==this.id||!Number.isFinite(this.video.duration))return;
    const at=operationTime(this.value?.events,this.operation),position=mapClock(this.samples,at),key=this.id+'|'+this.operation;
    if(position===null){this.$('game-locate').disabled=true;this.note('本关缺少可对齐的游戏时钟；可播放同局录像，不推测关卡位置。');return;}
    this.$('game-locate').disabled=false;if(this.seekKey===key&&!autoplay)return;this.seekKey=key;this.video.currentTime=Math.min(this.video.duration,position);
    this.note('已按完成记录定位第'+(this.stage?.index??'—')+'关开场。左侧方案随录像切关，拼装可单独重播。');
    if(autoplay&&this.surfaceActive)this.video.play().catch(()=>this.note('已定位本关；点击播放观看游戏录像。'));
  }
  update(sync=false){
    const usable=!this.video.hidden&&Number.isFinite(this.video.duration)&&this.video.duration>0;
    this.$('game-play').disabled=!usable;this.$('game-sound').disabled=!usable;this.$('game-seek').disabled=!usable;
    this.$('game-play').textContent=this.video.paused?'播放':'暂停';this.$('game-sound').textContent=this.video.muted?'开启声音':'静音';
    if(!usable){this.$('game-time').textContent='—';return;}
    this.$('game-seek').max=String(this.video.duration);this.$('game-seek').value=String(this.video.currentTime);
    this.$('game-time').textContent=fmt(this.video.currentTime)+' / '+fmt(this.video.duration);
    const game=mapClock(this.samples,this.video.currentTime,'video','game');
    const level=deploymentAt(this.value?.events,game);
    if(sync&&this.value?.mode!=='live'&&this.mediaId===this.id)this.onTimeline({session:this.id,operation:level?.data.operationId??null,gameTime:game});
    const wanted=level?.data?.operationId===this.operation;
    if(sync&&wanted&&level)this.note('录像与第'+(level.data.level??this.stage?.index??'—')+'关方案同步；左侧可单独重播拼装。');
    this.$('game-clock').textContent=game===null?'录像时钟':('游戏 '+fmt(game)+(level?(wanted?' · 第'+(level.data.level??this.stage?.index??'—')+'关':' · 正在同步关卡'):''));
  }
}

/* Display only fully decoded, same-session JPEG frames. Transport failure and
 * visibility changes never clear the last valid pixels; a new session does. */
const headerEnd=bytes=>{for(let i=0;i<bytes.length-3;i++)if(bytes[i]===13&&bytes[i+1]===10&&bytes[i+2]===13&&bytes[i+3]===10)return i;return -1;};
export class LiveGameSurface {
  constructor(image,onState=()=>{}) {
    this.image=image;this.onState=onState;this.session='';this.url='';this.active=false;
    this.hasFrame=false;this.state='idle';this.serial=0;this.attempt=0;this.retry=null;this.source=null;this.frames=0;
    this.canvas=document.createElement('canvas');this.canvas.hidden=true;
    this.canvas.setAttribute('role','img');this.canvas.setAttribute('aria-label',image.alt||'同局实时游戏画面');this.canvas.dataset.liveGameSurface='';
    this.canvas.style.cssText='position:absolute;inset:0;display:block;width:100%;height:100%;object-fit:contain;background:transparent;';
    image.after(this.canvas);this.context=this.canvas.getContext('2d',{alpha:false});
  }
  notify(state){if(this.state!==state){this.state=state;this.onState(state);}}
  connect(url,session){
    if(this.session!==session||this.url!==url){this.reset();this.session=session;this.url=url;}
    this.image.hidden=true;this.active=true;if(!this.source&&!this.retry)this.open();
  }
  open(){
    if(!this.active||!this.url)return;
    const serial=++this.serial,controller=new AbortController();this.source=controller;
    if(!this.hasFrame)this.notify('connecting');
    void this.read(serial,controller);
  }
  async read(serial,controller){
    let reader;
    try{
      const response=await fetch(this.url+(this.url.includes('?')?'&':'?')+'connection='+serial,{cache:'no-store',signal:controller.signal});
      if(!response.ok||!response.body||!response.headers.get('content-type')?.includes('multipart/x-mixed-replace'))throw Error('live_stream_unavailable');
      reader=response.body.getReader();let pending=new Uint8Array(0);
      while(this.active&&serial===this.serial){
        const part=await reader.read();if(part.done)throw Error('live_stream_ended');
        const joined=new Uint8Array(pending.length+part.value.length);joined.set(pending);joined.set(part.value,pending.length);pending=joined;
        if(pending.length>8*1024*1024)throw Error('live_frame_too_large');
        let latest=null;
        for(;;){
          const end=headerEnd(pending);if(end<0){if(pending.length>16384)throw Error('invalid_live_header');break;}
          const header=new TextDecoder().decode(pending.subarray(0,end)),match=/content-length:\s*(\d+)/i.exec(header);
          const length=Number(match?.[1]);if(!Number.isSafeInteger(length)||length<4||length>4*1024*1024||!/content-type:\s*image\/jpeg/i.test(header))throw Error('invalid_live_frame');
          const begin=end+4;if(pending.length<begin+length)break;
          const bytes=pending.slice(begin,begin+length);pending=pending.slice(begin+length);
          if(bytes[0]===255&&bytes[1]===216&&bytes.at(-2)===255&&bytes.at(-1)===217)latest=bytes;
        }
        // Drop superseded frames already in the buffer, avoiding playback lag.
        if(latest){
          let bitmap;
          try{bitmap=await createImageBitmap(new Blob([latest],{type:'image/jpeg'}));
            if(!this.active||serial!==this.serial)continue;
            if(this.canvas.width!==bitmap.width||this.canvas.height!==bitmap.height){this.canvas.width=bitmap.width;this.canvas.height=bitmap.height;}
            this.context.drawImage(bitmap,0,0);this.frames++;this.hasFrame=true;this.canvas.hidden=false;this.attempt=0;this.notify('ready');
          }catch(error){if(controller.signal.aborted)throw error;/* Keep previous pixels if one frame cannot decode. */}
          finally{bitmap?.close();}
        }
      }
    }catch{
      if(serial!==this.serial||!this.active||controller.signal.aborted)return;
      this.source=null;this.notify('reconnecting');clearTimeout(this.retry);
      this.retry=setTimeout(()=>{this.retry=null;this.open();},Math.min(4000,300*2**Math.min(this.attempt++,4)));
    }finally{await reader?.cancel().catch(()=>{});}
  }
  pause(){this.active=false;this.serial++;clearTimeout(this.retry);this.retry=null;this.source?.abort();this.source=null;}
  reset(){this.pause();this.session='';this.url='';this.hasFrame=false;this.state='idle';this.attempt=0;this.frames=0;this.canvas.hidden=true;this.context.clearRect(0,0,this.canvas.width,this.canvas.height);}
}
