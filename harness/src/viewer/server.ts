import { createDanmaku } from '../deskfront/danmaku.js';
import { createSessionService, SessionError, type BackendSource } from '../arena/sessions.js';
import { createDefaultRuntimeRegistry } from '../games/runtimes.js';
import { deskfrontPage } from '../deskfront/page.js';
import { battleFrame, synthesizeCommentary } from '../deskfront/commentary.js';
import { createCommentaryDirector } from '../deskfront/commentary-director.js';
import { appendFileSync, mkdirSync } from 'node:fs';
import type { RuntimeRegistry } from '../arena/runtime.js';
export type { BackendSource } from '../arena/sessions.js';
import { createEndlessHandler } from '../games/soldiers/endless-server.js';
import { createAntHandler } from '../games/ants/server.js';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import type { SystemOne } from '../systemone/types.js';
import type { GameRegistry } from '../arena/registry.js';
import type { RealtimeGame } from '../arena/plugin.js';
import type { TurnBasedGame } from '../arena/plugin.js';
import type { ModelsConfig } from '../config.js';
import { createDeskfrontOverlayRoutes } from './deskfront-routes.js';
import { handleConfigRoute } from './config-routes.js';
import { handleMatchRoute } from './match-routes.js';
import { handleStaticRoute } from './static-routes.js';
import { renderGamePage, renderHomePage, renderReplayPage, renderRuntimePage, type ExternalCatalogEntry } from './page-templates.js';


const require_ = createRequire(import.meta.url);
// kaplay 的 exports 未暴露 dist 子路径，先解析入口（dist/kaplay.cjs）再取同目录的 UMD 版本。
const KAPLAY_UMD = resolve(dirname(require_.resolve('kaplay')), 'kaplay.js');

export interface ViewerOptions {
  runtimes?: RuntimeRegistry;
  backend: SystemOne;
  backends?: BackendSource;
  registry: GameRegistry;
  port?: number;
  /** 监听地址，默认 127.0.0.1（本机工具，不暴露到局域网）。 */
  host?: string;
  logDir?: string;
  /** 可选：首页展示模型配置面板（key 选择、接入方式），保存时回调。 */
  config?: {
    get(): ModelsConfig;
    save(next: ModelsConfig): void;
    /** 用页面上填写（可能未保存）的配置试连模型，返回耗时或错误。 */
    test?(override: { target?: string; provider?: string; apiKey?: string; model?: string }): Promise<{ ok: boolean; ms?: number; error?: string }>;
  };
  /** AI 对局开始前的延迟毫秒（等页面加载），默认 3000。 */
  startDelayMs?: number;
  /** 回合制 AI 对局每回合间隔毫秒，默认 800。 */
  turnDelayMs?: number;
  /** 实时对局每帧实际 sleep 毫秒（测试加速用），默认 game.tickMs。 */
  tickSleepMs?: number;
}

