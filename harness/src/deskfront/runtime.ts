import { fileURLToPath } from 'node:url';
import { createExternalGameRuntime } from '../external/runtime.js';
import { GAME_PROTOCOL } from '../external/protocol.js';

/** Deskfront contributes only its manifest and engine adapter; the host is generic. */
export function createDeskfrontRuntime(host: { root: string; python: string; godot: string }) {
  return createExternalGameRuntime({
    protocol: GAME_PROTOCOL, id: 'deskfront', name: 'Deskfront 桌面前线',
    description: '当前版为无尽推进：火山 DeepSeek 指挥、JEV 小队执行、Godot 权威结算；human 能力目前仅提供暂停/结束控制，玩家战术指挥仍在后续闭环。',
    command: [host.python, fileURLToPath(new URL('./host.py', import.meta.url)), '--root', host.root, '--godot', host.godot],
    cwd: host.root, maxSessions: 1,
    // Live tactical command uses the fast DeepSeek route. WorldDirector's
    // experience analysis is the only caller that needs the analyst route.
    decisionRoles: { commander: 'deepseek', experience_analyst: 'analyst' },
    // The public product catalog exposes one current Deskfront experience.
    // Older duel/tactics variants remain callable by regression tests and
    // direct CLI/API requests, but are intentionally not advertised as peer
    // product modes with different capability sets.
    variants: [{ id: 'infinite', name: '无尽推进（当前版）' }, { id: 'infinite-headless', name: '无尽推进（后台回归）' }],
    options: { teamRequestLimit: { type: 'integer', min: 1, max: 10000, description: '无尽推进每队独立请求额度；不填写则沿用运行上限' }, redController: { type: 'string', enum: ['harness', 'local'], default: 'harness', description: '当前版红方默认由 Harness 指挥与执行；local 仅作回归对照' }, greenController: { type: 'string', enum: ['harness', 'local'], default: 'harness', description: '当前版绿方默认由 Harness 指挥与执行；local 仅作回归对照' }, secondStageTankShowcase: { type: 'boolean', default: false, description: '仅演示/回归：首关生成后跳过交火，第二关由 JEV 按坦克支援搭建并在坦克入场后暂停' }, secondStageTankRule: { type: 'boolean', default: true, description: '只影响第二关：是否生成坦克支援；默认开启，关闭后第二关不生成坦克' } },
    capabilities: { human: true, ai: true, seed: false },
  });
}
