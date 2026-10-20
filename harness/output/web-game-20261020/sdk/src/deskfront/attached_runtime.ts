import { fileURLToPath } from 'node:url';
import { createExternalGameRuntime } from '../external/runtime.js';
import { GAME_PROTOCOL } from '../external/protocol.js';

/** Public binary-only integration; no source game path or Godot installation. */
export function createAttachedDeskfrontRuntime(python = 'python') {
  return createExternalGameRuntime({
    protocol: GAME_PROTOCOL, id: 'deskfront', name: 'Deskfront 桌面前线',
    description: '独立游戏发行包＋外部 AI Harness；默认本地关卡，私有生成模块可选。',
    command: [python, fileURLToPath(new URL('./attached_entry.py', import.meta.url))],
    maxSessions: 1, decisionRoles: { commander: 'deepseek', experience_analyst: 'analyst' },
    variants: [{ id: 'attached', name: '接入独立发行包' }],
    options: {
      connectionFile: { type: 'string', default: '' },
      attachedWorldGeneration: { type: 'boolean', default: false },
      levelGeneratorModule: { type: 'string', default: '' },
      openingRescueRule: { type: 'boolean', default: false },
      secondStageTankRule: { type: 'boolean', default: false },
      storyMode: { type: 'string', enum: ['normal', 'story'], default: 'normal' },
      storyPrompt: { type: 'string', default: '' },
      teamRequestLimit: { type: 'integer', min: 1, max: 10000 },
      greenController: { type: 'string', enum: ['harness', 'local'], default: 'harness' },
      redController: { type: 'string', enum: ['harness', 'local'], default: 'harness' },
    },
    capabilities: { human: true, ai: true, seed: false },
  });
}
