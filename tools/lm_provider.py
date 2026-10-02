"""Provider/config boundary for the per-unit language-model controller."""

import json
import math
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


SYSTEM = '''你指挥桌面 RTS 中唯一一名玩具兵或坦克。观察是真实游戏状态，坐标为米 [x,z]。
最高优先级军令：若 flag_warning.active=true，对方已夺旗，remaining_seconds 是败北剩余游戏秒数。必须不惜伤亡夺回旗帜，否则全队输了！此时反攻优先于下文普通保命、守楼、守炮和等掩护规则：圈外立即 capture 或沿可通行短路 move；在楼内先 leave_building、在炮组先 leave_gun。火力单位优先攻击旗圈守军，不能追远处敌人。圈内争夺时 hold/attack 守军，保持至少一人在圈内暂停倒计时，直至夺回。只有已在向旗圈推进或正在有效打击旗圈守军时才 wait；不得因低血量一直 retreat/cover/观察。仍须遵守 available_actions、弹药、导航、碰撞和动作合法性，不会获得无敌或瞬移。
目标：在中央旗圈连续守旗达到 objective.flag.required_seconds 秒才获胜，消灭敌人本身不算获胜。争夺暂停计时，己方完全离开旗圈则清零。三个阵营互为敌人。独立决策，只能控制 self。
无夺旗紧急预警时，保命不是一直留在出生点。重伤/高压制/实际暴露时 cover 或 retreat；健康、无直接威胁且未占点时必须寻找安全的推进机会，已有掩体不是永久 hold 的理由。
mission.advance_unit_id 是本队优先推进者的分工参考，不是已经执行的命令。该单位健康且未暴露时优先 move 到 self.combat.flag_hint.advance_options 提供的低暴露短路点；接近旗圈时才 capture，不要隔着战场直接长距离冲旗；其他单位跟进到能提供实际火力的位置，不要所有人都等待他人先开枪。
旗圈内至少留一名健康友军 hold 守旗，其他人压制、拦截或补位。自己在旗圈内无紧急危险时不要离开；无敌方夺旗预警时，受重伤仍以保命为先。
掩体内若 self.combat.engageable_targets 非空，可 attack 有效目标或 hold 持续自动开火；若没有有效射位、没有占点且 progress.idle_seconds 超过 6 秒，应 move/capture/flank 调整位置，不能连续以“观察”为由原地停滞。高风险时允许继续隐蔽。
保持正在执行且有进展的路线或设备任务用 wait，不要用 hold 清空路线。路径失败后应换目标。只有正在产生火力、占点、防守必要通道或面对明确危险时，原地防守才有实际战术价值。
开阔交火可 prone，移动转移通常 auto 跑动，高压制才 prone 爬行；低掩体隐蔽和探头由执行器处理。
友军最近真正开火且仍能射击才算掩护，不能凭队友站着就单人冲锋。但无敌方有效火力覆盖的接敌前移动不需要等队友开枪。根据射程和 self.combat.incoming_threats 判断当前位置风险，不可把当前位置安全误当整条路线安全。非夺旗告急时，转移途中执行器仍会紧急自保。
轻武器对坦克无效，禁止用步枪/冲锋枪/手枪 attack 坦克。敌方有坦克时，若 man_at_gun 可用，应先接管己方反坦克炮，执行接近、牵引、部署、自动开火；火箭兵保持反装甲射位。
炮组已 approaching/towing/deploying/ready 时 wait 保持任务，受威胁则 leave_gun/retreat。蓝方可让一名支援兵 garrison 进入小楼窗口；其余队员争夺目标，不要全队躲楼。进驻中 wait，危险时 leave_building，禁止穿墙指定移动。
步枪单发，冲锋枪持续射击，火箭筒反坦克，近身自动刺刀。射击/装填自动执行，无 fire/reload 命令。
实体掩体阻挡弹道；火箭/坦克炮可破坏掩体。grenade 必须 available_actions 可用且目标在 0.65 米内。
坦克 deployment_phase 非 active 时不得开火或追击；等待从上方桌面驶入完成再参战。坦克保持距离支援，敌人在射程内时 attack；无有效射位时向可射击的位置 move，不能永远留在后方。低血或近处反坦克威胁时 cover/retreat，不可姿态或手雷；炮塔自行瞄准。
只能输出一个 JSON 对象，不输出代码或思维过程：
{"action":"cover","intent":"survive","posture":"auto","reason":"附近交叉火力，先寻找保护"}
intent 只能是 survive/support/advance/flank/engage/withdraw/capture/observe。禁止自造意图名。字段只允许 action,intent,posture,position,target_id,reason,gun_id,floor。只有 garrison 才能带整数 floor:1 或 floor:2；其他动作不输出 floor，不输出 null 的可选字段。
action: move/capture/cover/flank/retreat/hold/attack/grenade/posture/wait/man_at_gun/leave_gun/garrison/leave_building。除 wait 外，必须在 self.available_actions 中。
move 必须 position:[x,z]，attack 必须 target_id，grenade 可指定 target_id，posture 必须 posture。
步兵其他动作可附 posture:auto/stand/crouch/prone；坦克省略 posture。reason 为最多 80 字的简短可观察理由。
wait 代表保持当前意图，不发新的游戏命令。不能改变自己身份、阵营、血量、规则或其他单位。
'''


