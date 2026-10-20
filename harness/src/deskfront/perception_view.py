"""Small, read-only world overlay derived ONLY from a recorded model request.

Never joins live omniscient state. Display coordinates are converted back only
for fixed-grid requests, not historical frames with an unknown world origin.
"""
import re


def build_view(record):
    if record.get('availability') == 'waiting_for_request':
        return dict(session=record.get('session'), role=record.get('role'),
                    run_id=record.get('metadata', {}).get('run_id'),
                    available=False, status='waiting_for_request', projectable=False,
                    cells=[], actors=[], facts=[], decision='', time=None,
                    note=record['note'])
    preview = record.get('coordinatePreview', {})
    state = preview.get('state', {})
    shared = state.get('shared_facts', [])

    def expand(v):
        if isinstance(v, dict):
            if set(v) == {'ref'} and isinstance(v['ref'], int) and 0 <= v['ref'] < len(shared):
                return shared[v['ref']]
            return {k: expand(x) for k, x in v.items()}
        if isinstance(v, list):
            return [expand(x) for x in v]
        return v

    def rows(v):
        v = expand(v)
        if isinstance(v, list): return v
        if isinstance(v, dict) and 'columns' in v:
            return [dict(zip(v['columns'], r)) for r in v.get('rows', [])]
        return []

    state = expand(state)
    grid = state.get('tactical_map', {})
    scale = grid.get('distance_to_cells', 0)
    projectable = bool(preview.get('recorded') and not grid.get('legacy_frame', True) and scale > 0)
    # Preserve the request's own labels; faction/type badges are display aids.
    entities = dict(grid.get('entities', {})) if isinstance(grid.get('entities'), dict) else {}
    under_units = dict(grid.get('under_units', {})) if isinstance(grid.get('under_units'), dict) else {}
    entity_tokens = {uid: token for token, uid in entities.items()
                     if isinstance(token, str) and isinstance(uid, str)}

    def point(p):
        return [p[0] / scale, p[1] / scale] if projectable and isinstance(p, list) and len(p) == 2 else None

    actors = {}
    for u in rows(state.get('members')) + rows(state.get('contacts')) + rows(state.get('teammate_reports')) + [state.get('self', {})] + rows(state.get('battlefield_equipment')):
        if not isinstance(u, dict) or not u.get('id') or not point(u.get('position')): continue
        kind = 'T' if u.get('kind') == 'tank' or u.get('tank') else 'P' if u.get('kind') == 'mortar' else 'C' if u.get('equipment_role') in ('gunner', 'guard') else {'rifle':'I','pistol':'J','rocket':'K','smg':'S','machine_gun':'H','sniper':'N','cannon':'T'}.get(u.get('weapon'), '?')
        actors[u['id']] = dict(id=u['id'], symbol=kind, map_token=entity_tokens.get(u['id'], ''), position=point(u['position']), faction=u.get('faction', u['id'].split('-')[0]), self=u['id'] == state.get('self', {}).get('id'), source=u.get('source', ''), visible=u.get('visible'))
    cells = []
    origin = grid.get('origin', [0, 0])
    for line in grid.get('diagram', '').splitlines():
        m = re.match(r'^(-?\d+)\s*\|(.+)\|\s*$', line)
        if not m: continue
        for x, token in enumerate(m[2].split()):
            p = point([origin[0] + x + .5, int(m[1]) + .5])
            if p: cells.append(dict(position=p, token=token))
    candidates = []
    for site in rows(state.get('candidate_sites')) + rows(state.get('regions')):
        pos = point(site.get('position', site.get('center')))
        if pos: candidates.append(dict(position=pos, id=site.get('id', ''), checks=site.get('fire_checks'), targets=site.get('fire_targets')))
    decision = record.get('readableCase', {}).get('decision', {})
    raw = decision.get('raw') or {}
    response = raw.get('response') or {}
    answers = response.get('answers') or {}
    choices = []
    destinations = []
    for key, answer in answers.items():
        if not isinstance(answer, dict): continue
        value = answer.get('choice', answer.get('value'))
        if isinstance(value, dict):
            p = point(value.get('destination'))
            if p: destinations.append(p)
        if isinstance(value, str):
            choices.append(key + ': ' + value)
            # Only coordinate-bearing chosen values, never rationale text.
            for m in re.finditer(r'\((-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)\)', value):
                p = point([float(m[1]), float(m[2])])
                if p: destinations.append(p)
    return dict(session=record.get('session'), role=record.get('role'), time=state.get('time'),
                unit=record.get('metadata', {}).get('unit_id'), run_id=record.get('metadata', {}).get('run_id'), projectable=projectable,
                cell_size=1 / scale if projectable else 0, actors=list(actors.values()), cells=cells,
                entities=entities, under_units=under_units,
                candidates=candidates, destinations=destinations, choices=choices,
                facts=record.get('readableCase', {}).get('facts', []), decision=decision.get('text', ''),
                visibility=state.get('visibility', {}).get('mode', '未记录'),
                note='请求快照；标记为显示增强，模型回答不等于执行成功。' if projectable else '该记录缺少固定世界坐标绑定，不能叠加到当前战场。')
