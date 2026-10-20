"""Human-readable explanations for the read-only inspector, never game policy."""
import re
from map_packet import expand


def name(value):
    match = re.fullmatch(r'(green|red|blue)-(\d+)', str(value))
    return ({'green': '绿队', 'red': '红队', 'blue': '蓝队'}[match[1]] + match[2] + '号') if match else str(value)


def template_case(role):
    common = [
        dict(label='局面', text='绿队在墙西侧，敌人在墙东侧。敌人的位置已知，但墙挡住了枪口。'),
        dict(label='可走的路', text='墙边点能走到，却仍打不到敌人；北侧入口也能走到，但只是绕行中间点，入口之后的射界还要检查。'),
        dict(label='已经发生', text='士兵在墙边来回走，始终没有对这个敌人开火；换一条命令不能把这段失败历史清掉。'),
    ]
    text = {
        'commander': ('指挥该安排去哪？', '比较当前可选区域，决定继续绕行、换方向或恢复；不能直接给个人编造坐标。',
                      '一种可能的安排：把下一阶段改为北侧入口，目的写明“通过入口后重新判断射界”；到入口不算消灭敌人。'),
        'executor': ('小队该让谁走哪条路？', '把指挥的北侧入口目标分给成员；逐人比较可达路线和到位后的射界，不让受阻的一人拖停全队。',
                     '一种可能的分工：让能走北侧通路的人先接近；另一人只有确实能开火才负责火力掩护。没人能开火时，不能把站着等待叫作压制。'),
        'personal': ('个人该继续贴墙，还是换位置？', '只决定自己的动作。比较墙边和入口的真实候选、枪口检查与受阻记录；不能擅自换全队目标。',
                     '一种可能的动作：从本次合法选项中选择去入口的中间点，随后重新检查；如果职责范围内没有能改善局面的点，就报告受阻。'),
    }[role]
    return dict(title=text[0], badge='教学示例，不是真实对局结果', intro='用“敌人在墙另一边”解释这层提示词的作用。',
                facts=common + [dict(label='这一层的权限', text=text[1])], candidates=[],
                decision=dict(text=text[2], raw=None),
                takeaway='模型比较并选择；导航提供可达候选，引擎复验碰撞和射击。能走到、能开火、已经命中，是三个不同的结果。')


REASONS = {'muzzle_cover': '枪口被掩体挡住', 'target_occluded': '目标被障碍遮挡',
           'out_of_range': '超过武器射程', 'outside_radius': '还没进入接管范围',
           'no_visible_target': '没有可用目标', 'friendly_blast_risk': '落点可能炸到友军',
           'inside_minimum_range': '目标太近，低于最小射程'}
ACTIONS = {'continue_task': '继续当前任务', 'report_blocked': '报告受阻，请团队调整',
           'focus_fire': '暂停移动，集中瞄准指定敌人', 'peek_fire': '去指定掩体探头攻击',
           'move_to_site': '移动到指定位置', 'rush_to_site': '冲刺到指定位置',
           'prone_approach': '趴下匍匐接近指定位置', 'occupy_cover': '进入指定掩体',
           'satchel': '向指定目标投掷炸药包', 'advance': '推进', 'cover': '建立掩护',
           'bound': '交替推进', 'flank': '绕侧', 'hold': '保持阵位', 'regroup': '重新集合',
           'continue_order': '继续当前小队命令'}
ROLES = {'support': '提供支援', 'maneuver': '机动接近', 'reserve': '外围支援',
         'establish_fire': '寻找能开火的位置', 'fire_support': '提供真实火力支援',
         'protect': '寻找保护', 'hold': '保持阵位'}
INTENT_DETAILS = {'continue_order': '保持现有小队安排，观察实际进展。', 'advance': '安排成员推进。',
                  'cover': '安排成员建立掩护；是否真的形成火力要看射界和开火回执。',
                  'bound': '分批推进，并安排另一批提供掩护。', 'flank': '比较侧路与正面，安排绕行。',
                  'hold': '保持当前阵位。', 'regroup': '重新集合成员。'}


