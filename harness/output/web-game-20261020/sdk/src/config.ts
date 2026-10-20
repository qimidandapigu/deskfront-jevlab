import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { createSystemOne } from './systemone/index.js';

export interface JevConfig {
  provider: 'typesafe' | 'openrouter';
  apiKey: string;
  model?: string;
}

export interface DeepSeekConfig {
  provider: 'deepseek' | 'ark' | 'openrouter';
  apiKey: string;
  model?: string;
  /** Provider request options; temperature:null omits the sampling parameter. */
  extraBody?: Record<string, unknown>;
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
  const provider = slowModelProvider(chatUrl, env);
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
      provider,
      apiKey: provider === 'deepseek' ? '' : env['MODEL_API_KEY'] ?? '',
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

function slowModelProvider(chatUrl: string, env: NodeJS.ProcessEnv): DeepSeekConfig['provider'] {
  if (!chatUrl) return env['DEEPSEEK_API_KEY'] ? 'deepseek' : 'openrouter';
  const host = new URL(chatUrl).hostname;
  if (host === 'api.deepseek.com') return 'deepseek';
  if (host === 'volces.com' || host.endsWith('.volces.com')) return 'ark';
  if (host === 'openrouter.ai') return 'openrouter';
  throw new Error('未知慢脑接入地址；请显式配置 deepseek、ark 或 openrouter');
}

function slowModelEnv(ds: DeepSeekConfig, role: string, base: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  let chatUrl: string, defaultModel: string, defaults: Record<string, unknown>;
  switch (ds.provider) {
    case 'deepseek':
      chatUrl = 'https://api.deepseek.com/chat/completions';
      defaultModel = 'deepseek-flash';
      defaults = { thinking: { type: 'disabled' } };
      if (ds.extraBody && ('provider' in ds.extraBody || 'reasoning' in ds.extraBody)) {
        throw new Error('DeepSeek 官方配置不能包含 OpenRouter provider/reasoning 参数');
      }
      break;
    case 'ark':
      chatUrl = 'https://ark.cn-beijing.volces.com/api/v3/chat/completions';
      defaultModel = 'deepseek-v4-1-flash-260910';
      defaults = { thinking: { type: 'disabled' } };
      break;
    case 'openrouter':
      chatUrl = 'https://openrouter.ai/api/v1/chat/completions';
      defaultModel = 'deepseek/deepseek-chat-v3.1';
      defaults = role === 'analyst'
        ? { reasoning: { effort: 'none' }, provider: { require_parameters: true, sort: 'throughput' }, max_tokens: 3000 }
        : role === 'commentary'
          ? { reasoning: { effort: 'none' }, provider: { require_parameters: true, sort: 'throughput' } }
          : { provider: { require_parameters: true } };
      break;
    default:
      throw new Error('未知慢脑接入方式；请显式配置 deepseek、ark 或 openrouter');
  }
  // An official profile never inherits a generic MODEL/Ark/OpenRouter credential.
  const apiKey = ds.apiKey || (ds.provider === 'deepseek' ? base['DEEPSEEK_API_KEY'] : undefined);
  if (!apiKey) throw new Error(ds.provider === 'deepseek'
    ? 'DeepSeek 官方接口需要配置 DEEPSEEK_API_KEY 或该配置档的 API Key'
    : '请配置当前慢脑接入方式的 API Key');
  return { ...base, SYSTEMONE_BACKEND: 'deepseek', MODEL_API_KEY: apiKey,
    MODEL_CHAT_URL: chatUrl, MODEL_NAME: ds.model ?? defaultModel,
    MODEL_EXTRA_BODY: JSON.stringify({ ...defaults, ...ds.extraBody }) };
}

/** 按配置生成某个模型后端的 env，交给 createSystemOne 的注册表。 */
export function envForModel(config: ModelsConfig, name: string, base: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  if (name === 'analyst') {
    const ds = config.analyst;
    if (!ds || !ds.model) throw new Error('请配置独立的 analyst 分析模型；不会回退到打拳快速响应配置');
    return { ...slowModelEnv(ds, name, base), MODEL_ANALYSIS: '1' };
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
    return slowModelEnv(config.deepseek, name, base);
  }
  return { ...base, SYSTEMONE_BACKEND: name };
}
