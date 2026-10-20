import type { BattleFrame } from './commentary.js';
import { presenterStageContext } from './presenter-context.js';

type Row = Record<string, any>;
const row = (value: unknown): Row => value && typeof value === 'object' && !Array.isArray(value) ? value as Row : {};
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.map(row) : [];
const pick = (value: unknown, keys: string[]): Row => {
  const source = row(value), result: Row = {};
  for (const key of keys) {
    const item = source[key];
    if (typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean') result[key] = item;
  }
  return result;
};
const point = (value: unknown) => Array.isArray(value) && value.length === 2 && value.every(Number.isFinite) ? [...value] : undefined;
const mortarKeys = ['id', 'kind', 'hp', 'faction', 'crew_alive', 'capturable', 'capture_count', 'shots', 'available_current_encounter', 'retired'];

/** An explicit list, including an empty one, supersedes the legacy first-gun field. */
export function publicMortars(value: unknown): Row[] {
  const growth = row(value), seen = new Set<string>();
  const candidates = Array.isArray(growth.mortar_supports) ? growth.mortar_supports : [growth.mortar_support];
  return rows(candidates).filter(gun => {
    if (gun.kind !== 'mortar' || typeof gun.id !== 'string' || !gun.id || seen.has(gun.id)
      || gun.retired === true || gun.support_completed === true || ['retired', 'completed_support'].includes(gun.phase)) return false;
    seen.add(gun.id); return true;
  }).map(gun => pick(gun, mortarKeys));
}

/** Presentation evidence only. Never copy combat diagnostics, queries, orders or raw events.
 * Battle agents continue to read their original native observations unchanged.
 */
export function publicBattleFrame(frame: BattleFrame): BattleFrame {
  const w = frame.world, growth = row(w.world_growth), mission = row(growth.mission);
  return { kind: frame.kind, status: frame.status, presenterStage: frame.presenterStage ?? presenterStageContext(w),
    // This is the whitelisted, identity-bound director projection created by
    // battleFrame. Raw planner state never enters the public combat world.
    presenterExperience: frame.kind === 'ai' ? frame.presenterExperience : undefined, world: {
    ...pick(w, ['run_id', 'time', 'paused', 'winner']),
    units: rows(w.units).map(u => {
      const satchel = row(u.combat?.satchel);
      return { ...pick(u, ['id', 'faction', 'kind', 'tank', 'weapon', 'hp', 'max_hp', 'combat_ready', 'posture', 'in_cover', 'ammo_infinite', 'reload_remaining', 'last_shot_at']),
        position: point(u.position),
        // Only a displayed throw/explosion is public; failure reasons and safety checks are not.
        ...(['launched', 'detonated'].includes(satchel.status)
          ? { combat: { satchel: pick(satchel, ['status', 'time']) } } : {}),
      };
    }),
    world_growth: {
      ...pick(growth, ['enabled', 'revision']),
      mission: { ...pick(mission, ['index', 'status', 'enemies_remaining', 'operation_id']), entry: point(mission.entry), target: point(mission.target) },
      mortar_support: pick(growth.mortar_support, mortarKeys),
      mortar_supports: publicMortars(growth),
      mission_results: rows(growth.mission_results).slice(-12).map(result => ({
        ...pick(result, ['index', 'status', 'duration_seconds', 'ended']),
        green_start: pick(result.green_start, ['alive', 'hp_total']), green_end: pick(result.green_end, ['alive', 'hp_total']),
      })),
    },
  } };
}

/** Reject internal diagnoses even if a writer attaches an unrelated, otherwise valid fact id. */
export function publicSpectatorText(text: string): boolean {
  return !/射线|射界|寻路|导航|执行回执|路径失败|行进阻塞|卡墙|这墙.{0,6}过不去|firing[_ -]?awareness|fire[_ -]?block|muzzle[_ -]?cover|target[_ -]?occluded|path[_ -]?failure|blocked[_ -]?shots|raycast|line[_ -]?of[_ -]?fire|line[_ -]?of[_ -]?sight/iu.test(text)
    && !/(?:子弹|炮弹|弹道|开火|射击|枪|炮口).{0,18}(?:挡|堵|卡|打不到|打不着|不通|找不到路)|(?:墙|掩体|障碍).{0,14}(?:挡|堵|卡).{0,10}(?:子弹|炮弹|弹道|开火|射击|枪|炮口)|隔墙打不到|被.{0,4}墙挡/iu.test(text);
}