export function startViewer(options: ViewerOptions): Promise<{ port: number; close(): Promise<void> }> {
  const { registry } = options;
  const sessions = createSessionService({ ...options, runtimes: options.runtimes ?? createDefaultRuntimeRegistry(), startDelayMs: options.startDelayMs ?? Number(process.env.VIEWER_START_DELAY_MS ?? 3000), humanIdleMs: Number(process.env.VIEWER_HUMAN_IDLE_MS ?? 180000) });
  const endless = createEndlessHandler(sessions);
  const ants = createAntHandler(options.backends);
  const matches = sessions.matches;
  const commentary = createCommentaryDirector({
    directory: id => resolve(options.logDir ?? 'logs', id),
    read(id) {
      const match = matches.get(id);
      return match?.gameId === 'deskfront' && match.runtime ? battleFrame(match.runtime.snapshot(), match.kind) : undefined;
    },
    backend() {
      if (!options.backends) throw new Error('commentary-model-unavailable');
      return options.backends.create('commentary');
    },
    speech: (text, signal) => synthesizeCommentary(text, process.env, signal),
    record(id, event) {
      try {
        const folder = resolve(options.logDir ?? 'logs', 'commentary');
        mkdirSync(folder, { recursive: true });
        appendFileSync(resolve(folder, id + '.jsonl'), JSON.stringify(event) + '\n');
      } catch { /* Observational logs must never interrupt gameplay. */ }
    },
  });

  const danmaku = createDanmaku({
    directory: id => resolve(options.logDir ?? 'logs', id),
    read(id) { const match = matches.get(id); return match?.gameId === 'deskfront' && match.runtime ? battleFrame(match.runtime.snapshot(), match.kind) : undefined; },
    backend() { if (!options.backends) throw new Error('danmaku-model-unavailable'); return options.backends.create('commentary'); },
    record(id, event) { try { const folder=resolve(options.logDir ?? 'logs','danmaku'); mkdirSync(folder,{recursive:true}); appendFileSync(resolve(folder,id+'.jsonl'),JSON.stringify(event)+'\n'); } catch {} },
  });
  const handleDeskfrontOverlay = createDeskfrontOverlayRoutes({ matches, danmaku, commentary });

  const server = createServer((req, res) => {
    const url = new URL(req.url ?? '/', 'http://localhost');
    const send = (status: number, body: string | Buffer, type = 'text/html; charset=utf-8') => {
      res.writeHead(status, { 'Content-Type': type }); res.end(body);
    };
    (async () => {
      if (await handleDeskfrontOverlay(req, res, url, send)) return;
      if (await ants.handle(req, res, url)) return;
      if (await endless.handle(req, res, url)) return;
      if (req.method === 'GET' && url.pathname === '/api/games') return send(200, JSON.stringify(sessions.catalog()), 'application/json');
      if (req.method === 'GET' && url.pathname === '/api/backends') return send(200, JSON.stringify({ names: options.backends?.names ?? [], defaultName: options.backends?.defaultName }), 'application/json');
      const runtimePage = /^\/runtime\/([\w-]+)$/.exec(url.pathname);
      if (runtimePage && req.method === 'GET') {
        const entry = sessions.catalog().find(g => g.id === runtimePage[1] && g.mode === 'external');
        if (!entry) return send(404, 'Unknown game', 'text/plain');
        if (entry.id === 'deskfront') return send(200, deskfrontPage());
        return send(200, renderRuntimePage(entry as ExternalCatalogEntry, options.backends));
      }
      if (req.method === 'GET' && url.pathname === '/favicon.ico') {
        return send(200, Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="22" fill="#0b0e14" stroke="#2ee6a8" stroke-width="5"/><text x="50" y="70" font-size="52" text-anchor="middle" fill="#2ee6a8" font-family="monospace" font-weight="bold">QP</text></svg>'), 'image/svg+xml');
      }
      if (req.method === 'GET' && url.pathname === '/') {
        return send(200, renderHomePage({ registry, catalog: sessions.catalog(), matches, config: options.config, backends: options.backends, url }));
      }
      if (await handleConfigRoute(req, res, url, options, send)) return;
      const replayPage = /^\/replay\/([\w-]+)$/.exec(url.pathname);
      if (req.method === 'GET' && replayPage) {
        const match = matches.get(replayPage[1]!);
        if (!match) return send(404, '<!doctype html><meta charset="utf-8"><p>对局不存在或已被清理（服务器重启后回放不保留）。<a href="/">返回首页</a></p>');
        return send(200, renderReplayPage(replayPage[1]!, match, registry));
      }
      const preview = /^\/api\/preview\/([\w-]+)$/.exec(url.pathname);
      if (req.method === 'GET' && preview) {
        const plugin = registry.get(preview[1]!);
        const game = plugin.create(url.searchParams.get('variant') ?? undefined);
        const observation = plugin.mode === 'turn'
          ? (game as TurnBasedGame<unknown>).observe(game.initialState(), { turn: 0, recent: [], feedback: null })
          : (game as RealtimeGame<unknown>).observe(game.initialState());
        return send(200, JSON.stringify({ observation }), 'application/json');
      }
      const gamePage = /^\/game\/([\w-]+)$/.exec(url.pathname);
      if (req.method === 'GET' && gamePage) {
        return send(200, renderGamePage(gamePage[1]!, registry, options.backends));
      }
      if (await handleStaticRoute(req, res, url, { registry, kaplayUmd: KAPLAY_UMD }, send)) return;
      if (await handleMatchRoute(req, res, url, sessions, send)) return;
      send(404, 'not found', 'text/plain');
    })().catch(error => send(error instanceof SessionError ? error.status : 500, JSON.stringify({ error: error instanceof Error ? error.message : String(error) }), 'application/json'));
  });

  return new Promise((resolve, reject) => {
    // 端口占用等 listen 失败要拒掉 promise，否则调用方永远等不到 resolve
    server.once('error', reject);
    server.listen(options.port ?? 3777, options.host ?? '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address ? address.port : (options.port ?? 3777);
      resolve({ port, close: async () => { danmaku.close(); commentary.close(); ants.close(); await sessions.close(); await new Promise<void>(r => server.close(() => r())); } });
    });
  });
}
