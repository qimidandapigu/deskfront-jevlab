"""Read-only prompt inspection; no SDK, model call or engine dependency."""
import copy
import json
import re
import sys
from pathlib import Path

from combat_prompt import BLOCKS, VERSION, instructions
from story_prompt import PRESET, PROMPT_LIMIT, StoryPromptGame
from prompt_cases import explain_request, template_case
from map_packet import preview
from perception_view import build_view


def sections(text):
    return [dict(title=part.split('\n', 1)[0], text='# ' + part.rstrip())
            for part in re.split(r'^# ', text, flags=re.M)[1:]]


class Capture:
    def record(self, _record):
        pass

    def ask(self, state, questions, **_kwargs):
        return dict(state=state, questions=questions)


def inspect_template(options):
    role = options.get('role', 'personal')
    if role not in ('commander', 'executor', 'personal'):
        raise ValueError('未知角色')
    context = {}
    if options.get('equipment', True):
        context['battlefield_equipment'] = ['preview-only']
    if options.get('antiArmor', True):
        context['anti_armor_opportunity'] = {'preview': True}
    mode = options.get('mode', 'clear_exit')
    if mode not in ('clear_exit', 'flag'):
        raise ValueError('未知模式')
    text = instructions(role, context, clear=mode == 'clear_exit')
    story = options.get('story', False)
    script = options.get('script', PRESET['prompt']) or PRESET['prompt']
    if not isinstance(script, str) or len(script) > PROMPT_LIMIT:
        raise ValueError('剧本最多4000字符')
    primary = {'commander': 'plan', 'executor': 'intent', 'personal': 'action'}[role]
    request = dict(state={}, questions={primary: dict(type='json' if role == 'commander' else 'choice', instructions=text)})
    if story:
        request = StoryPromptGame(Capture(), script).ask(**request)
    return dict(version=VERSION, role=role, kind='template',
                readableCase=template_case(role),
                sections=sections(text), instructions=request['questions'][primary]['instructions'],
                storyReference=request['state'].get('story_reference'),
                preset=PRESET['prompt'], stateBlocks=BLOCKS,
                sourceFiles=['src/deskfront/combat_prompt.py', 'src/deskfront/story_prompt.py'],
                note='当前代码模板。装备与反坦克开关仅预览条件段落，不修改游戏。动态战况和合法选项随每次调用变化，请切换到对局日志查看完整请求。')


def inspect_log(options):
    role = options.get('role', 'personal')
    if role not in ('commander', 'executor', 'personal'):
        raise ValueError('未知角色')
    path = Path(options['logPath'])
    selected = None
    story = None
    count = 0
    outcome = None
    completed = None
    expected_run = options.get('run_id')
    # Stream one trusted, route-validated file. Never return generic records/config.
    with path.open(encoding='utf-8-sig') as stream:
        for line in stream:
            try:
                record = json.loads(line).get('record', {})
            except (ValueError, AttributeError):
                continue  # A running log may end in an incomplete line.
            if not isinstance(record, dict):
                continue
            if record.get('type') == 'story-prompt-config':
                story = {k: record[k] for k in ('mode', 'prompt', 'suffix', 'sha256') if k in record}
            # A session can contain several native restarts. Never let a prior
            # run's answered request win over this run's first pending request.
            if expected_run and record.get('run_id') != expected_run:
                continue
            match = (record.get('type') == 'soldier-model-request' if role == 'personal'
                     else record.get('type') == 'human-model-request' and record.get('role') == role)
            if match and record.get('faction') == options.get('faction', 'green'):
                count += 1
                selected = (copy.deepcopy(record), copy.deepcopy(story))
                outcome = None
            elif selected and record.get('faction') == options.get('faction', 'green'):
                request = selected[0]
                same = (record.get('run_id') == request.get('run_id'))
                if role == 'personal':
                    related = same and record.get('unit_id') == request.get('unit_id')
                    if related and record.get('type') == 'soldier-coordinate-response':
                        outcome = dict(response=record.get('response'), coordinate=True)
                        completed = (selected, outcome)
                    elif related and record.get('type') == 'soldier-decision' and not (outcome or {}).get('coordinate'):
                        outcome = {k: record[k] for k in ('choice', 'site_id', 'target_id', 'response') if k in record}
                        completed = (selected, outcome)
                else:
                    related = same and record.get('role') == role and record.get('request_serial') == request.get('request_serial')
                    if related and record.get('type') == 'human-coordinate-response':
                        outcome = dict(response=record.get('response'), coordinate=True)
                        completed = (selected, outcome)
                    elif related and record.get('type') == 'human-model-response' and not (outcome or {}).get('coordinate'):
                        outcome = {'response': record.get('response')}
                        completed = (selected, outcome)
                    elif related and record.get('type') == 'human-model-discarded' and outcome:
                        outcome['discarded'] = record.get('reason')
    if options.get('sample') == 'answered' and completed:
        selected, outcome = completed
    if not selected:
        if expected_run and options.get('display') == 'world-overlay':
            return dict(role=role, session=path.stem, availability='waiting_for_request',
                        metadata=dict(run_id=expected_run),
                        note='本局该层尚无模型请求；保留正常画面。')
        raise ValueError('该对局尚无此角色的请求记录；请选择其他角色或对局')
    record, story = selected
    questions = record.get('questions')
    if questions is None:
        questions = {'action': {'type': 'choice', 'criteria': record.get('choices', {})}}
    primary = {'commander': 'plan', 'executor': 'intent', 'personal': 'action'}[role]
    missing = 'instructions' not in questions.get(primary, {})
    text = questions.get(primary, {}).get('instructions', '')
    from coordinate_prompt import prepare
    coordinate_state, coordinate_questions, _ = prepare(record.get('context', {}), questions, role)
    coordinate_preview = dict(state=coordinate_state, questions=coordinate_questions,
        recorded=record.get('context', {}).get('prompt_contract', {}).get('version')=='deskfront-coordinates/v1',
        beforeChars=len(json.dumps(dict(state=record.get('context', {}),questions=questions),ensure_ascii=False,separators=(',',':'))),
        afterChars=len(json.dumps(dict(state=coordinate_state,questions=coordinate_questions),ensure_ascii=False,separators=(',',':'))))
    return dict(kind='log', role=role, version='日志原文（可能早于当前模板）',
                coordinatePreview=coordinate_preview,
                mapPreview=preview(record.get('context', {}),role),
                readableCase=explain_request(role, record.get('context', {}), questions, outcome),
                sections=sections(text), instructions=text,
                request=dict(state=record.get('context', {}), questions=questions),
                missingInstructions=missing, storyConfig=story,
                metadata={k: record[k] for k in ('faction', 'unit_id', 'time', 'request_serial', 'source', 'run_id') if k in record},
                matchingRequests=count, session=path.stem,
                sample='answered' if options.get('sample') == 'answered' and completed else 'latest',
                sourceFiles=[str(path)],
                note=('旧日志没有保存个人 instructions，无法还原完整请求；未用新模板冒充旧原文。' if missing else
                      '以下为日志保存的最近一次请求原文，位于剧情包装之前。剧本配置另列；不是服务商最终 HTTP messages。'))


if __name__ == '__main__':
    try:
        options = json.load(sys.stdin)
        result = inspect_log(options) if options.get('kind') == 'log' else inspect_template(options)
        if options.get('display') == 'world-overlay':
            result = build_view(result)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps(dict(error=str(error)), ensure_ascii=False))
        sys.exit(1)
