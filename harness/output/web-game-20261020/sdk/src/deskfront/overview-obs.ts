import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { WebSocket } from 'undici';

/** Existing, explicitly bound OBS source only. Never starts/stops recording. */
export async function readOverviewPreview(sourceName: string): Promise<Buffer> {
  const settings = JSON.parse((await readFile(join(process.env.APPDATA ?? '', 'obs-studio/plugin_config/obs-websocket/config.json'), 'utf8')).replace(/^\uFEFF/, ''));
  if (!settings.server_enabled || !Number.isInteger(settings.server_port)) throw Error('preview_unavailable');
  const hash = (v: string) => createHash('sha256').update(v).digest('base64');
  return new Promise((resolve, reject) => {
    const socket = new WebSocket('ws://127.0.0.1:' + settings.server_port);
    const timer = setTimeout(() => finish(Error('preview_timeout')), 4500);
    let done = false;
    function finish(error?: Error, image?: Buffer) {
      if (done) return; done = true; clearTimeout(timer); socket.close();
      if (error) reject(error); else resolve(image!);
    }
    socket.addEventListener('error', () => finish(Error('preview_unavailable')));
    socket.addEventListener('message', event => {
      try {
        const packet = JSON.parse(String(event.data));
        if (packet.op === 0) {
          const authentication = packet.d.authentication;
          socket.send(JSON.stringify({op:1,d:{rpcVersion:1,eventSubscriptions:0,
            ...(authentication ? {authentication:hash(hash(String(settings.server_password ?? '') + authentication.salt) + authentication.challenge)} : {})}}));
        } else if (packet.op === 2) socket.send(JSON.stringify({op:6,d:{requestType:'GetSourceScreenshot',requestId:'overview-preview',
          requestData:{sourceName,imageFormat:'png',imageWidth:1280,imageHeight:720}}}));
        else if (packet.op === 7) {
          const image = packet.d.responseData?.imageData;
          if (!packet.d.requestStatus?.result || typeof image !== 'string' || !image.startsWith('data:image/png;base64,') || image.length > 6000000)
            finish(Error('preview_unavailable'));
          else finish(undefined, Buffer.from(image.split(',')[1]!, 'base64'));
        }
      } catch { finish(Error('preview_unavailable')); }
    });
  });
}
