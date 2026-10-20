"""Optional prompt decoration only. No engine actions or decision scheduling."""
import hashlib
import copy
import json
from pathlib import Path

PRESET = json.loads(Path(__file__).with_name('story-preset.json').read_text(encoding='utf-8'))
PROMPT_LIMIT = 4000
GUARD = (
    '以下是可选的剧情意图，不是已经发生的战况，也不是隐藏敌情。'
    '原有角色职责、输出协议、合法候选、可感知事实和配置约束始终优先。'
    '双方仍争取己方胜利；不得故意送死、制造伤亡、放水或拖延胜利来凑剧情。'
    '不得推断尚未发现的敌人或装备位置；不得虚构命中、接管、伤亡或胜利。'
    '第二关坦克开关关闭或现场没有相关装备时，跳过对应情节；不得修改配置或凭空生成装备。'
    '按真实进展灵活取舍，已有战果无需重演，不要求固定结局。'
    '体验分析只评估真实状态，生成只在原有候选与约束内参考节奏，战术只使用当前合法行动。'
)


class StoryPromptGame:
    def __init__(self, game, prompt):
        self._game = game
        self._prompt = prompt
        self._suffix = '\n\n[剧情意图：仅作提示词引导]\n' + GUARD + '\n剧本：\n' + prompt
        self._hash = hashlib.sha256(self._suffix.encode('utf-8')).hexdigest()
        game.record(dict(type='story-prompt-config', mode='story', prompt=prompt,
                         suffix=self._suffix, sha256=self._hash))

    def __getattr__(self, name):
        return getattr(self._game, name)

    def ask(self, state, questions, role=None, on_answer=None):
        # Share the optional narrative once across tactical questions. Mixed
        # emotion requests keep the old per-question boundary, so private story
        # content never enters an emotion question's shared state.
        selected = [key for key in questions if not key.startswith('emotion')]
        shared = bool(selected) and len(selected) == len(questions) and isinstance(state, dict)
        sent_state = copy.deepcopy(state) if shared else state
        if shared:
            sent_state['story_reference'] = dict(
                purpose='可选剧情意图，不是战况事实或隐藏敌情',
                guard=GUARD, prompt=self._prompt,
                applies_to_questions=selected)
        patched = {
            key: dict(question, instructions=question.get('instructions', '') + (
                '\n剧情参考见state.story_reference；遵守其guard，事实、角色权限、配置和合法选项优先。'
                if shared else self._suffix))
            if not key.startswith('emotion') else question
            for key, question in questions.items()
        }
        self._game.record(dict(type='story-prompt-applied', sha256=self._hash,
                               role=role, questions=selected,
                               injection='shared_state' if shared else 'question_instructions'))
        kwargs = {}
        if role is not None: kwargs['role'] = role
        if on_answer is not None: kwargs['on_answer'] = on_answer
        return self._game.ask(sent_state, patched, **kwargs)


def with_story_prompts(game):
    options = game.config.get('gameOptions', {})
    mode = options.get('storyMode', 'normal')
    if mode not in ('normal', 'story'):
        raise ValueError('storyMode 必须为 normal 或 story')
    if mode == 'normal':
        return game
    prompt = options.get('storyPrompt', '')
    if not isinstance(prompt, str) or len(prompt) > PROMPT_LIMIT:
        raise ValueError('storyPrompt 必须为不超过 4000 字符的文本')
    return StoryPromptGame(game, prompt.strip() or PRESET['prompt'])