def explain_request(role, state, questions, outcome=None):
    state=expand(state)
    if state.get('prompt_contract',{}).get('version')=='deskfront-coordinates/v1':
        from coordinate_prompt import inspect_state
        state=inspect_state(state)
    facts, candidates = [], []
    time = state.get('time')
    intro = ('游戏时间 ' + str(time) + ' 秒。' if time is not None else '') + '以下内容来自这一条请求，中文是查看页的解释，展开后可对照原始字段。'
    units = [state['self']] if role == 'personal' and isinstance(state.get('self'), dict) else state.get('members', [])
    if role == 'personal' and units:
        facts.append(dict(label='我是谁',text='我是'+name(units[0].get('id','当前士兵'))+'。这次只选择我自己的动作，其他编号是队友或敌人。',raw={'self_id':units[0].get('id')}))
    for unit in units:
        text = name(unit.get('id', '成员'))
        if isinstance(unit.get('hp'), (float, int)) and unit.get('max_hp'):
            text += '，生命 ' + str(round(unit['hp'] / unit['max_hp'] * 100, 1)) + '%'
        if unit.get('posture'):
            text += '，' + {'prone': '卧倒', 'stand': '站立', 'standing': '站立', 'crouch': '蹲姿'}.get(unit['posture'], str(unit['posture']))
        if unit.get('ammo_infinite') is True:
            text += '，无限弹药，无需装填'
        elif unit.get('ammo') is not None:
            text += '，当前弹匣剩 ' + str(unit['ammo']) + ' 发'
        facts.append(dict(label='士兵状态', text=text, raw=unit))
    enemies = state.get('contacts', state.get('teammate_reports', []))
    facts.append(dict(label='敌人情报', text=('这条请求有 ' + str(len(enemies)) + ' 条敌人报告。位置报告不能证明当前枪口能打到。' if enemies else '这条请求没有敌人报告；不能因此断言全图已经安全。'), raw=enemies))
    plan = state.get('assignment') if role == 'personal' else state.get('current_plan')
    if plan:
        purpose = plan.get('objective') or ACTIONS.get(plan.get('intent')) or ROLES.get(plan.get('role')) or ('任务落点在区域 ' + str(plan['region_id']) if plan.get('region_id') else '日志没有文字目标；具体分配见原始字段')
        facts.append(dict(label='收到的任务', text=str(purpose), raw=plan))
    evidence = state.get('execution_evidence', {})
    rows = [(state.get('self', {}).get('id', '当前士兵'), evidence)] if role == 'personal' else list(evidence.get('members', {}).items())
    for uid, row in rows:
        awareness = row.get('firing_awareness', {})
        reason = row.get('fire_block_reason') or awareness.get('reason')
        targets = row.get('engageable_visible_targets')
        if reason:
            facts.append(dict(label='为什么打不到', text=name(uid) + '：' + REASONS.get(reason, '引擎报告受阻，原因码为 ' + str(reason)) + '。敌人在射程内，也不等于能穿过障碍开火。', raw=row))
        elif targets:
            facts.append(dict(label='当前射界', text=name(uid) + '的原生检查列出可攻击目标：' + '、'.join(map(name, targets)) + '。实际开火仍看后续回执。', raw=row))
        if row.get('seconds_since_last_shot') is not None:
            facts.append(dict(label='开火历史', text=name(uid) + '距上次开火 ' + str(row['seconds_since_last_shot']) + ' 秒。这个值不证明为何没有开火。', raw={'seconds_since_last_shot': row['seconds_since_last_shot']}))
    sites = state.get('candidate_sites', [])
    for site in sites[:4]:
        targets = site.get('fire_targets')
        sentence = ('这个采样位置的检查能打到：' + '、'.join(map(name, targets)) + '。') if targets else ('这个采样位置没有可开火目标。' if targets == [] else '未提供这个位置的可开火名单。')
        posture = site.get('fire_check_posture')
        if posture:
            sentence += '检查姿态：' + {'stand': '站立', 'prone': '卧倒'}.get(posture, str(posture)) + '。'
        sentence += '不是已经走到或已经开枪。'
        candidates.append(dict(label='位置 ' + str(site.get('id', '?')), text=sentence, raw=site))
    if not sites:
        primary = 'plan' if role == 'commander' else 'intent'
        options = state.get('regions', {}) if role == 'commander' else questions.get(primary, {}).get('criteria', {})
        if isinstance(options, dict):
            for key, value in list(options.items())[:4]:
                candidates.append(dict(label=('区域 ' + str(key)) if role == 'commander' else ACTIONS.get(key, key),
                                       text='这次可以选择的区域；具体通路与射界需分别核对。' if role == 'commander' else INTENT_DETAILS.get(key, '原始选项描述可以展开查看。'), raw={key: value}))
    decision = '这条请求后没有找到可关联的模型回答。不能把页面示例当作它已经做出的选择。'
    if outcome:
        answers = outcome.get('response', {}).get('answers', {})
        if role == 'commander':
            value = answers.get('plan', {}).get('value', {})
            if value:
                decision = '模型选择目标 ' + str(value.get('destination',value.get('region_id', '未填写'))) + '，目标写的是：' + str(value.get('objective', '未填写'))
        else:
            answer = answers.get('action' if role == 'personal' else 'intent', {})
            choice = answer.get('choice', outcome.get('choice'))
            if choice:
                parts = str(choice).split(':')
                decision = '模型实际选择：' + ACTIONS.get(parts[0], parts[0])
                if len(parts) > 1:
                    decision += '（位置 ' + parts[1] + ('，目标 ' + name(parts[2]) if len(parts) > 2 else '') + '）'
                decision += '。'
        if outcome.get('discarded'):
            decision += ' 这份回答后来被丢弃，原因：' + str(outcome['discarded']) + '。'
        decision += ' 这是回答记录，不证明引擎已经执行成功；日志中的选择也不等于模型写出了原因。'
    return dict(title={'commander': '这一刻，指挥收到什么', 'executor': '这一刻，小队 JEV 收到什么', 'personal': '这一刻，个人 JEV 收到什么'}[role],
                badge='真实日志案例', intro=intro, facts=facts, candidates=candidates,
                candidateCount=len(sites) if sites else None,
                decision=dict(text=decision, raw=outcome),
                takeaway='先看敌人在哪里，再看自己能不能打；能走到的中间点可以用于绕行，但到位之后仍被挡，就需要重新比较路线或反馈受阻。')
