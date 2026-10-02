import { createRequestManager } from './systemone/request.js';
import { createSystemOne } from './systemone/index.js';
import type { SystemOne } from './systemone/types.js';
import { createDefaultRegistry } from './games/index.js';
import { startViewer } from './viewer/server.js';
import { loadEnvironment, createConfiguredBackend, envForModel, loadModelsConfig, saveModelsConfig } from './config.js';


loadEnvironment();
const port = Number(process.env['VIEWER_PORT'] ?? 3777);

// 模型配置：首页可在线修改（key / 接入方式 / 默认模型），持久化到 config.local.json，
// 未配置时回退 .env。backendNames 即观测站可对比的模型，前端显示为模型名。
let modelsConfig = loadModelsConfig(process.env);
let defaultBackendName: string = modelsConfig.defaultModel;
function currentModelsConfig() {
  // Several local viewer ports can serve the same Harness checkout. Read the
  // shared saved settings when starting a new match, not just at process boot.
  modelsConfig = loadModelsConfig(process.env);
  return modelsConfig;
}
function createBackend(name: string): SystemOne {
  // Snapshot current configuration for each match; usage lives in per-request responses.
  return createConfiguredBackend(name, process.env, currentModelsConfig());
}

// fresh clone 没有任何 API key 时也要能起站：默认后端回退 mock，
// 新局使用最新配置创建独立后端。
function createDefaultBackend(): SystemOne {
  try {
    return createBackend(modelsConfig.defaultModel);
  } catch (error) {
    console.warn(`默认后端 ${modelsConfig.defaultModel} 不可用（${error instanceof Error ? error.message : String(error)}），回退 mock；在首页配置 API Key 后恢复`);
    const fallback = createSystemOne({ SYSTEMONE_BACKEND: 'mock' });
    // 离线规则不能挂在真实模型名称下，避免把演示结果误认为模型实测。
    defaultBackendName = 'mock';
    return fallback;
  }
}

startViewer({
  backend: createDefaultBackend(),
  backends: {
    names: ['jev', 'deepseek', 'mock'],
    defaultName: defaultBackendName,
    create: createBackend,
  },
  config: {
    get: currentModelsConfig,
    save(next) {
      modelsConfig = next;
      saveModelsConfig(next);
    },
    async test(override) {
      const target = override.target === 'deepseek' || override.target === 'analyst' ? override.target : 'jev';
      const current = currentModelsConfig()[target] ?? { provider: 'ark', apiKey: '', model: '' };
      const selected = {
          ...current,
          ...(override.provider ? { provider: override.provider } : {}),
          // 页面上留空 key 表示用已保存的
          apiKey: override.apiKey ? override.apiKey : current.apiKey,
          ...(override.model ? { model: override.model } : {}),
      };
      const merged = { ...modelsConfig, [target]: selected } as typeof modelsConfig;
      if (!selected.apiKey) return { ok: false, error: '未配置 API Key' };
      try {
        const backend = createSystemOne(envForModel(merged, target, process.env));
        const started = Date.now();
        await createRequestManager(backend).request({ ping: true }, {
          ping: { type: 'noul', instructions: '陈述「1 加 1 等于 2」是否为真' },
        });
        return { ok: true, ms: Date.now() - started };
      } catch (error) {
        return { ok: false, error: error instanceof Error ? error.message : String(error) };
      }
    },
  },
  registry: createDefaultRegistry(),
  port,
}).then(s => {
  console.log(`观测站: http://127.0.0.1:${s.port}  (backend=${defaultBackendName})`);
}).catch(error => {
  console.error('观测站启动失败:', error);
  process.exitCode = 1;
});
