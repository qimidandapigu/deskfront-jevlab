import { createReadStream } from 'node:fs';
import { readFile, readdir, stat } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { directorView, applyDirectorRecord } from '../deskfront/director-view.js';
import { directorConsolePage } from '../deskfront/director-console.js';
import { directorAssemblyPage } from '../deskfront/director-assembly-console.js';
import { deskfrontSessionStatus } from '../deskfront/session-status.js';

export function createDirectorRoutes(deps: {
  logDir: string; live: () => { id: string; status: string; gameId: string }[];
  state: (id: string) => any;
}) {
  const cache = new Map<string, { stamp: number; loadedAt: number; facts: any }>();
  const valid = /^deskfront-[a-zA-Z0-9-]+$/;
  return async (req: { method?: string; headers?: { range?: string } }, url: URL, send: (code: number, body: string | Buffer, type?: string, headers?: Record<string,string>) => void) => {
    if (req.method !== 'GET') return false;
    if (url.pathname.startsWith('/api/deskfront/runtime-status/')) {
      const id = url.pathname.slice('/api/deskfront/runtime-status/'.length);
      const json = (code: number, value: unknown) => send(code, JSON.stringify(value), 'application/json');
      if (!valid.test(id)) { json(400, { error: 'invalid_session_id' }); return true; }
      if (!deps.live().some(row => row.gameId === 'deskfront' && row.id === id)) {
        json(404, { error: 'session_not_found' }); return true;
      }
      // Poll only the in-memory session. Director history can be large and is
      // deliberately not involved in the cheap runtime-status path.
      try {
        const status = deskfrontSessionStatus(id, deps.state(id));
        if (status) json(200, status);
        else json(503, { error: 'runtime_status_unavailable' });
      } catch {
        json(503, { error: 'runtime_status_unavailable' });
      }
      return true;
    }
    const asset = /^\/director-assets\/([a-z0-9_-]+\.png|level-[a-z0-9-]+-projection\.json|assembly-[a-z0-9-]+\.(?:json|mp4)|catalog\.json)$/.exec(url.pathname);
    if (asset) {
      const body = await readFile(new URL('../deskfront/director-assets/' + asset[1], import.meta.url)).catch(() => null);
      if (!body) send(404, 'Preview unavailable', 'text/plain');
      else if(asset[1]!.endsWith('.mp4')) {
        const range = req.headers?.range;
        if(range){
          const match=/^bytes=(\d*)-(\d*)$/.exec(range);
          const start=match?.[1]?Number(match[1]):Math.max(0,body.length-Number(match?.[2]));
          const end=match?.[1]?(match[2]?Math.min(Number(match[2]),body.length-1):body.length-1):body.length-1;
          if(!match||(!match[1]&&!match[2])||!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start<0||start>=body.length||end<start){
            send(416,'','video/mp4',{'Content-Range':'bytes */'+body.length,'Accept-Ranges':'bytes'});
          }else send(206,body.subarray(start,end+1),'video/mp4',{'Content-Range':`bytes ${start}-${end}/${body.length}`,'Content-Length':String(end-start+1),'Accept-Ranges':'bytes'});
        }else send(200,body,'video/mp4',{'Content-Length':String(body.length),'Accept-Ranges':'bytes'});
      }
      else send(200, body, asset[1]!.endsWith('.png') ? 'image/png' : 'application/json; charset=utf-8');
      return true;
    }
    if (url.pathname === '/runtime/deskfront/director') { send(200, url.searchParams.get('view')==='records'?directorConsolePage():directorAssemblyPage()); return true; }
    if (!url.pathname.startsWith('/api/deskfront/director/')) return false;
    const key = url.pathname.slice('/api/deskfront/director/'.length);
    const json = (code: number, value: unknown) => send(code, JSON.stringify(value), 'application/json');
    const active = deps.live().filter(x => x.gameId === 'deskfront');
    if (key === 'sessions') {
      const names = (await readdir(deps.logDir).catch(() => [] as string[])).filter(x => x.endsWith('.jsonl') && valid.test(x.slice(0,-6)));
      const files = await Promise.all(names.map(async name => ({ id: name.slice(0,-6), modified: (await stat(resolve(deps.logDir,name)).catch(() => null))?.mtimeMs || 0 })));
      const ids = new Set(active.map(x => x.id));
      json(200, { sessions: [...active.map(x => ({ id:x.id, status:x.status, mode:x.status==='done'?'ended':'live' })), ...files.sort((a,b)=>b.modified-a.modified).filter(x=>!ids.has(x.id)).slice(0,30).map(x=>({...x,mode:'recording',status:'recorded'}))] });
      return true;
    }
    if (!valid.test(key)) { json(400,{error:'无效的会话编号'}); return true; }
    const liveState = active.some(x => x.id === key) ? deps.state(key) : null;
    const present = (facts: any) => {
      const current = liveState?.payload?.game?.worldDirector;
      const merged = liveState ? {...facts,...current} : facts;
      // The native director's observations is a sample count, whereas the log
      // projection uses that key for request-bound snapshots. Keep the latter;
      // substituting latest_observation would rewrite historical evidence.
      if (liveState && typeof current?.observations === 'number') merged.observations = facts.observations;
      return directorView(merged,
        {id:key,mode:liveState ? (liveState.status==='done'?'ended':'live') : 'recording',status:liveState?.status || 'recorded'});
    };
    const path=resolve(deps.logDir,key+'.jsonl'), info=await stat(path).catch(()=>null);
    if (!info) { if(liveState)json(200,present({}));else json(404,{error:'没有找到这局记录，请选择其他会话'}); return true; }
    if (info.size>200_000_000) { json(413,{error:'记录过大，请从运行中的会话查看导演状态'}); return true; }
    // Live snapshots stay current; historical enrichment need not rescan a large
    // append-only battle log on every 2.5-second UI poll.
    const cached = cache.get(key);
    if (cached && (cached.stamp === info.mtimeMs || (liveState && Date.now()-cached.loadedAt<10_000))) { json(200,present(cached.facts)); return true; }
    const d: any = {}, input=createReadStream(path,{encoding:'utf8'}), lines=createInterface({input,crlfDelay:Infinity});
    try { for await (const line of lines) {
      if (!line.includes('"world-') || line.length>4_000_000) continue;
      try { const v=JSON.parse(line); applyDirectorRecord(d,v.record||v); } catch { /* A live writer may leave a partial line. */ }
    } } finally { lines.close(); input.destroy(); }
    if(cache.size>=12)cache.delete(cache.keys().next().value!);
    cache.set(key,{stamp:info.mtimeMs,loadedAt:Date.now(),facts:d});json(200,present(d));return true;
  };
}
