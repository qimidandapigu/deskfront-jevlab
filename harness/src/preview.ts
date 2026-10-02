// 离线体验入口：不读取密钥、不调用外部模型，适合界面验收与直接游玩。
import { startViewer } from './viewer/server.js';
import { createDefaultRegistry } from './games/index.js';
import { createMockSystemOne } from './systemone/mock.js';

const viewer = await startViewer({
  backend: createMockSystemOne(),
  backends: { names: ['mock'], defaultName: 'mock', create: () => createMockSystemOne() },
  registry: createDefaultRegistry(),
  port: Number(process.env['PREVIEW_PORT'] ?? 3778),
  logDir: 'logs/offline-preview',
});
console.log(`离线游戏体验：http://127.0.0.1:${viewer.port}（真人游玩 / 规则演示，无模型调用）`);