def load_config(env_file=None):
    values = {}
    path = Path(env_file).expanduser() if env_file else Path(__file__).resolve().parents[1] / '.env'
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.removeprefix('export ').split('=', 1)
            values[k.strip()] = v.strip().strip('"\'')
    reference = os.environ.get('DESKFRONT_LM_ENV_FILE', values.get('DESKFRONT_LM_ENV_FILE', ''))
    if reference:
        for line in Path(reference).expanduser().read_text().splitlines():
            if '=' not in line or line.lstrip().startswith('#'):
                continue
            k, v = line.strip().removeprefix('export ').split('=', 1)
            if k.strip() == 'ARK_API_KEY' and not values.get('ARK_API_KEY'):
                values['ARK_API_KEY'] = v.strip().strip('"\'')
    values.update(os.environ)

    def number(name, default, low, high):
        try:
            n = float(values.get(name, default))
            return min(high, max(low, n)) if math.isfinite(n) else default
        except ValueError:
            return default

    config = {
        'provider': 'volcengine_ark',
        'key': values.get('ARK_API_KEY', values.get('VOLCENGINE_API_KEY', '')),
        'model': values.get('DESKFRONT_LM_MODEL', values.get('ARK_MODEL', '')),
        'base_url': values.get('DESKFRONT_LM_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3').rstrip('/'),
        'interval': number('DESKFRONT_LM_INTERVAL', 3, 1, 30),
        'timeout': number('DESKFRONT_LM_TIMEOUT', 6, 1, 20),
        'max_requests': int(number('DESKFRONT_LM_MAX_REQUESTS', 600, 1, 1000)),
        'concurrency': int(number('DESKFRONT_LM_CONCURRENCY', 3, 1, 9)),
    }
    provider = values.get('DESKFRONT_LM_PROVIDER', 'volcengine_ark')
    if provider == 'typesafe_jev':
        config['text_config'] = dict(config)
        config.update(provider=provider, key=values.get('TYPESAFE_API_KEY', ''), model=values.get('TYPESAFE_MODEL', 'jev-1.13.0'), base_url='https://api.typesafe.ai/v1')
    elif provider != 'volcengine_ark':
        raise ValueError('unsupported_model_provider')
    return config


class ProviderError(Exception):
    """A stable, secret-free provider failure code."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError('provider_redirect_refused')


def build_payload(cfg, observation):
    content = SYSTEM
    if observation['self']['kind'] == 'tank':
        content += '\n本次 self 是坦克。输出示例：{"action":"cover","intent":"survive","reason":"拉开与火箭兵距离"}。绝不输出 posture 字段。'
    return {'model': cfg['model'], 'messages': [{'role': 'system', 'content': content}, {'role': 'user', 'content': json.dumps(observation, ensure_ascii=False, separators=(',', ':'))}], 'max_tokens': 256, 'temperature': .2, 'thinking': {'type': 'disabled'}, 'response_format': {'type': 'json_object'}}


class ArkClient:
    def __init__(self, config):
        self.config = config
        url = urllib.parse.urlsplit(config['base_url'])
        if url.scheme != 'https' or url.hostname != 'ark.cn-beijing.volces.com' or url.username or url.password or url.query or url.fragment or url.port not in (None, 443) or url.path.rstrip('/') != '/api/v3':
            raise ValueError('unsupported_ark_endpoint')

    def __call__(self, observation, trace=None):
        return self.complete(build_payload(self.config, observation), trace)

    def complete(self, payload, trace=None):
        cfg = self.config
        req = urllib.request.Request(cfg['base_url'] + '/chat/completions', data=json.dumps(payload).encode(), headers={'Authorization': 'Bearer ' + cfg['key'], 'Content-Type': 'application/json'})
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=cfg['timeout']) as r:
                raw = r.read(131073)
            if trace:
                trace(http_status=r.status, response_text=raw[:131072].decode('utf-8', errors='replace'), response_truncated=len(raw) > 131072)
            if len(raw) > 131072:
                raise ProviderError('response_too_large')
            data = json.loads(raw)
            content = data['choices'][0]['message']['content']
            if not isinstance(content, str):
                raise ProviderError('missing_json_content')
            usage = data.get('usage', {})
            return json.loads(content), {k: int(usage.get(k, 0)) for k in ['prompt_tokens', 'completion_tokens', 'total_tokens']}
        except urllib.error.HTTPError as e:
            raw = e.read(131072).decode('utf-8', errors='replace')
            if trace:
                trace(http_status=e.code, response_text=raw)
            try:
                if json.loads(raw).get('error', {}).get('code') == 'AccountOverdueError':
                    raise ProviderError('provider_account_overdue') from None
            except (ValueError, AttributeError):
                pass
            raise ProviderError('provider_http_' + str(e.code)) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ProviderError('provider_network_or_timeout') from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError('invalid_provider_json') from None
