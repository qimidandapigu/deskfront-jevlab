"""Decision evidence for construction; geometry and capability inference stay out."""
import json
import math
from collections import Counter

from context_views import pick, rounded
from .catalog import CATALOG
from .design_memory import describe as describe_design


def context_chars(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')))


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _mean(values):
    values = [value for value in values if _number(value)]
    return sum(values)/len(values) if values else None


def _teams(state):
    result = {}
    units = state.get('units', [])
    for faction in sorted({u.get('faction', 'unknown') for u in units}):
        members = [u for u in units if u.get('faction', 'unknown') == faction]
        alive = [u for u in members if _number(u.get('hp')) and u['hp'] > 0]
        pressure = [u['suppression'] for u in alive if _number(u.get('suppression'))]
        health = [u for u in alive if _number(u.get('max_hp')) and u['max_hp'] > 0]
        result[faction] = dict(alive=len(alive),
            observed_dead=sum(_number(u.get('hp')) and u['hp'] <= 0 for u in members),
            controller=state.get('control', {}).get(faction, 'unknown'),
            hp_total=sum(u['hp'] for u in alive),
            hp_unknown=sum(not _number(u.get('hp')) for u in members),
            health_capacity_observed=len(health),
            injured=sum(u['hp'] < u['max_hp'] for u in health),
            hp_fraction=sum(u['hp'] for u in health)/sum(u['max_hp'] for u in health) if health else None,
            full_health_equivalents=sum(u['hp']/u['max_hp'] for u in health) if health else None,
            weapons=dict(Counter(u.get('weapon', 'unknown') for u in alive)),
            mean_pressure=_mean(pressure), pressure_observed=len(pressure))
    return result


def _mission(state):
    raw = state.get('world_growth', {}).get('mission') or {}
    result = pick(raw, ('name', 'option', 'status', 'support_type', 'support_status', 'arrived', 'required',
        'enemies_remaining', 'recovery_count', 'reason'))
    now = state.get('time')
    for source, target in [('started', 'elapsed_seconds'), ('last_progress', 'seconds_without_progress')]:
        if raw.get('status') == 'completed':
            end = raw.get('completed_at', raw.get('ended_at', now))
        elif raw.get('status') == 'failed':
            end = raw.get('failed_at', raw.get('ended_at', now))
        else:
            end = now
        if _number(raw.get(source)) and _number(end):
            result[target] = max(0, end-raw[source])
    defenders = raw.get('defenders')
    if isinstance(defenders, list):
        ids = set(defenders)
        total = len(ids)
        remaining = raw.get('enemies_remaining')
        result['enemies_total'] = total
        if _number(remaining) and 0 <= remaining <= total:
            result['enemies_cleared'] = total-remaining
            result['clear_fraction'] = (total-remaining)/total if total else None
        live = [u for u in state.get('units', []) if u.get('id') in ids and _number(u.get('hp')) and u['hp'] > 0]
        # A missing unit is not automatically dead. Confirm HP coverage using
        # the engine's authoritative remaining-guard count.
        result['defender_hp_remaining'] = sum(u['hp'] for u in live) if remaining == len(live) else None
    return result


def observation_sample(state):
    """One factual sample; individual life evidence is never sent to models."""
    units = state.get('units', [])
    living = [u for u in units if _number(u.get('hp')) and u['hp'] > 0]
    raw_mission = state.get('world_growth', {}).get('mission') or {}
    return dict(tick=state.get('tick'), time=state.get('time', 0), shots=state.get('shots'),
        alive=len(living), mean_pressure=_mean([u.get('suppression') for u in living]),
        pressure_scope='observed_living_units', teams=_teams(state),
        encounter=dict(_mission(state), revision=state.get('world_growth', {}).get('revision'),
            started=raw_mission.get('started')),
        unit_life={u['id']:dict(faction=u.get('faction', 'unknown'), hp=u.get('hp'))
                   for u in units if u.get('id')},
        human_evidence=[dict(id=u.get('id'), hp=u.get('hp'),
            order_mode=u.get('order_mode')) for u in living
            if state.get('control', {}).get(u.get('faction')) == 'player'])


def construction_view(row):
    spec = CATALOG.get(row.get('option'), {})
    return dict(pick(row, ('option', 'tick')), selection=spec.get('selection', {}),
                name=spec.get('name'), spawned_count=len(row.get('spawned', [])),
                status='construction_completed_not_proof_of_mission_clear')


def _window(state, samples):
    now = state.get('time', 0)
    rows = {row['time']:row for row in samples if _number(row.get('time'))
            and now-60 <= row['time'] <= now}
    return [rows[key] for key in sorted(rows)]


def _shot_delta(rows):
    values = [row.get('shots') for row in rows]
    if len(values) < 2 or not all(_number(value) for value in values):
        return None
    if any(b < a for a, b in zip(values, values[1:])):
        return None
    return values[-1]-values[0]


def _battle_trend(window):
    if not window:
        return dict(window_seconds=60, observed_seconds=0, samples=0, teams={}, status='unknown')
    factions = sorted({f for row in window for f in row.get('teams', {})})
    teams = {}
    for faction in factions:
        observed = [row['teams'][faction] for row in window if faction in row.get('teams', {})]
        first, last = observed[0], observed[-1]
        deaths, new, missing = set(), set(), set()
        seen, previous, life_samples = {}, None, 0
        for row in window:
            life = row.get('unit_life')
            if not isinstance(life, dict):
                continue
            life_samples += 1
            members = {uid:value for uid,value in life.items() if value.get('faction') == faction}
            if previous is not None:
                new.update(set(members)-set(seen))
                missing.update(set(previous)-set(members))
            for uid, value in members.items():
                before = seen.get(uid, {}).get('hp')
                after = value.get('hp')
                if _number(before) and _number(after) and before > 0 and after <= 0:
                    deaths.add(uid)
            seen.update(members)
            previous = members
        teams[faction] = dict(alive_start=first['alive'], alive_end=last['alive'],
            hp_start=first['hp_total'], hp_end=last['hp_total'],
            pressure_start=first.get('mean_pressure'), pressure_end=last.get('mean_pressure'),
            observed_deaths=len(deaths) if life_samples >= 2 else None,
            newly_observed=len(new) if life_samples >= 2 else None,
            disappeared=len(missing) if life_samples >= 2 else None)
    return dict(window_seconds=60, observed_seconds=window[-1]['time']-window[0]['time'],
        samples=len(window), teams=teams, shots_delta=_shot_delta(window),
        note='血量变化含补充与回血，不等于伤害；伤亡仅统计采样中确认死亡的单位，消失不等于死亡；射击数是全场活动量。')


def _observations(window):
    if not window:
        return []
    blocks = {}
    first = window[0]['time']
    for row in window:
        # Endpoints at +60 remain in the last bucket: at most six rows.
        blocks.setdefault(min(5, int((row['time']-first)/10)), []).append(row)
    result, previous = [], None
    for block in blocks.values():
        start = previous or block[0]
        teams = {}
        for faction in sorted({f for row in block for f in row.get('teams', {})}):
            rows = [row['teams'][faction] for row in block if faction in row.get('teams', {})]
            begin = start.get('teams', {}).get(faction, rows[0])
            teams[faction] = dict(alive=[begin['alive'], rows[-1]['alive']],
                hp=[begin['hp_total'], rows[-1]['hp_total']],
                pressure=_mean([row.get('mean_pressure') for row in rows]))
        # Share the preceding endpoint so deltas do not lose bucket boundaries.
        result.append(dict(from_time=start['time'], to_time=block[-1]['time'], teams=teams,
            shots_delta=_shot_delta(([previous] if previous else [])+block),
            mean_pressure=_mean([row.get('mean_pressure') for row in block
                if row.get('pressure_scope') == 'observed_living_units'])))
        previous = block[-1]
    return result


def _encounters(window):
    groups = {}
    for row in window:
        encounter = row.get('encounter', {})
        if not encounter.get('option'):
            continue
        key = (encounter.get('revision'), encounter.get('started'), encounter['option'])
        if key not in groups:
            groups[key] = dict(option=encounter['option'], observed_from=row['time'],
                enemies_start=encounter.get('enemies_remaining'))
        groups[key].update(observed_until=row['time'], status=encounter.get('status', 'unknown'),
            enemies_remaining=encounter.get('enemies_remaining'), elapsed_seconds=encounter.get('elapsed_seconds'))
    return list(groups.values())[-3:]


def _mission_results(world):
    # Terminal engine records, distinct from both construction receipts and
    # partial sampled encounters. No outcome is inferred from scene creation.
    keys = ('index', 'option', 'mission_kind', 'support_type', 'support_status', 'rescue_status', 'status', 'reason', 'duration_seconds', 'green_start',
            'green_before_reinforcement', 'green_end', 'friendly_added', 'enemies_initial', 'enemies_remaining')
    results = []
    for row in world.get('mission_results', [])[-4:]:
        result = pick(row, keys)
        for team in ('green_start', 'green_before_reinforcement', 'green_end'):
            if isinstance(result.get(team), dict):
                result[team] = pick(result[team], ('alive', 'hp_total'))
        results.append(result)
    return results


def macro_context(state, samples, hormones, phase):
    world = state.get('world_growth', {})
    window = _window(state, samples)
    current=world.get('mission') or {}
    design=(current.get('design') or current.get('spec') or {}) if isinstance(current,dict) else {}
    if not design:
        completed=world.get('completed',[])
        matching=[row for row in completed if row.get('operation_id')==current.get('operation_id')]
        design=(matching[-1].get('design') or {}) if matching else {}
    operations=design.get('build_operations',[]) if isinstance(design,dict) else []
    current_design=describe_design(operations,option=current.get('option'),actual_spec=design) if operations else None
    if current_design:
        current_design={key:current_design[key] for key in
            ('entry','exit','cells','connections','materials','material_profile','main_route','flank_route',
             'non_cell_materials') if key in current_design}
    return rounded(dict(schema='world-macro-v2', tick=state.get('tick'), teams=_teams(state),
        mission=_mission(state), objective='清除本段全部守军即解锁下一段；无需集合到出口，也不是占旗',
        current_design=current_design,
        construction=dict(revision=world.get('revision'), phase=world.get('phase'),
            planning_option_count=len(world.get('planning_options', world.get('options', []))),
            commit_option_count=len(world.get('options', [])),
            geometry_policy='引擎验证位置槽、碰撞、通路和施工占用；这里不推断可达性'),
        battle_trend=_battle_trend(window), recent_observations=_observations(window),
        observed_encounters=_encounters(window), recent_mission_results=_mission_results(world),
        observation_limits='null 为未知；历史旧样本缺少阵营或存活压力时不补造。满血当量仅是血量比例，不代表战斗力。',
        human_sample_count=sum(bool(row.get('human_evidence')) for row in window),
        evidence_limits='无操作级机会标签，不能推断玩家技能或偏好；无玩家证据时只调观战节奏。',
        previous_hormones=hormones, previous_phase=phase,
        recent_construction=[construction_view(row) for row in world.get('completed', [])[-6:]],
        recent_construction_failures=[pick(row, ('option', 'reason', 'tick'))
            for row in world.get('construction_failures', [])[-4:]]))


def generator_context(context):
    return rounded(dict(pick(context, ('teams', 'mission', 'objective', 'construction',
        'battle_trend', 'observed_encounters', 'observation_limits',
        'recent_construction', 'recent_construction_failures', 'hormones', 'phase',
        'macro_reason', 'player_assessment', 'evidence_limits')), schema='world-generator-v2',
        recent_mission_results=context.get('recent_mission_results', [])[-2:],
        composition_rules='策划选择任务、结构与战术关系；搭建逐格选择文具、偏移和方向，精确尺寸由共享规格编译，引擎独立校验。避免重复近期结构。'))
