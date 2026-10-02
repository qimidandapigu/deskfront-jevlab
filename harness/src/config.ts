import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { createSystemOne } from './systemone/index.js';

export interface JevConfig {
  provider: 'typesafe' | 'openrouter';
  apiKey: string;
  model?: string;
}

export interface DeepSeekConfig {
  provider: 'ark' | 'openrouter';
  apiKey: string;
  model?: string;
}

export interface ModelsConfig {
  defaultModel: 'jev' | 'deepseek';
  jev: JevConfig;
  deepseek: DeepSeekConfig;
  analyst?: DeepSeekConfig;
}

const CONFIG_FILE = 'config.local.json';

export function loadEnvironment(path = '.env'): void {
  if (!existsSync(path)) return;
  for (const line of readFileSync(path, 'utf8').split('\n')) {
    const match = /^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/.exec(line);
    if (match && !line.trim().startsWith('#') && process.env[match[1]!] === undefined) {
      process.env[match[1]!] = match[2]!.replace(/^["']|["']$/g, '');
    }
  }
}

/** One model resolver for the web, CLI, benchmark and external adapters. */
export function createConfiguredBackend(name: string, env: NodeJS.ProcessEnv = process.env, config?: ModelsConfig) {
  if (name === 'mock') return createSystemOne({ SYSTEMONE_BACKEND: 'mock' });
  const saved = config ?? (existsSync(CONFIG_FILE) ? loadModelsConfig(env) : undefined);
  return createSystemOne(saved ? envForModel(saved, name, env) : { ...env, SYSTEMONE_BACKEND: name });
}

export function defaultBackendName(env: NodeJS.ProcessEnv = process.env): string {
  return env.SYSTEMONE_BACKEND ?? (existsSync(CONFIG_FILE) ? loadModelsConfig(env).defaultModel : 'mock');
}

/** 从 .env 推导初始配置（无配置文件时的回退）。 */
function fromEnv(env: NodeJS.ProcessEnv): ModelsConfig {
  const chatUrl = env['MODEL_CHAT_URL'] ?? '';
  return {
    defaultModel: env['SYSTEMONE_BACKEND'] === 'deepseek' ? 'deepseek' : 'jev',
    jev: {
      provider: env['TYPESAFE_API_KEY'] ? 'typesafe' : 'openrouter',
      apiKey: env['TYPESAFE_API_KEY'] ?? env['OPENROUTER_API_KEY'] ?? '',
      ...(env['TYPESAFE_API_KEY']
        ? { ...(env['TYPESAFE_DEFAULT_MODEL'] ? { model: env['TYPESAFE_DEFAULT_MODEL'] } : {}) }
        : { ...(env['OPENROUTER_MODEL'] ? { model: env['OPENROUTER_MODEL'] } : {}) }),
    },
    deepseek: {
      provider: chatUrl.includes('volces.com') ? 'ark' : 'openrouter',
      apiKey: env['MODEL_API_KEY'] ?? '',
      ...(env['MODEL_NAME'] ? { model: env['MODEL_NAME'] } : {}),
    },
  };
}

export function loadModelsConfig(env: NodeJS.ProcessEnv): ModelsConfig {
  if (existsSync(CONFIG_FILE)) {
    try {
      return JSON.parse(readFileSync(CONFIG_FILE, 'utf8')) as ModelsConfig;
    } catch { /* 配置文件损坏时回退到 env */ }
  }
  return fromEnv(env);
}

export function saveModelsConfig(config: ModelsConfig): void {
  writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2) + '\n');
}

/** 按配置生成某个模型后端的 env，交给 createSystemOne 的注册表。 */
export function envForModel(config: ModelsConfig, name: string, base: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  if (name === 'analyst') {
    const ds = config.analyst;
    if (!ds?.apiKey || !ds.model) throw new Error('请配置独立的 analyst 分析模型；不会回退到打拳快速响应配置');
    return { ...base, SYSTEMONE_BACKEND: 'deepseek', MODEL_API_KEY: ds.apiKey,
      MODEL_CHAT_URL: ds.provider === 'ark' ? 'https://ark.cn-beijing.volces.com/api/v3/chat/completions' : 'https://openrouter.ai/api/v1/chat/completions', MODEL_NAME: ds.model,
      MODEL_EXTRA_BODY: ds.provider === 'ark' ? '{"thinking":{"type":"enabled"}}'
        : '{"reasoning":{"effort":"none"},"provider":{"require_parameters":true,"sort":"throughput"},"max_tokens":3000}',
      MODEL_ANALYSIS: '1' };
  }
  if (name === 'jev') {
    const jev = config.jev;
    if (jev.provider === 'openrouter') {
      return {
        ...base,
        SYSTEMONE_BACKEND: 'openrouter',
        OPENROUTER_API_KEY: jev.apiKey,
        ...(jev.model ? { OPENROUTER_MODEL: jev.model } : {}),
      };
    }
    return {
      ...base,
      SYSTEMONE_BACKEND: 'jev',
      TYPESAFE_API_KEY: jev.apiKey,
      ...(jev.model ? { TYPESAFE_DEFAULT_MODEL: jev.model } : {}),
    };
  }
  if (name === 'deepseek' || name === 'commentary') {
    const ds = config.deepseek;
    const ark = ds.provider === 'ark';
    return {
      ...base,
      SYSTEMONE_BACKEND: 'deepseek',
      MODEL_API_KEY: ds.apiKey,
      MODEL_CHAT_URL: ark
        ? 'https://ark.cn-beijing.volces.com/api/v3/chat/completions'
        : 'https://openrouter.ai/api/v1/chat/completions',
      MODEL_NAME: ds.model ?? (ark ? 'deepseek-v4-1-flash-260910' : 'deepseek/deepseek-chat-v3.1'),
      MODEL_EXTRA_BODY: ark ? '{"thinking":{"type":"disabled"}}' : name === 'commentary'
        ? '{"reasoning":{"effort":"none"},"provider":{"require_parameters":true,"sort":"throughput"}}'
        : '{"provider":{"require_parameters":true}}',
    };
  }
  return { ...base, SYSTEMONE_BACKEND: name };
}
