"""Presentation vocabulary; the soldier Agent chooses its own living emotion."""
EMOTIONS = {'calm': '平静', 'alert': '警觉', 'nervous': '紧张', 'afraid': '害怕',
            'angry': '生气', 'determined': '坚持', 'relieved': '安心',
            'sad': '难过', 'surprised': '惊讶', 'confused': '困惑',
            'exhausted': '疲惫', 'hurt': '痛苦', 'happy': '开心'}

# These are decision criteria for JEV, not engine rules or automatic reactions.
EMOTION_CRITERIA = {
    'calm': '眼前威胁较低，近期伤痛已缓解，内心平稳',
    'alert': '察觉危险并专注观察，但尚未明显慌乱',
    'nervous': '持续威胁或受压使自己紧绷不安',
    'afraid': '伤亡风险迫近，恐惧占主导；仍可以继续行动',
    'angry': '遭袭或队伍损失引发愤怒，怒意占主导',
    'determined': '压力下仍咬牙坚持，决心比恐惧更突出',
    'relieved': '危险有明确缓解证据后的短暂松口气',
    'sad': '得知队友伤亡或严重挫败后感到难过',
    'surprised': '突然的受击、爆炸或威胁使自己惊讶',
    'confused': '态势矛盾或突变，自己一时难以理解',
    'exhausted': '持续高压或消耗后感到疲惫；不能只按时间推断',
    'hurt': '新近受伤或仍在疼痛，痛感最突出；不必等到濒死',
    'happy': '明确的获救或成功带来喜悦',
}

EMOTION_INSTRUCTIONS = (
    '选此刻最突出的主观感受，用于表情，不决定行动。能继续作战不等于内心平静。'
    '先看affect_appraisal的0到1数值及danger_change：danger是本人所知危险，pain是伤痛，arousal是激活，'
    'coping是可应对程度，strain是累积消耗，loss是队友损失，surprise和relief是短暂冲击与缓解。'
    'emotion_support是程序基于这些数值给13种表情算的情境匹配度，0到1且不是概率。'
    '优先比较明显不同的匹配度，再结合emotion_evidence和本人状态选最贴切的一项；'
    '可因具体事实推翻最高分，不能把分数当成自动命令。旧表情最后参考。'
    '刚受击可能是痛苦、惊讶、警觉或紧张；反复受击和持续威胁也可能使人害怕、愤怒或咬牙坚持。'
    '结合这名士兵的具体处境选择，不把事件机械映射为某个表情，也不为多样化而轮换。'
    '旧表情只供连续性参考；近期无事件、无接敌、无压制时，可以回到平静，不要仅因上一表情是警觉就维持它。'
    '没有近期威胁或伤痛、确实已平稳时才适合平静；emergency_ended只表示引擎避险结束，不证明已安全。'
    'last_hit_at是自己命中敌人，不能当成自己受伤；队友阵亡只是队伍状态，不代表亲眼目睹。'
)
