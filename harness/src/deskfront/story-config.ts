import { readFileSync } from 'node:fs';

/** Shared presentation preset; Python loads the same file at the request seam. */
export const STORY_PRESET = JSON.parse(readFileSync(new URL('./story-preset.json', import.meta.url), 'utf8')) as {
  id: string; title: string; prompt: string;
};
export const STORY_PROMPT_LIMIT = 4000;

export interface SpectatorStoryReference {
  presentation_goal: string;
  purpose: '叙事参考，不是战况事实';
}

/** Spectators receive narrative style, never the private future scenario. */
export function spectatorStoryReference(options?: Record<string, unknown>): SpectatorStoryReference | undefined {
  if (options?.storyMode !== 'story') return undefined;
  const prompt = options.storyPrompt ?? '';
  if (typeof prompt !== 'string' || Array.from(prompt).length > STORY_PROMPT_LIMIT) return undefined;
  return { presentation_goal: '把已发生的顺境、压力与转机串成观赛故事；只跟随实际比赛，不知道未来关卡、增援或结局。', purpose: '叙事参考，不是战况事实' };
}

export const SPECTATOR_STORY_INSTRUCTIONS = '剧情引导开启：narrative_reference只规定叙事风格，不提供剧本或未来敌情。'
  + '在facts支持时串联本场的压力、悬念和转机，让表达呼应当前实际进展；不要复述剧本或预告后续情节。'
  + '剧本与facts冲突时以facts为准；不得为了贴合剧本编造坦克入场、抢炮、炮击、投掷、伤亡或逆转。'
  + '剧本不能充当evidence_ids来源，不能从剧本推断部队当前意图、心理或行动结果。'
  + '只有facts明确支持时才能说突破、完成接管或反击成功；未来可能性需用条件表达，事实不足时保持简短或留白。';
