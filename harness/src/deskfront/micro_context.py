"""Compact micro-combat facts for JEV; no action selection or safety inference."""
import math


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _distance(a, b):
    if not isinstance(a, (list, tuple)) or not isinstance(b, (list, tuple)) or len(a) != 2 or len(b) != 2:
        return None
    if any(_number(v) is None for v in [*a, *b]):
        return None
    return math.dist(a, b)


def _ids(values):
    return sorted({v for v in values if isinstance(v, str)})


def _one_volley(exposure, hp, known):
    """Compare raw one-shot weapon damage, never expected hits or a damage cap."""
    health = _number(hp)
    damage, shooters, incomplete = 0, [], []
    for row in exposure:
        ready = _number(row.get('ready_in_s'))
        if ready is None or ready < 0:
            incomplete.append(row['id'])
            continue
        if ready > 1:
            continue
        hit = _number(row.get('damage_per_hit'))
        if hit is None or hit < 0:
            incomplete.append(row['id'])
            continue
        shooters.append(row['id'])
        damage += hit
    return dict(horizon_s=1, status='unknown' if not known else 'partial' if incomplete else 'complete_sample',
                damage=round(damage, 3) if known else None, hp=health,
                damage_meets_current_hp=(damage >= health) if known and health is not None else None,
                shooters=shooters, unquantified_shooters=incomplete,
                basis='one_volley_potential: 1秒内已准备好的采样射界敌人各打一发基础伤害；不是预计命中伤害，也不是总伤害上界。未计命中、减伤、连射及溅射；移动和遮挡变化会改变结果。')


def build(unit, enemies, spatial, now):
    combat = unit.get('combat', {})
    own_range = _number(unit.get('weapon_range'))
    own_range = own_range if own_range is not None and own_range > 0 else None
    moving = bool(combat.get('path_active'))
    infantry = unit.get('kind', 'infantry') != 'tank'
    reload_s = _number(unit.get('reload_remaining'))
    blockers = []
    if moving and infantry:
        blockers.append('moving_infantry_cannot_fire')
    if unit.get('cover_step') and infantry:
        blockers.append('cover_step')
    if reload_s is not None and reload_s > 0:
        blockers.append('reloading')
    if unit.get('ammo') is not None and unit['ammo'] <= 0:
        blockers.append('empty_magazine')
    if infantry and unit.get('cqb_stance') == 'hide':
        blockers.append('hiding')
    if infantry and unit.get('suppression', 0) >= .95:
        blockers.append('heavy_suppression')

    sampled_at = _number(spatial.get('sampled_at'))
    age = now - sampled_at if sampled_at is not None else None
    origin_distance = _distance(unit.get('position'), spatial.get('origin'))
    fresh = age is not None and 0 <= age <= 2 and (origin_distance is None or origin_distance <= .15)
    checked = spatial if fresh else {}
    incoming = _ids(combat.get('incoming_threats', []))
    sampled_threats = _ids(checked.get('current_threats', []))
    exposure = [dict(id=r['id'], **{k: r[k] for k in ('ready_in_s', 'damage_per_hit') if k in r})
                for r in checked.get('threat_forecast', {}).get('standing_exposure', [])
                if isinstance(r, dict) and isinstance(r.get('id'), str)]
    check = combat.get('fire_check', {})
    check_at = _number(check.get('time'))
    check_distance = _distance(unit.get('position'), check.get('position'))
    check_fresh = check_at is not None and 0 <= now - check_at <= 3 and (check_distance is None or check_distance <= .08)
    targets = []
    for enemy in enemies:
        if enemy.get('hp', 0) <= 0 or not enemy.get('combat_ready', True):
            continue
        distance = _distance(unit.get('position'), enemy.get('position'))
        enemy_range = _number(enemy.get('weapon_range'))
        enemy_range = enemy_range if enemy_range is not None and enemy_range > 0 else None
        ours = distance <= own_range if distance is not None and own_range is not None else None
        theirs = distance <= enemy_range if distance is not None and enemy_range is not None else None
        relation = ('unknown' if ours is None or theirs is None else
                    'both' if ours and theirs else 'self_only' if ours else 'enemy_only' if theirs else 'neither')
        row = dict(id=enemy['id'], distance=round(distance, 3) if distance is not None else None,
                   enemy_range=enemy_range, self_range_reaches=ours, enemy_range_reaches=theirs,
                   distance_relation=relation)
        if distance is not None and own_range is not None:
            row['gap_to_self_range'] = round(max(0, distance - own_range), 3)
        lane = 'unknown'
        if enemy['id'] in combat.get('engageable_targets', []):
            lane = 'native_candidate_requires_muzzle_check'
        if enemy['id'] in checked.get('blocked_shots', []):
            lane = 'sampled_cover_obstruction'
        if check_fresh and check.get('target_id') == enemy['id']:
            lane = ('recent_muzzle_block:' + check.get('reason', 'blocked')
                    if check.get('status') == 'blocked' else 'recent_clear_muzzle_requires_recheck')
        row['fire_lane'] = lane
        targets.append(row)

    warnings = []
    if incoming:
        warnings.append('native_incoming_fire_lane')
    if sampled_threats:
        warnings.append('sampled_current_fire_lane')
    if exposure:
        warnings.append('predicted_standing_exposure')
    if any(t['enemy_range_reaches'] for t in targets):
        warnings.append('enemy_distance_reach_not_los')
    preferred = checked.get('preferred_distance')
    if not isinstance(preferred, (list, tuple)) or len(preferred) != 2 or any(_number(v) is None for v in preferred):
        preferred = [round(own_range * .6, 3), round(own_range * .9, 3)] if own_range else None
    return dict(
        range_basis='distance_only; 不含遮挡、瞄准、命中概率或炮弹伤害范围',
        own_range=own_range, moving=moving, reload_s=reload_s, fire_blockers=blockers,
        preferred_distance=dict(window=preferred, basis='spacing_heuristic_not_safe_range'),
        targets=targets,
        threats=dict(native=incoming, sampled=sampled_threats, standing_forecast=exposure,
                     query_status='fresh' if fresh else 'unknown_or_stale',
                     sampled_age_s=round(age, 3) if age is not None else None,
                     one_volley_potential=_one_volley(exposure, unit.get('hp'),
                         fresh and isinstance(checked.get('threat_forecast', {}).get('standing_exposure'), list)),
                     warning_before_damage=warnings),
        tradeoffs=dict(
            approach=dict(outside_range=[t['id'] for t in targets if t['self_range_reaches'] is False],
                          note='接近可进入射程；步兵移动期间暂停开火，比较当前短步的路径暴露，不要只看终点'),
            stop_and_fire=dict(within_range=[t['id'] for t in targets if t['self_range_reaches'] is True],
                               note='站定可恢复瞄准；还需装填完成、枪口无遮挡。已有有效射位时继续移动会中断输出'),
            withdraw=dict(queried_options=len(checked.get('withdrawal_positions', [])),
                          note='后撤可扩大距离或换射界，但移动会暂停步兵输出；比较后撤路径和终点威胁，远离一个敌人不等于安全')),
        limits='工具提供权衡，由JEV选择；没有威胁记录不等于安全，未知射界不可当成已开火，预测假设敌人位置不变')
